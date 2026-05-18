"""Tests for GrokBackend."""
from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from agents.backends.grok import GrokBackend


def _make_proc(lines: list[str], returncode: int = 0, stderr: str = "") -> MagicMock:
    """Return a mock Popen process whose stdout yields the given JSON lines."""
    proc = MagicMock()
    proc.stdout = iter(line + "\n" for line in lines)
    proc.stderr.read.return_value = stderr
    proc.returncode = returncode
    proc.wait.return_value = returncode
    return proc


def _msgs(text: str = "Hello") -> list[dict]:
    return [{"role": "user", "content": text}]


class TestGrokBackend:
    # ------------------------------------------------------------------ #
    # Core streaming behaviour (tested via _run_once → Popen mock)        #
    # ------------------------------------------------------------------ #

    def setup_method(self):
        """Create a shared backend instance with generous retry budget for timeout test."""
        self.backend = GrokBackend(model="grok/grok-4.3", max_retries=2)

    def test_call_collects_text_events(self):
        """Multiple text events are assembled into a single reply string."""
        events = [
            json.dumps({"type": "step_start"}),
            json.dumps({"type": "text", "content": "Hello "}),
            json.dumps({"type": "text", "content": "world"}),
            json.dumps({"type": "step_finish"}),
        ]
        proc = _make_proc(events)
        with patch("subprocess.Popen", return_value=proc):
            backend = GrokBackend(model="grok/grok-4.3")
            result = backend.call(_msgs())
        assert result == "Hello world"

    def test_call_streams_on_token(self):
        """on_token is called once per text event chunk."""
        events = [
            json.dumps({"type": "text", "content": "chunk1"}),
            json.dumps({"type": "text", "content": "chunk2"}),
        ]
        proc = _make_proc(events)
        tokens: list[str] = []
        with patch("subprocess.Popen", return_value=proc):
            backend = GrokBackend(model="grok/grok-4.3")
            backend.call(_msgs(), on_token=tokens.append)
        assert tokens == ["chunk1", "chunk2"]

    def test_call_raises_on_error_event(self):
        """A grok error event raises RuntimeError with the error message."""
        events = [json.dumps({"type": "error", "message": "API key missing"})]
        proc = _make_proc(events)
        with patch("subprocess.Popen", return_value=proc):
            backend = GrokBackend(model="grok/grok-4.3", max_retries=0)
            with pytest.raises(RuntimeError, match="API key missing"):
                backend.call(_msgs())

    def test_call_raises_on_empty_output(self):
        """No text events → RuntimeError('Empty response from grok')."""
        events = [json.dumps({"type": "step_start"})]
        proc = _make_proc(events)
        with patch("subprocess.Popen", return_value=proc):
            backend = GrokBackend(model="grok/grok-4.3", max_retries=0)
            with pytest.raises(RuntimeError, match="Empty response from grok"):
                backend.call(_msgs())

    def test_call_raises_on_nonzero_exit(self):
        """Non-zero exit code raises RuntimeError with stderr snippet."""
        proc = _make_proc([], returncode=1, stderr="connection refused")
        with patch("subprocess.Popen", return_value=proc):
            backend = GrokBackend(model="grok/grok-4.3", max_retries=0)
            with pytest.raises(RuntimeError, match="grok exited 1"):
                backend.call(_msgs())

    # ------------------------------------------------------------------ #
    # Retry logic (tested by patching _run_once)                          #
    # ------------------------------------------------------------------ #

    def test_call_retries_on_runtime_error(self):
        """RuntimeError triggers retry; succeeds on second attempt."""
        call_count = [0]

        def fake_run_once(cmd, on_token):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("grok exited 1: connection refused")
            return "recovered"

        with patch.object(GrokBackend, "_run_once", side_effect=fake_run_once):
            with patch("time.sleep"):
                backend = GrokBackend(model="grok/grok-4.3", max_retries=2)
                result = backend.call(_msgs())
        assert result == "recovered"
        assert call_count[0] == 2

    def test_call_raises_after_all_retries_exhausted(self):
        """RuntimeError is re-raised when max_retries is exhausted."""
        with patch.object(
            GrokBackend, "_run_once", side_effect=RuntimeError("persistent failure")
        ):
            with patch("time.sleep"):
                backend = GrokBackend(model="grok/grok-4.3", max_retries=1)
                with pytest.raises(RuntimeError, match="persistent failure"):
                    backend.call(_msgs())

    def test_call_retries_on_timeout(self):
        """call() retries subprocess.TimeoutExpired and succeeds on second attempt."""
        with patch.object(self.backend, "_run_once", side_effect=[
            subprocess.TimeoutExpired(cmd="grok", timeout=600),
            "response after timeout retry",
        ]) as mock_run:
            with patch("time.sleep"):
                result = self.backend.call(messages=[{"role": "user", "content": "hi"}])
        assert result == "response after timeout retry"
        assert mock_run.call_count == 2

    # ------------------------------------------------------------------ #
    # Tool calling                                                         #
    # ------------------------------------------------------------------ #

    def test_supports_tools_returns_false(self):
        backend = GrokBackend(model="grok/grok-4.3")
        assert backend.supports_tools() is False

    def test_call_with_tools_not_supported(self):
        """call_with_tools raises NotImplementedError."""
        backend = GrokBackend(model="grok/grok-4.3")
        with pytest.raises(NotImplementedError):
            backend.call_with_tools([], MagicMock())


class TestGrokBackendFactory:
    def test_factory_creates_grok_backend(self):
        """create_backend with grok/ prefix returns a GrokBackend."""
        from agents.backends.factory import create_backend
        backend = create_backend({"model": "grok/grok-4.3"})
        assert isinstance(backend, GrokBackend)
        assert backend.model == "grok-4.3"

    def test_factory_passes_kwargs_to_grok_backend(self):
        """Extra kwargs (timeout, max_retries) are forwarded to GrokBackend."""
        from agents.backends.factory import create_backend
        backend = create_backend({"model": "grok/grok-4.3", "timeout": 120, "max_retries": 1})
        assert isinstance(backend, GrokBackend)
        assert backend._timeout == 120
        assert backend._max_retries == 1
