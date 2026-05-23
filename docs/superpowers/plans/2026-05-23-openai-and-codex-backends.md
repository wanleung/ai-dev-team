# OpenAI API and Codex CLI Backends Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two new LLM backends — `openai/` (direct OpenAI API) and `codex/` (Codex CLI subprocess) — following existing patterns in `agents/backends/`.

**Architecture:** `openai_api.py` is a thin `OpenAICompatibleBackend` subclass pointing to `api.openai.com/v1` with `OPENAI_API_KEY`. `codex.py` is a subprocess backend mirroring `opencode.py`, running `codex exec --approval-mode full-auto` and capturing stdout. Both are wired into `factory.py` via prefix matching.

**Tech Stack:** Python 3.11+, `openai` SDK (already a dependency), `subprocess.Popen` with process-group kill.

**Spec:** `docs/superpowers/specs/2026-05-23-openai-and-codex-backends-design.md`

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `agents/backends/openai_api.py` | Create | OpenAI direct API backend (`openai/` prefix) |
| `agents/backends/codex.py` | Create | Codex CLI subprocess backend (`codex/` prefix) |
| `agents/backends/factory.py` | Modify | Add routing for `openai/` and `codex/` prefixes |
| `tests/test_openai_api.py` | Create | Unit tests for `OpenAIApiBackend` |
| `tests/test_codex.py` | Create | Unit tests for `CodexBackend` |
| `config.local.yaml` | Modify | Add commented example config blocks |

---

## Task 1: OpenAI API Backend

**Files:**
- Create: `agents/backends/openai_api.py`
- Create: `tests/test_openai_api.py`
- Modify: `agents/backends/factory.py`

### Step 1: Write the failing tests

Create `tests/test_openai_api.py`:

```python
"""Unit tests for OpenAI direct API backend."""
import os
from unittest.mock import MagicMock, patch

import pytest


# ── OpenAIApiBackend unit tests ───────────────────────────────────────────────

def test_strips_openai_prefix():
    """OpenAIApiBackend strips the 'openai/' prefix before passing model to client."""
    with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
        from agents.backends.openai_api import OpenAIApiBackend
        backend = OpenAIApiBackend(model="openai/gpt-4o")
        assert backend.model == "gpt-4o"


def test_requires_api_key(monkeypatch):
    """OpenAIApiBackend raises EnvironmentError when OPENAI_API_KEY is not set."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from agents.backends.openai_api import OpenAIApiBackend
    with pytest.raises(EnvironmentError, match="OPENAI_API_KEY"):
        OpenAIApiBackend(model="openai/gpt-4o")


def test_supports_tools():
    """OpenAIApiBackend.supports_tools() returns True."""
    with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
        from agents.backends.openai_api import OpenAIApiBackend
        backend = OpenAIApiBackend(model="openai/gpt-4o")
        assert backend.supports_tools() is True


def test_factory_routes_openai_prefix():
    """create_backend routes 'openai/...' models to OpenAIApiBackend."""
    with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
        from agents.backends.factory import create_backend
        from agents.backends.openai_api import OpenAIApiBackend
        backend = create_backend({"model": "openai/gpt-4o"})
        assert isinstance(backend, OpenAIApiBackend)
```

- [ ] Save the file above.

### Step 2: Run to verify tests fail

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_openai_api.py -v 2>&1 | tail -20
```

Expected: `ImportError` or `ModuleNotFoundError` — `openai_api` not yet defined.

### Step 3: Implement `agents/backends/openai_api.py`

```python
"""OpenAI direct API backend (api.openai.com)."""
from __future__ import annotations

import os

from openai import OpenAI

from agents.backends.base import OpenAICompatibleBackend, _DEFAULT_MAX_RETRIES, _DEFAULT_BASE_DELAY


class OpenAIApiBackend(OpenAICompatibleBackend):
    """OpenAI API backend via openai SDK.

    Auth: OPENAI_API_KEY env var.
    Model prefix 'openai/' is stripped; remainder is the model name
    passed directly to the OpenAI API (e.g. 'gpt-4o', 'gpt-4.1', 'o3').
    Supports tool calling.
    """

    def __init__(
        self,
        model: str,
        openai_api_key: str | None = None,
        inter_call_delay: int = 0,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        retry_delay: float = _DEFAULT_BASE_DELAY,
        stream: bool = True,
    ) -> None:
        key = openai_api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise EnvironmentError(
                "OPENAI_API_KEY environment variable is required for OpenAI API. "
                "Get your key at https://platform.openai.com/api-keys"
            )
        client = OpenAI(api_key=key)
        super().__init__(
            model=model.removeprefix("openai/"),
            client=client,
            inter_call_delay=inter_call_delay,
            max_retries=max_retries,
            retry_delay=retry_delay,
            stream=stream,
        )
