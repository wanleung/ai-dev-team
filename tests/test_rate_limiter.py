"""Tests for rate limiter service."""
import pytest
from unittest.mock import patch, MagicMock

from src.services.rate_limiter import (
    TokenBucket, RateLimiter, RateLimiterError,
    get_rate_limiter, reset_rate_limiter,
)


class TestTokenBucket:
    def test_initial_tokens_at_capacity(self):
        bucket = TokenBucket(capacity=10, refill_rate=1.0)
        assert bucket.tokens == 10.0

    @pytest.mark.asyncio
    async def test_acquire_decrements_tokens(self):
        bucket = TokenBucket(capacity=10, refill_rate=1.0)
        waited = await bucket.acquire()
        assert bucket.tokens < 10.0
        assert waited >= 0

    @pytest.mark.asyncio
    async def test_acquire_multiple_times(self):
        bucket = TokenBucket(capacity=5, refill_rate=1.0)
        for _ in range(5):
            await bucket.acquire()
        assert bucket.tokens < 1.0

    def test_available_tokens_property(self):
        bucket = TokenBucket(capacity=10, refill_rate=1.0)
        tokens = bucket.available_tokens
        assert tokens >= 0
        assert tokens <= 10.0

    @pytest.mark.asyncio
    async def test_release_adds_tokens(self):
        bucket = TokenBucket(capacity=10, refill_rate=1.0)
        await bucket.acquire()
        initial = bucket.tokens
        await bucket.release()
        assert bucket.tokens > initial

    @pytest.mark.asyncio
    async def test_release_does_not_exceed_capacity(self):
        bucket = TokenBucket(capacity=5, refill_rate=1.0)
        for _ in range(10):
            await bucket.release()
        assert bucket.tokens <= 5.0


class TestRateLimiter:
    def test_creates_google_bucket(self):
        limiter = RateLimiter()
        bucket = limiter._get_bucket("google")
        assert bucket is not None
        assert bucket.capacity == 10000

    def test_creates_outlook_bucket(self):
        limiter = RateLimiter()
        bucket = limiter._get_bucket("outlook")
        assert bucket is not None
        assert bucket.capacity == 10000

    def test_creates_default_bucket_for_unknown_provider(self):
        limiter = RateLimiter()
        bucket = limiter._get_bucket("unknown")
        assert bucket is not None
        assert bucket.capacity == 1000

    def test_custom_google_limits(self):
        limiter = RateLimiter(google_capacity=5000, google_refill_rate=50.0)
        bucket = limiter._get_bucket("google")
        assert bucket.capacity == 5000

    def test_custom_outlook_limits(self):
        limiter = RateLimiter(outlook_capacity=5000, outlook_refill_rate=8.33)
        bucket = limiter._get_bucket("outlook")
        assert bucket.capacity == 5000

    @pytest.mark.asyncio
    async def test_acquire_google(self):
        limiter = RateLimiter()
        await limiter.acquire("google", "test_op")

    @pytest.mark.asyncio
    async def test_acquire_outlook(self):
        limiter = RateLimiter()
        await limiter.acquire("outlook", "test_op")

    @pytest.mark.asyncio
    async def test_acquire_returns_on_success(self):
        limiter = RateLimiter()
        await limiter.acquire("google", "test_op")

    @pytest.mark.asyncio
    async def test_release_google(self):
        limiter = RateLimiter()
        await limiter.acquire("google", "test_op")
        await limiter.release("google", "test_op")

    @pytest.mark.asyncio
    async def test_release_outlook(self):
        limiter = RateLimiter()
        await limiter.acquire("outlook", "test_op")
        await limiter.release("outlook", "test_op")

    @pytest.mark.asyncio
    async def test_get_available_tokens(self):
        limiter = RateLimiter()
        tokens = await limiter.get_available_tokens("google")
        assert tokens > 0

    def test_reset_single_provider(self):
        limiter = RateLimiter()
        limiter._get_bucket("google")
        limiter.reset("google")
        assert "google" not in limiter._buckets

    def test_reset_all_providers(self):
        limiter = RateLimiter()
        limiter._get_bucket("google")
        limiter._get_bucket("outlook")
        limiter.reset()
        assert len(limiter._buckets) == 0

    def test_reset_nonexistent_provider(self):
        limiter = RateLimiter()
        limiter.reset("nonexistent")

    def test_reuses_existing_bucket(self):
        limiter = RateLimiter()
        bucket1 = limiter._get_bucket("google")
        bucket2 = limiter._get_bucket("google")
        assert bucket1 is bucket2


class TestGetRateLimiter:
    def test_returns_singleton(self):
        reset_rate_limiter()
        limiter1 = get_rate_limiter()
        limiter2 = get_rate_limiter()
        assert limiter1 is limiter2

    def test_reset_clears_singleton(self):
        reset_rate_limiter()
        limiter1 = get_rate_limiter()
        reset_rate_limiter()
        limiter2 = get_rate_limiter()
        assert limiter1 is not limiter2


class TestRateLimiterError:
    def test_error_attributes(self):
        error = RateLimiterError("google", "test_op", "Rate limited")
        assert error.provider == "google"
        assert error.operation == "test_op"
        assert str(error) == "Rate limited"

    def test_error_inherits_exception(self):
        error = RateLimiterError("google", "test_op", "Rate limited")
        assert isinstance(error, Exception)
