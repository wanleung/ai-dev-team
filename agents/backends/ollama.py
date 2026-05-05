"""Ollama backend — local Ollama server via OpenAI-compatible API."""
from __future__ import annotations

import os
import re
import time

import httpx
from openai import OpenAI

from agents.backends.base import (
    OpenAICompatibleBackend,
    _DEFAULT_MAX_RETRIES,
    _DEFAULT_BASE_DELAY,
    _retry_with_backoff,
)

_ollama_timeout = float(os.environ.get("OLLAMA_TIMEOUT", "0")) or None


class OllamaBackend(OpenAICompatibleBackend):
    """Local Ollama server backend.

    Model prefix "ollama/" is stripped before sending to the API.
    Supports think/no-think mode and optional preserve_thinking.
    Supports streaming (recommended for remote Ollama hosts).
    """

    def __init__(
        self,
        model: str,
        ollama_url: str = "http://localhost:11434",
        api_key: str = "ollama",
        think: bool = False,
        preserve_thinking: bool = False,
        stream: bool = True,
        inter_call_delay: int = 0,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        retry_delay: float = _DEFAULT_BASE_DELAY,
    ) -> None:
        self._think = think
        self._preserve_thinking = preserve_thinking
        client = OpenAI(
            base_url=f"{ollama_url.rstrip('/')}/v1",
            api_key=api_key,
            timeout=(
                httpx.Timeout(timeout=_ollama_timeout, connect=10.0)
                if _ollama_timeout
                else httpx.Timeout(timeout=None, connect=10.0)
            ),
        )
        super().__init__(
            model=model.removeprefix("ollama/"),
            client=client,
            inter_call_delay=inter_call_delay,
            max_retries=max_retries,
            retry_delay=retry_delay,
            stream=stream,
        )

    def _extra_body(self) -> dict:
        """Return extra kwargs for chat.completions.create() specific to Ollama.

        - think=False  → {"extra_body": {"think": False}}  (force no-think mode)
        - think=True, preserve_thinking=True  → {}  (capture reasoning_content in _stream_call)
        - think=True, preserve_thinking=False → {}  (let Ollama use default think, strip tags in post-process)
        """
        if not self._think:
            return {"extra_body": {"think": False}}
        return {}

    def _stream_call(self, messages: list[dict]) -> str:
        """Collect a streaming Ollama response, including thinking content when requested.

        Ollama thinking models stream reasoning via ``delta.model_extra['reasoning_content']``
        and the actual response via ``delta.content``.  The base class only reads
        ``delta.content``, so with ``think=True`` the result was always empty.

        When ``preserve_thinking=True``: assembles ``<think>reasoning</think>\\nresponse``.
        When ``preserve_thinking=False``: collects only ``delta.content`` (actual response);
            any residual ``<think>`` tags are stripped by ``_post_process``.
        """
        if self._inter_call_delay > 0:
            time.sleep(self._inter_call_delay)

        preserve = self._preserve_thinking

        def _collect(stream) -> str:
            reasoning_parts: list[str] = []
            content_parts: list[str] = []
            for chunk in stream:
                if not chunk.choices:
                    continue  # final usage/stop chunks have empty choices
                delta = chunk.choices[0].delta
                # Reasoning content lives in model_extra for Ollama thinking models
                extra = getattr(delta, "model_extra", None) or {}
                rc = extra.get("reasoning_content")
                if rc and preserve:
                    reasoning_parts.append(rc)
                if delta.content:
                    content_parts.append(delta.content)
            content = "".join(content_parts)
            if not content and not reasoning_parts:
                # Stream completed with zero chunks — LiteLLM likely timed out server-side.
                # Raise so _retry_with_backoff retries, and FallbackLLMBackend can switch backends.
                raise ConnectionError(
                    "Ollama stream returned no content (server may have timed out or model is unavailable)"
                )
            if preserve and reasoning_parts:
                thinking = "".join(reasoning_parts)
                return f"<think>{thinking}</think>\n{content}"
            return content

        reply = _retry_with_backoff(
            lambda: _collect(
                self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.3,
                    stream=True,
                    **self._extra_body(),
                )
            ),
            max_retries=self._max_retries,
            base_delay=self._retry_delay,
        )
        return self._post_process(reply)

    def _post_process(self, text: str) -> str:
        """Strip <think>…</think> blocks unless preserve_thinking is enabled.

        Args:
            text: Raw assistant reply text from Ollama.

        Returns:
            Cleaned reply with thinking blocks removed (or preserved, if configured).
        """
        if self._preserve_thinking:
            return text.strip()
        return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
