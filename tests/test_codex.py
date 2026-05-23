"""Unit tests for Codex CLI subprocess backend."""
import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest


def _make_popen_mock(returncode=0, stdout="Here is the response.", stderr=""):
    """Return a mock Popen instance with communicate() pre-configured."""
    proc = MagicMock()
    proc.communicate.return_value = (stdout, stderr)
    proc.returncode = returncode
    proc.poll.return_value = returncode
    proc.pid = 99999
    return proc


# ── CodexBackend unit tests ───────────────────────────────────────────────────

def test_strips_codex_prefix():
    """CodexBackend strips 'codex/' prefix; remainder becomes --model value."""
    from agents.backends.codex import CodexBackend
    backend = CodexBackend(model="codex/codex-mini-latest")
    assert backend.model == "codex-mini-latest"


def test_does_not_support_tools():
    """CodexBackend.supports_tools() returns False."""
    from agents.backends.codex import CodexBackend
    backend = CodexBackend(model="codex/codex-mini-latest")
    assert backend.supports_tools() is False


def test_call_success():
    """CodexBackend.call() returns stripped stdout on success."""
    from agents.backends.codex import CodexBackend
    backend = CodexBackend(model="codex/codex-mini-latest")
    proc = _make_popen_mock(stdout="The answer is 42.")

    with patch("agents.backends.codex.subprocess.Popen", return_value=proc):
        result = backend.call([{"role": "user", "content": "What is the answer?"}])

    assert result == "The answer is 42."


def test_call_uses_correct_command():
    """CodexBackend.call() invokes: codex exec --approval-mode full-auto --model <model> <prompt>"""
    from agents.backends.codex import CodexBackend
    backend = CodexBackend(model="codex/codex-mini-latest")
    proc = _make_popen_mock(stdout="ok")

    with patch("agents.backends.codex.subprocess.Popen", return_value=proc) as mock_popen:
        backend.call([{"role": "user", "content": "Hello"}])

    cmd = mock_popen.call_args[0][0]
    assert cmd[0] == "codex"
    assert "exec" in cmd
    assert "--approval-mode" in cmd
    assert "full-auto" in cmd
    assert "--model" in cmd
    assert "codex-mini-latest" in cmd


def test_codex_bin_override():
    """CODEX_BIN env var overrides the codex binary path."""
    from agents.backends.codex import CodexBackend
    backend = CodexBackend(model="codex/codex-mini-latest")
    proc = _make_popen_mock(stdout="ok")

    with patch.dict(os.environ, {"CODEX_BIN": "/opt/codex/bin/codex"}):
        with patch("agents.backends.codex.subprocess.Popen", return_value=proc) as mock_popen:
            backend.call([{"role": "user", "content": "Hello"}])

    cmd = mock_popen.call_args[0][0]
    assert cmd[0] == "/opt/codex/bin/codex"


def test_call_timeout_retries():
    """CodexBackend retries on TimeoutExpired and raises after max_retries."""
    from agents.backends.codex import CodexBackend
    backend = CodexBackend(model="codex/codex-mini-latest", max_retries=1)
    proc = _make_popen_mock()
    proc.communicate.side_effect = subprocess.TimeoutExpired(cmd="codex", timeout=600)
    proc.poll.return_value = None  # process still running

    with patch("agents.backends.codex.subprocess.Popen", return_value=proc):
        with pytest.raises(subprocess.TimeoutExpired):
            backend.call([{"role": "user", "content": "Hello"}])

    # With max_retries=1, communicate() should be called twice (1 attempt + 1 retry)
    assert proc.communicate.call_count == 2


def test_factory_routes_codex_prefix():
    """create_backend routes 'codex/...' models to CodexBackend."""
    from agents.backends.factory import create_backend
    from agents.backends.codex import CodexBackend
    backend = create_backend({"model": "codex/codex-mini-latest"})
    assert isinstance(backend, CodexBackend)
