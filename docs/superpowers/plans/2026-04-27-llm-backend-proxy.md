# LLM Backend Proxy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract all LLM backend code from `base_agent.py` into `agents/backends/` with a `FallbackLLMBackend` that auto-switches on connection errors and replays conversation history.

**Architecture:** `LLMBackend` abstract base + `OpenAICompatibleBackend` shared base for OpenAI-SDK backends. `FallbackLLMBackend` wraps an ordered list of backends. `factory.py` builds the right backend (or fallback chain) from a config dict. `BaseAgent` shrinks to agent logic only, delegating all LLM calls to `self._llm`.

**Tech Stack:** Python 3.11+, openai SDK, anthropic SDK (optional), httpx, pytest

**Spec:** `docs/superpowers/specs/2026-04-27-llm-backend-proxy-design.md`

---

### Task 1: Create git worktree + backends package skeleton + base.py

**Files:**
- Create: `agents/backends/__init__.py`
- Create: `agents/backends/base.py`
- Create: `tests/test_backends_base.py`

- [ ] **Step 1: Create feature branch in a worktree**

```bash
cd /home/wanleung/Projects/ai-software-house
git worktree add ../ai-software-house-llm-proxy feature/llm-backend-proxy 2>/dev/null \
  || git worktree add ../ai-software-house-llm-proxy -b feature/llm-backend-proxy
cd ../ai-software-house-llm-proxy
```

All subsequent steps run in `/home/wanleung/Projects/ai-software-house-llm-proxy`.

- [ ] **Step 2: Create backends package directory**

```bash
mkdir -p agents/backends
```

- [ ] **Step 3: Write the failing tests for base.py**

Create `tests/test_backends_base.py`:

```python
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
    assert issubclass(ConnectionError, FALLBACK_ERRORS)
    assert issubclass(httpx.ConnectError, FALLBACK_ERRORS)
    assert issubclass(httpx.TimeoutException, FALLBACK_ERRORS)


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
```

- [ ] **Step 4: Run tests — expect failures (module not found)**

```bash
cd /home/wanleung/Projects/ai-software-house-llm-proxy
source venv/bin/activate
pytest tests/test_backends_base.py -v 2>&1 | tail -20
```

Expected: `ModuleNotFoundError: No module named 'agents.backends.base'`

- [ ] **Step 5: Create `agents/backends/__init__.py`**

```python
"""LLM backend implementations for ai-software-house.

Usage:
    from agents.backends import create_backend
    llm = create_backend({"model": "ollama/qwen3.6", "ollama_think": True})
    reply = llm.call(messages)
"""
from agents.backends.factory import create_backend

__all__ = ["create_backend"]
```

- [ ] **Step 6: Create `agents/backends/base.py`**

```python
"""Abstract LLM backend base classes and shared utilities."""
from __future__ import annotations

import logging
import os
import random
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tools.registry import ToolRegistry

import httpx
from openai import (
    APIConnectionError as _OAIConnError,
    APITimeoutError as _OAITimeoutError,
    AuthenticationError as _OAIAuthError,
    BadRequestError as _OAIBadRequest,
    InternalServerError as _OAIServerError,
    RateLimitError as _OAIRateLimit,
)

_log = logging.getLogger(__name__)

_DEFAULT_MAX_RETRIES: int = int(os.environ.get("AGENT_MAX_RETRIES", "3"))
_DEFAULT_BASE_DELAY: float = float(os.environ.get("AGENT_RETRY_BASE_DELAY", "1.0"))

# Errors that FallbackLLMBackend uses to trigger a switch to the next backend.
# These are infrastructure/transient failures — not caller errors.
FALLBACK_ERRORS = (
    ConnectionError,
    httpx.ConnectError,
    httpx.TimeoutException,
    _OAIConnError,
    _OAITimeoutError,
)


def _retry_with_backoff(
    fn,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    base_delay: float = _DEFAULT_BASE_DELAY,
):
    """Call fn() and retry with exponential backoff on transient API errors.

    Retryable: APIConnectionError, APITimeoutError, RateLimitError, InternalServerError
               (and Anthropic equivalents when installed).
    Non-retryable: AuthenticationError, BadRequestError — raised immediately.
    """
    _retryable: list = [
        _OAIConnError,
        _OAITimeoutError,
        _OAIRateLimit,
        _OAIServerError,
    ]
    _non_retryable = (_OAIAuthError, _OAIBadRequest)

    try:
        import anthropic as _ant
        _retryable.extend([
            _ant.APIConnectionError,
            _ant.APITimeoutError,
            _ant.InternalServerError,
            _ant.RateLimitError,
        ])
    except ImportError:
        pass

    _retryable_tuple = tuple(_retryable)
    last_exc: BaseException | None = None

    for attempt in range(max_retries + 1):
        try:
            return fn()
        except _non_retryable:
            raise
        except _retryable_tuple as exc:  # type: ignore[misc]
            last_exc = exc
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt) * random.uniform(0.9, 1.1)
                _log.warning(
                    "Retrying in %.1fs (attempt %d/%d): %s: %s",
                    delay, attempt + 1, max_retries, type(exc).__name__, str(exc)[:120],
                )
                time.sleep(delay)
            else:
                _log.error(
                    "All %d retries exhausted: %s: %s",
                    max_retries, type(exc).__name__, str(exc)[:120],
                )
        except Exception:
            raise

    raise last_exc  # type: ignore[misc]


class LLMBackend(ABC):
    """Abstract base for all LLM backends."""

    model: str  # bare model name (without prefix, e.g. "qwen3.6" not "ollama/qwen3.6")

    @abstractmethod
    def call(self, messages: list[dict]) -> str:
        """Send a message list and return the assistant reply.

        Args:
            messages: Full message list including system prompt, history, and
                      the new user message. Format: OpenAI chat messages.
        """

    @abstractmethod
    def call_with_tools(
        self,
        messages: list[dict],
        tools: "ToolRegistry",
        max_turns: int = 8,
    ) -> str:
        """Send messages, execute any tool calls, and return the final reply.

        Args:
            messages: Full message list (system + history + user message).
            tools:    ToolRegistry providing schemas and call() dispatch.
            max_turns: Max tool-call rounds before forcing a text response.
        """

    def supports_tools(self) -> bool:
        """Return False for backends that do not support function calling."""
        return True


class OpenAICompatibleBackend(LLMBackend):
    """Shared base for all backends using the OpenAI Python SDK.

    Subclasses override:
        _extra_body()   — return extra_body dict (e.g. Ollama think options)
        _post_process() — transform reply text (e.g. strip <think> blocks)
        _pre_call()     — pre-call hook (e.g. Copilot session token refresh)
    """

    def __init__(
        self,
        model: str,
        client,  # openai.OpenAI instance
        inter_call_delay: int = 0,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        retry_delay: float = _DEFAULT_BASE_DELAY,
    ) -> None:
        self.model = model
        self._client = client
        self._inter_call_delay = inter_call_delay
        self._max_retries = max_retries
        self._retry_delay = retry_delay

    def _extra_body(self) -> dict:
        return {}

    def _post_process(self, text: str) -> str:
        return text

    def _pre_call(self) -> None:
        pass

    def call(self, messages: list[dict]) -> str:
        self._pre_call()
        if self._inter_call_delay > 0:
            time.sleep(self._inter_call_delay)
        response = _retry_with_backoff(
            lambda: self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.3,
                **self._extra_body(),
            ),
            max_retries=self._max_retries,
            base_delay=self._retry_delay,
        )
        return self._post_process(response.choices[0].message.content or "")

    def call_with_tools(
        self,
        messages: list[dict],
        tools: "ToolRegistry",
        max_turns: int = 8,
    ) -> str:
        self._pre_call()
        messages = list(messages)  # local copy for tool loop

        for _ in range(max_turns):
            if self._inter_call_delay > 0:
                time.sleep(self._inter_call_delay)
            response = _retry_with_backoff(
                lambda: self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=tools.schemas,
                    tool_choice="auto",
                    temperature=0.3,
                    **self._extra_body(),
                ),
                max_retries=self._max_retries,
                base_delay=self._retry_delay,
            )
            msg = response.choices[0].message
            if not msg.tool_calls:
                return self._post_process(msg.content or "")

            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ],
            })
            for tc in msg.tool_calls:
                print(f"    🔧 Tool call: {tc.function.name}({tc.function.arguments[:80]}…)")
                result = tools.call(tc.function.name, tc.function.arguments)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

        # Max turns reached — force a final text response
        messages.append({
            "role": "user",
            "content": "Please provide your final response based on the tool results above.",
        })
        response = _retry_with_backoff(
            lambda: self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.3,
                **self._extra_body(),
            ),
            max_retries=self._max_retries,
            base_delay=self._retry_delay,
        )
        return self._post_process(response.choices[0].message.content or "")
```

- [ ] **Step 7: Run tests — expect them to pass**

```bash
pytest tests/test_backends_base.py -v 2>&1 | tail -20
```

Expected: `9 passed`

- [ ] **Step 8: Commit**

```bash
git add agents/backends/__init__.py agents/backends/base.py tests/test_backends_base.py
git commit -m "feat(backends): add LLMBackend ABC + OpenAICompatibleBackend + retry utils"
```

---

### Task 2: GitHubModelsBackend

**Files:**
- Create: `agents/backends/github_models.py`
- Create: `tests/test_backend_github_models.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_backend_github_models.py`:

