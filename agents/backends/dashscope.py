"""Alibaba DashScope backend — OpenAI-compatible API.

DashScope uses the standard OpenAI chat completions protocol with an
Alibaba-specific base URL.  Thinking models (e.g. qwen3-*) stream
reasoning via ``delta.reasoning_content`` and the answer via
``delta.content``, identical to the Ollama backend.

Config keys (in llm: section of config.yaml / config.local.yaml):
  dashscope_api_key  — API key (falls back to DASHSCOPE_API_KEY env var)
  dashscope_url      — optional base URL override (default: international endpoint)
  dashscope_think    — bool, pass enable_thinking=True (default: False)
  dashscope_preserve_thinking — bool, keep <think> block in output (default: False)
  dashscope_stream   — bool, use streaming (default: True)

Model prefix: ``dashscope/``

Example config.local.yaml snippet::

    llm:
      model: "dashscope/qwen3-plus"
      dashscope_api_key: "sk-xxx"
      dashscope_think: true
      dashscope_preserve_thinking: false
"""
from __future__ import annotations

import os
import re
import time
from collections.abc import Callable

from openai import OpenAI

from agents.backends.base import (
    OpenAICompatibleBackend,
    _DEFAULT_BASE_DELAY,
    _DEFAULT_MAX_RETRIES,
    _retry_with_backoff,
)
from agents.token_ledger import current_stage, estimate_tokens, get_ledger

_DASHSCOPE_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"


class DashScopeBackend(OpenAICompatibleBackend):
    """Alibaba DashScope API backend (OpenAI-compatible).

    Model prefix ``dashscope/`` is stripped before sending to the API.
    Supports thinking mode (``enable_thinking``) and streaming.
    """

    def __init__(
        self,
        model: str,
        dashscope_api_key: str | None = None,
        dashscope_url: str | None = None,
        think: bool = False,
        preserve_thinking: bool = False,
        stream: bool = True,
        inter_call_delay: int = 0,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        retry_delay: float = _DEFAULT_BASE_DELAY,
    ) -> None:
        key = dashscope_api_key or os.environ.get("DASHSCOPE_API_KEY")
        if not key:
            raise EnvironmentError(
                "DASHSCOPE_API_KEY environment variable is required for DashScope. "
                "Get your key at https://dashscope-intl.console.aliyun.com/"
            )
        base_url = (dashscope_url or _DASHSCOPE_BASE_URL).rstrip("/")
        self._think = think
        self._preserve_thinking = preserve_thinking
        client = OpenAI(base_url=base_url, api_key=key)
        super().__init__(
            model=model.removeprefix("dashscope/"),
            client=client,
            inter_call_delay=inter_call_delay,
            max_retries=max_retries,
            retry_delay=retry_delay,
            stream=stream,
        )

    def _extra_body(self) -> dict:
        if self._think:
            return {"extra_body": {"enable_thinking": True}}
        return {}

    def _stream_call(
        self,
        messages: list[dict],
        run_id: str | None = None,
        on_token: Callable[[str], None] | None = None,
    ) -> str:
        """Stream response from DashScope, collecting reasoning_content when thinking."""
        if self._inter_call_delay > 0:
            time.sleep(self._inter_call_delay)

        preserve = self._preserve_thinking

        def _collect(stream) -> str:
            reasoning_parts: list[str] = []
            content_parts: list[str] = []
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                # DashScope thinking models emit reasoning via reasoning_content
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
                            pass
            content = "".join(content_parts)
            if not content and not reasoning_parts:
                raise ConnectionError(
                    "DashScope stream returned no content (check API key or model availability)"
                )
            if reasoning_parts and preserve:
                return f"<think>{''.join(reasoning_parts)}</think>\n{content}"
            return content

        full_content = _retry_with_backoff(
            lambda: _collect(
                self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
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
        if self._preserve_thinking:
            return text.strip()
        return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
