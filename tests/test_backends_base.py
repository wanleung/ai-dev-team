"""Tests for agents/backends/base.py — LLMBackend ABC and retry utility."""
from __future__ import annotations
from unittest.mock import MagicMock, patch
import pytest


def test_retry_succeeds_first_try():
    from agents.backends.base import _retry_with_backoff
    assert _retry_with_backoff(lambda: "ok", max_retries=3) == "ok"


def test_retry_retries_on_rate_limit_then_succeeds():
    import openai
    from agents.backends.base import _retry_with_backoff
    calls = []
    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise openai.RateLimitError(
                "rate limit", response=MagicMock(status_code=429, headers={}), body=None
            )
        return "ok"
    with patch("time.sleep"):
        result = _retry_with_backoff(fn, max_retries=5, base_delay=0.01)
    assert result == "ok"
    assert len(calls) == 3


def test_retry_raises_non_retryable_immediately():
    import openai
    from agents.backends.base import _retry_with_backoff
    calls = []
    def fn():
        calls.append(1)
        raise openai.AuthenticationError(
            "bad key", response=MagicMock(status_code=401, headers={}), body=None
        )
    with pytest.raises(openai.AuthenticationError):
        _retry_with_backoff(fn, max_retries=3)
    assert len(calls) == 1  # no retries


def test_retry_exhausts_retries_and_raises():
    import openai
    from agents.backends.base import _retry_with_backoff
    def fn():
        raise openai.APIConnectionError(request=MagicMock())
    with patch("time.sleep"):
        with pytest.raises(openai.APIConnectionError):
            _retry_with_backoff(fn, max_retries=2, base_delay=0.01)


def test_fallback_errors_includes_connection_errors():
    from agents.backends.base import FALLBACK_ERRORS
    import httpx
    assert issubclass(ConnectionError, FALLBACK_ERRORS)
    assert issubclass(httpx.ConnectError, FALLBACK_ERRORS)
    assert issubclass(httpx.TimeoutException, FALLBACK_ERRORS)


def test_llm_backend_is_abstract():
    from agents.backends.base import LLMBackend
    with pytest.raises(TypeError):
        LLMBackend()  # cannot instantiate abstract class


def test_openai_compatible_backend_call():
    from agents.backends.base import OpenAICompatibleBackend
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="hello", tool_calls=None))]
    )
    backend = OpenAICompatibleBackend(model="gpt-4.1", client=mock_client)
    messages = [{"role": "user", "content": "hi"}]
    result = backend.call(messages)
    assert result == "hello"
    mock_client.chat.completions.create.assert_called_once()


def test_openai_compatible_backend_call_with_tools_no_tool_calls():
    from agents.backends.base import OpenAICompatibleBackend
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="done", tool_calls=None))]
    )
    mock_tools = MagicMock()
    mock_tools.schemas = []
    backend = OpenAICompatibleBackend(model="gpt-4.1", client=mock_client)
    result = backend.call_with_tools([{"role": "user", "content": "hi"}], mock_tools)
    assert result == "done"


def test_openai_compatible_backend_supports_tools():
    from agents.backends.base import OpenAICompatibleBackend
    backend = OpenAICompatibleBackend(model="x", client=MagicMock())
    assert backend.supports_tools() is True