```python
"""Tests for GitHubModelsBackend."""
from __future__ import annotations
import os
from unittest.mock import MagicMock, patch
import pytest


def _mock_response(content: str):
    return MagicMock(
        choices=[MagicMock(message=MagicMock(content=content, tool_calls=None))]
    )


def test_github_models_backend_requires_token():
    from agents.backends.github_models import GitHubModelsBackend
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(EnvironmentError, match="GITHUB_TOKEN"):
            GitHubModelsBackend(model="gpt-4.1", github_token=None)


def test_github_models_backend_uses_env_token():
    from agents.backends.github_models import GitHubModelsBackend
    with patch("agents.backends.github_models.OpenAI") as mock_cls:
        mock_cls.return_value = MagicMock()
        with patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"}):
            backend = GitHubModelsBackend(model="gpt-4.1")
    assert backend.model == "gpt-4.1"


def test_github_models_backend_call():
    from agents.backends.github_models import GitHubModelsBackend
    with patch("agents.backends.github_models.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_response("hello")
        mock_cls.return_value = mock_client
        with patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"}):
            backend = GitHubModelsBackend(model="gpt-4.1")
    result = backend.call([{"role": "user", "content": "hi"}])
    assert result == "hello"


def test_github_models_backend_supports_tools():
    from agents.backends.github_models import GitHubModelsBackend
    with patch("agents.backends.github_models.OpenAI"):
        with patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"}):
            backend = GitHubModelsBackend(model="gpt-4.1")
    assert backend.supports_tools() is True
```

- [ ] **Step 2: Run — expect failures**

```bash
pytest tests/test_backend_github_models.py -v 2>&1 | tail -10
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement `agents/backends/github_models.py`**

```python
"""GitHub Models API backend (OpenAI-compatible, uses GITHUB_TOKEN)."""
from __future__ import annotations

import os
from typing import Optional

from openai import OpenAI

from agents.backends.base import OpenAICompatibleBackend, _DEFAULT_MAX_RETRIES, _DEFAULT_BASE_DELAY


class GitHubModelsBackend(OpenAICompatibleBackend):
    """GitHub Models API via OpenAI SDK.

    Model names are passed as-is (no prefix to strip).
    Auth: GITHUB_TOKEN env var or github_token constructor arg.
    """

    def __init__(
        self,
        model: str,
        github_token: Optional[str] = None,
        inter_call_delay: int = 0,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        retry_delay: float = _DEFAULT_BASE_DELAY,
    ) -> None:
        token = github_token or os.environ.get("GITHUB_TOKEN")
        if not token:
            raise EnvironmentError(
                "GITHUB_TOKEN environment variable is required for GitHub Models. "
                "Create a token at https://github.com/settings/personal-access-tokens/new "
                "with 'Copilot Requests', 'Contents', 'Issues', and 'Pull requests' permissions."
            )
        client = OpenAI(base_url="https://models.github.ai/inference", api_key=token)
        super().__init__(
            model=model,
            client=client,
            inter_call_delay=inter_call_delay,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )
```

- [ ] **Step 4: Run tests — expect pass**

```bash
pytest tests/test_backend_github_models.py -v 2>&1 | tail -10
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add agents/backends/github_models.py tests/test_backend_github_models.py
git commit -m "feat(backends): add GitHubModelsBackend"
```

---

### Task 3: OllamaBackend

**Files:**
- Create: `agents/backends/ollama.py`
- Create: `tests/test_backend_ollama.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_backend_ollama.py`:

```python
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
```

- [ ] **Step 2: Run — expect failures**

```bash
pytest tests/test_backend_ollama.py -v 2>&1 | tail -10
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement `agents/backends/ollama.py`**

```python
"""Ollama backend — local Ollama server via OpenAI-compatible API."""
from __future__ import annotations

import os
import re
import time

import httpx
from openai import OpenAI

from agents.backends.base import (
    OpenAICompatibleBackend,
    _retry_with_backoff,
    _DEFAULT_MAX_RETRIES,
    _DEFAULT_BASE_DELAY,
)

_ollama_timeout = float(os.environ.get("OLLAMA_TIMEOUT", "0")) or None


class OllamaBackend(OpenAICompatibleBackend):
    """Local Ollama server backend.

    Model prefix "ollama/" is stripped before sending to the API.
    Supports think/no-think mode and optional preserve_thinking.
    Supports streaming (recommended for remote Ollama hosts).
    """

    def __init__(
        self,
        model: str,
        ollama_url: str = "http://localhost:11434",
        think: bool = False,
        preserve_thinking: bool = False,
        stream: bool = True,
        inter_call_delay: int = 0,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        retry_delay: float = _DEFAULT_BASE_DELAY,
    ) -> None:
        self._think = think
        self._preserve_thinking = preserve_thinking
        self._stream = stream
        client = OpenAI(
            base_url=f"{ollama_url.rstrip('/')}/v1",
            api_key="ollama",
            timeout=(
                httpx.Timeout(timeout=_ollama_timeout, connect=10.0)
                if _ollama_timeout
                else httpx.Timeout(timeout=None, connect=10.0)
            ),
        )
        super().__init__(
            model=model.removeprefix("ollama/"),
            client=client,
            inter_call_delay=inter_call_delay,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )

    def _extra_body(self) -> dict:
        if not self._think:
            return {"extra_body": {"think": False}}
        if self._preserve_thinking:
            return {"extra_body": {"options": {"preserve_thinking": True}}}
        return {}

    def _post_process(self, text: str) -> str:
        if self._preserve_thinking:
            return text.strip()
        return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    def call(self, messages: list[dict]) -> str:
        """Ollama call — uses streaming if enabled."""
        self._pre_call()
        if self._stream:
            return self._stream_call(messages)
        return super().call(messages)

    def _stream_call(self, messages: list[dict]) -> str:
        if self._inter_call_delay > 0:
            time.sleep(self._inter_call_delay)

        def _collect(stream) -> str:
            collected = ""
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    collected += delta
            return collected

        reply = _retry_with_backoff(
            lambda: _collect(
                self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.3,
                    stream=True,
                    **self._extra_body(),
                )
            ),
            max_retries=self._max_retries,
            base_delay=self._retry_delay,
        )
        return self._post_process(reply)
```

- [ ] **Step 4: Run tests — expect pass**

```bash
pytest tests/test_backend_ollama.py -v 2>&1 | tail -10
```

Expected: `9 passed`

- [ ] **Step 5: Commit**

```bash
git add agents/backends/ollama.py tests/test_backend_ollama.py
git commit -m "feat(backends): add OllamaBackend with think/preserve_thinking/stream"
```

---

### Task 4: AnthropicBackend

**Files:**
- Create: `agents/backends/anthropic.py`
- Create: `tests/test_backend_anthropic.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_backend_anthropic.py`:

```python
"""Tests for AnthropicBackend."""
from __future__ import annotations
import os
from unittest.mock import MagicMock, patch
import pytest


def test_anthropic_backend_requires_key():
    from agents.backends.anthropic import AnthropicBackend
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(EnvironmentError, match="ANTHROPIC_API_KEY"):
            AnthropicBackend(model="claude-sonnet-4-5")


def test_anthropic_backend_supports_tools_false():
    from agents.backends.anthropic import AnthropicBackend
    with patch("agents.backends.anthropic.anthropic") as mock_ant:
        mock_ant.Anthropic.return_value = MagicMock()
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test"}):
            b = AnthropicBackend(model="claude-sonnet-4-5")
    assert b.supports_tools() is False


def test_anthropic_backend_call_raises_for_tools():
    from agents.backends.anthropic import AnthropicBackend
    with patch("agents.backends.anthropic.anthropic") as mock_ant:
        mock_ant.Anthropic.return_value = MagicMock()
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test"}):
            b = AnthropicBackend(model="claude-sonnet-4-5")
    with pytest.raises(NotImplementedError, match="anthropic"):
        b.call_with_tools([], MagicMock())


def test_anthropic_backend_call_extracts_system_from_messages():
    from agents.backends.anthropic import AnthropicBackend
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="Hello")]
    )
    with patch("agents.backends.anthropic.anthropic") as mock_ant:
        mock_ant.Anthropic.return_value = mock_client
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test"}):
            b = AnthropicBackend(model="claude-sonnet-4-5")

    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Hi"},
    ]
    result = b.call(messages)
    assert result == "Hello"

    _, kwargs = mock_client.messages.create.call_args
    assert kwargs["system"] == "You are helpful."
    assert kwargs["messages"] == [{"role": "user", "content": "Hi"}]


def test_anthropic_backend_call_no_system():
    from agents.backends.anthropic import AnthropicBackend
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="Reply")]
    )
    with patch("agents.backends.anthropic.anthropic") as mock_ant:
        mock_ant.Anthropic.return_value = mock_client
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test"}):
            b = AnthropicBackend(model="claude-sonnet-4-5")

    b.call([{"role": "user", "content": "Hi"}])
    _, kwargs = mock_client.messages.create.call_args
    assert "system" not in kwargs or kwargs.get("system") == ""
```

- [ ] **Step 2: Run — expect failures**

```bash
pytest tests/test_backend_anthropic.py -v 2>&1 | tail -10
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement `agents/backends/anthropic.py`**

```python
"""Anthropic Claude backend — uses the anthropic SDK directly."""
from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING

from agents.backends.base import LLMBackend, _retry_with_backoff, _DEFAULT_MAX_RETRIES, _DEFAULT_BASE_DELAY

if TYPE_CHECKING:
    from tools.registry import ToolRegistry

try:
    import anthropic
except ImportError:
    anthropic = None  # type: ignore[assignment]


