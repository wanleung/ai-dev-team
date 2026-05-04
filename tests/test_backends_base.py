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
    import openai
    assert issubclass(ConnectionError, FALLBACK_ERRORS)
    assert issubclass(httpx.ConnectError, FALLBACK_ERRORS)
    assert issubclass(httpx.TimeoutException, FALLBACK_ERRORS)
    assert issubclass(openai.APIConnectionError, FALLBACK_ERRORS)
    assert issubclass(openai.APITimeoutError, FALLBACK_ERRORS)
    assert issubclass(openai.InternalServerError, FALLBACK_ERRORS)


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


def test_openai_compatible_backend_call_with_tools_executes_tool():
    from agents.backends.base import OpenAICompatibleBackend
    mock_client = MagicMock()
    tool_call = MagicMock()
    tool_call.id = "tc1"
    tool_call.function.name = "my_tool"
    tool_call.function.arguments = '{"x": 1}'

    mock_client.chat.completions.create.side_effect = [
        MagicMock(choices=[MagicMock(message=MagicMock(content="", tool_calls=[tool_call]))]),
        MagicMock(choices=[MagicMock(message=MagicMock(content="final", tool_calls=None))]),
    ]
    mock_tools = MagicMock()
    mock_tools.schemas = []
    mock_tools.call.return_value = "tool_result"

    backend = OpenAICompatibleBackend(model="gpt-4.1", client=mock_client)
    result = backend.call_with_tools([{"role": "user", "content": "go"}], mock_tools)

    assert result == "final"
    mock_tools.call.assert_called_once_with("my_tool", '{"x": 1}')
    assert mock_client.chat.completions.create.call_count == 2


def test_openai_compatible_backend_max_turns_forces_final_response():
    from agents.backends.base import OpenAICompatibleBackend
    mock_client = MagicMock()
    tool_call = MagicMock()
    tool_call.id = "tc1"
    tool_call.function.name = "tool"
    tool_call.function.arguments = "{}"

    always_tool = MagicMock(choices=[MagicMock(message=MagicMock(content="", tool_calls=[tool_call]))])
    final = MagicMock(choices=[MagicMock(message=MagicMock(content="forced", tool_calls=None))])
    mock_client.chat.completions.create.side_effect = [always_tool] * 2 + [final]

    mock_tools = MagicMock(schemas=[], call=MagicMock(return_value="r"))
    backend = OpenAICompatibleBackend(model="x", client=mock_client)
    result = backend.call_with_tools([{"role": "user", "content": "go"}], mock_tools, max_turns=2)

    assert result == "forced"


def test_base_stream_call_assembles_chunks():
    """OpenAICompatibleBackend._stream_call() collects chunks into a string."""
    from agents.backends.base import OpenAICompatibleBackend

    chunk1 = MagicMock(choices=[MagicMock(delta=MagicMock(content="Hel"))])
    chunk2 = MagicMock(choices=[MagicMock(delta=MagicMock(content="lo"))])
    chunk3 = MagicMock(choices=[MagicMock(delta=MagicMock(content=None))])  # None delta skipped

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = iter([chunk1, chunk2, chunk3])

    b = OpenAICompatibleBackend(model="gpt-4.1", client=mock_client, stream=True)
    result = b._stream_call([{"role": "user", "content": "hi"}])
    assert result == "Hello"
    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert call_kwargs.get("stream") is True


def test_openai_compatible_backend_call_dispatches_to_stream_call():
    from agents.backends.base import OpenAICompatibleBackend
    mock_client = MagicMock()
    chunk = MagicMock(choices=[MagicMock(delta=MagicMock(content="hi"))])
    mock_client.chat.completions.create.return_value = iter([chunk])
    backend = OpenAICompatibleBackend(model="gpt-4.1", client=mock_client, stream=True)
    result = backend.call([{"role": "user", "content": "hello"}])
    assert result == "hi"
    assert mock_client.chat.completions.create.call_args.kwargs.get("stream") is True
