"""Tests for OpenCodeBackend (subprocess)."""
import subprocess
from unittest.mock import MagicMock, patch
import pytest


def test_opencode_strips_prefix():
    from agents.backends.opencode import OpenCodeBackend
    b = OpenCodeBackend(model="opencode/anthropic/claude-3-5-sonnet")
    assert b.model == "anthropic/claude-3-5-sonnet"


def test_opencode_supports_tools_false():
    from agents.backends.opencode import OpenCodeBackend
    b = OpenCodeBackend(model="opencode/anthropic/claude-3-5-sonnet")
    assert b.supports_tools() is False


def test_opencode_call_with_tools_raises():
    from agents.backends.opencode import OpenCodeBackend
    b = OpenCodeBackend(model="opencode/anthropic/claude-3-5-sonnet")
    with pytest.raises(NotImplementedError, match="opencode"):
        b.call_with_tools([], MagicMock())


def test_opencode_call_success():
    from agents.backends.opencode import OpenCodeBackend
    b = OpenCodeBackend(model="opencode/anthropic/claude-3-5-sonnet")
    mock_result = MagicMock(returncode=0, stdout="The answer\n", stderr="")
    with patch("subprocess.run", return_value=mock_result):
        result = b.call([{"role": "user", "content": "What is 2+2?"}])
    assert result == "The answer"


def test_opencode_call_retries_on_failure():
    from agents.backends.opencode import OpenCodeBackend
    b = OpenCodeBackend(model="opencode/x/y", max_retries=2)
    calls = []
    def fake_run(*args, **kwargs):
        calls.append(1)
        if len(calls) < 3:
            raise subprocess.TimeoutExpired(cmd=args[0], timeout=600)
        return MagicMock(returncode=0, stdout="ok", stderr="")
    with patch("subprocess.run", side_effect=fake_run):
        with patch("time.sleep"):
            result = b.call([{"role": "user", "content": "hi"}])
    assert result == "ok"
    assert len(calls) == 3