class AnthropicBackend(LLMBackend):
    """Anthropic Claude API backend.

    Does NOT support tool calling (use github_models or ollama for tools).
    Extracts system prompt from messages list if present as first "system" role message.
    Auth: ANTHROPIC_API_KEY env var.
    """

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        inter_call_delay: int = 0,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        retry_delay: float = _DEFAULT_BASE_DELAY,
    ) -> None:
        if anthropic is None:
            raise ImportError("anthropic package required: pip install anthropic")
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise EnvironmentError(
                "ANTHROPIC_API_KEY environment variable is required for Claude models. "
                "Get your key at https://console.anthropic.com/"
            )
        self.model = model
        self._client = anthropic.Anthropic(api_key=key)
        self._inter_call_delay = inter_call_delay
        self._max_retries = max_retries
        self._retry_delay = retry_delay

    def supports_tools(self) -> bool:
        return False

    def call(self, messages: list[dict]) -> str:
        # Extract system prompt from messages if first message is "system" role
        system = ""
        chat_messages = []
        for m in messages:
            if m["role"] == "system" and not chat_messages:
                system = m["content"]
            else:
                chat_messages.append(m)

        if self._inter_call_delay > 0:
            time.sleep(self._inter_call_delay)

        kwargs: dict = {
            "model": self.model,
            "max_tokens": 8096,
            "messages": chat_messages,
        }
        if system:
            kwargs["system"] = system

        response = _retry_with_backoff(
            lambda: self._client.messages.create(**kwargs),
            max_retries=self._max_retries,
            base_delay=self._retry_delay,
        )
        return response.content[0].text

    def call_with_tools(
        self,
        messages: list[dict],
        tools: "ToolRegistry",
        max_turns: int = 8,
    ) -> str:
        raise NotImplementedError(
            "call_with_tools is not supported for the 'anthropic' backend. "
            "Use 'github_models', 'ollama', 'copilot', or 'nvidia_nim' for tool calling."
        )
```

- [ ] **Step 4: Run tests — expect pass**

```bash
pytest tests/test_backend_anthropic.py -v 2>&1 | tail -10
```

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add agents/backends/anthropic.py tests/test_backend_anthropic.py
git commit -m "feat(backends): add AnthropicBackend"
```

---

### Task 5: CopilotBackend

**Files:**
- Create: `agents/backends/copilot.py`
- Create: `tests/test_backend_copilot.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_backend_copilot.py`:

```python
"""Tests for CopilotBackend — token discovery and session refresh."""
from __future__ import annotations
import io
import json
import os
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, mock_open
import pytest


def _expires_str(minutes_from_now: int = 30) -> str:
    dt = datetime.now(timezone.utc) + timedelta(minutes=minutes_from_now)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_discover_oauth_token_from_env():
    from agents.backends.copilot import _discover_copilot_oauth_token
    with patch.dict(os.environ, {"COPILOT_OAUTH_TOKEN": "gho_test"}):
        assert _discover_copilot_oauth_token() == "gho_test"


def test_discover_oauth_token_from_config_file():
    from agents.backends.copilot import _discover_copilot_oauth_token
    cfg = {"copilot_tokens": {"https://github.com:user": "gho_fromfile"}}
    with patch.dict(os.environ, {}, clear=True):
        with patch("builtins.open", mock_open(read_data=json.dumps(cfg))):
            assert _discover_copilot_oauth_token() == "gho_fromfile"


def test_discover_oauth_token_raises_when_missing():
    from agents.backends.copilot import _discover_copilot_oauth_token
    with patch.dict(os.environ, {}, clear=True):
        with patch("builtins.open", side_effect=FileNotFoundError):
            with pytest.raises(EnvironmentError, match="COPILOT_OAUTH_TOKEN"):
                _discover_copilot_oauth_token()


def test_fetch_session_token_success():
    from agents.backends.copilot import _fetch_copilot_session_token, _COPILOT_SESSION
    body = json.dumps({"token": "session_abc", "expires_at": _expires_str(30)}).encode()
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = body
    with patch("urllib.request.urlopen", return_value=mock_resp):
        token = _fetch_copilot_session_token("gho_test")
    assert token == "session_abc"
    assert _COPILOT_SESSION["token"] == "session_abc"


def test_copilot_backend_refreshes_expired_session():
    from agents.backends.copilot import CopilotBackend, _COPILOT_SESSION
    _COPILOT_SESSION["token"] = "old_token"
    _COPILOT_SESSION["expires_at"] = time.time() - 10  # expired

    new_body = json.dumps({"token": "new_token", "expires_at": _expires_str(30)}).encode()
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = new_body

    with patch.dict(os.environ, {"COPILOT_OAUTH_TOKEN": "gho_test"}):
        with patch("agents.backends.copilot.OpenAI") as mock_oai:
            mock_oai.return_value = MagicMock()
            with patch("urllib.request.urlopen", return_value=mock_resp):
                backend = CopilotBackend(model="copilot/gpt-4.1")

    assert backend.model == "gpt-4.1"
    assert _COPILOT_SESSION["token"] == "new_token"


def test_copilot_backend_call_refreshes_before_call():
    from agents.backends.copilot import CopilotBackend, _COPILOT_SESSION
    _COPILOT_SESSION["token"] = "valid_token"
    _COPILOT_SESSION["expires_at"] = time.time() + 3600  # valid

    with patch.dict(os.environ, {"COPILOT_OAUTH_TOKEN": "gho_test"}):
        with patch("agents.backends.copilot.OpenAI") as mock_oai:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = MagicMock(
                choices=[MagicMock(message=MagicMock(content="reply", tool_calls=None))]
            )
            mock_oai.return_value = mock_client
            backend = CopilotBackend(model="copilot/gpt-4.1")

    result = backend.call([{"role": "user", "content": "hi"}])
    assert result == "reply"
```

- [ ] **Step 2: Run — expect failures**

```bash
pytest tests/test_backend_copilot.py -v 2>&1 | tail -10
```

- [ ] **Step 3: Implement `agents/backends/copilot.py`**

```python
"""GitHub Copilot Chat API backend — OpenAI-compatible with session token refresh."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Optional

from openai import OpenAI

from agents.backends.base import OpenAICompatibleBackend, _DEFAULT_MAX_RETRIES, _DEFAULT_BASE_DELAY

_COPILOT_API_BASE = "https://api.githubcopilot.com"
_COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
_COPILOT_CONFIG_PATH = os.path.expanduser("~/.copilot/config.json")

# Module-level session cache — shared across all CopilotBackend instances.
_COPILOT_SESSION: dict = {"token": "", "expires_at": 0.0}


def _discover_copilot_oauth_token() -> str:
    """Return the Copilot OAuth token from COPILOT_OAUTH_TOKEN env or ~/.copilot/config.json."""
    token = os.environ.get("COPILOT_OAUTH_TOKEN")
    if token:
        return token
    try:
        with open(_COPILOT_CONFIG_PATH, encoding="utf-8") as fh:
            cfg = json.load(fh)
        tokens: dict = cfg.get("copilot_tokens", {})
        if tokens:
            return next(iter(tokens.values()))
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    raise EnvironmentError(
        "No GitHub Copilot OAuth token found. Either:\n"
        "  1. Set COPILOT_OAUTH_TOKEN=<gho_...> environment variable, or\n"
        "  2. Log in to Copilot CLI (token auto-discovered from ~/.copilot/config.json)."
    )


def _fetch_copilot_session_token(oauth_token: str) -> str:
    """Exchange OAuth token for a short-lived session token. Updates _COPILOT_SESSION."""
    req = urllib.request.Request(
        _COPILOT_TOKEN_URL,
        headers={"Authorization": f"token {oauth_token}"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:500]
        raise RuntimeError(
            f"Copilot token exchange failed: HTTP {exc.code} — {exc.reason}\n{body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Copilot token exchange failed: network error — {exc.reason}"
        ) from exc

    try:
        session_token: str = data["token"]
        expires_str: str = data["expires_at"]
        dt = datetime.fromisoformat(expires_str.replace("Z", "+00:00"))
    except (KeyError, ValueError) as exc:
        raise RuntimeError(
            f"Copilot token exchange failed: unexpected response format — {exc}"
        ) from exc

    _COPILOT_SESSION["token"] = session_token
    _COPILOT_SESSION["expires_at"] = dt.timestamp()
    return session_token


def _build_copilot_client(token: str) -> OpenAI:
    return OpenAI(
        base_url=_COPILOT_API_BASE,
        api_key=token,
        default_headers={
            "Editor-Version": "vscode/1.90.0",
            "Copilot-Integration-Id": "vscode-chat",
        },
    )


class CopilotBackend(OpenAICompatibleBackend):
    """GitHub Copilot Chat API backend.

    Auto-refreshes the short-lived session token before each API call.
    Model prefix "copilot/" is stripped.
    Auth: COPILOT_OAUTH_TOKEN env var or ~/.copilot/config.json.
    """

    def __init__(
        self,
        model: str,
        inter_call_delay: int = 0,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        retry_delay: float = _DEFAULT_BASE_DELAY,
    ) -> None:
        self._oauth_token = _discover_copilot_oauth_token()
        if time.time() >= _COPILOT_SESSION["expires_at"] - 60:
            _fetch_copilot_session_token(self._oauth_token)
        client = _build_copilot_client(_COPILOT_SESSION["token"])
        super().__init__(
            model=model.removeprefix("copilot/"),
            client=client,
            inter_call_delay=inter_call_delay,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )

    def _pre_call(self) -> None:
        """Refresh session token if within 60s of expiry; rebuild client if refreshed."""
        if time.time() < _COPILOT_SESSION["expires_at"] - 60:
            return
        new_token = _fetch_copilot_session_token(self._oauth_token)
        self._client = _build_copilot_client(new_token)
```

