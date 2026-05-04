"""Tests for OllamaBackend."""
from __future__ import annotations
from unittest.mock import MagicMock, patch
import pytest


def _mock_response(content: str):
    return MagicMock(
        choices=[MagicMock(message=MagicMock(content=content, tool_calls=None))]
    )


def test_ollama_strips_prefix():
    from agents.backends.ollama import OllamaBackend
    with patch("agents.backends.ollama.OpenAI"):
        b = OllamaBackend(model="ollama/qwen3.6")
    assert b.model == "qwen3.6"


def test_ollama_extra_body_think_false():
    from agents.backends.ollama import OllamaBackend
    with patch("agents.backends.ollama.OpenAI"):
        b = OllamaBackend(model="ollama/qwen3.6", think=False)
    assert b._extra_body() == {"extra_body": {"think": False}}


def test_ollama_extra_body_think_true_no_preserve():
    from agents.backends.ollama import OllamaBackend
    with patch("agents.backends.ollama.OpenAI"):
        b = OllamaBackend(model="ollama/qwen3.6", think=True, preserve_thinking=False)
    assert b._extra_body() == {}


def test_ollama_extra_body_think_true_preserve():
    """think=True + preserve_thinking=True: no extra_body; reasoning captured in _stream_call."""
    from agents.backends.ollama import OllamaBackend
    with patch("agents.backends.ollama.OpenAI"):
        b = OllamaBackend(model="ollama/qwen3.6", think=True, preserve_thinking=True)
    assert b._extra_body() == {}  # reasoning_content captured via model_extra in _stream_call


def test_ollama_post_process_strips_think_blocks():
    from agents.backends.ollama import OllamaBackend
    with patch("agents.backends.ollama.OpenAI"):
        b = OllamaBackend(model="ollama/qwen3.6", think=True, preserve_thinking=False)
    result = b._post_process("<think>internal reasoning</think>Final answer")
    assert result == "Final answer"


def test_ollama_post_process_preserves_when_enabled():
    from agents.backends.ollama import OllamaBackend
    with patch("agents.backends.ollama.OpenAI"):
        b = OllamaBackend(model="ollama/qwen3.6", think=True, preserve_thinking=True)
    text = "<think>reason</think>Answer"
    assert b._post_process(text) == text


def test_ollama_call_non_streaming():
    from agents.backends.ollama import OllamaBackend
    with patch("agents.backends.ollama.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_response("reply")
        mock_cls.return_value = mock_client
        b = OllamaBackend(model="ollama/qwen3.6", stream=False)
    result = b.call([{"role": "user", "content": "hi"}])
    assert result == "reply"


def test_ollama_call_streaming():
    from agents.backends.ollama import OllamaBackend

    chunk1 = MagicMock(choices=[MagicMock(delta=MagicMock(content="hel"))])
    chunk2 = MagicMock(choices=[MagicMock(delta=MagicMock(content="lo"))])

    with patch("agents.backends.ollama.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = iter([chunk1, chunk2])
        mock_cls.return_value = mock_client
        b = OllamaBackend(model="ollama/qwen3.6", stream=True)
    result = b.call([{"role": "user", "content": "hi"}])
    assert result == "hello"


def _make_thinking_chunks(reasoning: str, content: str):
    """Build streaming chunks that simulate Ollama thinking model output.

    Reasoning content goes to model_extra['reasoning_content']; actual response
    goes to delta.content — matching real Ollama thinking model behaviour.
    """
    def _reasoning_chunk(text):
        delta = MagicMock(content=None)
        delta.model_extra = {"reasoning_content": text}
        return MagicMock(choices=[MagicMock(delta=delta)])

    def _content_chunk(text):
        delta = MagicMock(content=text)
        delta.model_extra = {}
        return MagicMock(choices=[MagicMock(delta=delta)])

    return [_reasoning_chunk(reasoning), _content_chunk(content)]


def test_ollama_stream_thinking_preserve():
    """preserve_thinking=True: reasoning_content wrapped in <think> tags + actual response."""
    from agents.backends.ollama import OllamaBackend
    chunks = _make_thinking_chunks("let me think", "the answer")
    with patch("agents.backends.ollama.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = lambda *a, **kw: iter(chunks)
        mock_cls.return_value = mock_client
        b = OllamaBackend(model="ollama/thinker", think=True, preserve_thinking=True, stream=True)
    result = b.call([{"role": "user", "content": "hi"}])
    assert "<think>let me think</think>" in result
    assert "the answer" in result


def test_ollama_stream_thinking_no_preserve():
    """preserve_thinking=False: reasoning_content ignored, only delta.content returned."""
    from agents.backends.ollama import OllamaBackend
    chunks = _make_thinking_chunks("internal reasoning", "clean response")
    with patch("agents.backends.ollama.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = lambda *a, **kw: iter(chunks)
        mock_cls.return_value = mock_client
        b = OllamaBackend(model="ollama/thinker", think=True, preserve_thinking=False, stream=True)
    result = b.call([{"role": "user", "content": "hi"}])
    assert result == "clean response"
    assert "internal reasoning" not in result
    assert "<think>" not in result


def test_ollama_stream_thinking_no_content_with_preserve():
    """When model produces only reasoning and no actual content, preserve_thinking still returns reasoning."""
    from agents.backends.ollama import OllamaBackend

    def _reasoning_chunk(text):
        delta = MagicMock(content=None)
        delta.model_extra = {"reasoning_content": text}
        return MagicMock(choices=[MagicMock(delta=delta)])

    chunks = [_reasoning_chunk("full design here")]
    with patch("agents.backends.ollama.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = lambda *a, **kw: iter(chunks)
        mock_cls.return_value = mock_client
        b = OllamaBackend(model="ollama/thinker", think=True, preserve_thinking=True, stream=True)
    result = b.call([{"role": "user", "content": "hi"}])
    assert "full design here" in result  # reasoning content captured, not lost



def test_ollama_stream_empty_raises_server_error():
    """When stream returns zero chunks (LiteLLM timed out server-side), raise ConnectionError
    instead of returning empty string — lets FallbackLLMBackend switch backends."""
    from agents.backends.ollama import OllamaBackend

    with patch("agents.backends.ollama.OpenAI") as mock_cls:
        mock_client = MagicMock()
        # Return empty stream (0 chunks) — simulates LiteLLM closing stream with no output
        mock_client.chat.completions.create.side_effect = lambda *a, **kw: iter([])
        mock_cls.return_value = mock_client
        b = OllamaBackend(model="ollama/thinker", think=True, stream=True, max_retries=0)
    with pytest.raises(ConnectionError, match="no content"):
        b.call([{"role": "user", "content": "hi"}])
