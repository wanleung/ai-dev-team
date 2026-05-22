"""OpenCode CLI subprocess backend."""
from __future__ import annotations
import os
import re
import signal
import subprocess
import tempfile
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

    def call(self, messages: list[dict], run_id: str | None = None,
             on_token: "Callable[[str], None] | None" = None) -> str:
        """Build a combined prompt from messages and run via opencode CLI.

        Args:
            messages:  Full message list (system + history + user message).
            run_id:    Optional pipeline run ID (unused by this backend).
            on_token:  Optional streaming callback — intentionally not forwarded;
                       this backend does not support streaming.

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

        for attempt in range(self._max_retries + 1):
            tmp_path = None
            try:
                # Write prompt to a temp file to avoid ARG_MAX (Errno 7) on large prompts.
                # Pass it via --file so opencode reads the content as attached context,
                # with a short trigger message instructing the agent to follow it.
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".md", delete=False, encoding="utf-8"
                ) as tmp:
                    tmp.write(full_prompt)
                    tmp_path = tmp.name
                cmd = [
                    bin_path, "run",
                    "--model", self.model,
                    "--file", tmp_path,
                    "--dangerously-skip-permissions",
                    "--",
                    "Follow the instructions in the attached file exactly.",
                ]
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    # Put opencode in its own process group so SIGTERM/SIGKILL
                    # reaches it even if Python is signalled externally.
                    start_new_session=True,
                )
                try:
                    stdout, stderr = proc.communicate(timeout=self._timeout)
                except subprocess.TimeoutExpired:
                    # Kill the entire process group (catches any spawned children)
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    proc.wait()
                    raise RuntimeError(
                        f"opencode timed out after {self._timeout}s"
                    )
                finally:
                    # Belt-and-suspenders: ensure the process is dead
                    if proc.poll() is None:
                        try:
                            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        proc.wait()
                if proc.returncode != 0:
                    raise RuntimeError(
                        f"opencode exited {proc.returncode}: {stderr[:300]}"
                    )
                output = stdout.strip()
                if not output:
                    raise RuntimeError("Empty response from opencode")
                output = _ANSI_ESCAPE.sub("", output).strip()
                if not output:
                    raise RuntimeError("Empty response from opencode after stripping ANSI codes")
                return output
            except (subprocess.TimeoutExpired, RuntimeError):
                if attempt == self._max_retries:
                    raise
                time.sleep(2 ** attempt)
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    os.unlink(tmp_path)

    def call_with_tools(
        self,
        messages: list[dict],
        tools: "ToolRegistry",
        max_turns: int = 8,
        run_id: str | None = None,
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
