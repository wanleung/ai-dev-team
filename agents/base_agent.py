"""
BaseAgent: calls GitHub Models API (OpenAI-compatible) using GITHUB_TOKEN.
This is the same AI backbone that powers GitHub Copilot CLI.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

from openai import OpenAI


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
            base_url="https://models.inference.ai.azure.com",
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
