# T4-B: Pipeline Correctness — Design

**Date:** 2026-05-09  
**Status:** Approved  
**Branch:** `t4-b-pipeline-correctness`

## Problem

Three correctness gaps that cause incorrect behaviour without clear errors:

1. `estimate_tokens()` always uses `cl100k_base` (OpenAI encoding). Ollama/Claude/Gemini token counts are wrong by 10–30%, causing budget enforcement to under/over-trip.
2. `pipeline.yaml` loop blocks accept any non-empty `until:` string. Typos (e.g. `APPROVD`) silently loop forever.
3. When an upstream critical stage's circuit breaker opens (e.g. PM agent fails threshold), downstream stages still run and fail with confusing errors rather than being skipped.

## Architecture

### Fix 4 — Multi-backend token estimation (`agents/token_ledger.py`)

Add optional `model: str = ""` parameter to `estimate_tokens(messages, reply, model="")`.

Dispatch logic:
```
model contains "gpt" or "text-" → tiktoken cl100k_base (existing)
model contains "claude"         → char-based: chars // 3.5 (Anthropic approximation)
model contains "gemini"         → char-based: chars // 4
everything else (Ollama, etc.)  → char-based: chars // 4 (safe fallback)
```

No new hard dependencies — `tiktoken` already present; char-based needs only Python builtins. Callers in `orchestrator.py` already have model name available via `backend.model`; pass it through.

### Fix 5 — Loop verdict validation (`orchestrator.py`)

In `_load_pipeline_yaml()` around line 1429, after the non-empty check, add:

```python
VALID_VERDICTS = {"APPROVED", "NEEDS_REVISION"}
if str(loop["until"]).upper() not in VALID_VERDICTS:
    raise ConfigurationError(
        f"pipeline.yaml loop 'until' must be one of {VALID_VERDICTS}. Got: {loop['until']!r}"
    )
```

Comparison is case-insensitive; stored value is normalised to uppercase. `ConfigurationError` already exists in the codebase.

### Fix 6 — CB cascade for critical stages (`orchestrator.py`)

Add `is_critical: bool = False` field to `PipelineStage` dataclass (line ~445).

In `_make_stage_registry()`, mark `"pm"` and `"architect"` as `is_critical=True`.

Add `_critical_cb_open() -> str | None` helper that iterates `_make_stage_registry()` critical stages, calls `get_registry().get_or_create("agent", name).state`, returns the stage name if `state == "open"`, else None.

In `_run_stage()`, at the top (before any execution), call `_critical_cb_open()`. If a critical upstream CB is open and the current stage is NOT itself critical, raise `PipelineError(stage="cb_cascade", message=f"Skipping: upstream '{name}' circuit breaker is open")`. This gets caught by `_run_stage_safe()` and recorded in `result.errors`.

**Scope boundary:** only skip non-critical stages when a critical one is open. Critical stages still attempt (they might recover via FallbackLLMBackend).

## Data Flow

```
_run_stage(label, ...)
  ├─ [NEW] _critical_cb_open() → if open, raise PipelineError and return
  ├─ estimate_tokens(messages, reply, model=backend.model)  [now model-aware]
  └─ ... existing stage logic ...

_load_pipeline_yaml()
  └─ validate loop_until against VALID_VERDICTS  [NEW]
```

## Error Handling

- Token fallback: if model string unrecognised, use char//4 (never raises)
- Verdict validation: raises `ConfigurationError` at load time — fail fast, not mid-run
- CB cascade: `PipelineError` recorded in `result.errors` with clear stage name `"cb_cascade"`; pipeline continues to next stage group

## Testing

- `tests/test_token_ledger.py` — add 4 tests: OpenAI model uses tiktoken, Claude model uses char estimate, Gemini model uses char estimate, unknown model uses char fallback
- `tests/test_pipeline_yaml_validation.py` — add 2 tests: invalid verdict raises ConfigurationError, valid "APPROVED" passes
- `tests/test_cb_cascade.py` (new) — 3 tests: critical CB open → downstream skipped, critical CB closed → downstream runs, critical stage itself not skipped when upstream CB open

## Acceptance Criteria

- [ ] `estimate_tokens(..., model="claude-3-opus")` returns char-based estimate, not tiktoken
- [ ] `pipeline.yaml` with `until: APPROVD` raises `ConfigurationError` at load time
- [ ] When PM circuit breaker is open, engineer/reviewer stages are skipped with clear error message
- [ ] All existing tests still pass