- [ ] **Step 4: Run tests — expect pass**

```bash
pytest tests/test_backend_copilot.py -v 2>&1 | tail -10
```

Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add agents/backends/copilot.py tests/test_backend_copilot.py
git commit -m "feat(backends): add CopilotBackend with session token refresh"
```

---

### Task 6: NvidiaNimBackend, OpenCodeBackend

**Files:**
- Create: `agents/backends/nvidia_nim.py`
- Create: `agents/backends/opencode.py`
- Create: `tests/test_backend_nvidia_nim.py`
- Create: `tests/test_backend_opencode.py`

- [ ] **Step 1: Write failing tests for NvidiaNimBackend**

Create `tests/test_backend_nvidia_nim.py`:

```python
"""Tests for NvidiaNimBackend."""
import os
from unittest.mock import MagicMock, patch
import pytest


def test_nvidia_nim_requires_api_key():
    from agents.backends.nvidia_nim import NvidiaNimBackend
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(EnvironmentError, match="NVIDIA_API_KEY"):
            NvidiaNimBackend(model="nvidia-nim/nvidia/llama-3.1-8b")


def test_nvidia_nim_strips_prefix():
    from agents.backends.nvidia_nim import NvidiaNimBackend
    with patch("agents.backends.nvidia_nim.OpenAI"):
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "nvapi_test"}):
            b = NvidiaNimBackend(model="nvidia-nim/nvidia/glm-4.1-9b-ea")
    assert b.model == "nvidia/glm-4.1-9b-ea"


def test_nvidia_nim_call():
    from agents.backends.nvidia_nim import NvidiaNimBackend
    with patch("agents.backends.nvidia_nim.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="ok", tool_calls=None))]
        )
        mock_cls.return_value = mock_client
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "nvapi_test"}):
            b = NvidiaNimBackend(model="nvidia-nim/nvidia/llama-3.1-8b")
    assert b.call([{"role": "user", "content": "hi"}]) == "ok"
```

- [ ] **Step 2: Write failing tests for OpenCodeBackend**

Create `tests/test_backend_opencode.py`:

```python
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
```

- [ ] **Step 3: Run — expect failures**

```bash
pytest tests/test_backend_nvidia_nim.py tests/test_backend_opencode.py -v 2>&1 | tail -10
```

- [ ] **Step 4: Implement `agents/backends/nvidia_nim.py`**

```python
"""NVIDIA NIM API backend — OpenAI-compatible."""
from __future__ import annotations
import os
from openai import OpenAI
from agents.backends.base import OpenAICompatibleBackend, _DEFAULT_MAX_RETRIES, _DEFAULT_BASE_DELAY


class NvidiaNimBackend(OpenAICompatibleBackend):
    """NVIDIA NIM API (OpenAI-compatible).

    Model prefix "nvidia-nim/" is stripped.
    Auth: NVIDIA_API_KEY env var or nvidia_nim_api_key constructor arg.
    """

    def __init__(
        self,
        model: str,
        nvidia_nim_api_key: str | None = None,
        nvidia_nim_base_url: str | None = None,
        inter_call_delay: int = 0,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        retry_delay: float = _DEFAULT_BASE_DELAY,
    ) -> None:
        key = nvidia_nim_api_key or os.environ.get("NVIDIA_API_KEY")
        if not key:
            raise EnvironmentError(
                "NVIDIA_API_KEY environment variable is required for NVIDIA NIM. "
                "Get your key at https://build.nvidia.com/"
            )
        base_url = (
            nvidia_nim_base_url
            or os.environ.get("NVIDIA_NIM_BASE_URL")
            or "https://integrate.api.nvidia.com/v1"
        ).rstrip("/")
        client = OpenAI(base_url=base_url, api_key=key)
        super().__init__(
            model=model.removeprefix("nvidia-nim/"),
            client=client,
            inter_call_delay=inter_call_delay,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )
```

- [ ] **Step 5: Implement `agents/backends/opencode.py`**

```python
"""OpenCode CLI subprocess backend."""
from __future__ import annotations
import os
import re
import subprocess
import time
from typing import TYPE_CHECKING

from agents.backends.base import LLMBackend, _DEFAULT_MAX_RETRIES

if TYPE_CHECKING:
    from tools.registry import ToolRegistry


class OpenCodeBackend(LLMBackend):
    """OpenCode CLI backend — runs opencode subprocess for each call.

    Model prefix "opencode/" is stripped; remainder is the provider/model
    passed to `opencode run --model <provider/model>`.
    Does NOT support tool calling.
    """

    def __init__(
        self,
        model: str,
        timeout: int = 600,
        max_retries: int = 2,
    ) -> None:
        self.model = model.removeprefix("opencode/")
        self._timeout = timeout
        self._max_retries = max_retries

    def supports_tools(self) -> bool:
        return False

    def call(self, messages: list[dict]) -> str:
        """Build a combined prompt from messages and run via opencode CLI."""
        bin_path = os.environ.get("OPENCODE_BIN", "opencode")

        # Reconstruct system + history + final user message into a single prompt
        parts: list[str] = []
        chat_messages = []
        for m in messages:
            if m["role"] == "system" and not chat_messages:
                parts.append(f"[SYSTEM ROLE]\n{m['content']}")
            else:
                chat_messages.append(m)

        history = chat_messages[:-1]
        user_message = chat_messages[-1]["content"] if chat_messages else ""

        if history:
            history_lines = []
            for turn in history:
                label = "USER" if turn["role"] == "user" else "ASSISTANT"
                history_lines.append(f"{label}: {turn['content'][:2000]}")
            parts.append("[CONVERSATION HISTORY]\n" + "\n\n".join(history_lines))
        parts.append(user_message)

        full_prompt = "\n\n".join(parts)
        cmd = [bin_path, "run", "--model", self.model, full_prompt]

        for attempt in range(self._max_retries + 1):
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=self._timeout,
                )
                if result.returncode != 0:
                    raise RuntimeError(
                        f"opencode exited {result.returncode}: {result.stderr[:300]}"
                    )
                output = result.stdout.strip()
                if not output:
                    raise RuntimeError("Empty response from opencode")
                output = re.sub(r"\x1b\[[0-9;]*[mGKHF]", "", output).strip()
                if not output:
                    raise RuntimeError("Empty response from opencode after stripping ANSI codes")
                return output
            except (subprocess.TimeoutExpired, RuntimeError):
                if attempt == self._max_retries:
                    raise
                time.sleep(2 ** attempt)

        raise RuntimeError("All opencode retries exhausted")

    def call_with_tools(
        self,
        messages: list[dict],
        tools: "ToolRegistry",
        max_turns: int = 8,
    ) -> str:
        raise NotImplementedError(
            "call_with_tools is not supported for the 'opencode' backend. "
            "Use 'github_models', 'ollama', 'copilot', or 'nvidia_nim' for tool calling."
        )
```

- [ ] **Step 6: Run tests — expect pass**

```bash
pytest tests/test_backend_nvidia_nim.py tests/test_backend_opencode.py -v 2>&1 | tail -10
```

Expected: `7 passed`

- [ ] **Step 7: Commit**

```bash
git add agents/backends/nvidia_nim.py agents/backends/opencode.py \
        tests/test_backend_nvidia_nim.py tests/test_backend_opencode.py
git commit -m "feat(backends): add NvidiaNimBackend and OpenCodeBackend"
```

---

### Task 7: OpenCodeZenBackend and OpenCodeGoBackend

**Files:**
- Create: `agents/backends/opencode_zen.py`
- Create: `agents/backends/opencode_go.py`
- Create: `tests/test_backend_opencode_zen_go.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_backend_opencode_zen_go.py`:

```python
"""Tests for OpenCodeZenBackend and OpenCodeGoBackend."""
import os
from unittest.mock import MagicMock, patch
import pytest


# ── OpenCodeZenBackend ────────────────────────────────────────────────────────

def test_opencode_zen_requires_key():
    from agents.backends.opencode_zen import OpenCodeZenBackend
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(EnvironmentError, match="OPENCODE_ZEN_API_KEY"):
            OpenCodeZenBackend(model="opencode-zen/gpt-4.1")


def test_opencode_zen_non_claude_uses_openai_client():
    from agents.backends.opencode_zen import OpenCodeZenBackend
    with patch("agents.backends.opencode_zen.OpenAI") as mock_oai:
        mock_oai.return_value = MagicMock()
        with patch.dict(os.environ, {"OPENCODE_ZEN_API_KEY": "key_test"}):
            b = OpenCodeZenBackend(model="opencode-zen/gpt-4.1")
    assert b.model == "gpt-4.1"
    assert b.supports_tools() is True


def test_opencode_zen_claude_uses_anthropic_client():
    from agents.backends.opencode_zen import OpenCodeZenBackend
    with patch("agents.backends.opencode_zen.anthropic") as mock_ant:
        mock_ant.Anthropic.return_value = MagicMock()
        with patch.dict(os.environ, {"OPENCODE_ZEN_API_KEY": "key_test"}):
            b = OpenCodeZenBackend(model="opencode-zen/claude-sonnet-4-5")
    assert b.supports_tools() is False


