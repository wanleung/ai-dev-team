# T6-A Design: Operational Correctness

**Date:** 2026-05-10  
**Branch:** `t6-a-operational-correctness`  
**Tier:** T6 — post-merge hardening, first PR

---

## Problem

Four correctness gaps remain after T5 that affect runtime reliability:

1. **`required_output_fields` never populated** — 12 of 14 `_run_stage()` call sites omit the field list, leaving `OutputVerifier` (added in T5-B) permanently dormant. Stage failures that produce partial results go undetected.
2. **`_validate_pipeline_stages` only warns** — unknown stage names log a warning but don't stop execution; the first pipeline run crashes with a `KeyError` instead.
3. **No graceful shutdown** — receiving `SIGTERM` or `SIGINT` mid-run causes abrupt process termination; any in-flight stage has no opportunity to clean up, checkpoint, or drain the DLQ.
4. **`result.errors.append()` is not thread-safe** — when `MAX_PARALLEL_STAGES > 1` (T5-A), multiple stage threads can corrupt the shared `errors` list with concurrent appends.

---

## Architecture

All four fixes are confined to `orchestrator.py` (and `PipelineResult`). No new files or abstractions are introduced; each fix applies an existing pattern consistently.

---

## Fix 1: Populate `required_output_fields` at all call sites

**Location:** `orchestrator.py` — 12 `_run_stage()` call sites that currently omit the parameter.

**Approach:** For each call site, inspect the stage function body to determine which `PipelineResult` fields it is expected to populate, then set `required_output_fields` to that list. Fields that are optional (set only on the happy path) are excluded; only the fields that must be present for downstream stages to proceed are included.

**Representative mapping** (engineer to confirm each during implementation):

| Stage | `required_output_fields` |
|-------|--------------------------|
| `qa_plan` stage | `["qa_plan"]` |
| `implement` / `code` stage | `["code"]` |
| `review` stage | `["review"]` |
| `deploy` stage | `["deploy_files"]` |
| Stages that set `verdict` | `["verdict"]` |

Call sites at lines 1295 (`["prd"]`) and 1311 (`["design"]`) are already correct and are left unchanged.

---

## Fix 2: Promote `_validate_pipeline_stages` from warn to raise

**Location:** `orchestrator.py`, method `_validate_pipeline_stages()` (~line 1571).

**Current behaviour:** Logs a `WARNING` when unknown stage names are found.

**New behaviour:** Raises `ConfigurationError` (already defined in `orchestrator.py`) instead of warning. The call sites at lines 1556 and 1566 already propagate exceptions, so this change requires no other edits.

```python
# Before
if unknown:
    logging.getLogger(__name__).warning(...)

# After
if unknown:
    raise ConfigurationError(
        f"Pipeline {source!r} references unknown stage(s) {unknown}. "
        f"Valid stages: {sorted(registry.keys())}"
    )
```

This turns a silent, late crash into an explicit, early failure.

---

## Fix 3: Graceful shutdown signal handlers

**Location:** `Orchestrator.__init__()` — register handlers once on construction.

**Design:**

```python
import signal

self._shutdown_event = threading.Event()

def _handle_shutdown(signum, frame):
    self._shutdown_event.set()

signal.signal(signal.SIGTERM, _handle_shutdown)
signal.signal(signal.SIGINT, _handle_shutdown)
```

**`_run_stage()` shutdown check:**  
At the start of `_run_stage()`, before acquiring any lock or calling the stage function:

```python
if self._shutdown_event.is_set():
    raise SystemExit("Pipeline shutting down — SIGTERM/SIGINT received")
```

**Behaviour on shutdown:**
- Current stage completes (not interrupted mid-execution — avoids partial writes).
- Next `_run_stage()` call raises `SystemExit`, unwinding the call stack cleanly.
- Existing checkpoint logic (already persists `PipelineResult` after each stage) ensures progress is preserved.

**Edge cases:**
- Signal received while a stage is in progress: stage completes, next stage is blocked.
- `SystemExit` propagates up through `run()`, which already has a top-level `try/except Exception` — `SystemExit` is NOT a subclass of `Exception`, so it propagates correctly to the process boundary.

---

## Fix 4: Thread-safe `result.errors`

**Location:** `PipelineResult` dataclass and `_run_stage()`.

**Change:** Add `_errors_lock: threading.Lock = field(default_factory=threading.Lock)` to `PipelineResult`. Mark it `repr=False` and exclude from serialisation helpers.

In `_run_stage()` (and any other site that appends to `result.errors`):

```python
with result._errors_lock:
    result.errors.append(error)
```

**Scope:** Only `append` calls need the lock; reads of `result.errors` (after all parallel stages finish) are safe without it.

---

## Error Handling

| Scenario | Behaviour |
|----------|-----------|
| Unknown stage in YAML | `ConfigurationError` raised at load time — pipeline never starts |
| Required field missing after stage | `OutputVerificationError` raised inside `_run_stage()` — existing error path handles it |
| SIGTERM mid-run | Current stage finishes; next stage raises `SystemExit` |
| SIGINT (Ctrl-C) | Same as SIGTERM |
| Concurrent `errors.append()` | Serialised via `_errors_lock` |

---

## Testing

Tests for this PR focus on the new contracts, not full integration:

| Test | Assertion |
|------|-----------|
| `test_validate_pipeline_raises_on_unknown.py` | `_validate_pipeline_stages()` raises `ConfigurationError` on unknown stage name |
| `test_required_output_fields_verified.py` | `_run_stage()` raises `OutputVerificationError` when stage omits a required field |
| `test_graceful_shutdown_sigterm.py` | After `_shutdown_event.set()`, next `_run_stage()` call raises `SystemExit` |
| `test_errors_lock_thread_safety.py` | 50 threads concurrently appending errors produce exactly 50 entries |

---

## Constraints

- No new files (all changes in `orchestrator.py` / `PipelineResult`).
- `signal.signal()` must be called from the main thread — `Orchestrator.__init__()` is always called from the main thread in production.
- `threading.Lock` added to `PipelineResult` must be excluded from `__eq__`, `__hash__`, and JSON serialisation to avoid breaking existing checkpoint/comparison code.
