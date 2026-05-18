# GrokBackend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `GrokBackend` — a streaming subprocess backend for xAI's grok-cli — so pipelines can use `model: grok/<model-name>` to drive Grok models with live X/web search.

**Architecture:** `GrokBackend` extends `LLMBackend` (not `OpenAICompatibleBackend`). It spawns `grok --prompt "..." --format json --model <model> --directory <dir>` as a subprocess, reads stdout line-by-line as newline-delimited JSON events, calls `on_token` per `text` event, and retries on `RuntimeError` or `TimeoutExpired`. A background thread drains stderr to prevent pipe deadlock. A `threading.Timer` kills the process on timeout. Factory routes `grok/` prefix to this class.

**Tech Stack:** Python stdlib (`subprocess`, `threading`, `json`, `re`), pytest with `unittest.mock`

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `agents/backends/grok.py` | `GrokBackend` class — subprocess + JSON streaming |
| Modify | `agents/backends/factory.py` | Register `grok/` prefix |
| Create | `tests/test_grok_backend.py` | 7 tests covering all behaviours |

---

## Task 1: Write failing tests for GrokBackend

**Files:**
- Create: `tests/test_grok_backend.py`

- [ ] **Step 1: Create the test file**

```python
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
        """Extra kwargs (timeout, directory) are forwarded to GrokBackend."""
        from agents.backends.factory import create_backend
        backend = create_backend({"model": "grok/grok-4.3", "timeout": 120, "max_retries": 1})
        assert isinstance(backend, GrokBackend)
        assert backend._timeout == 120
        assert backend._max_retries == 1
```

- [ ] **Step 2: Run tests to confirm they fail (module not found)**

```bash
cd /path/to/worktree
python3 -m pytest tests/test_grok_backend.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'agents.backends.grok'`

- [ ] **Step 3: Commit the failing tests**

```bash
git add tests/test_grok_backend.py
git commit -m "test(grok): add failing tests for GrokBackend"
```

---

## Task 2: Implement GrokBackend

**Files:**
- Create: `agents/backends/grok.py`

- [ ] **Step 1: Create the implementation file**

