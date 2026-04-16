"""
BaseAgent: supports four LLM backends, selectable per-agent via config.yaml.

  backend: github_models   — GitHub Models API (OpenAI-compatible, uses GITHUB_TOKEN)
  backend: anthropic       — Anthropic Claude API (uses ANTHROPIC_API_KEY)
  backend: ollama          — Local Ollama server (OpenAI-compatible, model prefix "ollama/")
  backend: opencode        — OpenCode CLI subprocess (model prefix "opencode/")

Default backend is github_models for backwards compatibility.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from tools.registry import ToolRegistry

from openai import OpenAI

_ANTHROPIC_MODELS = {
    "claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-4-5",
    "claude-3-7-sonnet-20250219", "claude-3-5-sonnet-20241022",
    "claude-3-5-haiku-20241022", "claude-3-opus-20240229",
}

def _is_anthropic_model(model: str) -> bool:
    return model.startswith("claude-") or model in _ANTHROPIC_MODELS


def _is_ollama_model(model: str) -> bool:
    """Return True if the model name indicates an Ollama-hosted model."""
    return model.startswith("ollama/")


def _is_opencode_model(model: str) -> bool:
    """Return True if the model should be run via the opencode CLI subprocess."""
    return model.startswith("opencode/")


class BaseAgent:
    """Base class for all software house agents.

    Supports four backends:
      - github_models: GitHub Models API via OpenAI SDK (GITHUB_TOKEN)
      - anthropic:     Anthropic Claude API (ANTHROPIC_API_KEY)
      - ollama:        Local Ollama server via OpenAI SDK (model prefix "ollama/")
      - opencode:      OpenCode CLI subprocess (model prefix "opencode/<provider>/<model>")

    Backend is auto-selected from the model name unless overridden.
    """

    role_name: str = ""

    def __init__(
        self,
        model: str = "gpt-4.1",
        github_token: Optional[str] = None,
        roles_dir: Optional[Path] = None,
        backend: Optional[str] = None,  # "github_models" | "anthropic" | "ollama" | "opencode" | None (auto)
        ollama_url: str = "http://localhost:11434",
    ) -> None:
        self.model = model
        self.system_prompt = self._load_system_prompt(roles_dir)

        # Short-term conversation history — persists within a pipeline run.
        # Call agent.reset_history() between unrelated tasks.
        self._history: list[dict] = []

        # Auto-detect backend from model name if not explicitly set
        use_anthropic = (backend == "anthropic") or (
            backend is None and _is_anthropic_model(model)
        )
        use_ollama = (backend == "ollama") or (
            backend is None and _is_ollama_model(model)
        )
        use_opencode = (backend == "opencode") or (
            backend is None and _is_opencode_model(model)
        )

        if use_opencode:
            self._backend = "opencode"
            # Strip "opencode/" prefix → remainder is the provider/model for opencode CLI
            # e.g. "opencode/anthropic/claude-3-5-sonnet" → "anthropic/claude-3-5-sonnet"
            self._api_model = model.removeprefix("opencode/")
            self.client = None
            self._anthropic_client = None
        elif use_anthropic:
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                raise EnvironmentError(
                    "ANTHROPIC_API_KEY environment variable is required for Claude models. "
                    "Get your key at https://console.anthropic.com/"
                )
            import anthropic as _anthropic
            self._anthropic_client = _anthropic.Anthropic(api_key=api_key)
            self._backend = "anthropic"
            self.client = None
            self._api_model = model
        elif use_ollama:
            self._backend = "ollama"
            self._api_model = model.removeprefix("ollama/")
            self.client = OpenAI(base_url=f"{ollama_url.rstrip('/')}/v1", api_key="ollama")
            self._anthropic_client = None
        else:
            token = github_token or os.environ.get("GITHUB_TOKEN")
            if not token:
                raise EnvironmentError(
                    "GITHUB_TOKEN environment variable is required. "
                    "Create a token at https://github.com/settings/personal-access-tokens/new "
                    "with 'Copilot Requests', 'Contents', 'Issues', and 'Pull requests' permissions."
                )
            self.client = OpenAI(
                base_url="https://models.github.ai/inference",
                api_key=token,
            )
            self._backend = "github_models"
            self._api_model = model
            self._anthropic_client = None

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

    def _call_anthropic(self, full_message: str, max_retries: int = 5, delay: int = 15) -> str:
        """Call the Anthropic Claude API with history and retry on rate limits."""
        # Build messages including history
        messages = list(self._history) + [{"role": "user", "content": full_message}]
        kwargs = dict(
            model=self.model,
            max_tokens=8096,
            messages=messages,
        )
        if self.system_prompt:
            kwargs["system"] = self.system_prompt

        for attempt in range(max_retries):
            try:
                response = self._anthropic_client.messages.create(**kwargs)
                reply = response.content[0].text
                # Update history
                self._history.append({"role": "user", "content": full_message})
                self._history.append({"role": "assistant", "content": reply})
                return reply
            except Exception as exc:
                is_rate_limit = "429" in str(exc) or "rate_limit" in str(exc).lower()
                if is_rate_limit and attempt < max_retries - 1:
                    wait = delay * (2 ** attempt)
                    print(f"    ⏳ Rate limited (Anthropic) — waiting {wait}s…")
                    time.sleep(wait)
                else:
                    raise
        raise RuntimeError("All Anthropic retries exhausted")

    def _call_opencode(self, prompt: str, max_retries: int = 2, timeout: int | None = None) -> str:
        """Run a prompt via the opencode CLI subprocess.

        Builds a combined prompt (system role + conversation history + task) and
        passes it as a single message to `opencode run --model <provider/model>`.
        The OPENCODE_BIN environment variable overrides the binary path.
        """
        bin_path = os.environ.get("OPENCODE_BIN", "opencode")
        _timeout = timeout or getattr(self, "timeout", 600)

        # Build combined prompt: system role + conversation history + task
        parts: list[str] = []
        if self.system_prompt:
            parts.append(f"[SYSTEM ROLE]\n{self.system_prompt}")
        if self._history:
            history_lines = []
            for turn in self._history:
                label = "USER" if turn["role"] == "user" else "ASSISTANT"
                history_lines.append(f"{label}: {turn['content'][:2000]}")
            parts.append("[CONVERSATION HISTORY]\n" + "\n\n".join(history_lines))
        parts.append(prompt)
        full_prompt = "\n\n".join(parts)

        cmd = [bin_path, "run", "--model", self._api_model, full_prompt]

        for attempt in range(max_retries + 1):
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=_timeout,
                )
                if result.returncode != 0:
                    raise RuntimeError(
                        f"opencode exited {result.returncode}: {result.stderr[:300]}"
                    )
                output = result.stdout.strip()
                if not output:
                    raise RuntimeError("Empty response from opencode")
                # Strip ANSI escape codes from formatted output
                output = re.sub(r"\x1b\[[0-9;]*[mGKHF]", "", output).strip()
                if not output:
                    raise RuntimeError("Empty response from opencode after stripping ANSI codes")
                # Persist to history
                self._history.append({"role": "user", "content": prompt})
                self._history.append({"role": "assistant", "content": output})
                return output
            except subprocess.TimeoutExpired:
                if attempt == max_retries:
                    raise
                time.sleep(2 ** attempt)
            except RuntimeError as exc:
                if attempt == max_retries:
                    raise
                time.sleep(2 ** attempt)

        raise RuntimeError("All opencode retries exhausted")

    def call_with_tools(
        self,
        user_message: str,
        tools: "ToolRegistry",
        context: Optional[str] = None,
        max_turns: int = 8,
    ) -> str:
        """Send a message to the LLM, executing tool calls until a final answer.

        The LLM may call tools zero or more times before producing a text response.
        This method handles the full tool-call loop automatically.

        MCP migration path (Option B):
            Pass an MCPToolRegistry instead of LocalToolRegistry.
            `tools.schemas` will be fetched from the MCP server.
            `tools.call()` will route through the MCP client.
            This method stays identical.

        Args:
            user_message: The main task/prompt.
            tools:        A ToolRegistry (LocalToolRegistry or future MCPToolRegistry).
            context:      Optional context prepended to user_message.
            max_turns:    Max tool-call rounds before forcing a text response.

        Returns:
            The LLM's final text response.
        """
        if self._backend in ("opencode", "anthropic"):
            raise NotImplementedError(
                f"call_with_tools is not supported for the '{self._backend}' backend. "
                "Use the 'github_models' or 'ollama' backend for tool-calling."
            )
        full_message = f"{context}\n\n{user_message}" if context else user_message

        messages: list[dict] = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.append({"role": "user", "content": full_message})

        max_retries = 5
        delay = 15

        for turn in range(max_turns):
            # Call the API with tool schemas
            for attempt in range(max_retries):
                try:
                    response = self.client.chat.completions.create(
                        model=self._api_model,
                        messages=messages,
                        tools=tools.schemas,
                        tool_choice="auto",
                        temperature=0.3,
                    )
                    break
                except Exception as exc:
                    is_rate_limit = "429" in str(exc) or "RateLimitReached" in str(exc)
                    if is_rate_limit and attempt < max_retries - 1:
                        wait = delay * (2 ** attempt)
                        print(f"    ⏳ Rate limited — waiting {wait}s (turn {turn + 1})…")
                        time.sleep(wait)
                    else:
                        raise

            msg = response.choices[0].message

            # No tool calls → final answer
            if not msg.tool_calls:
                return msg.content or ""

            # Append assistant message (with tool_calls) to history
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

            # Execute each tool call and append results
            for tc in msg.tool_calls:
                tool_name = tc.function.name
                print(f"    🔧 Tool call: {tool_name}({tc.function.arguments[:80]}…)")
                result = tools.call(tool_name, tc.function.arguments)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

        # Max turns reached — ask for a final response without tools
        messages.append({
            "role": "user",
            "content": "Please provide your final response based on the tool results above.",
        })
        response = self.client.chat.completions.create(
            model=self._api_model,
            messages=messages,
            temperature=0.3,
        )
        return response.choices[0].message.content or ""

    def call(self, user_message: str, context: Optional[str] = None) -> str:
        """Send a message to the LLM and return the response.

        Maintains conversation history within the same agent instance so the
        LLM has context of what it said earlier in the same pipeline run.
        Routes to Anthropic, GitHub Models, Ollama, or OpenCode based on backend.
        Retries up to 5 times with exponential backoff on rate-limit errors.
        """
        full_message = f"{context}\n\n{user_message}" if context else user_message

        if self._backend == "anthropic":
            return self._call_anthropic(full_message)

        if self._backend == "opencode":
            return self._call_opencode(full_message)

        # OpenAI-compatible backends (GitHub Models + Ollama) — include history
        messages: list[dict] = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.extend(self._history)
        messages.append({"role": "user", "content": full_message})

        max_retries = 5
        delay = 15
        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self._api_model,
                    messages=messages,
                    temperature=0.3,
                )
                reply = response.choices[0].message.content or ""
                # Persist to history
                self._history.append({"role": "user", "content": full_message})
                self._history.append({"role": "assistant", "content": reply})
                return reply
            except Exception as exc:
                is_rate_limit = "429" in str(exc) or "RateLimitReached" in str(exc)
                if is_rate_limit and attempt < max_retries - 1:
                    wait = delay * (2 ** attempt)
                    print(f"    ⏳ Rate limited — waiting {wait}s before retry {attempt + 2}/{max_retries}…")
                    time.sleep(wait)
                else:
                    raise

    @staticmethod
    def truncate_files(files: dict[str, str], max_chars: int = 12_000) -> dict[str, str]:
        """Return a subset of files that fits within max_chars total.

        Prioritises non-test, non-config files (source code first).
        Truncates individual files that are very long.
        Adds a summary comment when files are dropped.
        """
        # Sort: source files first, then config, then tests
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

        for path, content in sorted_files:
            # Truncate a single file if it's huge
            max_per_file = min(3_000, max_chars // 2)
            if len(content) > max_per_file:
                content = content[:max_per_file] + f"\n... [truncated — {len(content) - max_per_file} chars omitted]"

            entry_len = len(path) + len(content) + 40  # overhead for markers
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
