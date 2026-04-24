"""Unit tests for the async token bucket rate limiter.

Tests cover:
- TokenBucket initialization, refill, acquire, release
- RateLimiter per-provider bucket management
- RateLimiterError exception attributes
- Singleton behavior (get_rate_limiter / reset_rate_limiter)
- Exponential backoff on acquisition failures
- Default provider bucket creation
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.rate_limiter import (
    RateLimiter,
    RateLimiterError,
    TokenBucket,
    get_rate_limiter,
    reset_rate_limiter,
)


# ---------------------------------------------------------------------------
# TokenBucket tests
# ---------------------------------------------------------------------------


class TestTokenBucketInit:
    """Tests for TokenBucket initialization."""

    def test_initial_tokens_at_capacity(self) -> None:
        bucket = TokenBucket(capacity=100, refill_rate=10.0)
        assert bucket.tokens == 100.0

    def test_custom_capacity(self) -> None:
        bucket = TokenBucket(capacity=500, refill_rate=50.0)
        assert bucket.capacity == 500
        assert bucket.tokens == 500.0

    def test_refill_rate_stored(self) -> None:
        bucket = TokenBucket(capacity=10, refill_rate=5.0)
        assert bucket.refill_rate == 5.0


class TestTokenBucketRefill:
    """Tests for TokenBucket._refill()."""

    def test_refill_adds_tokens_based_on_elapsed_time(self) -> None:
        bucket = TokenBucket(capacity=100, refill_rate=10.0)
        # Consume all tokens
        bucket.tokens = 0.0
        bucket.last_refill = time.monotonic() - 5.0  # 5 seconds ago
        bucket._refill()
        # 5s * 10 tokens/s = 50 tokens
        assert bucket.tokens == pytest.approx(50.0, abs=1.0)

    def test_refill_caps_at_capacity(self) -> None:
        bucket = TokenBucket(capacity=100, refill_rate=1000.0)
        bucket.tokens = 50.0
        bucket.last_refill = time.monotonic() - 10.0  # would add 10000 tokens
        bucket._refill()
        assert bucket.tokens == 100.0

    def test_refill_with_no_elapsed_time(self) -> None:
        bucket = TokenBucket(capacity=100, refill_rate=10.0)
        bucket.tokens = 50.0
        bucket._refill()
        # Very little time passed, tokens should be ~50
        assert bucket.tokens == pytest.approx(50.0, abs=1.0)


class TestTokenBucketAcquire:
    """Tests for TokenBucket.acquire()."""

    @pytest.mark.asyncio
    async def test_acquire_when_tokens_available(self) -> None:
        bucket = TokenBucket(capacity=10, refill_rate=1.0)
        waited = await bucket.acquire()
        assert waited == 0.0
        assert bucket.tokens == 9.0

    @pytest.mark.asyncio
    async def test_acquire_decrements_tokens(self) -> None:
        bucket = TokenBucket(capacity=5, refill_rate=1.0)
        await bucket.acquire()
        await bucket.acquire()
        await bucket.acquire()
        assert bucket.tokens == pytest.approx(2.0, abs=0.1)

    @pytest.mark.asyncio
    async def test_acquire_waits_when_empty(self) -> None:
        bucket = TokenBucket(capacity=1, refill_rate=100.0)
        await bucket.acquire()  # consume the only token
        # Now bucket is empty; with refill_rate=100, should wait ~0.01s
        waited = await bucket.acquire()
        assert waited > 0

    @pytest.mark.asyncio
    async def test_acquire_multiple_concurrent(self) -> None:
        """Multiple coroutines acquiring tokens concurrently."""
        bucket = TokenBucket(capacity=10, refill_rate=100.0)
        tasks = [bucket.acquire() for _ in range(5)]
        results = await asyncio.gather(*tasks)
        # All should succeed
        assert all(r >= 0 for r in results)


class TestTokenBucketRelease:
    """Tests for TokenBucket.release()."""

    @pytest.mark.asyncio
    async def test_release_adds_token(self) -> None:
        bucket = TokenBucket(capacity=10, refill_rate=1.0)
        bucket.tokens = 5.0
        await bucket.release()
        assert bucket.tokens == 6.0

    @pytest.mark.asyncio
    async def test_release_caps_at_capacity(self) -> None:
        bucket = TokenBucket(capacity=10, refill_rate=1.0)
        bucket.tokens = 10.0
        await bucket.release()
        assert bucket.tokens == 10.0

    @pytest.mark.asyncio
    async def test_release_after_acquire(self) -> None:
        bucket = TokenBucket(capacity=10, refill_rate=1.0)
        await bucket.acquire()
        assert bucket.tokens == 9.0
        await bucket.release()
        assert bucket.tokens == 10.0


class TestTokenBucketAvailableTokens:
    """Tests for TokenBucket.available_tokens property."""

    def test_available_tokens_returns_current(self) -> None:
        bucket = TokenBucket(capacity=100, refill_rate=10.0)
        bucket.tokens = 42.0
        assert bucket.available_tokens == pytest.approx(42.0, abs=1.0)

    def test_available_tokens_refills(self) -> None:
        bucket = TokenBucket(capacity=100, refill_rate=100.0)
        bucket.tokens = 0.0
        bucket.last_refill = time.monotonic() - 1.0
        # 1s * 100 tokens/s = 100, capped at 100
        assert bucket.available_tokens == 100.0


# ---------------------------------------------------------------------------
# RateLimiterError tests
# ---------------------------------------------------------------------------


class TestRateLimiterError:
    """Tests for RateLimiterError exception."""

    def test_exception_message(self) -> None:
        err = RateLimiterError(
            provider="google",
            operation="list_calendars",
            message="rate limit exceeded",
        )
        assert str(err) == "rate limit exceeded"

    def test_exception_attributes(self) -> None:
        err = RateLimiterError(
            provider="outlook",
            operation="create_event",
            message="too many retries",
        )
        assert err.provider == "outlook"
        assert err.operation == "create_event"

    def test_is_exception(self) -> None:
        err = RateLimiterError(provider="google", operation="x", message="y")
        assert isinstance(err, Exception)


# ---------------------------------------------------------------------------
# RateLimiter tests
# ---------------------------------------------------------------------------


class TestRateLimiterInit:
    """Tests for RateLimiter initialization."""

    def test_default_initialization(self) -> None:
        limiter = RateLimiter()
        assert limiter._buckets == {}

    def test_custom_google_params(self) -> None:
        limiter = RateLimiter(google_capacity=500, google_refill_rate=50.0)
        assert limiter._google_capacity == 500
        assert limiter._google_refill_rate == 50.0

    def test_custom_outlook_params(self) -> None:
        limiter = RateLimiter(outlook_capacity=200, outlook_refill_rate=20.0)
        assert limiter._outlook_capacity == 200
        assert limiter._outlook_refill_rate == 20.0


class TestRateLimiterGetBucket:
    """Tests for RateLimiter._get_bucket()."""

    def test_creates_google_bucket(self) -> None:
        limiter = RateLimiter(google_capacity=500, google_refill_rate=50.0)
        bucket = limiter._get_bucket("google")
        assert isinstance(bucket, TokenBucket)
        assert bucket.capacity == 500
        assert bucket.refill_rate == 50.0

    def test_creates_outlook_bucket(self) -> None:
        limiter = RateLimiter(outlook_capacity=300, outlook_refill_rate=30.0)
        bucket = limiter._get_bucket("outlook")
        assert bucket.capacity == 300
        assert bucket.refill_rate == 30.0

    def test_creates_default_bucket_for_unknown_provider(self) -> None:
        limiter = RateLimiter()
        bucket = limiter._get_bucket("custom_provider")
        assert isinstance(bucket, TokenBucket)
        assert bucket.capacity == 1000  # default
        assert bucket.refill_rate == 10.0  # default

    def test_reuses_existing_bucket(self) -> None:
        limiter = RateLimiter()
        bucket1 = limiter._get_bucket("google")
        bucket2 = limiter._get_bucket("google")
        assert bucket1 is bucket2

    def test_different_providers_get_different_buckets(self) -> None:
        limiter = RateLimiter()
        google_bucket = limiter._get_bucket("google")
        outlook_bucket = limiter._get_bucket("outlook")
        assert google_bucket is not outlook_bucket


class TestRateLimiterAcquire:
    """Tests for RateLimiter.acquire()."""

    @pytest.mark.asyncio
    async def test_acquire_google(self) -> None:
        limiter = RateLimiter(google_capacity=10, google_refill_rate=10.0)
        await limiter.acquire("google", "list_calendars")
        bucket = limiter._get_bucket("google")
        assert bucket.tokens == pytest.approx(9.0, abs=0.5)

    @pytest.mark.asyncio
    async def test_acquire_outlook(self) -> None:
        limiter = RateLimiter(outlook_capacity=10, outlook_refill_rate=10.0)
        await limiter.acquire("outlook", "create_event")
        bucket = limiter._get_bucket("outlook")
        assert bucket.tokens == pytest.approx(9.0, abs=0.5)

    @pytest.mark.asyncio
    async def test_acquire_unknown_provider(self) -> None:
        limiter = RateLimiter()
        await limiter.acquire("custom", "test_op")
        bucket = limiter._get_bucket("custom")
        assert bucket.tokens < bucket.capacity

    @pytest.mark.asyncio
    async def test_acquire_multiple_times(self) -> None:
        limiter = RateLimiter(google_capacity=10, google_refill_rate=1.0)
        for _ in range(5):
            await limiter.acquire("google")
        bucket = limiter._get_bucket("google")
        assert bucket.tokens == pytest.approx(5.0, abs=0.5)

    @pytest.mark.asyncio
    async def test_acquire_raises_error_after_max_retries(self) -> None:
        limiter = RateLimiter()
        limiter._max_retries = 2
        limiter._backoff_base = 0.01  # fast backoff for test

        # Make the bucket's acquire always raise
        bucket = TokenBucket(capacity=1, refill_rate=0.0)
        bucket.acquire = AsyncMock(side_effect=RuntimeError("bucket broken"))
        limiter._buckets["google"] = bucket

        with pytest.raises(RateLimiterError) as exc_info:
            await limiter.acquire("google", "test_op")

        assert exc_info.value.provider == "google"
        assert exc_info.value.operation == "test_op"
        assert "2 attempts" in str(exc_info.value)


class TestRateLimiterRelease:
    """Tests for RateLimiter.release()."""

    @pytest.mark.asyncio
    async def test_release_google(self) -> None:
        limiter = RateLimiter(google_capacity=10, google_refill_rate=1.0)
        bucket = limiter._get_bucket("google")
        bucket.tokens = 5.0
        await limiter.release("google")
        assert bucket.tokens == 6.0

    @pytest.mark.asyncio
    async def test_release_outlook(self) -> None:
        limiter = RateLimiter(outlook_capacity=10, outlook_refill_rate=1.0)
        bucket = limiter._get_bucket("outlook")
        bucket.tokens = 3.0
        await limiter.release("outlook")
        assert bucket.tokens == 4.0

    @pytest.mark.asyncio
    async def test_release_creates_bucket_if_needed(self) -> None:
        limiter = RateLimiter()
        await limiter.release("new_provider")
        assert "new_provider" in limiter._buckets


class TestRateLimiterGetAvailableTokens:
    """Tests for RateLimiter.get_available_tokens()."""

    @pytest.mark.asyncio
    async def test_returns_available_tokens(self) -> None:
        limiter = RateLimiter(google_capacity=100, google_refill_rate=1.0)
        tokens = await limiter.get_available_tokens("google")
        assert tokens == pytest.approx(100.0, abs=0.5)

    @pytest.mark.asyncio
    async def test_returns_after_acquire(self) -> None:
        limiter = RateLimiter(google_capacity=10, google_refill_rate=0.0)
        await limiter.acquire("google")
        tokens = await limiter.get_available_tokens("google")
        assert tokens == pytest.approx(9.0, abs=0.5)


class TestRateLimiterReset:
    """Tests for RateLimiter.reset()."""

    def test_reset_single_provider(self) -> None:
        limiter = RateLimiter()
        limiter._get_bucket("google")
        limiter._get_bucket("outlook")
        assert len(limiter._buckets) == 2

        limiter.reset("google")
        assert "google" not in limiter._buckets
        assert "outlook" in limiter._buckets

    def test_reset_all_providers(self) -> None:
        limiter = RateLimiter()
        limiter._get_bucket("google")
        limiter._get_bucket("outlook")
        assert len(limiter._buckets) == 2

        limiter.reset()
        assert len(limiter._buckets) == 0

    def test_reset_nonexistent_provider(self) -> None:
        limiter = RateLimiter()
        limiter.reset("nonexistent")  # should not raise

    def test_reset_then_recreate(self) -> None:
        limiter = RateLimiter(google_capacity=50, google_refill_rate=5.0)
        limiter._get_bucket("google")
        limiter.reset("google")
        bucket = limiter._get_bucket("google")
        assert bucket.capacity == 50
        assert bucket.tokens == 50.0


# ---------------------------------------------------------------------------
# Singleton tests
# ---------------------------------------------------------------------------


class TestSingleton:
    """Tests for get_rate_limiter() and reset_rate_limiter()."""

    def setup_method(self) -> None:
        reset_rate_limiter()

    def teardown_method(self) -> None:
        reset_rate_limiter()

    def test_get_rate_limiter_returns_instance(self) -> None:
        limiter = get_rate_limiter()
        assert isinstance(limiter, RateLimiter)

    def test_get_rate_limiter_returns_same_instance(self) -> None:
        limiter1 = get_rate_limiter()
        limiter2 = get_rate_limiter()
        assert limiter1 is limiter2

    def test_reset_rate_limiter_creates_new_instance(self) -> None:
        limiter1 = get_rate_limiter()
        reset_rate_limiter()
        limiter2 = get_rate_limiter()
        assert limiter1 is not limiter2