def test_opencode_zen_claude_call_extracts_system():
    from agents.backends.opencode_zen import OpenCodeZenBackend
    mock_ant_client = MagicMock()
    mock_ant_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="Reply")]
    )
    with patch("agents.backends.opencode_zen.anthropic") as mock_ant:
        mock_ant.Anthropic.return_value = mock_ant_client
        with patch.dict(os.environ, {"OPENCODE_ZEN_API_KEY": "key_test"}):
            b = OpenCodeZenBackend(model="opencode-zen/claude-sonnet-4-5")
    result = b.call([{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}])
    assert result == "Reply"
    _, kwargs = mock_ant_client.messages.create.call_args
    assert kwargs["system"] == "sys"


# ── OpenCodeGoBackend ─────────────────────────────────────────────────────────

def test_opencode_go_requires_key():
    from agents.backends.opencode_go import OpenCodeGoBackend
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(EnvironmentError, match="OPENCODE_ZEN_API_KEY"):
            OpenCodeGoBackend(model="opencode-go/kimi-k2.5")


def test_opencode_go_non_minimax_uses_openai_client():
    from agents.backends.opencode_go import OpenCodeGoBackend
    with patch("agents.backends.opencode_go.OpenAI") as mock_oai:
        mock_oai.return_value = MagicMock()
        with patch.dict(os.environ, {"OPENCODE_ZEN_API_KEY": "key_test"}):
            b = OpenCodeGoBackend(model="opencode-go/kimi-k2.5")
    assert b.model == "kimi-k2.5"
    assert b.supports_tools() is True


def test_opencode_go_minimax_uses_anthropic_client():
    from agents.backends.opencode_go import OpenCodeGoBackend
    with patch("agents.backends.opencode_go.anthropic") as mock_ant:
        mock_ant.Anthropic.return_value = MagicMock()
        with patch.dict(os.environ, {"OPENCODE_ZEN_API_KEY": "key_test"}):
            b = OpenCodeGoBackend(model="opencode-go/minimax-m2.7")
    assert b.supports_tools() is False
```

- [ ] **Step 2: Run — expect failures**

```bash
pytest tests/test_backend_opencode_zen_go.py -v 2>&1 | tail -10
```

- [ ] **Step 3: Implement `agents/backends/opencode_zen.py`**

```python
"""OpenCode Zen API backend — OpenAI-compatible or Anthropic-routed for Claude models."""
from __future__ import annotations
import os
import time
from typing import TYPE_CHECKING

from agents.backends.base import (
    LLMBackend, OpenAICompatibleBackend,
    _retry_with_backoff, _DEFAULT_MAX_RETRIES, _DEFAULT_BASE_DELAY,
)

if TYPE_CHECKING:
    from tools.registry import ToolRegistry

try:
    import anthropic
except ImportError:
    anthropic = None  # type: ignore[assignment]

_ANTHROPIC_MODELS = {
    "claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-4-5",
    "claude-3-7-sonnet-20250219", "claude-3-5-sonnet-20241022",
    "claude-3-5-haiku-20241022", "claude-3-opus-20240229",
}


def _zen_key_and_base(
    api_key: str | None = None,
    base_url: str | None = None,
) -> tuple[str, str]:
    key = api_key or os.environ.get("OPENCODE_ZEN_API_KEY") or os.environ.get("OPENCODE_API_KEY")
    if not key:
        raise EnvironmentError(
            "OPENCODE_ZEN_API_KEY environment variable is required for the opencode_zen backend. "
            "Get your key at https://opencode.ai/auth"
        )
    base = (
        base_url
        or os.environ.get("OPENCODE_ZEN_BASE_URL")
        or "https://opencode.ai/zen/v1"
    ).rstrip("/")
    return key, base


class OpenCodeZenBackend(LLMBackend):
    """OpenCode Zen API backend.

    Claude models are routed through the Anthropic Messages API (no tools).
    All other models use the OpenAI-compatible chat/completions endpoint.
    """

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        inter_call_delay: int = 0,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        retry_delay: float = _DEFAULT_BASE_DELAY,
    ) -> None:
        key, base = _zen_key_and_base(api_key, base_url)
        bare_model = model.removeprefix("opencode-zen/")
        self.model = bare_model
        self._inter_call_delay = inter_call_delay
        self._max_retries = max_retries
        self._retry_delay = retry_delay

        if bare_model in _ANTHROPIC_MODELS:
            if anthropic is None:
                raise ImportError("anthropic package required: pip install anthropic")
            self._anthropic_client = anthropic.Anthropic(api_key=key, base_url=base)
            self._oai_backend: OpenAICompatibleBackend | None = None
        else:
            from openai import OpenAI
            client = OpenAI(base_url=base, api_key=key)
            self._oai_backend = OpenAICompatibleBackend(
                model=bare_model, client=client,
                inter_call_delay=inter_call_delay, max_retries=max_retries, retry_delay=retry_delay,
            )
            self._anthropic_client = None

    def supports_tools(self) -> bool:
        return self._oai_backend is not None

    def call(self, messages: list[dict]) -> str:
        if self._oai_backend:
            return self._oai_backend.call(messages)
        # Anthropic path — extract system from messages
        system = ""
        chat_messages = []
        for m in messages:
            if m["role"] == "system" and not chat_messages:
                system = m["content"]
            else:
                chat_messages.append(m)
        if self._inter_call_delay > 0:
            time.sleep(self._inter_call_delay)
        kwargs: dict = {"model": self.model, "max_tokens": 8096, "messages": chat_messages}
        if system:
            kwargs["system"] = system
        response = _retry_with_backoff(
            lambda: self._anthropic_client.messages.create(**kwargs),
            max_retries=self._max_retries, base_delay=self._retry_delay,
        )
        return response.content[0].text

    def call_with_tools(
        self, messages: list[dict], tools: "ToolRegistry", max_turns: int = 8,
    ) -> str:
        if self._oai_backend:
            return self._oai_backend.call_with_tools(messages, tools, max_turns)
        raise NotImplementedError(
            "call_with_tools is not supported for opencode_zen with Claude models. "
            "Use a non-Claude model or switch to github_models/ollama for tool calling."
        )
```

- [ ] **Step 4: Implement `agents/backends/opencode_go.py`**

```python
"""OpenCode Go plan API backend — OpenAI-compatible or Anthropic-routed for MiniMax models."""
from __future__ import annotations
import os
import time
from typing import TYPE_CHECKING

from agents.backends.base import (
    LLMBackend, OpenAICompatibleBackend,
    _retry_with_backoff, _DEFAULT_MAX_RETRIES, _DEFAULT_BASE_DELAY,
)

if TYPE_CHECKING:
    from tools.registry import ToolRegistry

try:
    import anthropic
except ImportError:
    anthropic = None  # type: ignore[assignment]

_OPENCODE_GO_ANTHROPIC_MODELS = {"minimax-m2.7", "minimax-m2.5"}


class OpenCodeGoBackend(LLMBackend):
    """OpenCode Go plan API backend.

    MiniMax models are routed through the Anthropic Messages API (no tools).
    All other models use the OpenAI-compatible chat/completions endpoint (tools supported).
    """

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        inter_call_delay: int = 0,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        retry_delay: float = _DEFAULT_BASE_DELAY,
    ) -> None:
        key = api_key or os.environ.get("OPENCODE_ZEN_API_KEY") or os.environ.get("OPENCODE_API_KEY")
        if not key:
            raise EnvironmentError(
                "OPENCODE_ZEN_API_KEY environment variable is required for the opencode_go backend. "
                "Get your key at https://opencode.ai/auth"
            )
        base = (
            base_url
            or os.environ.get("OPENCODE_GO_BASE_URL")
            or "https://opencode.ai/zen/go/v1"
        ).rstrip("/")

        bare_model = model.removeprefix("opencode-go/")
        self.model = bare_model
        self._inter_call_delay = inter_call_delay
        self._max_retries = max_retries
        self._retry_delay = retry_delay

        if bare_model in _OPENCODE_GO_ANTHROPIC_MODELS:
            if anthropic is None:
                raise ImportError("anthropic package required: pip install anthropic")
            self._anthropic_client = anthropic.Anthropic(api_key=key, base_url=base)
            self._oai_backend: OpenAICompatibleBackend | None = None
        else:
            from openai import OpenAI
            client = OpenAI(base_url=base, api_key=key)
            self._oai_backend = OpenAICompatibleBackend(
                model=bare_model, client=client,
                inter_call_delay=inter_call_delay, max_retries=max_retries, retry_delay=retry_delay,
            )
            self._anthropic_client = None

    def supports_tools(self) -> bool:
        return self._oai_backend is not None

    def call(self, messages: list[dict]) -> str:
        if self._oai_backend:
            return self._oai_backend.call(messages)
        system = ""
        chat_messages = []
        for m in messages:
            if m["role"] == "system" and not chat_messages:
                system = m["content"]
            else:
                chat_messages.append(m)
        if self._inter_call_delay > 0:
            time.sleep(self._inter_call_delay)
        kwargs: dict = {"model": self.model, "max_tokens": 8096, "messages": chat_messages}
        if system:
            kwargs["system"] = system
        response = _retry_with_backoff(
            lambda: self._anthropic_client.messages.create(**kwargs),
            max_retries=self._max_retries, base_delay=self._retry_delay,
        )
        return response.content[0].text

    def call_with_tools(
        self, messages: list[dict], tools: "ToolRegistry", max_turns: int = 8,
    ) -> str:
        if self._oai_backend:
            return self._oai_backend.call_with_tools(messages, tools, max_turns)
        raise NotImplementedError(
            "call_with_tools is not supported for opencode_go with MiniMax models."
        )
