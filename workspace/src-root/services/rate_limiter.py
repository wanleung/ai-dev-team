"""Async token bucket rate limiter with provider-specific limits.

Implements a token bucket algorithm for rate limiting API calls to calendar
providers (Google Calendar, Outlook/Microsoft Graph). Each provider has its
own bucket with configurable capacity and refill rate.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from src.config.settings import settings


@dataclass
class TokenBucket:
    """Token bucket implementation for rate limiting.
    
    Tokens are added at a fixed rate up to a maximum capacity. Each request
    consumes one token. If no tokens are available, the caller must wait.
    """

    capacity: int
    """Maximum number of tokens the bucket can hold."""
    
    refill_rate: float
    """Tokens added per second."""
    
    tokens: float = field(init=False)
    """Current number of available tokens."""
    
    last_refill: float = field(init=False, default_factory=time.monotonic)
    """Monotonic timestamp of the last token refill."""
    
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    """Async lock for thread-safe token operations."""

    def __post_init__(self) -> None:
        """Initialize tokens to full capacity."""
        self.tokens = float(self.capacity)

    def _refill(self) -> None:
        """Refill tokens based on elapsed time since last refill."""
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

    async def acquire(self) -> float:
        """Acquire a token, waiting if necessary.
        
        Returns:
            Time waited in seconds (0 if token was immediately available).
        """
        waited = 0.0
        while True:
            async with self.lock:
                self._refill()
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return waited
                # Calculate wait time for next token
                wait_time = (1.0 - self.tokens) / self.refill_rate
            
            # Wait outside the lock to allow other coroutines to proceed
            await asyncio.sleep(wait_time)
            waited += wait_time

    async def release(self) -> None:
        """Release a token back to the bucket (up to capacity).
        
        Note: In most rate limiting scenarios, release is a no-op since
        tokens are consumed by making API calls. This method is provided
        for cases where a token should be returned (e.g., failed request).
        """
        async with self.lock:
            self.tokens = min(self.capacity, self.tokens + 1.0)

    @property
    def available_tokens(self) -> float:
        """Get the current number of available tokens without modifying state."""
        self._refill()
        return self.tokens


class RateLimiterError(Exception):
    """Raised when rate limiting fails after maximum retries."""

    def __init__(self, provider: str, operation: str, message: str) -> None:
        super().__init__(message)
        self.provider = provider
        self.operation = operation


class RateLimiter:
    """Async rate limiter with provider-specific token buckets.
    
    Manages separate token buckets for each calendar provider, enforcing
    API rate limits client-side to avoid 429 responses.
    """

    def __init__(
        self,
        google_capacity: int | None = None,
        google_refill_rate: float | None = None,
        outlook_capacity: int | None = None,
        outlook_refill_rate: float | None = None,
    ) -> None:
        """Initialize rate limiter with provider-specific configurations.
        
        Args:
            google_capacity: Max tokens for Google Calendar bucket.
                Defaults to settings.rate_limit_google_capacity or 10000.
            google_refill_rate: Tokens/second for Google Calendar.
                Defaults to settings.rate_limit_google_refill_rate or 100.0.
            outlook_capacity: Max tokens for Outlook Calendar bucket.
                Defaults to settings.rate_limit_outlook_capacity or 10000.
            outlook_refill_rate: Tokens/second for Outlook Calendar.
                Defaults to settings.rate_limit_outlook_refill_rate or ~16.67.
        """
        self._buckets: dict[str, TokenBucket] = {}
        
        # Google Calendar: 10k requests per 100 seconds = 100 tokens/sec
        self._google_capacity = google_capacity or getattr(settings, 'rate_limit_google_capacity', 10000)
        self._google_refill_rate = google_refill_rate or getattr(settings, 'rate_limit_google_refill_rate', 100.0)
        
        # Outlook Calendar: 10k requests per 10 minutes (600s) = ~16.67 tokens/sec
        self._outlook_capacity = outlook_capacity or getattr(settings, 'rate_limit_outlook_capacity', 10000)
        self._outlook_refill_rate = outlook_refill_rate or getattr(settings, 'rate_limit_outlook_refill_rate', 10000 / 600)
        
        self._default_capacity = getattr(settings, 'rate_limit_default_capacity', 1000)
        self._default_refill_rate = getattr(settings, 'rate_limit_default_refill_rate', 10.0)
        
        self._max_retries = getattr(settings, 'rate_limit_max_retries', 3)
        self._backoff_base = getattr(settings, 'rate_limit_backoff_base', 1.0)

    def _get_bucket(self, provider: str) -> TokenBucket:
        """Get or create a token bucket for the specified provider.
        
        Args:
            provider: Provider name ("google", "outlook", or custom).
            
        Returns:
            TokenBucket instance for the provider.
        """
        if provider not in self._buckets:
            if provider == "google":
                self._buckets[provider] = TokenBucket(
                    capacity=self._google_capacity,
                    refill_rate=self._google_refill_rate,
                )
            elif provider == "outlook":
                self._buckets[provider] = TokenBucket(
                    capacity=self._outlook_capacity,
                    refill_rate=self._outlook_refill_rate,
                )
            else:
                # Unknown provider gets default limits
                self._buckets[provider] = TokenBucket(
                    capacity=self._default_capacity,
                    refill_rate=self._default_refill_rate,
                )
        return self._buckets[provider]

    async def acquire(self, provider: str, operation: str = "default") -> None:
        """Acquire a rate limit token for the specified provider.
        
        Blocks until a token is available, with exponential backoff on
        repeated failures.
        
        Args:
            provider: Provider name ("google", "outlook", or custom).
            operation: Operation name for error context (e.g., "list_calendars").
            
        Raises:
            RateLimiterError: If acquisition fails after max retries.
        """
        bucket = self._get_bucket(provider)
        
        for attempt in range(self._max_retries):
            try:
                waited = await bucket.acquire()
                if waited > 0:
                    # Log rate limit wait if needed
                    pass
                return
            except Exception as e:
                if attempt == self._max_retries - 1:
                    raise RateLimiterError(
                        provider=provider,
                        operation=operation,
                        message=f"Failed to acquire rate limit token after {self._max_retries} attempts: {e}",
                    ) from e
                # Exponential backoff
                backoff = self._backoff_base * (2 ** attempt)
                await asyncio.sleep(backoff)

    async def release(self, provider: str, operation: str = "default") -> None:
        """Release a rate limit token back to the provider's bucket.
        
        Args:
            provider: Provider name ("google", "outlook", or custom).
            operation: Operation name for error context.
        """
        bucket = self._get_bucket(provider)
        await bucket.release()

    async def get_available_tokens(self, provider: str) -> float:
        """Get the number of available tokens for a provider.
        
        Args:
            provider: Provider name.
            
        Returns:
            Number of tokens currently available.
        """
        bucket = self._get_bucket(provider)
        return bucket.available_tokens

    def reset(self, provider: str | None = None) -> None:
        """Reset token bucket(s) to full capacity.
        
        Args:
            provider: If specified, reset only that provider's bucket.
                     If None, reset all buckets.
        """
        if provider:
            if provider in self._buckets:
                del self._buckets[provider]
        else:
            self._buckets.clear()


# Module-level singleton for convenience
_rate_limiter: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    """Get the global rate limiter instance.
    
    Returns:
        Singleton RateLimiter instance.
    """
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
    return _rate_limiter


def reset_rate_limiter() -> None:
    """Reset the global rate limiter instance (useful for testing)."""
    global _rate_limiter
    _rate_limiter = None