```

### Step 4: Wire `openai/` into `factory.py`

In `agents/backends/factory.py`, add this block **before** the `if "/" not in model:` GitHub Models fallback and **after** the `grok-oauth/` block:

```python
    if model.startswith("openai/"):
        from agents.backends.openai_api import OpenAIApiBackend
        ck = {k: v for k, v in kwargs.items() if k not in _ALL_PROVIDER_SPECIFIC}
        return OpenAIApiBackend(model=model, **ck)
```

Also update the `raise ValueError` error message to include `'openai/'`:

```python
    raise ValueError(
        f"Cannot determine backend for model {model!r}. "
        "Prefix with 'ollama/', 'copilot/', 'nvidia-nim/', 'dashscope/', 'opencode/', "
        "'opencode-zen/', 'opencode-go/', 'grok/', 'grok-oauth/', 'openai/', 'codex/', "
        "or use 'claude-*' for Anthropic."
    )
```

### Step 5: Run tests to verify they pass

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_openai_api.py -v 2>&1 | tail -20
```

Expected:
```
tests/test_openai_api.py::test_strips_openai_prefix PASSED
tests/test_openai_api.py::test_requires_api_key PASSED
tests/test_openai_api.py::test_supports_tools PASSED
tests/test_openai_api.py::test_factory_routes_openai_prefix PASSED
4 passed
```

### Step 6: Commit

```bash
cd /home/wanleung/Projects/ai-software-house
git add agents/backends/openai_api.py agents/backends/factory.py tests/test_openai_api.py
git commit -m "feat: add OpenAI direct API backend (openai/ prefix)

Adds OpenAIApiBackend pointing to api.openai.com/v1 with OPENAI_API_KEY.
Wires openai/ prefix in factory.py. Supports tool calling and streaming.

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 2: Codex CLI Backend

**Files:**
- Create: `agents/backends/codex.py`
- Create: `tests/test_codex.py`
- Modify: `agents/backends/factory.py`

### Step 1: Write the failing tests

Create `tests/test_codex.py`:

```python
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
```

- [ ] Save the file above.

### Step 2: Run to verify tests fail

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_codex.py -v 2>&1 | tail -20
```

Expected: `ImportError` — `codex` module not yet defined.

### Step 3: Implement `agents/backends/codex.py`

```python
"""OpenAI Codex CLI subprocess backend."""
from __future__ import annotations

import os
import re
import signal
import subprocess
import time
from typing import TYPE_CHECKING

from agents.backends.base import LLMBackend, _DEFAULT_MAX_RETRIES

if TYPE_CHECKING:
    from tools.registry import ToolRegistry

_ANSI_ESCAPE = re.compile(
    r'\x1b(?:'
    r'\[[0-9;?]*[A-Za-z]'
    r'|\][^\x07\x1b]*(?:\x07|\x1b\\)'
    r'|[@-_]'
    r')'
)


class CodexBackend(LLMBackend):
    """OpenAI Codex CLI backend — runs codex subprocess for each call.

    Runs `codex exec --approval-mode full-auto --model <model> <prompt>`.
    Auth: ChatGPT plan OAuth (user must already be signed in via `codex` CLI).
    Model prefix 'codex/' is stripped; remainder passed as --model value.
    Does NOT support tool calling.

    Install: curl -fsSL https://chatgpt.com/codex/install.sh | sh
    Sign in: codex  (select 'Sign in with ChatGPT')
    Override binary: CODEX_BIN env var (default: 'codex')
    """

    def __init__(
        self,
        model: str,
        timeout: int = 600,
        max_retries: int = 2,
    ) -> None:
        self.model = model.removeprefix("codex/")
        self._timeout = timeout
        self._max_retries = max_retries

    def supports_tools(self) -> bool:
        """Return False — Codex CLI does not support function calling."""
        return False

    def call(
        self,
        messages: list[dict],
        run_id: str | None = None,
        on_token: "Callable[[str], None] | None" = None,
    ) -> str:
        """Build a combined prompt from messages and run via codex CLI.

        Args:
            messages:  Full message list (system + history + user message).
            run_id:    Optional pipeline run ID (unused by this backend).
            on_token:  Optional streaming callback — not forwarded; codex exec
                       does not support streaming.

        Returns:
            The assistant reply text.

        Raises:
            RuntimeError: If codex exits with non-zero status or returns empty output.
            subprocess.TimeoutExpired: If the subprocess exceeds timeout and all retries exhausted.
            FileNotFoundError: If the codex binary is not found.
        """
        bin_path = os.environ.get("CODEX_BIN", "codex")

        # Reconstruct system + history + final user message into a single prompt
        parts: list[str] = []
        chat_messages = []
        for m in messages:
            if m["role"] == "system" and not chat_messages:
                parts.append(f"[SYSTEM ROLE]\n{m['content']}")
            else:
                chat_messages.append(m)

        history = chat_messages[:-1]
        user_message = (chat_messages[-1].get("content") or "") if chat_messages else ""

        if history:
            history_lines = []
            for turn in history:
                label = "USER" if turn["role"] == "user" else "ASSISTANT"
                history_lines.append(f"{label}: {(turn.get('content') or '')[:2000]}")
            parts.append("[CONVERSATION HISTORY]\n" + "\n\n".join(history_lines))
        parts.append(user_message)

        full_prompt = "\n\n".join(parts)

        for attempt in range(self._max_retries + 1):
            proc = None
            try:
                cmd = [
                    bin_path, "exec",
                    "--approval-mode", "full-auto",
                    "--model", self.model,
                    full_prompt,
                ]
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    start_new_session=True,
                )
                stdout, stderr = proc.communicate(timeout=self._timeout)

                if proc.returncode != 0:
                    raise RuntimeError(
                        f"codex exited with code {proc.returncode}. stderr: {stderr.strip()[:500]}"
                    )

                output = _ANSI_ESCAPE.sub("", stdout).strip()
                if not output:
                    raise RuntimeError(
                        f"codex returned empty output. stderr: {stderr.strip()[:500]}"
                    )
                return output

            except subprocess.TimeoutExpired:
                if proc is not None and proc.poll() is None:
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                if attempt < self._max_retries:
                    time.sleep(2 ** attempt)
                    continue
                raise

            finally:
                if proc is not None and proc.poll() is None:
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except ProcessLookupError:
                        pass

        # Unreachable — loop always returns or raises
        raise RuntimeError("codex: all retries exhausted")  # pragma: no cover

    def call_with_tools(
        self,
        messages: list[dict],
        tools: "ToolRegistry",
        max_turns: int = 8,
        run_id: str | None = None,
    ) -> str:
        """Not supported — raises NotImplementedError."""
        raise NotImplementedError(
            "call_with_tools is not supported for the 'codex' backend. "
            "Use 'openai/', 'github_models', or 'copilot/' for tool calling."
        )
```