```

- [ ] **Step 5: Run tests — expect pass**

```bash
pytest tests/test_backend_opencode_zen_go.py -v 2>&1 | tail -10
```

Expected: `7 passed`

- [ ] **Step 6: Commit**

```bash
git add agents/backends/opencode_zen.py agents/backends/opencode_go.py \
        tests/test_backend_opencode_zen_go.py
git commit -m "feat(backends): add OpenCodeZenBackend and OpenCodeGoBackend"
```

---

### Task 8: FallbackLLMBackend

**Files:**
- Create: `agents/backends/fallback.py`
- Create: `tests/test_backend_fallback.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_backend_fallback.py`:

```python
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
    assert "mock/ok" in captured.out or "secondary_reply" in captured.out


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
```

- [ ] **Step 2: Run — expect failures**

```bash
pytest tests/test_backend_fallback.py -v 2>&1 | tail -10
```

- [ ] **Step 3: Implement `agents/backends/fallback.py`**

```python
"""FallbackLLMBackend — tries backends in order, switches on connection errors."""
from __future__ import annotations
from typing import TYPE_CHECKING

from agents.backends.base import LLMBackend, FALLBACK_ERRORS

if TYPE_CHECKING:
    from tools.registry import ToolRegistry


class FallbackLLMBackend(LLMBackend):
    """Ordered list of LLMBackend instances — tries each on connection failure.

    On a FALLBACK_ERRORS exception from backend N:
      - Prints a visible ⚠️ warning to stdout
      - Passes the full messages list (with history) to backend N+1
      - If all backends fail, re-raises the last exception

    Does NOT fall back on auth errors or bad-request errors — those indicate
    a configuration problem that switching backends won't fix.
    """

    def __init__(self, backends: list[LLMBackend]) -> None:
        if not backends:
            raise ValueError("FallbackLLMBackend requires at least one backend")
        self._backends = backends

    @property
    def model(self) -> str:
        return self._backends[0].model

    def supports_tools(self) -> bool:
        return self._backends[0].supports_tools()

    def call(self, messages: list[dict]) -> str:
        last_exc: BaseException | None = None
        for i, backend in enumerate(self._backends):
            try:
                return backend.call(messages)
            except FALLBACK_ERRORS as exc:
                last_exc = exc
                if i < len(self._backends) - 1:
                    next_model = self._backends[i + 1].model
                    print(
                        f"⚠️  {backend.model} unreachable ({type(exc).__name__}: {exc}), "
                        f"falling back to {next_model}"
                    )
                else:
                    raise
        raise last_exc  # type: ignore[misc]

    def call_with_tools(
        self,
        messages: list[dict],
        tools: "ToolRegistry",
        max_turns: int = 8,
    ) -> str:
        last_exc: BaseException | None = None
        for i, backend in enumerate(self._backends):
            try:
                return backend.call_with_tools(messages, tools, max_turns)
            except FALLBACK_ERRORS as exc:
                last_exc = exc
                if i < len(self._backends) - 1:
                    next_model = self._backends[i + 1].model
                    print(
                        f"⚠️  {backend.model} unreachable ({type(exc).__name__}: {exc}), "
                        f"falling back to {next_model}"
                    )
                else:
                    raise
        raise last_exc  # type: ignore[misc]
```

- [ ] **Step 4: Run tests — expect pass**

```bash
pytest tests/test_backend_fallback.py -v 2>&1 | tail -10
```

Expected: `9 passed`

- [ ] **Step 5: Commit**

```bash
git add agents/backends/fallback.py tests/test_backend_fallback.py
git commit -m "feat(backends): add FallbackLLMBackend with visible ⚠️ warnings"
```

---

### Task 9: factory.py

**Files:**
- Create: `agents/backends/factory.py`
- Create: `tests/test_backend_factory.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_backend_factory.py`:

```python
"""Tests for factory.create_backend()."""
from __future__ import annotations
import os
from unittest.mock import MagicMock, patch
import pytest


def test_factory_returns_github_models_by_default():
    from agents.backends.factory import create_backend
    from agents.backends.github_models import GitHubModelsBackend
    with patch("agents.backends.github_models.OpenAI"):
        with patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"}):
            b = create_backend({"model": "gpt-4.1"})
    assert isinstance(b, GitHubModelsBackend)
    assert b.model == "gpt-4.1"


def test_factory_returns_ollama_backend():
    from agents.backends.factory import create_backend
    from agents.backends.ollama import OllamaBackend
    with patch("agents.backends.ollama.OpenAI"):
        b = create_backend({"model": "ollama/qwen3.6"})
    assert isinstance(b, OllamaBackend)
    assert b.model == "qwen3.6"


def test_factory_passes_ollama_options():
    from agents.backends.factory import create_backend
    from agents.backends.ollama import OllamaBackend
    with patch("agents.backends.ollama.OpenAI"):
        b = create_backend({
            "model": "ollama/qwen3.6",
            "ollama_think": True,
            "ollama_preserve_thinking": True,
            "ollama_stream": False,
        })
    assert isinstance(b, OllamaBackend)
    assert b._think is True
    assert b._preserve_thinking is True
    assert b._stream is False


def test_factory_returns_fallback_backend_when_fallbacks_configured():
    from agents.backends.factory import create_backend
    from agents.backends.fallback import FallbackLLMBackend
    from agents.backends.github_models import GitHubModelsBackend
    from agents.backends.ollama import OllamaBackend
    with patch("agents.backends.ollama.OpenAI"):
        with patch("agents.backends.github_models.OpenAI"):
            with patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"}):
                b = create_backend({
                    "model": "ollama/qwen3.6",
                    "fallbacks": [{"model": "gpt-4.1"}],
                })
    assert isinstance(b, FallbackLLMBackend)
    assert isinstance(b._backends[0], OllamaBackend)
    assert isinstance(b._backends[1], GitHubModelsBackend)


def test_factory_no_fallbacks_returns_plain_backend():
    from agents.backends.factory import create_backend
    from agents.backends.fallback import FallbackLLMBackend
    with patch("agents.backends.ollama.OpenAI"):
        b = create_backend({"model": "ollama/qwen3.6", "fallbacks": []})
    assert not isinstance(b, FallbackLLMBackend)


def test_factory_fallback_inherits_global_config():
    """Fallback backends inherit inter_call_delay from top-level config."""
    from agents.backends.factory import create_backend
    from agents.backends.fallback import FallbackLLMBackend
    with patch("agents.backends.ollama.OpenAI"):
        with patch("agents.backends.github_models.OpenAI"):
            with patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"}):
                b = create_backend({
                    "model": "ollama/qwen3.6",
                    "inter_call_delay": 5,
                    "fallbacks": [{"model": "gpt-4.1"}],
                })
    assert isinstance(b, FallbackLLMBackend)
    # fallback backend inherits inter_call_delay
    assert b._backends[1]._inter_call_delay == 5


def test_factory_copilot_backend():
    from agents.backends.factory import create_backend
    from agents.backends.copilot import CopilotBackend
    import time
    with patch("agents.backends.copilot._fetch_copilot_session_token"):
        with patch("agents.backends.copilot.OpenAI"):
            with patch("agents.backends.copilot._COPILOT_SESSION", {"token": "t", "expires_at": time.time() + 3600}):
                with patch.dict(os.environ, {"COPILOT_OAUTH_TOKEN": "gho_test"}):
                    b = create_backend({"model": "copilot/gpt-4.1"})
    assert isinstance(b, CopilotBackend)
    assert b.model == "gpt-4.1"
```

- [ ] **Step 2: Run — expect failures**

```bash
pytest tests/test_backend_factory.py -v 2>&1 | tail -10
```

- [ ] **Step 3: Implement `agents/backends/factory.py`**

```python
"""Factory for creating LLMBackend instances from config dicts."""
from __future__ import annotations
from typing import Optional

from agents.backends.base import LLMBackend, _DEFAULT_MAX_RETRIES, _DEFAULT_BASE_DELAY


def create_backend(
    cfg: dict,
    github_token: Optional[str] = None,
) -> LLMBackend:
    """Create an LLMBackend (or FallbackLLMBackend) from a config dict.

    Args:
        cfg: Dict with at minimum {"model": "..."}.
             Optional keys: ollama_url, ollama_think, ollama_preserve_thinking,
             ollama_stream, nvidia_nim_api_key, nvidia_nim_base_url,
             opencode_zen_api_key, opencode_zen_base_url, opencode_go_base_url,
             inter_call_delay, max_api_retries, retry_delay, fallbacks.
        github_token: Passed to GitHubModelsBackend / CopilotBackend.

    Returns:
        A plain LLMBackend if no fallbacks configured,
        or FallbackLLMBackend([primary, ...fallbacks]) if fallbacks present.
    """
    fallbacks_cfg: list[dict] = cfg.get("fallbacks", [])

    primary = _create_single(cfg, github_token)
    if not fallbacks_cfg:
        return primary

    from agents.backends.fallback import FallbackLLMBackend
    backends = [primary]
    for fb_override in fallbacks_cfg:
        # Fallback inherits all global settings unless overridden in its own dict
        merged = {**cfg, **fb_override, "fallbacks": []}
        backends.append(_create_single(merged, github_token))
    return FallbackLLMBackend(backends)


