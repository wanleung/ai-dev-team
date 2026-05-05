"""Abstract LLM backend base classes and shared utilities."""
from __future__ import annotations

import logging
import os
import random
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tools.registry import ToolRegistry

from agents.token_ledger import current_stage, estimate_tokens, get_ledger

import httpx
from openai import (
    APIConnectionError as _OAIConnError,
    APITimeoutError as _OAITimeoutError,
    AuthenticationError as _OAIAuthError,
    BadRequestError as _OAIBadRequest,
    InternalServerError as _OAIServerError,
    RateLimitError as _OAIRateLimit,
)

_log = logging.getLogger(__name__)

_DEFAULT_MAX_RETRIES: int = int(os.environ.get("AGENT_MAX_RETRIES", "3"))
_DEFAULT_BASE_DELAY: float = float(os.environ.get("AGENT_RETRY_BASE_DELAY", "1.0"))

# When a 5xx error carries retry_after >= this threshold (seconds), short
# exponential-backoff retries are useless — skip them and let FallbackLLMBackend
# switch to the next backend immediately.  Override via AGENT_FAST_FAIL_RETRY_AFTER.
_FAST_FAIL_RETRY_AFTER: int = int(os.environ.get("AGENT_FAST_FAIL_RETRY_AFTER", "30"))

# Errors that FallbackLLMBackend uses to trigger a switch to the next backend.
# These are infrastructure/transient failures — not caller errors.
FALLBACK_ERRORS = (
    ConnectionError,
    httpx.ConnectError,
    httpx.TimeoutException,
    httpx.RemoteProtocolError,  # server closed connection mid-stream (e.g. LiteLLM timeout)
    httpx.ReadError,            # TCP read error during streaming
    _OAIConnError,
    _OAITimeoutError,
    _OAIServerError,  # covers HTTP 503/502/504 — triggers backend fallback
    _OAIRateLimit,   # 429 quota exhausted — fall through to next backend
)


def _get_retry_after(exc: BaseException) -> int:
    """Return the retry_after value (seconds) from a server error body, or 0."""
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        return int(body.get("retry_after", 0) or 0)
    return 0


def _retry_with_backoff(
    fn,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    base_delay: float = _DEFAULT_BASE_DELAY,
):
    """Call fn() and retry with exponential backoff on transient API errors.

    Retryable: APIConnectionError, APITimeoutError, RateLimitError, InternalServerError
               (and Anthropic equivalents when installed).
    Non-retryable: AuthenticationError, BadRequestError — raised immediately.

    Fast-fail: if the error body carries retry_after >= _FAST_FAIL_RETRY_AFTER seconds,
               skip exponential retries and raise immediately so FallbackLLMBackend can
               switch backends without waiting.  (e.g. Cloudflare 524 with retry_after=120)
    """
    _retryable: list = [
        _OAIConnError,
        _OAITimeoutError,
        _OAIRateLimit,
        _OAIServerError,
    ]
    _non_retryable = (_OAIAuthError, _OAIBadRequest)

    try:
        import anthropic as _ant
        _retryable.extend([
            _ant.APIConnectionError,
            _ant.APITimeoutError,
            _ant.InternalServerError,
            _ant.RateLimitError,
        ])
    except ImportError:
        pass

    _retryable_tuple = tuple(_retryable)
    last_exc: BaseException | None = None

    for attempt in range(max_retries + 1):
        try:
            return fn()
        except _non_retryable:
            raise
        except _retryable_tuple as exc:  # type: ignore[misc]
            last_exc = exc
            retry_after = _get_retry_after(exc)
            # Fast-fail on permanent quota exhaustion (no point retrying)
            _err_code = getattr(exc, "code", None) or (
                getattr(exc, "body", {}) or {}
            ).get("error", {}).get("code", "")
            if _err_code == "insufficient_quota":
                _log.warning("Fast-failing (insufficient_quota): %s", str(exc)[:120])
                raise
            if retry_after >= _FAST_FAIL_RETRY_AFTER:
                _log.warning(
                    "Fast-failing (retry_after=%ds >= threshold %ds): %s: %s",
                    retry_after, _FAST_FAIL_RETRY_AFTER, type(exc).__name__, str(exc)[:120],
                )
                raise
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt) * random.uniform(0.9, 1.1)
                _log.warning(
                    "Retrying in %.1fs (attempt %d/%d): %s: %s",
                    delay, attempt + 1, max_retries, type(exc).__name__, str(exc)[:120],
                )
                time.sleep(delay)
            else:
                _log.error(
                    "All %d retries exhausted: %s: %s",
                    max_retries, type(exc).__name__, str(exc)[:120],
                )
        except Exception:
            raise

    raise last_exc  # type: ignore[misc]


