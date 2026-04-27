"""Tests for FallbackLLMBackend."""
from __future__ import annotations
from unittest.mock import MagicMock
import pytest


def _make_backend(reply: str = "ok", raises=None):
    """Create a mock LLMBackend."""
    from agents.backends.base import LLMBackend

    class MockBackend(LLMBackend):
        def __init__(self, model, reply, raises):
            self.model = model
            self._reply = reply
            self._raises = raises
            self.call_count = 0

        def call(self, messages):
            self.call_count += 1
            if self._raises:
                raise self._raises
            return self._reply

        def call_with_tools(self, messages, tools, max_turns=8):
            self.call_count += 1
            if self._raises:
                raise self._raises
            return self._reply

    return MockBackend(model=f"mock/{reply}", reply=reply, raises=raises)


def test_fallback_uses_first_backend_when_healthy():
    from agents.backends.fallback import FallbackLLMBackend
    primary = _make_backend("primary_reply")
    secondary = _make_backend("secondary_reply")
    fb = FallbackLLMBackend([primary, secondary])
    result = fb.call([{"role": "user", "content": "hi"}])
    assert result == "primary_reply"
    assert primary.call_count == 1
    assert secondary.call_count == 0


def test_fallback_switches_on_connection_error(capsys):
    from agents.backends.fallback import FallbackLLMBackend
    primary = _make_backend(raises=ConnectionError("refused"))
    secondary = _make_backend("secondary_reply")
    fb = FallbackLLMBackend([primary, secondary])
    result = fb.call([{"role": "user", "content": "hi"}])
    assert result == "secondary_reply"
    captured = capsys.readouterr()
    assert "⚠️" in captured.out


def test_fallback_switches_on_httpx_connect_error(capsys):
    import httpx
    from agents.backends.fallback import FallbackLLMBackend
    primary = _make_backend(raises=httpx.ConnectError("connect failed"))
    secondary = _make_backend("from_secondary")
    fb = FallbackLLMBackend([primary, secondary])
    result = fb.call([{"role": "user", "content": "hi"}])
    assert result == "from_secondary"
    assert "⚠️" in capsys.readouterr().out


def test_fallback_does_not_switch_on_auth_error():
    import openai
    from agents.backends.fallback import FallbackLLMBackend
    primary = _make_backend(
        raises=openai.AuthenticationError(
            "bad key", response=MagicMock(status_code=401, headers={}), body=None
        )
    )
    secondary = _make_backend("secondary")
    fb = FallbackLLMBackend([primary, secondary])
    with pytest.raises(openai.AuthenticationError):
        fb.call([{"role": "user", "content": "hi"}])
    assert secondary.call_count == 0


def test_fallback_exhausts_all_backends_and_raises():
    from agents.backends.fallback import FallbackLLMBackend
    backends = [
        _make_backend(raises=ConnectionError("err1")),
        _make_backend(raises=ConnectionError("err2")),
        _make_backend(raises=ConnectionError("err3")),
    ]
    fb = FallbackLLMBackend(backends)
    with pytest.raises(ConnectionError):
        fb.call([{"role": "user", "content": "hi"}])


def test_fallback_replays_history_on_secondary():
    from agents.backends.fallback import FallbackLLMBackend
    received_messages = []

    class CapturingBackend:
        model = "capturing"
        def call(self, messages):
            received_messages.extend(messages)
            return "captured"
        def call_with_tools(self, messages, tools, max_turns=8):
            return "captured"
        def supports_tools(self):
            return True

    primary = _make_backend(raises=ConnectionError("err"))
    fb = FallbackLLMBackend([primary, CapturingBackend()])
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "prev"},
        {"role": "assistant", "content": "prev reply"},
        {"role": "user", "content": "new"},
    ]
    fb.call(messages)
    assert received_messages == messages  # full history passed to secondary


def test_fallback_model_is_primary_model():
    from agents.backends.fallback import FallbackLLMBackend
    primary = _make_backend("p")
    primary.model = "primary-model"
    fb = FallbackLLMBackend([primary, _make_backend("s")])
    assert fb.model == "primary-model"


def test_fallback_call_with_tools_switches():
    from agents.backends.fallback import FallbackLLMBackend
    primary = _make_backend(raises=ConnectionError("err"))
    secondary = _make_backend("tool_reply")
    fb = FallbackLLMBackend([primary, secondary])
    result = fb.call_with_tools([{"role": "user", "content": "hi"}], MagicMock())
    assert result == "tool_reply"
