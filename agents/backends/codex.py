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
        on_token=None,
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
                    proc.wait()
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
                    proc.wait()

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
