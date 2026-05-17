"""OpenCode Go plan API backend — OpenAI-compatible or Anthropic-routed for MiniMax models."""
from __future__ import annotations
import logging
import os
import time
from typing import TYPE_CHECKING

_log = logging.getLogger(__name__)

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

_OPENCODE_GO_ANTHROPIC_MODELS = {"minimax-m2.7", "minimax-m2.5"}


class OpenCodeGoBackend(LLMBackend):
    """OpenCode Go plan API backend.

    MiniMax models are routed through the Anthropic Messages API (no tools).
    All other models use the OpenAI-compatible chat/completions endpoint (tools supported).
    """

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        inter_call_delay: int = 0,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        retry_delay: float = _DEFAULT_BASE_DELAY,
        stream: bool = True,
    ) -> None:
        key = (
            api_key
            or os.environ.get("OPENCODE_GO_API_KEY")
            or os.environ.get("OPENCODE_ZEN_API_KEY")
            or os.environ.get("OPENCODE_API_KEY")
        )
        if not key:
            raise EnvironmentError(
                "OPENCODE_GO_API_KEY (or OPENCODE_ZEN_API_KEY) environment variable is required "
                "for the opencode_go backend. Get your key at https://opencode.ai/auth"
            )
        base = (
            base_url
            or os.environ.get("OPENCODE_GO_BASE_URL")
            or "https://opencode.ai/zen/go/v1"
        ).rstrip("/")

        bare_model = model.removeprefix("opencode-go/")
        self.model = bare_model
        self._inter_call_delay = inter_call_delay
        self._max_retries = max_retries
        self._retry_delay = retry_delay

        if bare_model in _OPENCODE_GO_ANTHROPIC_MODELS:
            if anthropic is None:
                raise ImportError("anthropic package required: pip install anthropic")
            self._anthropic_client = anthropic.Anthropic(api_key=key, base_url=base)
            self._oai_backend: OpenAICompatibleBackend | None = None
        else:
            if OpenAI is None:
                raise ImportError("openai package required: pip install openai")
            client = OpenAI(base_url=base, api_key=key)
            self._oai_backend = OpenAICompatibleBackend(
                model=bare_model, client=client,
                inter_call_delay=inter_call_delay, max_retries=max_retries, retry_delay=retry_delay,
                stream=stream,
            )
            self._anthropic_client = None

    def supports_tools(self) -> bool:
        """Return True if this backend supports tool/function calling."""
        return self._oai_backend is not None

    def call(self, messages: list[dict], run_id: str | None = None,
             on_token: "Callable[[str], None] | None" = None) -> str:
        """Call the backend with a list of messages and return the response text.

        Args:
            messages:  Full message list in OpenAI chat format.
            run_id:    Optional pipeline run ID for token ledger emission.
            on_token:  Optional streaming callback forwarded to the OAI backend
                       for non-MiniMax models.  Intentionally not forwarded on
                       the Anthropic path; that backend does not support streaming.
        """
        if self._oai_backend:
            return self._oai_backend.call(messages, run_id=run_id, on_token=on_token)
        system = ""
        chat_messages = []
        for m in messages:
            if m["role"] == "system":
                if not chat_messages:
                    system = m["content"] or ""
                else:
                    _log.warning(
                        "Ignoring mid-list system message for Anthropic call (model=%s)", self.model
                    )
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
        if not response.content:
            raise RuntimeError(
                f"Anthropic returned empty content for model {self.model!r}. "
                f"stop_reason={response.stop_reason!r}"
            )
        return response.content[0].text

    def call_with_tools(
        self, messages: list[dict], tools: "ToolRegistry", max_turns: int = 8,
        run_id: str | None = None,
    ) -> str:
        """Call the backend with tool support. Only available for non-MiniMax models."""
        if self._oai_backend:
            return self._oai_backend.call_with_tools(messages, tools, max_turns)
        raise NotImplementedError(
            "call_with_tools is not supported for opencode_go with MiniMax models."
        )