def _create_single(cfg: dict, github_token: Optional[str]) -> LLMBackend:
    """Build one backend from a config dict (no fallback wrapping)."""
    model: str = cfg.get("model", "gpt-4.1")
    inter_call_delay: int = cfg.get("inter_call_delay", 0)
    max_retries: int = cfg.get("max_api_retries", _DEFAULT_MAX_RETRIES)
    retry_delay: float = float(cfg.get("retry_delay", _DEFAULT_BASE_DELAY))

    common = dict(
        inter_call_delay=inter_call_delay,
        max_retries=max_retries,
        retry_delay=retry_delay,
    )

    if model.startswith("ollama/"):
        from agents.backends.ollama import OllamaBackend
        return OllamaBackend(
            model=model,
            ollama_url=cfg.get("ollama_url", "http://localhost:11434"),
            think=cfg.get("ollama_think", False),
            preserve_thinking=cfg.get("ollama_preserve_thinking", False),
            stream=cfg.get("ollama_stream", True),
            **common,
        )

    if model.startswith("copilot/"):
        from agents.backends.copilot import CopilotBackend
        return CopilotBackend(model=model, **common)

    if model.startswith("nvidia-nim/"):
        from agents.backends.nvidia_nim import NvidiaNimBackend
        return NvidiaNimBackend(
            model=model,
            nvidia_nim_api_key=cfg.get("nvidia_nim_api_key"),
            nvidia_nim_base_url=cfg.get("nvidia_nim_base_url"),
            **common,
        )

    if model.startswith("opencode/"):
        from agents.backends.opencode import OpenCodeBackend
        return OpenCodeBackend(
            model=model,
            timeout=cfg.get("opencode_timeout", 600),
            max_retries=cfg.get("opencode_max_retries", 2),
        )

    if model.startswith("opencode-zen/"):
        from agents.backends.opencode_zen import OpenCodeZenBackend
        return OpenCodeZenBackend(
            model=model,
            api_key=cfg.get("opencode_zen_api_key"),
            base_url=cfg.get("opencode_zen_base_url"),
            **common,
        )

    if model.startswith("opencode-go/"):
        from agents.backends.opencode_go import OpenCodeGoBackend
        return OpenCodeGoBackend(
            model=model,
            api_key=cfg.get("opencode_zen_api_key"),
            base_url=cfg.get("opencode_go_base_url"),
            **common,
        )

    # Anthropic direct (model names like "claude-sonnet-4-5", no prefix)
    _ANTHROPIC_PREFIXES = ("claude-",)
    if any(model.startswith(p) for p in _ANTHROPIC_PREFIXES):
        from agents.backends.anthropic import AnthropicBackend
        return AnthropicBackend(model=model, **common)

    # Default: GitHub Models
    from agents.backends.github_models import GitHubModelsBackend
    return GitHubModelsBackend(model=model, github_token=github_token, **common)
```

- [ ] **Step 4: Run tests — expect pass**

```bash
pytest tests/test_backend_factory.py -v 2>&1 | tail -10
```

Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add agents/backends/factory.py tests/test_backend_factory.py
git commit -m "feat(backends): add factory.create_backend()"
```

---

### Task 10: Refactor BaseAgent

**Files:**
- Modify: `agents/base_agent.py` (remove ~400 lines of backend code, add `self._llm`)

- [ ] **Step 1: Run existing base-agent-related tests to establish baseline**

```bash
pytest tests/test_copilot_backend.py tests/test_ollama.py tests/test_opencode.py \
       tests/test_opencode_zen.py tests/test_opencode_go.py -v 2>&1 | tail -20
```

Note any failures — these tests will need import path updates after refactoring.

- [ ] **Step 2: Replace `__init__` and remove backend code from `base_agent.py`**

Replace the entire `BaseAgent.__init__` with the new signature (lines ~292–490 in the original). The new `__init__` receives `llm: LLMBackend` directly:

```python
def __init__(
    self,
    model: str = "gpt-4.1",
    llm: Optional["LLMBackend"] = None,
    roles_dir: Optional[Path] = None,
    retry_delay: int = 15,
    max_api_retries: int = 5,
    inter_call_delay: int = 0,
) -> None:
    from agents.backends.base import LLMBackend as _LLMBackend
    self.model = model
    if llm is None:
        # Backward-compat: build a default GitHubModelsBackend
        from agents.backends.factory import create_backend
        llm = create_backend({"model": model, "max_api_retries": max_api_retries,
                               "retry_delay": float(retry_delay), "inter_call_delay": inter_call_delay})
    self._llm = llm
    self.system_prompt = self._load_system_prompt(roles_dir)
    self._retry_delay = retry_delay
    self._max_api_retries = max_api_retries
    self._inter_call_delay = inter_call_delay
    self._history: list[dict] = []
```

Also remove these methods that move to backend files:
- `_ollama_extra_body()` (now in `OllamaBackend`)
- `_strip_thinking()` (now in `OllamaBackend`)
- `_build_copilot_client()` (now in `copilot.py`)
- `_ensure_copilot_session()` (now in `CopilotBackend._pre_call()`)
- `_call_anthropic()` (now in `AnthropicBackend.call()`)
- `_call_opencode()` (now in `OpenCodeBackend.call()`)

And remove all module-level backend detection functions (`_is_ollama_model` etc.) — they move to `factory.py` or become inline in factory.

- [ ] **Step 3: Update `call()` method to delegate to `self._llm`**

Replace the entire `call()` method body:

```python
def call(self, user_message: str, context: Optional[str] = None) -> str:
    """Send a message and return the assistant reply.

    Maintains conversation history within the same agent instance.
    """
    full_message = f"{context}\n\n{user_message}" if context else user_message
    messages: list[dict] = []
    if self.system_prompt:
        messages.append({"role": "system", "content": self.system_prompt})
    messages.extend(self._history)
    messages.append({"role": "user", "content": full_message})

    if self._inter_call_delay > 0:
        import time
        time.sleep(self._inter_call_delay)

    reply = self._llm.call(messages)

    self._history.append({"role": "user", "content": full_message})
    self._history.append({"role": "assistant", "content": reply})
    return reply
```

- [ ] **Step 4: Update `call_with_tools()` to delegate to `self._llm`**

Replace the entire `call_with_tools()` method body:

```python
def call_with_tools(
    self,
    user_message: str,
    tools: "ToolRegistry",
    context: Optional[str] = None,
    max_turns: int = 8,
) -> str:
    """Send a message, execute tool calls, return final reply.

    History is NOT updated — tool-call turns are ephemeral.
    """
    if not self._llm.supports_tools():
        raise NotImplementedError(
            f"call_with_tools is not supported for the '{type(self._llm).__name__}' backend. "
            "Use github_models, ollama, copilot, or nvidia_nim for tool calling."
        )
    full_message = f"{context}\n\n{user_message}" if context else user_message
    messages: list[dict] = []
    if self.system_prompt:
        messages.append({"role": "system", "content": self.system_prompt})
    messages.append({"role": "user", "content": full_message})
    return self._llm.call_with_tools(messages, tools, max_turns)
```

- [ ] **Step 5: Remove module-level backend imports/constants no longer needed in base_agent.py**

At the top of `base_agent.py`, remove:
- `import httpx` (no longer used)
- `_COPILOT_SESSION`, `_COPILOT_API_BASE`, `_COPILOT_TOKEN_URL`, `_COPILOT_CONFIG_PATH`
- `_OPENCODE_GO_ANTHROPIC_MODELS`
- All `_is_*_model()` functions
- `_discover_copilot_oauth_token()`, `_fetch_copilot_session_token()`
- `_retry_with_backoff()`, `_DEFAULT_MAX_RETRIES`, `_DEFAULT_BASE_DELAY`
- `_ANTHROPIC_MODELS`
- `_ollama_timeout`

Keep: `import re`, `import os`, `import time`, `import subprocess` (for any remaining uses), `from openai import OpenAI` → remove this too.

Update the module docstring to reflect the new simpler structure.

- [ ] **Step 6: Run all backend tests + base agent tests**

```bash
pytest tests/test_backends_base.py tests/test_backend_github_models.py \
       tests/test_backend_ollama.py tests/test_backend_anthropic.py \
       tests/test_backend_copilot.py tests/test_backend_nvidia_nim.py \
       tests/test_backend_opencode.py tests/test_backend_opencode_zen_go.py \
       tests/test_backend_fallback.py tests/test_backend_factory.py -v 2>&1 | tail -20
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add agents/base_agent.py
git commit -m "refactor(base_agent): delegate all LLM calls to self._llm backend"
```

---

### Task 11: Refactor Orchestrator

**Files:**
- Modify: `orchestrator.py` — build LLMBackend via factory, keep backward-compat config API
- Modify: `config.yaml` — add `fallbacks` documentation

- [ ] **Step 1: Update `Orchestrator.__init__` to build backends via factory**

In `orchestrator.py`, replace the `agent_kwargs` dict and `_agent_ollama_kwargs` function with a `_make_backend` helper. Keep all existing `__init__` params for backward compatibility.

Find these lines (~306–313):
```python
agent_kwargs: dict = {"github_token": github_token, "ollama_url": ollama_url,
                      "ollama_think": ollama_think, "ollama_preserve_thinking": ollama_preserve_thinking,
                      "ollama_stream": ollama_stream,
                      "nvidia_nim_api_key": nvidia_nim_api_key,
                      "nvidia_nim_base_url": nvidia_nim_base_url,
                      "retry_delay": retry_delay, "max_api_retries": max_api_retries,
                      "inter_call_delay": inter_call_delay}
self.agent_kwargs = agent_kwargs
```

Replace with:

