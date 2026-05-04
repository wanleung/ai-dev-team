"""Ollama backend — local Ollama server via OpenAI-compatible API."""
from __future__ import annotations

import os
import re

import httpx
from openai import OpenAI

from agents.backends.base import (
    OpenAICompatibleBackend,
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
