"""Ollama backend — local Ollama server via OpenAI-compatible API."""
from __future__ import annotations

import os
import re
import time
from collections.abc import Callable

import httpx
from openai import OpenAI

from agents.backends.base import (
    OpenAICompatibleBackend,
    _DEFAULT_MAX_RETRIES,
    _DEFAULT_BASE_DELAY,
    _retry_with_backoff,
)
from agents.token_ledger import current_stage, estimate_tokens, get_ledger

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

    def _stream_call(
        self,
        messages: list[dict],
        run_id: str | None = None,
        on_token: Callable[[str], None] | None = None,
    ) -> str:
        """Collect a streaming Ollama response, including thinking content when requested.

        Ollama thinking models stream reasoning via ``delta.model_extra['reasoning_content']``
        and the actual response via ``delta.content``.  The base class only reads
        ``delta.content``, so with ``think=True`` the result was always empty.

        When ``preserve_thinking=True``: assembles ``<think>reasoning</think>\\nresponse``.
        When ``preserve_thinking=False``: collects only ``delta.content`` (actual response);
            any residual ``<think>`` tags are stripped by ``_post_process``.

        Args:
            messages:  Full message list in OpenAI chat format.
            run_id:    Optional pipeline run ID for token ledger emission.
            on_token:  Optional callable invoked with each content chunk as it
                       arrives.  Only called for ``delta.content`` chunks, not
                       for ``reasoning_content``.
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
                # Reasoning content lives in model_extra for Ollama thinking models.
                # Always collect it (regardless of preserve) so we can detect
                # thinking-only models (e.g. via LiteLLM proxy that never emits delta.content).
                extra = getattr(delta, "model_extra", None) or {}
                rc = extra.get("reasoning_content") if isinstance(extra, dict) else None
                if rc and isinstance(rc, str):
                    reasoning_parts.append(rc)
                if delta.content:
                    content_parts.append(delta.content)
                    if on_token is not None:
                        try:
                            on_token(delta.content)
                        except Exception:
                            pass  # never let console errors kill the LLM response
            content = "".join(content_parts)
            if not content and not reasoning_parts:
                # Stream completed with zero chunks — LiteLLM likely timed out server-side.
                # Raise so _retry_with_backoff retries, and FallbackLLMBackend can switch backends.
                raise ConnectionError(
                    "Ollama stream returned no content (server may have timed out or model is unavailable)"
                )
            if reasoning_parts:
                thinking = "".join(reasoning_parts)
                if preserve:
                    return f"<think>{thinking}</think>\n{content}"
                if not content:
                    # Thinking model (via LiteLLM proxy) only emitted reasoning_content and
                    # never produced a separate delta.content chunk.  Use the reasoning as
                    # the actual response so downstream stages receive useful text.
                    return thinking
            return content

        full_content = _retry_with_backoff(
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
        result = self._post_process(full_content)
        effective_run_id = run_id if run_id is not None else get_ledger().active_run_id()
        if effective_run_id is not None:
            pt, ct = estimate_tokens(messages, full_content, model=self.model)
            get_ledger().record(effective_run_id, current_stage.get(), self.model, pt, ct)
        return result

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
