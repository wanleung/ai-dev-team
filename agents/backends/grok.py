"""Grok CLI subprocess backend."""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from agents.backends.base import LLMBackend, _DEFAULT_MAX_RETRIES

if TYPE_CHECKING:
    from tools.registry import ToolRegistry

_log = logging.getLogger(__name__)

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
        max_retries: int = _DEFAULT_MAX_RETRIES,
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

        MAX_PROMPT_BYTES = 1_500_000  # 1.5 MB — leaves headroom for env + argv overhead
        prompt_bytes = full_prompt.encode()
        if len(prompt_bytes) > MAX_PROMPT_BYTES:
            raise ValueError(
                f"Prompt exceeds safe ARG_MAX limit ({len(prompt_bytes)} bytes). "
                "Reduce conversation history length."
            )

        cmd = [
            bin_path,
            "--prompt", full_prompt,
            "--format", "json",
            "--model", self.model,
            "--directory", directory,
        ]

        for attempt in range(self._max_retries + 1):
            try:
                result = self._run_once(
                    cmd,
                    on_token=on_token if attempt == 0 else None,
                )
                return result
            except (subprocess.TimeoutExpired, RuntimeError) as exc:
                if attempt == self._max_retries:
                    raise
                _log.warning("grok attempt %d/%d failed: %s — retrying in %ds",
                             attempt + 1, self._max_retries, exc, 2 ** attempt)
                time.sleep(2 ** attempt)

        raise AssertionError("unreachable")  # satisfies type checkers

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

        if user_message:
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
            if proc.poll() is None:
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
