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
        """Return False — Anthropic backend does not support tool calling."""
        return False

    def call(self, messages: list[dict]) -> str:
        """Call the Anthropic API with the given messages.

        Extracts the system prompt from the first "system" role message (if present)
        and passes it separately to ``client.messages.create(system=...)``.

        Args:
            messages: List of message dicts with "role" and "content" keys.

        Returns:
            The text content of the first response block.
        """
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
        """Not implemented — Anthropic backend does not support tool calling.

        Raises:
            NotImplementedError: Always, directing users to a compatible backend.
        """
        raise NotImplementedError(
            "call_with_tools is not supported for the 'anthropic' backend. "
            "Use 'github_models', 'ollama', 'copilot', or 'nvidia_nim' for tool calling."
        )
