"""Tests for the _retry_with_backoff helper in agents/backends/base.py."""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call

import httpx
import openai
import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _conn_error() -> openai.APIConnectionError:
    """Build a minimal openai.APIConnectionError."""
    return openai.APIConnectionError(request=httpx.Request("GET", "https://api.openai.com"))


def _rate_limit_error() -> openai.RateLimitError:
    req = httpx.Request("GET", "https://api.openai.com")
    resp = httpx.Response(429, request=req)
    return openai.RateLimitError(message="Rate limit exceeded", response=resp, body={})


def _auth_error() -> openai.AuthenticationError:
    req = httpx.Request("GET", "https://api.openai.com")
    resp = httpx.Response(401, request=req)
    return openai.AuthenticationError(message="Invalid API key", response=resp, body={})


def _bad_request_error() -> openai.BadRequestError:
    req = httpx.Request("POST", "https://api.openai.com")
    resp = httpx.Response(400, request=req)
    return openai.BadRequestError(message="Bad request", response=resp, body={})


def _internal_server_error() -> openai.InternalServerError:
    req = httpx.Request("POST", "https://api.openai.com")
    resp = httpx.Response(500, request=req)
    return openai.InternalServerError(message="Internal server error", response=resp, body={})


def _timeout_error() -> openai.APITimeoutError:
    return openai.APITimeoutError(request=httpx.Request("POST", "https://api.openai.com"))


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestRetryWithBackoff:
    """Tests for agents.backends.base._retry_with_backoff."""

    def test_success_on_first_attempt(self):
        """fn() succeeds immediately — no sleep, returns result."""
        from agents.backends.base import _retry_with_backoff

        sentinel = object()
        mock_fn = MagicMock(return_value=sentinel)

        with patch("time.sleep") as mock_sleep:
            result = _retry_with_backoff(mock_fn, max_retries=3, base_delay=1.0)

        assert result is sentinel
        mock_fn.assert_called_once()
        mock_sleep.assert_not_called()

    def test_retry_succeeds_on_second_attempt(self):
        """APIConnectionError on first call, success on second — sleep called once."""
        from agents.backends.base import _retry_with_backoff

        valid_response = MagicMock()
        mock_fn = MagicMock(side_effect=[
            _conn_error(),
            valid_response,
        ])

        with patch("time.sleep") as mock_sleep:
            result = _retry_with_backoff(mock_fn, max_retries=3, base_delay=1.0)

        assert result is valid_response
        assert mock_fn.call_count == 2
        assert mock_sleep.call_count == 1

    def test_retry_exhausted_raises(self):
        """After max_retries+1 total attempts, raises the last exception."""
        from agents.backends.base import _retry_with_backoff

        # Use a list of 4 exception instances — mock raises each one (max_retries=3 → 4 total calls)
        mock_fn = MagicMock(side_effect=[
            _conn_error(), _conn_error(), _conn_error(), _conn_error(),
        ])

        with patch("time.sleep"):
            with pytest.raises(openai.APIConnectionError):
                _retry_with_backoff(mock_fn, max_retries=3, base_delay=1.0)

        # 1 initial + 3 retries = 4 total calls
        assert mock_fn.call_count == 4

    def test_no_retry_on_auth_error(self):
        """AuthenticationError raises immediately — no retry, no sleep."""
        from agents.backends.base import _retry_with_backoff

        mock_fn = MagicMock(side_effect=[_auth_error()])

        with patch("time.sleep") as mock_sleep:
            with pytest.raises(openai.AuthenticationError):
                _retry_with_backoff(mock_fn, max_retries=3, base_delay=1.0)

        assert mock_fn.call_count == 1
        mock_sleep.assert_not_called()

    def test_no_retry_on_bad_request_error(self):
        """BadRequestError raises immediately — no retry, no sleep."""
        from agents.backends.base import _retry_with_backoff

        mock_fn = MagicMock(side_effect=[_bad_request_error()])

        with patch("time.sleep") as mock_sleep:
            with pytest.raises(openai.BadRequestError):
                _retry_with_backoff(mock_fn, max_retries=3, base_delay=1.0)

        assert mock_fn.call_count == 1
        mock_sleep.assert_not_called()

    def test_exponential_backoff_delays(self):
        """Three consecutive failures then success — delays ~1.0, ~2.0, ~4.0 (±20%)."""
        from agents.backends.base import _retry_with_backoff

        valid_response = MagicMock()
        mock_fn = MagicMock(side_effect=[
            _conn_error(),
            _conn_error(),
            _conn_error(),
            valid_response,
        ])

        with patch("time.sleep") as mock_sleep:
            result = _retry_with_backoff(mock_fn, max_retries=3, base_delay=1.0)

        assert result is valid_response
        assert mock_sleep.call_count == 3

        delays = [c.args[0] for c in mock_sleep.call_args_list]
        # base_delay * 2^0 * jitter → roughly 1.0 (±10%, allow ±20% margin)
        assert 0.8 <= delays[0] <= 1.2, f"First delay {delays[0]} out of expected range [0.8, 1.2]"
        # base_delay * 2^1 * jitter → roughly 2.0
        assert 1.6 <= delays[1] <= 2.4, f"Second delay {delays[1]} out of expected range [1.6, 2.4]"
        # base_delay * 2^2 * jitter → roughly 4.0
        assert 3.2 <= delays[2] <= 4.8, f"Third delay {delays[2]} out of expected range [3.2, 4.8]"

    def test_rate_limit_retried(self):
        """RateLimitError triggers retry and eventually returns success."""
        from agents.backends.base import _retry_with_backoff

        valid_response = MagicMock()
        mock_fn = MagicMock(side_effect=[
            _rate_limit_error(),
            valid_response,
        ])

        with patch("time.sleep") as mock_sleep:
            result = _retry_with_backoff(mock_fn, max_retries=3, base_delay=1.0)

        assert result is valid_response
        assert mock_sleep.call_count == 1

    def test_internal_server_error_retried(self):
        """InternalServerError (5xx) triggers retry."""
        from agents.backends.base import _retry_with_backoff

        valid_response = MagicMock()
        mock_fn = MagicMock(side_effect=[
            _internal_server_error(),
            valid_response,
        ])

        with patch("time.sleep") as mock_sleep:
            result = _retry_with_backoff(mock_fn, max_retries=3, base_delay=1.0)

        assert result is valid_response
        assert mock_sleep.call_count == 1

    def test_timeout_error_retried(self):
        """APITimeoutError triggers retry."""
        from agents.backends.base import _retry_with_backoff

        valid_response = MagicMock()
        mock_fn = MagicMock(side_effect=[
            _timeout_error(),
            valid_response,
        ])

        with patch("time.sleep") as mock_sleep:
            result = _retry_with_backoff(mock_fn, max_retries=3, base_delay=1.0)

        assert result is valid_response
        assert mock_sleep.call_count == 1

    def test_non_api_exception_raises_immediately(self):
        """A completely unrelated exception is not retried."""
        from agents.backends.base import _retry_with_backoff

        mock_fn = MagicMock(side_effect=ValueError("unexpected"))

        with patch("time.sleep") as mock_sleep:
            with pytest.raises(ValueError, match="unexpected"):
                _retry_with_backoff(mock_fn, max_retries=3, base_delay=1.0)

        assert mock_fn.call_count == 1
        mock_sleep.assert_not_called()

    def test_max_retries_zero_raises_immediately(self):
        """With max_retries=0, raises on the first failure without sleeping."""
        from agents.backends.base import _retry_with_backoff

        mock_fn = MagicMock(side_effect=[_conn_error()])

        with patch("time.sleep") as mock_sleep:
            with pytest.raises(openai.APIConnectionError):
                _retry_with_backoff(mock_fn, max_retries=0, base_delay=1.0)

        assert mock_fn.call_count == 1
        mock_sleep.assert_not_called()

    def test_warning_logged_on_retry(self, caplog):
        """A WARNING is emitted for each retry attempt."""
        import logging
        from agents.backends.base import _retry_with_backoff

        valid_response = MagicMock()
        mock_fn = MagicMock(side_effect=[_conn_error(), valid_response])

        with patch("time.sleep"):
            with caplog.at_level(logging.WARNING, logger="agents.backends.base"):
                _retry_with_backoff(mock_fn, max_retries=3, base_delay=1.0)

        assert any("Retrying" in r.message for r in caplog.records)
        warning_record = next(r for r in caplog.records if "Retrying" in r.message)
        assert "1/3" in warning_record.message
        assert "APIConnectionError" in warning_record.message

    def test_error_logged_on_exhaustion(self, caplog):
        """An ERROR is logged when all retries are exhausted."""
        import logging
        from agents.backends.base import _retry_with_backoff

        # max_retries=1 → 2 total calls
        mock_fn = MagicMock(side_effect=[_conn_error(), _conn_error()])

        with patch("time.sleep"):
            with caplog.at_level(logging.ERROR, logger="agents.backends.base"):
                with pytest.raises(openai.APIConnectionError):
                    _retry_with_backoff(mock_fn, max_retries=1, base_delay=1.0)

        assert any(r.levelno == logging.ERROR for r in caplog.records)
