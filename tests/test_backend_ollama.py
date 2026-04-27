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
    from agents.backends.ollama import OllamaBackend
    with patch("agents.backends.ollama.OpenAI"):
        b = OllamaBackend(model="ollama/qwen3.6", think=True, preserve_thinking=True)
    assert b._extra_body() == {"extra_body": {"options": {"preserve_thinking": True}}}


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