```python
"""Grok CLI subprocess backend."""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from agents.backends.base import LLMBackend

if TYPE_CHECKING:
    from tools.registry import ToolRegistry

# Broad ANSI escape stripping — CSI, OSC, and Fe sequences.
_ANSI_ESCAPE = re.compile(
    r'\x1b(?:'
    r'\[[0-9;?]*[A-Za-z]'               # CSI sequences
    r'|\][^\x07\x1b]*(?:\x07|\x1b\\)'  # OSC sequences
    r'|[@-_]'                            # Fe escape sequences
    r')'
)


class GrokBackend(LLMBackend):
    """Grok CLI subprocess backend — runs `grok` for each LLM call.

    Spawns: grok --prompt "<text>" --format json --model <model> --directory <dir>

    Reads stdout line-by-line as newline-delimited JSON events, streaming each
    ``{"type": "text"}`` chunk to ``on_token`` as it arrives.  A background
    thread drains stderr to prevent pipe deadlock.  A ``threading.Timer``
    kills the process if ``timeout`` is exceeded.

    Retries on ``RuntimeError`` or ``subprocess.TimeoutExpired`` up to
    ``max_retries`` times with exponential backoff.

    Prefix ``"grok/"`` is stripped from *model* before passing to ``--model``.
    Does NOT support tool calling (grok manages its own tool ecosystem).
    """

    def __init__(
        self,
        model: str,
        timeout: int = 600,
        max_retries: int = 2,
        directory: str | None = None,
    ) -> None:
        self.model = model.removeprefix("grok/")
        self._timeout = timeout
        self._max_retries = max_retries
        self._directory = directory  # None → os.getcwd() at call time

    def supports_tools(self) -> bool:
        return False

    def call(
        self,
        messages: list[dict],
        run_id: str | None = None,
        on_token: Callable[[str], None] | None = None,
    ) -> str:
        """Spawn grok and return the assembled reply.

        Args:
            messages:  Full message list (system + history + user message).
            run_id:    Ignored — grok handles its own token counting.
            on_token:  Called with each text chunk as grok emits it.

        Returns:
            Assembled and ANSI-stripped reply text.

        Raises:
            RuntimeError: Non-zero exit, error event, or empty output.
            subprocess.TimeoutExpired: Timeout exceeded after all retries.
        """
        bin_path = os.environ.get("GROK_BIN", "grok")
        directory = self._directory or os.getcwd()
        full_prompt = self._build_prompt(messages)

        cmd = [
            bin_path,
            "--prompt", full_prompt,
            "--format", "json",
            "--model", self.model,
            "--directory", directory,
        ]

        for attempt in range(self._max_retries + 1):
            try:
                return self._run_once(cmd, on_token)
            except (subprocess.TimeoutExpired, RuntimeError):
                if attempt == self._max_retries:
                    raise
                time.sleep(2 ** attempt)

    def _build_prompt(self, messages: list[dict]) -> str:
        """Combine a message list into a single prompt string."""
        parts: list[str] = []
        chat_messages: list[dict] = []

        for m in messages:
            if m["role"] == "system" and not chat_messages:
                parts.append(f"[SYSTEM ROLE]\n{m['content']}")
            else:
                chat_messages.append(m)

        history = chat_messages[:-1]
        user_message = (chat_messages[-1].get("content") or "") if chat_messages else ""

        if history:
            lines = []
            for turn in history:
                label = "USER" if turn["role"] == "user" else "ASSISTANT"
                lines.append(f"{label}: {(turn.get('content') or '')[:2000]}")
            parts.append("[CONVERSATION HISTORY]\n" + "\n\n".join(lines))

        parts.append(user_message)
        return "\n\n".join(parts)

    def _run_once(
        self,
        cmd: list[str],
        on_token: Callable[[str], None] | None,
    ) -> str:
        """Spawn grok once, stream its output, and return the assembled reply."""
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        timed_out = [False]

        def _kill() -> None:
            timed_out[0] = True
            proc.kill()

        # Drain stderr in a background thread to prevent deadlock when grok
        # writes a large error to stderr while stdout is still open.
        stderr_chunks: list[str] = []

        def _read_stderr() -> None:
            if proc.stderr:
                stderr_chunks.append(proc.stderr.read())

        stderr_thread = threading.Thread(target=_read_stderr, daemon=True)
        timer = threading.Timer(self._timeout, _kill)
        reply_parts: list[str] = []
        error_message: str | None = None

        try:
            stderr_thread.start()
            timer.start()
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip("\n")
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue  # skip non-JSON progress lines

                event_type = event.get("type", "")
                if event_type == "text":
                    content = event.get("content", "")
                    if content:
                        reply_parts.append(content)
                        if on_token is not None:
                            try:
                                on_token(content)
                            except Exception:
                                pass  # never let console errors kill the response
                elif event_type == "error":
                    error_message = event.get("message", "Unknown grok error")
        finally:
            timer.cancel()
            proc.wait()
            stderr_thread.join(timeout=5)

        if timed_out[0]:
            raise subprocess.TimeoutExpired(cmd, self._timeout)

        rc = proc.returncode
        if rc != 0:
            stderr_output = stderr_chunks[0][:300] if stderr_chunks else ""
            raise RuntimeError(f"grok exited {rc}: {stderr_output}")

        if error_message:
            raise RuntimeError(f"grok error: {error_message}")

        reply = _ANSI_ESCAPE.sub("", "".join(reply_parts)).strip()
        if not reply:
            raise RuntimeError("Empty response from grok")
        return reply

    def call_with_tools(
        self,
        messages: list[dict],
        tools: "ToolRegistry",
        max_turns: int = 8,
        run_id: str | None = None,
    ) -> str:
        raise NotImplementedError(
            "call_with_tools is not supported for the 'grok' backend. "
            "Use 'github_models', 'ollama', 'copilot', or 'nvidia_nim' for tool calling."
        )
```

