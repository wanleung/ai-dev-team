"""
BaseAgent: delegates all LLM calls to an LLMBackend instance.

Supports eight backends, auto-selected from the model prefix or set via ``backend=``:

  github_models  — GitHub Models API (GITHUB_TOKEN)          [default fallback]
  anthropic      — Anthropic Claude API (ANTHROPIC_API_KEY)
  ollama         — Local Ollama server (prefix "ollama/")
  opencode       — OpenCode CLI subprocess (prefix "opencode/")
  opencode_zen   — OpenCode Zen API (prefix "opencode-zen/", OPENCODE_ZEN_API_KEY)
  opencode_go    — OpenCode Go plan API (prefix "opencode-go/", OPENCODE_ZEN_API_KEY)
  nvidia_nim     — NVIDIA NIM API (prefix "nvidia-nim/", NVIDIA_API_KEY)
  copilot        — GitHub Copilot Chat API (prefix "copilot/", COPILOT_OAUTH_TOKEN)

Pass ``llm=<LLMBackend instance>`` to bypass auto-detection and inject any backend.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from tools.registry import ToolRegistry

from openai import OpenAI  # noqa: F401 – kept so tests can patch agents.base_agent.OpenAI
from agents.backends.base import (
    LLMBackend as _LLMBackend,
    OpenAICompatibleBackend as _OAIBackend,
    _retry_with_backoff,  # noqa: F401 – backward-compat re-export
)
from agents.backends.copilot import (
    _discover_copilot_oauth_token,  # noqa: F401 – backward-compat re-export
    _fetch_copilot_session_token,   # noqa: F401 – backward-compat re-export
    _COPILOT_SESSION,               # noqa: F401 – backward-compat re-export (same dict object)
    _COPILOT_API_BASE,              # noqa: F401 – backward-compat re-export
)

_log = logging.getLogger(__name__)


# ── Backward-compat predicates (kept so external code can still import them) ──

def _is_anthropic_model(model: str) -> bool:
    """Return True if *model* is an Anthropic Claude model."""
    return model.startswith("claude-")


def _is_ollama_model(model: str) -> bool:
    """Return True if the model name indicates an Ollama-hosted model."""
    return model.startswith("ollama/")


def _is_opencode_model(model: str) -> bool:
    """Return True if the model should be run via the opencode CLI subprocess."""
    return model.startswith("opencode/")


def _is_opencode_zen_model(model: str) -> bool:
    """Return True if the model should use the OpenCode Zen direct API."""
    return model.startswith("opencode-zen/")


def _is_opencode_go_model(model: str) -> bool:
    """Return True if the model should use the OpenCode Go plan direct API."""
    return model.startswith("opencode-go/")


def _is_nvidia_nim_model(model: str) -> bool:
    """Return True if the model should use the NVIDIA NIM API."""
    return model.startswith("nvidia-nim/")


def _is_copilot_model(model: str) -> bool:
    """Return True if the model name indicates a GitHub Copilot model."""
    return model.startswith("copilot/")


class BaseAgent:
    """Base class for all software house agents.

    Accepts an optional ``llm`` parameter to inject a pre-built
    :class:`~agents.backends.base.LLMBackend`.  When ``llm`` is *None*
    (the default) the backend is auto-selected from the model prefix or
    the explicit ``backend=`` argument, exactly as before this refactor.
    """

    role_name: str = ""

    def __init__(
        self,
        model: str = "gpt-4.1",
        llm: "Optional[_LLMBackend]" = None,
        github_token: Optional[str] = None,
        roles_dir: Optional[Path] = None,
        backend: Optional[str] = None,
        ollama_url: str = "http://localhost:11434",
        ollama_think: bool = False,
        ollama_preserve_thinking: bool = False,
        ollama_stream: bool = True,
        opencode_stream: bool = True,
        github_models_stream: bool = True,
        opencode_zen_api_key: Optional[str] = None,
        opencode_zen_base_url: Optional[str] = None,
        opencode_go_base_url: Optional[str] = None,
        nvidia_nim_api_key: Optional[str] = None,
        nvidia_nim_base_url: Optional[str] = None,
        retry_delay: int = 15,
        max_api_retries: int = 5,
        inter_call_delay: int = 0,
        **kwargs,
    ) -> None:
        self.model = model
        self.system_prompt = self._load_system_prompt(roles_dir)
        self._token = github_token
        self._retry_delay = retry_delay
        self._max_api_retries = max_api_retries
        self._inter_call_delay = inter_call_delay
        self._ollama_think = ollama_think
        self._ollama_preserve_thinking = ollama_preserve_thinking
        self._ollama_stream = ollama_stream
        self._opencode_stream = opencode_stream
        self._github_models_stream = github_models_stream
        self._history: list[dict] = []

        if llm is not None:
            self._llm: _LLMBackend = llm
        else:
            self._llm = self._build_backend(
                model=model,
                github_token=github_token,
                backend=backend,
                ollama_url=ollama_url,
                ollama_think=ollama_think,
                ollama_preserve_thinking=ollama_preserve_thinking,
                ollama_stream=ollama_stream,
                opencode_stream=opencode_stream,
                github_models_stream=github_models_stream,
                opencode_zen_api_key=opencode_zen_api_key,
                opencode_zen_base_url=opencode_zen_base_url,
                opencode_go_base_url=opencode_go_base_url,
                nvidia_nim_api_key=nvidia_nim_api_key,
                nvidia_nim_base_url=nvidia_nim_base_url,
                retry_delay=retry_delay,
                max_api_retries=max_api_retries,
                inter_call_delay=inter_call_delay,
            )

        # Backward-compat attributes derived from the backend
        self._backend: str = self._detect_backend_name()
        self._api_model: str = self._llm.model
        # Keep self.model in sync with the injected backend's actual model string
        self.model = self._llm.model

    # ── Backward-compat properties ─────────────────────────────────────────────

    @property
    def client(self):
        """Return the OpenAI client from the backend (None for Anthropic-only backends)."""
        if isinstance(self._llm, _OAIBackend):
            return self._llm._client
        oai = getattr(self._llm, "_oai_backend", None)
        if oai is not None:
            return getattr(oai, "_client", None)
        return None

    @client.setter
    def client(self, value) -> None:
        """Update the OpenAI client stored in the backend (used by tests)."""
        if isinstance(self._llm, _OAIBackend):
            self._llm._client = value
            return
        oai = getattr(self._llm, "_oai_backend", None)
        if oai is not None:
            oai._client = value

    @property
    def _anthropic_client(self):
        """Return the Anthropic client from the backend (None for OpenAI-only backends)."""
        from agents.backends.anthropic import AnthropicBackend
        if isinstance(self._llm, AnthropicBackend):
            return self._llm._client
        return getattr(self._llm, "_anthropic_client", None)

    @_anthropic_client.setter
    def _anthropic_client(self, value) -> None:
        """Update the Anthropic client stored in the backend (used by tests)."""
        from agents.backends.anthropic import AnthropicBackend
        if isinstance(self._llm, AnthropicBackend):
            self._llm._client = value
        elif hasattr(self._llm, "_anthropic_client"):
            self._llm._anthropic_client = value

    # ── Private helpers ────────────────────────────────────────────────────────

    def _detect_backend_name(self) -> str:
        """Return the string backend name for the current ``_llm`` instance."""
        from agents.backends.ollama import OllamaBackend
        from agents.backends.github_models import GitHubModelsBackend
        from agents.backends.copilot import CopilotBackend
        from agents.backends.anthropic import AnthropicBackend
        from agents.backends.opencode import OpenCodeBackend
        from agents.backends.opencode_zen import OpenCodeZenBackend
        from agents.backends.opencode_go import OpenCodeGoBackend
        from agents.backends.nvidia_nim import NvidiaNimBackend

        b = self._llm
        if isinstance(b, OllamaBackend):      return "ollama"
        if isinstance(b, CopilotBackend):     return "copilot"
        if isinstance(b, AnthropicBackend):   return "anthropic"
        if isinstance(b, OpenCodeBackend):    return "opencode"
        if isinstance(b, OpenCodeZenBackend): return "opencode_zen"
        if isinstance(b, OpenCodeGoBackend):  return "opencode_go"
        if isinstance(b, NvidiaNimBackend):   return "nvidia_nim"
        if isinstance(b, GitHubModelsBackend):return "github_models"
        return "custom"

    def _build_backend(
        self,
        model: str,
        github_token: Optional[str],
        backend: Optional[str],
        ollama_url: str,
        ollama_think: bool,
        ollama_preserve_thinking: bool,
        ollama_stream: bool,
        opencode_stream: bool,
        github_models_stream: bool,
        opencode_zen_api_key: Optional[str],
        opencode_zen_base_url: Optional[str],
        opencode_go_base_url: Optional[str],
        nvidia_nim_api_key: Optional[str],
        nvidia_nim_base_url: Optional[str],
        retry_delay: int,
        max_api_retries: int,
        inter_call_delay: int,
    ) -> _LLMBackend:
        """Detect which backend to use and construct it from the supplied kwargs."""
        use_opencode_zen = (backend == "opencode_zen") or (
            backend is None and _is_opencode_zen_model(model)
        )
        use_opencode_go = (backend == "opencode_go") or (
            backend is None and _is_opencode_go_model(model)
        )
        use_nvidia_nim = (backend == "nvidia_nim") or (
            backend is None and _is_nvidia_nim_model(model)
        )
        use_copilot = (backend == "copilot") or (
            backend is None and _is_copilot_model(model)
        )
        use_anthropic = (backend == "anthropic") or (
            backend is None
            and not use_opencode_zen and not use_opencode_go
            and not use_nvidia_nim and not use_copilot
            and _is_anthropic_model(model)
        )
        use_ollama = (backend == "ollama") or (
            backend is None and _is_ollama_model(model)
        )
        use_opencode = (backend == "opencode") or (
            backend is None and _is_opencode_model(model)
        )

        common = dict(
            inter_call_delay=inter_call_delay,
            max_retries=max_api_retries,
            retry_delay=retry_delay,
        )

        if use_copilot:
            from agents.backends.copilot import CopilotBackend
            return CopilotBackend(model=model, **common)

        if use_opencode_go:
            from agents.backends.opencode_go import OpenCodeGoBackend
            return OpenCodeGoBackend(
                model=model,
                api_key=opencode_zen_api_key,
                base_url=opencode_go_base_url,
                stream=opencode_stream,
                **common,
            )

        if use_opencode_zen:
            from agents.backends.opencode_zen import OpenCodeZenBackend
            return OpenCodeZenBackend(
                model=model,
                api_key=opencode_zen_api_key,
                base_url=opencode_zen_base_url,
                stream=opencode_stream,
                **common,
            )

        if use_nvidia_nim:
            from agents.backends.nvidia_nim import NvidiaNimBackend
            return NvidiaNimBackend(
                model=model,
                nvidia_nim_api_key=nvidia_nim_api_key,
                nvidia_nim_base_url=nvidia_nim_base_url,
                **common,
            )

        if use_opencode:
            from agents.backends.opencode import OpenCodeBackend
            return OpenCodeBackend(model=model)

        if use_anthropic:
            from agents.backends.anthropic import AnthropicBackend
            return AnthropicBackend(model=model, **common)

        if use_ollama:
            from agents.backends.ollama import OllamaBackend
            return OllamaBackend(
                model=model,
                ollama_url=ollama_url,
                think=ollama_think,
                preserve_thinking=ollama_preserve_thinking,
                stream=ollama_stream,
                **common,
            )

        # Default: GitHub Models
        from agents.backends.github_models import GitHubModelsBackend
        return GitHubModelsBackend(
            model=model,
            github_token=github_token,
            stream=github_models_stream,
            **common,
        )

    def _ensure_copilot_session(self) -> None:
        """Backward-compat shim: refresh Copilot session token if near expiry."""
        if self._backend == "copilot" and hasattr(self._llm, "_pre_call"):
            self._llm._pre_call()

    # ── Public interface ───────────────────────────────────────────────────────

    def reset_history(self) -> None:
        """Clear conversation history (call between unrelated pipeline tasks)."""
        self._history = []

    def _history_messages(self) -> list[dict]:
        """Return history formatted for OpenAI-compatible API."""
        return list(self._history)

    def _load_system_prompt(self, roles_dir: Optional[Path]) -> str:
        """Load the role instruction file as the system prompt."""
        if not self.role_name:
            return ""

        base = roles_dir or (Path(__file__).parent.parent / "roles")
        prompt_file = base / f"{self.role_name}.md"

        if not prompt_file.exists():
            raise FileNotFoundError(f"Role instruction file not found: {prompt_file}")

        return prompt_file.read_text(encoding="utf-8")

    def request_clarification(self, questions: list[str]) -> None:
        """Pause the pipeline and ask the human clarifying questions.

        Raises ClarificationNeeded which the orchestrator catches at the stage
        boundary.  The orchestrator posts the questions to the GitHub issue and
        sets the agent-waiting label.

        Args:
            questions: List of question strings, e.g. ["Q1: What DB?", "Q2: Async?"]
        """
        from orchestrator import ClarificationNeeded
        raise ClarificationNeeded(questions)

    # ── Backward-compat routing methods ────────────────────────────────────────

    def _call_anthropic(self, full_message: str, max_retries: int | None = None, delay: int | None = None) -> str:
        """Route a call through the backend's Anthropic path (with history).

        Kept for backward compatibility — tests patch this method to intercept
        Anthropic-routed calls from :meth:`call`.
        """
        messages: list[dict] = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.extend(self._history)
        messages.append({"role": "user", "content": full_message})
        from llm_pool import get_pool
        with get_pool().acquire(self._backend):
            reply = self._llm.call(messages)
        self._history.append({"role": "user", "content": full_message})
        self._history.append({"role": "assistant", "content": reply})
        return reply

    def _call_opencode(self, prompt: str, max_retries: int = 2, timeout: int | None = None) -> str:
        """Run a prompt via the opencode CLI backend (with history).

        Kept for backward compatibility — tests call and patch this method.
        The subprocess logic now lives in
        :class:`~agents.backends.opencode.OpenCodeBackend`.
        """
        messages: list[dict] = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.extend(self._history)
        messages.append({"role": "user", "content": prompt})

        # Temporarily override retry/timeout settings if the caller specifies them
        old_retries = self._llm._max_retries
        old_timeout = getattr(self._llm, "_timeout", 600)
        self._llm._max_retries = max_retries
        if timeout is not None:
            self._llm._timeout = timeout
        try:
            from llm_pool import get_pool
            with get_pool().acquire(self._backend):
                reply = self._llm.call(messages)
        finally:
            self._llm._max_retries = old_retries
            if timeout is not None:
                self._llm._timeout = old_timeout

        self._history.append({"role": "user", "content": prompt})
        self._history.append({"role": "assistant", "content": reply})
        return reply

    # ── Core LLM interface ─────────────────────────────────────────────────────

    def call(self, user_message: str, context: Optional[str] = None) -> str:
        """Send a message to the LLM and return the response.

        Maintains conversation history within the same agent instance so the
        LLM has context of what it said earlier in the same pipeline run.
        Delegates to :attr:`_llm` for the actual API call.

        Args:
            user_message: The main user prompt.
            context:      Optional context string prepended to ``user_message``.

        Returns:
            The assistant's reply text.
        """
        full_message = f"{context}\n\n{user_message}" if context else user_message

        # Route through backward-compat methods so tests can patch them.
        if self._backend in ("anthropic",) or (
            self._backend in ("opencode_zen", "opencode_go")
            and getattr(self._llm, "_anthropic_client", None) is not None
        ):
            return self._call_anthropic(full_message)

        if self._backend == "opencode":
            return self._call_opencode(full_message)

        # All other (OpenAI-compatible) backends: delegate to _llm directly.
        messages: list[dict] = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.extend(self._history)
        messages.append({"role": "user", "content": full_message})

        from llm_pool import get_pool
        with get_pool().acquire(self._backend):
            reply = self._llm.call(messages)
        self._history.append({"role": "user", "content": full_message})
        self._history.append({"role": "assistant", "content": reply})
        return reply

    def call_with_tools(
        self,
        user_message: str,
        tools: "ToolRegistry",
        context: Optional[str] = None,
        max_turns: int = 8,
    ) -> str:
        """Send a message to the LLM, executing tool calls until a final answer.

        Delegates to :attr:`_llm` for the full tool-call loop.

        Args:
            user_message: The main task/prompt.
            tools:        A ToolRegistry (local or MCP-backed).
            context:      Optional context prepended to ``user_message``.
            max_turns:    Maximum tool-call rounds before forcing a text response.

        Returns:
            The LLM's final text response.

        Raises:
            NotImplementedError: If the current backend does not support tool calling.
        """
        if not self._llm.supports_tools():
            suffix = ""
            if self._backend == "opencode_go":
                suffix = " (MiniMax models use Anthropic endpoint)"
            elif self._backend == "opencode_zen":
                suffix = " (Claude models)"
            raise NotImplementedError(
                f"call_with_tools is not supported for the '{self._backend}' backend{suffix}. "
                "Use the 'github_models', 'ollama', 'opencode_zen' (non-Claude), "
                "or 'opencode_go' (non-MiniMax) backend for tool-calling."
            )

        full_message = f"{context}\n\n{user_message}" if context else user_message
        messages: list[dict] = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.extend(self._history)
        messages.append({"role": "user", "content": full_message})

        from llm_pool import get_pool
        with get_pool().acquire(self._backend):
            reply = self._llm.call_with_tools(messages, tools, max_turns)
        self._history.append({"role": "user", "content": full_message})
        self._history.append({"role": "assistant", "content": reply})
        return reply

    # ── Utilities ──────────────────────────────────────────────────────────────

    @staticmethod
    def truncate_files(
        files: dict[str, str],
        max_chars: int = 12_000,
        max_per_file: int | None = None,
    ) -> dict[str, str]:
        """Return a subset of files that fits within max_chars total.

        Prioritises non-test, non-config files (source code first).
        Truncates individual files that are very long.
        Adds a summary comment when files are dropped.

        Args:
            max_chars:    Total character budget across all files.
            max_per_file: Per-file character cap. Defaults to min(3_000, max_chars // 2).
        """
        def priority(path: str) -> int:
            p = path.lower()
            if "/test" in p or p.startswith("test"):
                return 3
            if p.endswith((".yaml", ".yml", ".json", ".toml", ".cfg", ".ini", ".md")):
                return 2
            return 1

        sorted_files = sorted(files.items(), key=lambda kv: priority(kv[0]))
        result: dict[str, str] = {}
        used = 0
        skipped = []

        _max_per_file = max_per_file if max_per_file is not None else min(3_000, max_chars // 2)

        for path, content in sorted_files:
            if len(content) > _max_per_file:
                content = content[:_max_per_file] + f"\n... [truncated — {len(content) - _max_per_file} chars omitted]"

            entry_len = len(path) + len(content) + 40
            if used + entry_len <= max_chars:
                result[path] = content
                used += entry_len
            else:
                skipped.append(path)

        if skipped:
            result["__summary__"] = (
                f"[{len(skipped)} additional file(s) omitted to fit token limit: "
                + ", ".join(skipped) + "]"
            )

        return result

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(model={self.model!r})"