### Step 4: Wire `codex/` into `factory.py`

In `agents/backends/factory.py`, add this block after the `openai/` block you added in Task 1 (before the `if "/" not in model:` GitHub Models fallback):

```python
    if model.startswith("codex/"):
        from agents.backends.codex import CodexBackend
        ck = {k: v for k, v in kwargs.items() if k not in _ALL_PROVIDER_SPECIFIC}
        return CodexBackend(model=model, **ck)
```

The `raise ValueError` at the bottom was already updated in Task 1 to include `'codex/'`.

### Step 5: Run tests to verify they pass

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_codex.py -v 2>&1 | tail -20
```

Expected:
```
tests/test_codex.py::test_strips_codex_prefix PASSED
tests/test_codex.py::test_does_not_support_tools PASSED
tests/test_codex.py::test_call_success PASSED
tests/test_codex.py::test_call_uses_correct_command PASSED
tests/test_codex.py::test_codex_bin_override PASSED
tests/test_codex.py::test_call_timeout_retries PASSED
tests/test_codex.py::test_factory_routes_codex_prefix PASSED
7 passed
```

### Step 6: Commit

```bash
cd /home/wanleung/Projects/ai-software-house
git add agents/backends/codex.py agents/backends/factory.py tests/test_codex.py
git commit -m "feat: add Codex CLI subprocess backend (codex/ prefix)

Adds CodexBackend running 'codex exec --approval-mode full-auto'.
OAuth auth via ChatGPT plan sign-in. Process-group kill on timeout.
Wires codex/ prefix in factory.py.

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 3: Config Examples and Full Test Run

**Files:**
- Modify: `config.local.yaml`

### Step 1: Add commented config examples to `config.local.yaml`

Find the `# LLM backend examples` section (or the end of the file) in `config.local.yaml` and add:

```yaml
  # ── OpenAI direct API (BusinessChatGPT / Plus / Pro) ─────────────────────
  # Requires: OPENAI_API_KEY env var (https://platform.openai.com/api-keys)
  #
  #  model: "openai/gpt-4o"
  #  fallbacks:
  #    - model: "openai/gpt-4.1"
  #    - model: "openai/o4-mini"

  # ── OpenAI Codex CLI (ChatGPT Business/Plus plan, OAuth) ──────────────────
  # Requires: codex CLI installed and signed in (run `codex` → Sign in with ChatGPT)
  # Install:  curl -fsSL https://chatgpt.com/codex/install.sh | sh
  #
  #  model: "codex/codex-mini-latest"
```

### Step 2: Run the full test suite

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: All tests pass. If any pre-existing tests fail, note them but do not fix them (out of scope).

### Step 3: Commit

```bash
cd /home/wanleung/Projects/ai-software-house
git add config.local.yaml
git commit -m "docs: add OpenAI and Codex backend config examples to config.local.yaml

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Done

After Task 3, all three tasks are complete. Use `superpowers:finishing-a-development-branch` to merge/push.

**Usage after deployment:**

```yaml
# In config.local.yaml overrides section:
product_manager: "openai/gpt-4o"
# or
product_manager: "codex/codex-mini-latest"
```