- [ ] **Step 2: Run the tests — all should pass except the factory tests**

```bash
python3 -m pytest tests/test_grok_backend.py -v -k "not Factory"
```

Expected: 9 tests PASS. `TestGrokBackendFactory` still fails (factory not wired yet).

- [ ] **Step 3: Commit the implementation**

```bash
git add agents/backends/grok.py
git commit -m "feat(backends): add GrokBackend subprocess streaming backend"
```

---

## Task 3: Register GrokBackend in factory

**Files:**
- Modify: `agents/backends/factory.py` (add `grok/` block before the `opencode/` block)

- [ ] **Step 1: Add the grok/ routing block in `_make_single_backend()`**

Open `agents/backends/factory.py`. Find the block:

```python
    if model.startswith("opencode/"):
        from agents.backends.opencode import OpenCodeBackend
        return OpenCodeBackend(model=model, **kwargs)
```

Insert the following **before** that block:

```python
    if model.startswith("grok/"):
        from agents.backends.grok import GrokBackend
        return GrokBackend(model=model, **kwargs)
```

- [ ] **Step 2: Update the error message at the bottom of `_make_single_backend()`**

Find:

```python
    raise ValueError(
        f"Cannot determine backend for model {model!r}. "
        "Prefix with 'ollama/', 'copilot/', 'nvidia-nim/', 'opencode/', "
        "'opencode-zen/', 'opencode-go/', or use 'claude-*' for Anthropic."
    )
```

Replace with:

```python
    raise ValueError(
        f"Cannot determine backend for model {model!r}. "
        "Prefix with 'ollama/', 'copilot/', 'nvidia-nim/', 'grok/', 'opencode/', "
        "'opencode-zen/', 'opencode-go/', or use 'claude-*' for Anthropic."
    )
```

- [ ] **Step 3: Run all GrokBackend tests — all should now pass**

```bash
python3 -m pytest tests/test_grok_backend.py -v
```

Expected: 11 tests PASS, 0 failed.

- [ ] **Step 4: Run full test suite to check for regressions**

```bash
python3 -m pytest tests/ -q --ignore=tests/test_deployment.py
```

Expected: all non-deployment tests pass (same count as before ±11 new).

- [ ] **Step 5: Commit the factory registration**

```bash
git add agents/backends/factory.py
git commit -m "feat(factory): register grok/ prefix → GrokBackend"
```

---

## Task 4: Push branch and open PR

- [ ] **Step 1: Push branch**

```bash
git push -u origin feature/grok-backend
```

- [ ] **Step 2: Open PR**

```bash
gh pr create \
  --title "feat: GrokBackend — xAI Grok CLI subprocess backend" \
  --body "## Summary

Adds \`GrokBackend\` so pipelines can use \`model: grok/<model-name>\` to drive xAI's Grok models via the grok-cli subprocess.

- **Streaming**: reads grok's \`--format json\` events line-by-line; calls \`on_token\` per \`text\` event in real time
- **Timeout safety**: \`threading.Timer\` kills the process; background thread drains stderr to prevent pipe deadlock
- **Retry**: exponential backoff on \`RuntimeError\` or \`TimeoutExpired\` (default 2 retries)
- **Config**: \`GROK_BIN\` env var overrides binary path; \`directory\` param (default cwd)
- **No tool calling**: \`supports_tools() → False\`; grok manages its own tool ecosystem

## Files
- \`agents/backends/grok.py\` (new)
- \`agents/backends/factory.py\` (register \`grok/\` prefix)
- \`tests/test_grok_backend.py\` (new, 11 tests)

## Usage
\`\`\`yaml
model: grok/grok-4.3
timeout: 300
directory: /path/to/project
\`\`\`

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>" \
  --base master \
  --head feature/grok-backend
```

Expected: PR URL printed (e.g. `https://github.com/wanleung/ai-software-house/pull/77`)