class LLMBackend(ABC):
    """Abstract base for all LLM backends."""

    model: str  # bare model name (without prefix, e.g. "qwen3.6" not "ollama/qwen3.6")

    @abstractmethod
    def call(self, messages: list[dict], run_id: str | None = None) -> str:
        """Send a message list and return the assistant reply.

        Args:
            messages: Full message list including system prompt, history, and
                      the new user message. Format: OpenAI chat messages.
            run_id:   Optional pipeline run ID for token ledger emission.
        """

    @abstractmethod
    def call_with_tools(
        self,
        messages: list[dict],
        tools: "ToolRegistry",
        max_turns: int = 8,
        run_id: str | None = None,
    ) -> str:
        """Send messages, execute any tool calls, and return the final reply.

        Args:
            messages: Full message list (system + history + user message).
            tools:    ToolRegistry providing schemas and call() dispatch.
            max_turns: Max tool-call rounds before forcing a text response.
            run_id:   Optional pipeline run ID for token ledger emission.
        """

    def supports_tools(self) -> bool:
        """Return False for backends that do not support function calling."""
        return True


class OpenAICompatibleBackend(LLMBackend):
    """Shared base for all backends using the OpenAI Python SDK.

    Subclasses override:
        _extra_body()   — return extra_body dict (e.g. Ollama think options)
        _post_process() — transform reply text (e.g. strip <think> blocks)
        _pre_call()     — pre-call hook (e.g. Copilot session token refresh)
    """

    def __init__(
        self,
        model: str,
        client,  # openai.OpenAI instance
        inter_call_delay: int = 0,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        retry_delay: float = _DEFAULT_BASE_DELAY,
        stream: bool = False,
    ) -> None:
        self.model = model
        self._client = client
        self._inter_call_delay = inter_call_delay
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._stream = stream

    def _extra_body(self) -> dict:
        """Return additional kwargs for chat.completions.create().

        E.g. {"extra_body": {"options": {"preserve_thinking": True}}} for Ollama.
        Subclasses override this to inject backend-specific parameters.
        """
        return {}

    def _post_process(self, text: str) -> str:
        return text

    def _pre_call(self) -> None:
        pass

    def _stream_call(self, messages: list[dict], run_id: str | None = None) -> str:
        """Collect a streaming response into a single string.

        Args:
            messages: Full message list in OpenAI chat format.
            run_id:   Optional pipeline run ID for token ledger emission.

        Returns:
            Assembled and post-processed assistant reply text.
        """
        if self._inter_call_delay > 0:
            time.sleep(self._inter_call_delay)

        def _collect(stream) -> str:
            collected = ""
            for chunk in stream:
                if not chunk.choices:
                    continue  # final usage/stop chunks have empty choices
                delta = chunk.choices[0].delta.content
                if delta:
                    collected += delta
            return collected

        # The entire stream creation AND iteration is retried as a unit.
        # If a mid-stream error occurs, the request restarts from scratch.
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
        effective_run_id = run_id if run_id is not None else get_ledger().active_run_id()
        if effective_run_id is not None:
            pt, ct = estimate_tokens(messages, reply)
            get_ledger().record(effective_run_id, current_stage.get(), self.model, pt, ct)
        return self._post_process(reply)

    def call(self, messages: list[dict], run_id: str | None = None) -> str:
        """Send a message list and return the assistant reply.

        Args:
            messages: Full message list including system prompt, history, and
                      the new user message. Format: OpenAI chat messages.
            run_id:   Optional pipeline run ID for token ledger emission.
                      Falls back to the ledger's active run ID when omitted.
        """
        self._pre_call()
        if self._stream:
            return self._stream_call(messages, run_id=run_id)
        if self._inter_call_delay > 0:
            time.sleep(self._inter_call_delay)
        response = _retry_with_backoff(
            lambda: self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.3,
                **self._extra_body(),
            ),
            max_retries=self._max_retries,
            base_delay=self._retry_delay,
        )
        content = response.choices[0].message.content or ""
        effective_run_id = run_id if run_id is not None else get_ledger().active_run_id()
        if effective_run_id is not None:
            usage = getattr(response, "usage", None)
            if usage:
                get_ledger().record(effective_run_id, current_stage.get(), self.model,
                                    usage.prompt_tokens, usage.completion_tokens)
            else:
                pt, ct = estimate_tokens(messages, content)
                get_ledger().record(effective_run_id, current_stage.get(), self.model, pt, ct)
        return self._post_process(content)

    def call_with_tools(
        self,
        messages: list[dict],
        tools: "ToolRegistry",
        max_turns: int = 8,
        run_id: str | None = None,
    ) -> str:
        messages = list(messages)  # local copy for tool loop

        for _ in range(max_turns):
            # Fix 2 (Option B): call _pre_call() before every API call so that
            # backends like CopilotBackend can refresh a short-lived session token
            # that may expire mid tool-loop.  The default _pre_call() is a no-op,
            # so this is safe for all other backends.
            self._pre_call()
            if self._inter_call_delay > 0:
                time.sleep(self._inter_call_delay)
            response = _retry_with_backoff(
                lambda: self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=tools.schemas,
                    tool_choice="auto",
                    temperature=0.3,
                    **self._extra_body(),
                ),
                max_retries=self._max_retries,
                base_delay=self._retry_delay,
            )
            effective_run_id = run_id if run_id is not None else get_ledger().active_run_id()
            if effective_run_id is not None:
                usage = getattr(response, "usage", None)
                if usage:
                    get_ledger().record(effective_run_id, current_stage.get(), self.model,
                                        usage.prompt_tokens, usage.completion_tokens)
                else:
                    # fallback for backends that don't return usage in tool-call path
                    pt, ct = estimate_tokens(messages, response.choices[0].message.content or "")
                    get_ledger().record(effective_run_id, current_stage.get(), self.model, pt, ct)
            msg = response.choices[0].message
            if not msg.tool_calls:
                return self._post_process(msg.content or "")

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
            for tc in msg.tool_calls:
                _log.info("Tool call: %s(%s…)", tc.function.name, tc.function.arguments[:80])
                result = tools.call(tc.function.name, tc.function.arguments)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

        # Max turns reached — force a final text response
        messages.append({
            "role": "user",
            "content": "Please provide your final response based on the tool results above.",
        })
        self._pre_call()
        response = _retry_with_backoff(
            lambda: self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.3,
                **self._extra_body(),
            ),
            max_retries=self._max_retries,
            base_delay=self._retry_delay,
        )
        effective_run_id = run_id if run_id is not None else get_ledger().active_run_id()
        if effective_run_id is not None:
            usage = getattr(response, "usage", None)
            if usage:
                get_ledger().record(effective_run_id, current_stage.get(), self.model,
                                    usage.prompt_tokens, usage.completion_tokens)
            else:
                # fallback for backends that don't return usage in tool-call path
                pt, ct = estimate_tokens(messages, response.choices[0].message.content or "")
                get_ledger().record(effective_run_id, current_stage.get(), self.model, pt, ct)
        return self._post_process(response.choices[0].message.content or "")
