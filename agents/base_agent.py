"""
BaseAgent: calls GitHub Models API (OpenAI-compatible) using GITHUB_TOKEN.
This is the same AI backbone that powers GitHub Copilot CLI.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from openai import OpenAI

if TYPE_CHECKING:
    from tools.registry import ToolRegistry


class BaseAgent:
    """Base class for all software house agents.

    Each agent subclass defines its role by providing a role_name that maps to
    a markdown instruction file in the roles/ directory.
    """

    # Role name used to load the system prompt from roles/<role_name>.md
    role_name: str = ""

    def __init__(
        self,
        model: str = "gpt-4.1",
        github_token: Optional[str] = None,
        roles_dir: Optional[Path] = None,
    ) -> None:
        token = github_token or os.environ.get("GITHUB_TOKEN")
        if not token:
            raise EnvironmentError(
                "GITHUB_TOKEN environment variable is required. "
                "Create a token at https://github.com/settings/personal-access-tokens/new "
                "with 'Copilot Requests', 'Contents', 'Issues', and 'Pull requests' permissions."
            )

        # GitHub Models API is OpenAI-compatible — same backend as Copilot CLI
        self.client = OpenAI(
            base_url="https://models.github.ai/inference",
            api_key=token,
        )
        self.model = model
        self.system_prompt = self._load_system_prompt(roles_dir)

    def _load_system_prompt(self, roles_dir: Optional[Path]) -> str:
        """Load the role instruction file as the system prompt."""
        if not self.role_name:
            return ""

        base = roles_dir or (Path(__file__).parent.parent / "roles")
        prompt_file = base / f"{self.role_name}.md"

        if not prompt_file.exists():
            raise FileNotFoundError(f"Role instruction file not found: {prompt_file}")

        return prompt_file.read_text(encoding="utf-8")

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
                        model=self.model,
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
            model=self.model,
            messages=messages,
            temperature=0.3,
        )
        return response.choices[0].message.content or ""

    def call(self, user_message: str, context: Optional[str] = None) -> str:
        """Send a message to the LLM and return the response.

        Retries up to 5 times with exponential backoff on 429 rate-limit errors.

        Args:
            user_message: The main task/prompt for the agent.
            context: Optional additional context prepended to the message.

        Returns:
            The LLM's text response.
        """
        full_message = f"{context}\n\n{user_message}" if context else user_message

        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.append({"role": "user", "content": full_message})

        max_retries = 5
        delay = 15  # seconds — start conservative for the 60-req/min window
        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.3,
                )
                return response.choices[0].message.content or ""
            except Exception as exc:
                # Check for rate-limit (429) — back off and retry
                is_rate_limit = "429" in str(exc) or "RateLimitReached" in str(exc)
                if is_rate_limit and attempt < max_retries - 1:
                    wait = delay * (2 ** attempt)  # 15s, 30s, 60s, 120s
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
