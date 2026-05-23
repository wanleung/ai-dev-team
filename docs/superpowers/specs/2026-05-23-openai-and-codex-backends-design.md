# Design: OpenAI API and Codex CLI Backends

**Date:** 2026-05-23  
**Status:** Approved

## Overview

Add two new LLM backends to `ai-software-house`:

1. **`openai/` prefix** — Direct OpenAI API (api.openai.com), for ChatGPT Business/Plus/Pro subscribers using API keys.
2. **`codex/` prefix** — OpenAI Codex CLI subprocess backend, for subscribers using ChatGPT plan sign-in.

Both follow the existing backend patterns in `agents/backends/`.

---

## Backend 1: OpenAI API (`openai/`)

### File
`agents/backends/openai_api.py`

### Design

A thin subclass of `OpenAICompatibleBackend` (same base class as `GitHubModelsBackend`, `NvidiaNimBackend`, etc.).

| Property | Value |
|----------|-------|
| Base URL | `https://api.openai.com/v1` |
| Auth | `OPENAI_API_KEY` env var |
| Model prefix stripped | `openai/` |
| Tool calling | ✅ Yes (OpenAI native) |
| Streaming | ✅ Yes |

### Config Examples

```yaml
model: "openai/gpt-4o"
model: "openai/gpt-4.1"
model: "openai/o3"
model: "openai/o4-mini"
```

Fallback example:
```yaml
model: "openai/gpt-4o"
fallbacks:
  - model: "openai/gpt-4.1"
  - model: "openai/o4-mini"
```

### Factory Routing

```python
if model.startswith("openai/"):
    from agents.backends.openai_api import OpenAIApiBackend
    ck = {k: v for k, v in kwargs.items() if k not in _ALL_PROVIDER_SPECIFIC}
    return OpenAIApiBackend(model=model, **ck)
```

Add `openai/` to the error message in the `raise ValueError` at the bottom of `_make_single_backend`.

### Environment Variable

`OPENAI_API_KEY` — required. Get from https://platform.openai.com/api-keys.

---

## Backend 2: Codex CLI (`codex/`)

### File
`agents/backends/codex.py`

### Design

A subprocess backend mirroring `opencode.py`. Runs `codex exec` in non-interactive mode.

| Property | Value |
|----------|-------|
| CLI binary | `codex` (override via `CODEX_BIN` env var) |
| Invocation | `codex exec --approval-mode full-auto --model <model> "<prompt>"` |
| Auth | ChatGPT plan OAuth (user already signed in via `codex` CLI) |
| Model prefix stripped | `codex/` |
| Tool calling | ❌ No (CLI subprocess) |
| Streaming | ❌ No (captures stdout) |
| Process management | Same as `opencode.py`: `Popen` + `start_new_session=True` + `os.killpg(SIGKILL)` on timeout/exit |

### Config Examples

```yaml
model: "codex/codex-mini-latest"
```

As a fallback from another backend:
```yaml
model: "openai/gpt-4o"
fallbacks:
  - model: "codex/codex-mini-latest"
```

### Command Construction

```python
bin_path = os.environ.get("CODEX_BIN", "codex")
# model is e.g. "codex-mini-latest" after stripping "codex/" prefix
cmd = [bin_path, "exec", "--approval-mode", "full-auto", "--model", self.model, prompt]
```

The `prompt` is constructed by combining system + message history into a single string, same as `opencode.py`.

### Process Lifecycle

Mirrors `opencode.py` exactly:
- `Popen(..., start_new_session=True)` to create a new process group
- `proc.communicate(timeout=self._timeout)` to wait for output
- `os.killpg(os.getpgid(proc.pid), signal.SIGKILL)` in `except`/`finally` to ensure cleanup
- ANSI escape stripping on output (codex CLI may emit terminal codes)

### Error Handling

- Non-zero exit code → `RuntimeError`
- Empty output after stripping → `RuntimeError`
- Timeout → `subprocess.TimeoutExpired` (retried up to `max_retries`)
- Binary not found → `FileNotFoundError` with install instructions

---

## Tests

### `tests/test_openai_api.py`

- `test_strips_openai_prefix` — model `openai/gpt-4o` → passed to client as `gpt-4o`
- `test_requires_api_key` — raises `EnvironmentError` when `OPENAI_API_KEY` unset
- `test_supports_tools` — returns `True`
- `test_factory_routes_openai_prefix` — `create_backend({"model": "openai/gpt-4o"})` returns `OpenAIApiBackend`

### `tests/test_codex.py`

- `test_strips_codex_prefix` — model `codex/codex-mini-latest` → passed as `--model codex-mini-latest`
- `test_does_not_support_tools` — returns `False`
- `test_call_success` — mock Popen returns stdout, assert correct text returned
- `test_call_timeout_retries` — mock Popen raises `TimeoutExpired`, assert retry and eventually raises
- `test_factory_routes_codex_prefix` — `create_backend({"model": "codex/codex-mini-latest"})` returns `CodexBackend`
- `test_codex_bin_override` — `CODEX_BIN=my-codex` env → subprocess called with `my-codex`

---

## Files Changed

| File | Change |
|------|--------|
| `agents/backends/openai_api.py` | New — OpenAI API backend |
| `agents/backends/codex.py` | New — Codex CLI backend |
| `agents/backends/factory.py` | Add `openai/` and `codex/` routing |
| `tests/test_openai_api.py` | New — unit tests |
| `tests/test_codex.py` | New — unit tests |
| `config.local.yaml` | Add commented examples for both backends |

---

## Non-Goals

- Azure OpenAI (different endpoint per deployment) — out of scope
- Codex CLI with API key auth — out of scope (OAuth only)
- Streaming output from Codex CLI — not supported by `codex exec`
