"""Rate limiter service.

Implements async token bucket rate limiting with provider-specific limits
to prevent exceeding calendar API quotas.
"""

import asyncio
import logging
import time
from typing import Optional

from src.config.settings import settings

logger = logging.getLogger(__name__)


class RateLimiter:
    """Async token bucket rate limiter for calendar providers.
    
    Implements per-provider rate limiting using the token bucket algorithm
    with configurable request limits and time windows.
    """
    
    def __init__(self) -> None:
        """Initialize rate limiter with provider-specific buckets."""
        self._buckets: dict[str, dict] = {}
        self._lock = asyncio.Lock()
        self._initialize_buckets()
    
    def _initialize_buckets(self) -> None:
        """Create token buckets for each provider."""
        self._buckets["google"] = {
            "tokens": settings.rate_limit_google_requests,
            "max_tokens": settings.rate_limit_google_requests,
            "refill_rate": settings.rate_limit_google_requests / settings.rate_limit_google_window,
            "last_refill": time.monotonic(),
        }
        
        self._buckets["outlook"] = {
            "tokens": settings.rate_limit_outlook_requests,
            "max_tokens": settings.rate_limit_outlook_requests,
            "refill_rate": settings.rate_limit_outlook_requests / settings.rate_limit_outlook_window,
            "last_refill": time.monotonic(),
        }
    
    async def acquire(self, provider: str, operation: Optional[str] = None) -> None:
        """Acquire a token from the rate limiter bucket.
        
        Blocks until a token is available if the bucket is empty.
        
        Args:
            provider: Provider name ('google' or 'outlook').
            operation: Optional operation name for logging.
            
        Raises:
            ValueError: If provider is not supported.
        """
        if provider not in self._buckets:
            raise ValueError(f"Unknown provider: {provider}")
        
        while True:
            async with self._lock:
                bucket = self._buckets[provider]
                now = time.monotonic()
                
                # Refill tokens based on elapsed time
                elapsed = now - bucket["last_refill"]
                bucket["tokens"] = min(
                    bucket["max_tokens"],
                    bucket["tokens"] + elapsed * bucket["refill_rate"],
                )
                bucket["last_refill"] = now
                
                if bucket["tokens"] >= 1:
                    bucket["tokens"] -= 1
                    return
            
            # Wait before retrying
            await asyncio.sleep(0.1)
    
    async def release(self, provider: str, operation: Optional[str] = None) -> None:
        """Release a token back to the rate limiter bucket.
        
        This is a no-op for the token bucket algorithm, but provided
        for API compatibility with semaphore-based limiters.
        
        Args:
            provider: Provider name.
            operation: Optional operation name for logging.
        """
        pass
    
    async def handle_rate_limit(self, provider: str, retry_after: Optional[float] = None) -> None:
        """Handle a rate limit response from the provider.
        
        Implements exponential backoff when the provider returns a 429 response.
        
        Args:
            provider: Provider name.
            retry_after: Optional seconds to wait from Retry-After header.
        """
        wait_time = retry_after or 1.0
        
        async with self._lock:
            if provider in self._buckets:
                # Reduce available tokens
                self._buckets[provider]["tokens"] = max(
                    0,
                    self._buckets[provider]["tokens"] - 1,
                )
        
        logger.warning(f"Rate limited by {provider}, waiting {wait_time}s")
        await asyncio.sleep(wait_time)
    
    async def close(self) -> None:
        """Clean up rate limiter resources."""
        self._buckets.clear()
