# GrokBackend Design

**Date:** 2026-05-18  
**Status:** Approved

## Problem

ai-software-house has no backend for xAI's Grok models. grok-cli is a headless-capable
terminal agent (`grok --prompt "..." --format json`) that can be driven as a subprocess,
bringing live X/web search, Grok model variants, and built-in sub-agent delegation to
the pipeline.

## Approach

Subprocess backend modelled on `OpenCodeBackend`, extended with real-time streaming via
grok's newline-delimited JSON event format.

---

## Architecture

### Registration

- **Prefix:** `grok/` (e.g. `grok/grok-4.3`, `grok/grok-4.20-non-reasoning`)
- **New file:** `agents/backends/grok.py`
- **Factory:** `agents/backends/factory.py` — add `if model.startswith("grok/")` block
- **Class:** `GrokBackend(LLMBackend)` — standalone, does NOT extend `OpenAICompatibleBackend`

Pipeline YAML example:
```yaml
model: grok/grok-4.3
timeout: 300          # seconds, default 600
directory: /path/to/project   # optional, defaults to os.getcwd()
max_retries: 2        # example value; default comes from _DEFAULT_MAX_RETRIES (env AGENT_MAX_RETRIES, default 3)
```

### Binary Resolution

`GROK_BIN` environment variable overrides the binary path; default is `"grok"`.
Consistent with `OPENCODE_BIN` convention.

---

## Call Flow

### `call(messages, run_id=None, on_token=None)`

1. **Build prompt** — concatenate system block, truncated conversation history
   (≤2000 chars per turn), and final user message into a single string. Same
   pattern as `OpenCodeBackend`.

2. **Spawn process:**
   ```
   grok --prompt "<text>" --format json --model <model> --directory <dir>
   ```
   via `subprocess.Popen(stdout=PIPE, stderr=PIPE, text=True)`.

3. **Stream stdout line by line** — each line is a newline-delimited JSON object:
   - `{"type": "text", "content": "..."}` → append `content` to reply buffer;
     call `on_token(content)` if set (guarded with `try/except`).
   - `{"type": "error", "message": "..."}` → record error message.
   - `{"type": "step_start" | "step_finish" | ...}` → skip.
   - Non-JSON line → skip silently (defensive; grok may emit progress lines).

4. **After process exits:**
   - Non-zero return code → raise `RuntimeError(f"grok exited {rc}: {stderr[:300]}")`.
   - Recorded error event → raise `RuntimeError(error_message)`.
   - Strip ANSI escape codes from assembled reply (same regex as `OpenCodeBackend`).
   - Empty reply after strip → raise `RuntimeError("Empty response from grok")`.
   - Return reply string.

5. **Retry** — on `TimeoutExpired` or `RuntimeError`, retry up to `max_retries` times
   with `2^attempt` second backoff. Raise on final failure.

### `call_with_tools(messages, tools, max_turns, run_id)`

Raises `NotImplementedError`. grok manages its own tool ecosystem internally;
OpenAI-style function calling is not supported via this backend.

### `supports_tools()`

Returns `False`.

---

## Error Handling

| Condition | Behaviour |
|-----------|-----------|
| `subprocess.TimeoutExpired` | Retry with `2^attempt` backoff; raise after `max_retries` |
| Non-zero exit code | Raise `RuntimeError` with stderr snippet |
| `{"type": "error"}` event | Raise `RuntimeError` with grok's error message |
| Empty output after ANSI strip | Raise `RuntimeError("Empty response from grok")` |
| JSON parse failure on a line | Skip silently |
| `GROK_API_KEY` not set | Surfaces as non-zero exit; no pre-flight check |

---

## Testing

File: `tests/test_grok_backend.py`

| # | Test | What it verifies | Status |
|---|------|-----------------|--------|
| 1 | `test_call_collects_text_events` | Mock Popen emitting text events → reply assembled correctly | ✅ |
| 2 | `test_call_streams_on_token` | `on_token` called once per text event chunk | ✅ |
| 3 | `test_call_retries_on_timeout` | First call raises `TimeoutExpired`, second succeeds | ✅ |
| 4 | `test_call_raises_on_error_event` | `{"type":"error"}` event → `RuntimeError` | ✅ |
| 5 | `test_call_raises_on_empty_output` | No text events → `RuntimeError` | ✅ |
| 6 | `test_call_with_tools_not_supported` | `call_with_tools()` → `NotImplementedError` | ✅ |
| 7 | `test_factory_creates_grok_backend` | `create_backend({"model": "grok/grok-4.3"})` → `GrokBackend` | ✅ |

---

## Out of Scope

- Batch API (`--batch-api`) support
- Session continuity (`--session`) across pipeline runs
- Exposing grok's sub-agent delegation to the ai-software-house tool registry
- `--format` modes other than `json`
