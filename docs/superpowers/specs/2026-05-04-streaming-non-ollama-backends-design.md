# Streaming Support for Non-Ollama Backends

**Date:** 2026-05-04  
**Status:** Approved

## Problem

Non-Ollama backends (opencode_go, opencode_zen, github_models, nvidia_nim, copilot) make
non-streaming API calls via `OpenAICompatibleBackend.call()`. For large model responses or slow
networks, the full response is buffered before returning — often exceeding Cloudflare's 100-second
timeout, causing HTTP 524 errors. Only `OllamaBackend` already streams.

## Goals

- Add streaming to `OpenAICompatibleBackend` so all OAI-compatible backends can opt-in.
- Default to `stream=True` for `OpenCodeGoBackend` (primary 524 source).
- Keep backward compatibility — all other backends default to `stream=False`.
- Eliminate duplicated streaming logic between `OllamaBackend` and the base class.

## Architecture

### `OpenAICompatibleBackend` (agents/backends/base.py)

Add `stream: bool = False` constructor parameter stored as `self._stream`.

Add `_stream_call(messages)` method — collects streamed chunks into a single string:

```python
def _stream_call(self, messages: list[dict]) -> str:
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
```

`call()` dispatches based on `self._stream`:

```python
def call(self, messages):
    self._pre_call()
    if self._stream:
        return self._stream_call(messages)
    # existing non-streaming path unchanged
```

`call_with_tools()` always uses non-streaming (tool responses need structured JSON, not streamed text).

### `OllamaBackend` (agents/backends/ollama.py)

Remove `_stream_call()` — inherits from base class.  
Pass `stream=ollama_stream` to `super().__init__()`.  
Remove `call()` override entirely — base class `call()` now handles both streaming dispatch and
`_pre_call()`, so the override is redundant.

### `OpenCodeGoBackend` (agents/backends/opencode_go.py)

Add `stream: bool = True` constructor parameter.  
Pass `stream=stream` when constructing `OpenAICompatibleBackend`.  
The Anthropic (MiniMax) path is unaffected — Anthropic SDK handles its own streaming differently
and is not subject to Cloudflare timeouts.

### `BaseAgent` (agents/base_agent.py)

Add `opencode_go_stream: bool = True` parameter to `__init__()`.  
Pass through `_build_backend()` to `OpenCodeGoBackend`.

Other backends (`opencode_zen`, `github_models`, `nvidia_nim`, `copilot`) keep `stream=False` by
default. They can be upgraded in a follow-up if needed.

### Orchestrator (orchestrator.py)

Add `opencode_go_stream` to the agent kwargs wiring (same pattern as `ollama_stream`).

### Config (config.yaml)

```yaml
pipeline:
  opencode_go_stream: true   # stream responses from opencode_go backend (prevents 524)
```

## Error Handling

- Streaming failures (connection drop mid-stream) will raise `APIConnectionError` or
  `APITimeoutError` — both are already in `FALLBACK_ERRORS` and retried by `_retry_with_backoff`.
- Partial responses (stream cut off) will be returned as-is; the agent layer will treat them as a
  truncated reply and may retry at the orchestrator level if the response is unparseable.

## Testing

- Existing `test_non_ollama_not_streaming` test in `tests/test_ollama.py` will need updating —
  it asserts `stream` is not True for github_models; still valid since github_models defaults False.
- Add test: `OpenCodeGoBackend` with `stream=True` passes `stream=True` to the OAI client.
- Add test: `OpenAICompatibleBackend._stream_call()` assembles chunks correctly.
- `OllamaBackend` streaming tests remain green (same behaviour, now via base class).

## Out of Scope

- Streaming for `call_with_tools()` — structured tool responses require complete JSON; streaming
  adds complexity with no 524 benefit (tool calls are fast).
- Streaming for Anthropic/MiniMax path in `OpenCodeGoBackend`.
- Adding `stream` config for `opencode_zen`, `github_models`, `nvidia_nim`, `copilot` — can be
  done as a follow-up with a single `api_stream` flag.
