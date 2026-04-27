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

# Fix 3 — broader ANSI escape stripping (CSI, OSC, and Fe sequences)
_ANSI_ESCAPE = re.compile(
    r'\x1b(?:'
    r'\[[0-9;?]*[A-Za-z]'              # CSI sequences
    r'|\][^\x07\x1b]*(?:\x07|\x1b\\)'  # OSC sequences
    r'|[@-_]'                           # Fe escape sequences
    r')'
)


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
        """Return False — opencode CLI does not support function calling."""
        return False

    def call(self, messages: list[dict]) -> str:
        """Build a combined prompt from messages and run via opencode CLI.

        Args:
            messages: Full message list (system + history + user message).

        Returns:
            The assistant reply text.

        Raises:
            RuntimeError: If opencode exits with a non-zero status or returns empty output.
            subprocess.TimeoutExpired: If the subprocess exceeds the configured timeout
                                       and all retries are exhausted.
        """
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
        # Fix 1 — content can be None for assistant messages with only tool calls
        user_message = (chat_messages[-1].get("content") or "") if chat_messages else ""

        if history:
            history_lines = []
            for turn in history:
                label = "USER" if turn["role"] == "user" else "ASSISTANT"
                # Fix 1 — content can be None for assistant messages with only tool calls
                history_lines.append(f"{label}: {(turn.get('content') or '')[:2000]}")
            parts.append("[CONVERSATION HISTORY]\n" + "\n\n".join(history_lines))
        parts.append(user_message)

        full_prompt = "\n\n".join(parts)
        # Fix 2 — add "--" separator to terminate option parsing before the prompt
        cmd = [bin_path, "run", "--model", self.model, "--", full_prompt]

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
                # Fix 3 — use broader ANSI escape regex
                output = _ANSI_ESCAPE.sub("", output).strip()
                if not output:
                    raise RuntimeError("Empty response from opencode after stripping ANSI codes")
                return output
            except (subprocess.TimeoutExpired, RuntimeError):
                if attempt == self._max_retries:
                    raise
                time.sleep(2 ** attempt)

        # Fix 4 — removed unreachable RuntimeError("All opencode retries exhausted");
        # the last loop iteration always does a bare raise, so this line is never reached.

    def call_with_tools(
        self,
        messages: list[dict],
        tools: "ToolRegistry",
        max_turns: int = 8,
    ) -> str:
        """Not supported — raises NotImplementedError.

        Args:
            messages: Message list (unused).
            tools:    ToolRegistry (unused).
            max_turns: Max turns (unused).

        Raises:
            NotImplementedError: Always. Use a different backend for tool calling.
        """
        raise NotImplementedError(
            "call_with_tools is not supported for the 'opencode' backend. "
            "Use 'github_models', 'ollama', 'copilot', or 'nvidia_nim' for tool calling."
        )