```python
# Global LLM config dict — used by factory to build backends
_global_llm_cfg: dict = {
    "ollama_url": ollama_url,
    "ollama_think": ollama_think,
    "ollama_preserve_thinking": ollama_preserve_thinking,
    "ollama_stream": ollama_stream,
    "nvidia_nim_api_key": nvidia_nim_api_key,
    "nvidia_nim_base_url": nvidia_nim_base_url,
    "max_api_retries": max_api_retries,
    "retry_delay": retry_delay,
    "inter_call_delay": inter_call_delay,
    "fallbacks": llm_fallbacks,  # see from_config below
}

# Shared non-LLM kwargs passed to every agent constructor
agent_kwargs: dict = {
    "github_token": github_token,
    "retry_delay": retry_delay,
    "max_api_retries": max_api_retries,
    "inter_call_delay": inter_call_delay,
}
self.agent_kwargs = agent_kwargs

from agents.backends.factory import create_backend as _create_backend

def _make_backend(agent_name: str) -> "LLMBackend":
    override = self.model_overrides.get(agent_name, {})
    if isinstance(override, str):
        override = {"model": override}
    cfg = {**_global_llm_cfg, "model": _model(agent_name), **override}
    return _create_backend(cfg, github_token=github_token)
```

- [ ] **Step 2: Update all agent instantiation calls to use `llm=_make_backend(...)`**

Find and replace agent constructor calls (~lines 347–400). Example pattern:

Before:
```python
self.pm = ProductManagerAgent(model=_model("product_manager"), **{**agent_kwargs, **_agent_ollama_kwargs("product_manager")})
```

After:
```python
self.pm = ProductManagerAgent(
    model=_model("product_manager"),
    llm=_make_backend("product_manager"),
    **agent_kwargs,
)
```

Apply this pattern to all 15+ agent instantiations in `__init__`. Remove the `_agent_ollama_kwargs` function entirely.

- [ ] **Step 3: Add `llm_fallbacks` param to `__init__` and `from_config`**

In `Orchestrator.__init__` signature add:
```python
llm_fallbacks: list[dict] | None = None,
```

In `from_config`, read it:
```python
llm_fallbacks=llm.get("fallbacks", []),
```

- [ ] **Step 4: Document `fallbacks` in config.yaml**

Find the `ollama_preserve_thinking` block in `config.yaml` and add after it:

```yaml
  # Fallback chain — if the primary model is unreachable (connection error,
  # timeout), the pipeline auto-switches to the next backend and prints a
  # ⚠️ warning. Each fallback inherits global llm settings unless overridden.
  # fallbacks:
  #   - model: "copilot/gpt-4.1"
  #   - model: "github_models/gpt-4o-mini"
  #
  # Per-agent fallback (in overrides):
  #   architect:
  #     model: "ollama/qwen3.6"
  #     fallbacks:
  #       - model: "copilot/claude-sonnet-4.6"
```

- [ ] **Step 5: Run orchestrator tests**

```bash
pytest tests/test_architect_tier.py tests/test_bug_fix_retry.py \
       tests/test_code_reviewer.py tests/test_copilot_backend.py \
       tests/test_revision.py tests/test_prd_design_loops.py \
       tests/test_junior_senior_engineer.py -v 2>&1 | tail -25
```

Fix any import errors from moved symbols.

- [ ] **Step 6: Commit**

```bash
git add orchestrator.py config.yaml
git commit -m "refactor(orchestrator): build LLMBackend via factory, add fallbacks support"
```

---

### Task 12: Update Existing Backend Tests

**Files:**
- Modify: `tests/test_copilot_backend.py` — update imports from `base_agent` → `backends.copilot`
- Modify: `tests/test_ollama.py` — update imports for `_is_ollama_model` (now in factory)
- Modify: `tests/test_opencode.py`, `tests/test_opencode_zen.py`, `tests/test_opencode_go.py` — update imports

- [ ] **Step 1: Update `tests/test_copilot_backend.py` imports**

Find all lines importing from `agents.base_agent` that reference moved symbols:

```python
# Before
from agents.base_agent import _is_copilot_model
from agents.base_agent import _discover_copilot_oauth_token
from agents.base_agent import _fetch_copilot_session_token
from agents.base_agent import _COPILOT_SESSION

# After
from agents.backends.copilot import _discover_copilot_oauth_token
from agents.backends.copilot import _fetch_copilot_session_token
from agents.backends.copilot import _COPILOT_SESSION
```

For `_is_copilot_model` — the factory uses model prefix detection inline, so the function no longer exists. Replace those tests with:
```python
def test_copilot_model_detected_by_factory():
    from agents.backends.factory import _create_single
    import os
    with patch("agents.backends.copilot.OpenAI"):
        with patch("agents.backends.copilot._fetch_copilot_session_token"):
            with patch.dict(os.environ, {"COPILOT_OAUTH_TOKEN": "gho_test"}):
                with patch("agents.backends.copilot._COPILOT_SESSION", {"token": "t", "expires_at": 9999999999.0}):
                    b = _create_single({"model": "copilot/gpt-4.1"}, github_token=None)
    from agents.backends.copilot import CopilotBackend
    assert isinstance(b, CopilotBackend)
```

- [ ] **Step 2: Update `tests/test_ollama.py` imports**

```python
# Before
from agents.base_agent import _is_ollama_model
from agents.base_agent import BaseAgent

# After — _is_ollama_model replaced by factory prefix detection
# Test via factory instead:
def test_ollama_model_detected_by_factory():
    from agents.backends.factory import _create_single
    with patch("agents.backends.ollama.OpenAI"):
        b = _create_single({"model": "ollama/qwen3.6"}, github_token=None)
    from agents.backends.ollama import OllamaBackend
    assert isinstance(b, OllamaBackend)
```

For `BaseAgent` tests that check `agent._backend == "ollama"`, replace with:
```python
from agents.backends.ollama import OllamaBackend
assert isinstance(agent._llm, OllamaBackend)
```

- [ ] **Step 3: Update opencode test imports similarly**

For `tests/test_opencode.py`, `tests/test_opencode_zen.py`, `tests/test_opencode_go.py`:
- Replace `from agents.base_agent import _is_opencode_model` with factory-based tests
- Replace `agent._backend == "opencode"` checks with `isinstance(agent._llm, OpenCodeBackend)`

- [ ] **Step 4: Run all updated tests**

```bash
pytest tests/test_copilot_backend.py tests/test_ollama.py tests/test_opencode.py \
       tests/test_opencode_zen.py tests/test_opencode_go.py -v 2>&1 | tail -20
```

Fix any remaining import errors or assertion failures.

- [ ] **Step 5: Commit**

```bash
git add tests/test_copilot_backend.py tests/test_ollama.py tests/test_opencode.py \
        tests/test_opencode_zen.py tests/test_opencode_go.py
git commit -m "test: update backend test imports after refactor"
```

---

### Task 13: Full test run + create PR

- [ ] **Step 1: Run the full test suite**

```bash
pytest tests/ -q --ignore=tests/test_deployment.py --ignore=tests/integration \
       --ignore=tests/test_event_normalizer.py --ignore=tests/unit 2>&1 | tail -30
```

Expected: same pass count as before refactor (397 tests). Fix any failures before proceeding.

- [ ] **Step 2: Verify base_agent.py line count has meaningfully reduced**

```bash
wc -l agents/base_agent.py agents/backends/*.py
```

Expected: `base_agent.py` ≤ 520 lines; total across all backend files ~600 lines.

- [ ] **Step 3: Commit any final fixes**

```bash
git add -A
git commit -m "fix: resolve any remaining test failures after backend extraction"
```

- [ ] **Step 4: Push feature branch**

```bash
git push -u origin feature/llm-backend-proxy
```

- [ ] **Step 5: Create Pull Request**

```bash
gh pr create \
  --base master \
  --title "feat: extract LLM backends to agents/backends/ with FallbackLLMBackend" \
  --body "$(cat <<'EOF'
## Summary

- Extracted all LLM backend code from \`base_agent.py\` (905 lines → ~520 lines) into \`agents/backends/\`
- Added \`FallbackLLMBackend\`: auto-switches on connection errors, replays full history, prints ⚠️ warning
- Added \`factory.create_backend()\`: builds backend (or fallback chain) from config dict
- Config-driven global + per-agent fallback chains via \`llm.fallbacks\` in \`config.yaml\`

## New files
- \`agents/backends/base.py\` — \`LLMBackend\` ABC, \`OpenAICompatibleBackend\`, \`_retry_with_backoff\`
- \`agents/backends/fallback.py\` — \`FallbackLLMBackend\`
- \`agents/backends/factory.py\` — \`create_backend()\`
- \`agents/backends/github_models.py\`, \`ollama.py\`, \`anthropic.py\`, \`copilot.py\`
- \`agents/backends/nvidia_nim.py\`, \`opencode.py\`, \`opencode_zen.py\`, \`opencode_go.py\`

## Test plan
- [ ] All existing tests pass
- [ ] New unit tests for each backend class
- [ ] New unit tests for \`FallbackLLMBackend\` (connection error switch, auth error no-switch, history replay)
- [ ] New unit tests for \`factory.create_backend()\`

## Backward compatibility
- \`config.yaml\` keys unchanged
- \`Orchestrator.__init__\` signature unchanged (new optional \`llm_fallbacks\` param)
- \`BaseAgent.__init__\` accepts \`llm=None\` (defaults to GitHubModelsBackend for backward compat)
EOF
)"
```

- [ ] **Step 6: Print PR URL**

```bash
gh pr view --web
```

Share the PR URL with the user for review before merging.
