"""Ollama backend — local Ollama server via OpenAI-compatible API."""
from __future__ import annotations

import os
import re
import time

import httpx
from openai import OpenAI

from agents.backends.base import (
    OpenAICompatibleBackend,
    _retry_with_backoff,
    _DEFAULT_MAX_RETRIES,
    _DEFAULT_BASE_DELAY,
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
        self._stream = stream
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
        )

    def _extra_body(self) -> dict:
        """Return extra kwargs for chat.completions.create() specific to Ollama.

        - think=False  → {"extra_body": {"think": False}}  (force no-think mode)
        - think=True, preserve_thinking=True  → {"extra_body": {"options": {"preserve_thinking": True}}}
        - think=True, preserve_thinking=False → {}  (let Ollama use default think, strip tags in post-process)
        """
        if not self._think:
            return {"extra_body": {"think": False}}
        if self._preserve_thinking:
            return {"extra_body": {"options": {"preserve_thinking": True}}}
        return {}

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

    def call(self, messages: list[dict]) -> str:
        """Send messages to Ollama and return the assistant reply.

        Uses streaming if ``stream=True`` (the default), otherwise falls back
        to the parent class non-streaming path.

        Args:
            messages: Full message list in OpenAI chat format.

        Returns:
            Assistant reply text, with <think> blocks stripped if applicable.
        """
        self._pre_call()
        if self._stream:
            return self._stream_call(messages)
        return super().call(messages)

    def _stream_call(self, messages: list[dict]) -> str:
        """Collect a streaming response from Ollama into a single string.

        Args:
            messages: Full message list in OpenAI chat format.

        Returns:
            Assembled and post-processed assistant reply text.
        """
        if self._inter_call_delay > 0:
            time.sleep(self._inter_call_delay)

        def _collect(stream) -> str:
            collected = ""
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    collected += delta
            return collected

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
