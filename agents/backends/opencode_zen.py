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

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None  # type: ignore[assignment,misc]

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
            client = OpenAI(base_url=base, api_key=key)
            self._oai_backend = OpenAICompatibleBackend(
                model=bare_model, client=client,
                inter_call_delay=inter_call_delay, max_retries=max_retries, retry_delay=retry_delay,
            )
            self._anthropic_client = None

    def supports_tools(self) -> bool:
        """Return True if this backend supports tool/function calling."""
        return self._oai_backend is not None

    def call(self, messages: list[dict]) -> str:
        """Call the backend with a list of messages and return the response text."""
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
        """Call the backend with tool support. Only available for non-Claude models."""
        if self._oai_backend:
            return self._oai_backend.call_with_tools(messages, tools, max_turns)
        raise NotImplementedError(
            "call_with_tools is not supported for opencode_zen with Claude models. "
            "Use a non-Claude model or switch to github_models/ollama for tool calling."
        )
