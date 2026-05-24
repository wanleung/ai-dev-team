"""Tests for FallbackLLMBackend."""
from __future__ import annotations
from unittest.mock import MagicMock
import pytest


def _make_backend(reply: str = "ok", raises=None, supports_tools: bool = True):
    """Create a mock LLMBackend."""
    from agents.backends.base import LLMBackend

    class MockBackend(LLMBackend):
        def __init__(self, model, reply, raises, _supports_tools):
            self.model = model
            self._reply = reply
            self._raises = raises
            self._supports_tools = _supports_tools
            self.call_count = 0
            self.call_with_tools_count = 0

        def supports_tools(self):
            return self._supports_tools

        def call(self, messages, run_id=None, on_token=None):
            self.call_count += 1
            if self._raises:
                raise self._raises
            return self._reply

        def call_with_tools(self, messages, tools, max_turns=8):
            self.call_with_tools_count += 1
            if self._raises:
                raise self._raises
            return self._reply

    return MockBackend(model=f"mock/{reply}", reply=reply, raises=raises, _supports_tools=supports_tools)


def test_fallback_uses_first_backend_when_healthy():
    from agents.backends.fallback import FallbackLLMBackend
    primary = _make_backend("primary_reply")
    secondary = _make_backend("secondary_reply")
    fb = FallbackLLMBackend([primary, secondary])
    result = fb.call([{"role": "user", "content": "hi"}])
    assert result == "primary_reply"
    assert primary.call_count == 1
    assert secondary.call_count == 0


def test_fallback_switches_on_connection_error(caplog):
    import logging
    from agents.backends.fallback import FallbackLLMBackend
    primary = _make_backend(raises=ConnectionError("refused"))
    secondary = _make_backend("secondary_reply")
    fb = FallbackLLMBackend([primary, secondary])
    with caplog.at_level(logging.WARNING, logger="agents.backends.fallback"):
        result = fb.call([{"role": "user", "content": "hi"}])
    assert result == "secondary_reply"
    assert "⚠️" in caplog.text


def test_fallback_switches_on_httpx_connect_error(caplog):
    import httpx
    import logging
    from agents.backends.fallback import FallbackLLMBackend
    primary = _make_backend(raises=httpx.ConnectError("connect failed"))
    secondary = _make_backend("from_secondary")
    fb = FallbackLLMBackend([primary, secondary])
    with caplog.at_level(logging.WARNING, logger="agents.backends.fallback"):
        result = fb.call([{"role": "user", "content": "hi"}])
    assert result == "from_secondary"
    assert "⚠️" in caplog.text


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
        def call(self, messages, run_id=None, on_token=None):
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
    # verify the right method was dispatched on each backend
    assert primary.call_count == 0
    assert primary.call_with_tools_count == 1
    assert secondary.call_count == 0
    assert secondary.call_with_tools_count == 1


def test_fallback_mixed_tool_support_warns_and_skips_in_call_with_tools():
    """Mixed tool-capability is allowed but non-tool backends are skipped for call_with_tools."""
    from agents.backends.fallback import FallbackLLMBackend
    tool_backend = _make_backend("tool_reply", supports_tools=True)
    non_tool_backend = _make_backend("plain_reply", supports_tools=False)
    # Construction should not raise
    fb = FallbackLLMBackend([non_tool_backend, tool_backend])
    assert fb.supports_tools() is False  # first backend determines supports_tools()

    # call_with_tools must skip non-tool backends and use the tool-capable one
    registry = MagicMock()
    tool_backend.call_with_tools = MagicMock(return_value="tool result")
    non_tool_backend.call_with_tools = MagicMock(return_value="should not be called")
    result = fb.call_with_tools([{"role": "user", "content": "hi"}], registry)
    assert result == "tool result"
    tool_backend.call_with_tools.assert_called_once()
    non_tool_backend.call_with_tools.assert_not_called()


# ---------------------------------------------------------------------------
# QuotaExhaustedError: permanent dead-backend tracking
# ---------------------------------------------------------------------------

def test_quota_exhausted_marks_backend_dead_and_falls_back():
    """QuotaExhaustedError should fall back AND permanently skip that backend."""
    from agents.backends.base import QuotaExhaustedError
    from agents.backends.fallback import FallbackLLMBackend
    primary = _make_backend(raises=QuotaExhaustedError("free tier exhausted"))
    secondary = _make_backend("secondary_reply")
    fb = FallbackLLMBackend([primary, secondary])
    result = fb.call([{"role": "user", "content": "hi"}])
    assert result == "secondary_reply"
    assert id(primary) in fb._dead


def test_quota_exhausted_backend_skipped_on_subsequent_calls():
    """Dead (quota-exhausted) backend is skipped without being called again."""
    from agents.backends.base import QuotaExhaustedError
    from agents.backends.fallback import FallbackLLMBackend
    primary = _make_backend(raises=QuotaExhaustedError("exhausted"))
    secondary = _make_backend("reply")
    fb = FallbackLLMBackend([primary, secondary])
    fb.call([{"role": "user", "content": "first"}])
    primary.call_count = 0  # reset counter after first call
    fb.call([{"role": "user", "content": "second"}])
    assert primary.call_count == 0  # must NOT have been called again


def test_connection_error_does_not_mark_backend_dead():
    """Plain ConnectionError should fall back but not mark backend permanently dead."""
    from agents.backends.fallback import FallbackLLMBackend
    primary = _make_backend(raises=ConnectionError("temporary failure"))
    secondary = _make_backend("reply")
    fb = FallbackLLMBackend([primary, secondary])
    fb.call([{"role": "user", "content": "hi"}])
    assert id(primary) not in fb._dead
