# T7-A Design: Bug Fixes — Stage Timeouts, NameError, Token Estimation, Budget Bypass, HTTP Contract, Memory Stacking

**Date:** 2026-05-10
**Branch:** `t7-a-bug-fixes`
**PR target:** `master`

---

## Problem Statement

Six correctness bugs were identified in T7 analysis, two of which break 20+ existing tests and one of which causes a silent runtime crash in production. All are isolated, well-scoped fixes with no cross-cutting design changes.

---

## Task 1: `_stage_timeouts` Missing on `__new__` Instances

**File:** `orchestrator.py`

**Problem:** `_stage_timeouts` is initialised only in `__init__` (lines 867–875). Tests and any partial-construction path that calls `Orchestrator.__new__(Orchestrator)` without `__init__` hit `AttributeError` when `_make_stage_registry()` is called at line 1439. This breaks 20+ tests in `test_pipeline_modes.py` and `test_pipeline_yaml.py`.

**Fix:** Add a class-level default:
```python
class Orchestrator:
    _stage_timeouts: dict[str, float] = {}
    ...
```
This makes the attribute always present; `__init__` still overwrites it with the instance-level value as before.

**Tests:** Verify the 20+ previously-failing tests now pass with no new failures.

---

## Task 2: `logger` NameError in `watcher._collect_issue_prior_context`

**File:** `watcher.py:317`

**Problem:** The `except Exception` handler calls `logger.debug(...)`, but the module-level logger is named `_log` (line 71). This raises `NameError: name 'logger' is not defined` at runtime whenever fetching prior-context comments raises any exception (network blip, rate limit, etc.), crashing the watcher dispatch instead of failing gracefully.

**Fix:** Change `logger.debug(...)` → `_log.debug(...)` at line 317.

**Tests:** Add/update `test_collect_issue_prior_context_logs_on_exception` to confirm the except path is reached without raising NameError.

---

## Task 3: `estimate_tokens` Zero-Count for Short Strings

**File:** `agents/token_ledger.py`

**Problem:** Token estimation uses integer floor division: `len(text) // 4`. For strings shorter than the divisor (e.g. `"hi"` → `2 // 4 == 0`), the result is 0. This silently under-reports costs for short completions and can prevent `BudgetExceededError` from triggering correctly.

**Fix:** Replace `len(text) // divisor` with `max(1, round(len(text) / divisor))` for both prompt and completion estimation paths. This ensures at minimum 1 token is counted per non-empty string.

**Tests:** Parametrize `test_estimate_tokens_*` with short strings (`"4"`, `"hi"`, `" "`) and assert results ≥ 1.

---

## Task 4: `BudgetExceededError` in Parallel Stage Batch Bypasses `_finish()`

**File:** `orchestrator.py` (~line 2489)

**Problem:** In the parallel stage batch, `future.result()` is called in a bare loop. If a stage raises `BudgetExceededError`, it propagates through `_run_stage` → `future.result()` → crashes the `as_completed` iterator, bypassing `_finish()`. No checkpoint is saved, no GitHub cleanup runs, and the run summary is lost.

**Fix:** Wrap the `as_completed` loop body:
```python
try:
    stage_results[s.checkpoint_key] = future.result()
except BudgetExceededError:
    # Cancel remaining futures, then clean up
    for pending_f in futures.values():
        pending_f.cancel()
    return self._finish(result, start_time)
```

**Tests:** Add `test_parallel_budget_exceeded_calls_finish` — mock one stage to raise `BudgetExceededError`, assert `_finish()` is called and checkpoint is saved.

---

## Task 5: Watcher HTTP Error Contract Mismatch

**Files:** `watcher.py` — `get_open_prs()`, `get_pr_comments()`

**Problem:** Both functions call `resp.raise_for_status()` which raises `requests.HTTPError` on 4xx/5xx. Callers catch `RuntimeError`, not `HTTPError`, so non-retryable failures (404, 403, 429) propagate as uncaught exceptions. The rest of `watcher.py` raises `RuntimeError` for API errors (lines 1133/1147) — these two functions should be consistent.

**Fix:** After `resp = requests.get(...)`, add:
```python
if not resp.ok:
    raise RuntimeError(f"GitHub API error {resp.status_code}: {resp.text[:200]}")
```
Remove the `resp.raise_for_status()` call (redundant once the check is in place).

**Tests:** Update `test_get_open_prs_raises_on_api_error` and add `test_get_pr_comments_raises_on_api_error` with a 404 mock, asserting `RuntimeError` is raised.

---

## Task 6: Memory-Context Prompt Stacking on Repeated `run()` Calls

**File:** `orchestrator.py` (~lines 2305–2313)

**Problem:** Memory injection prepends to `agent.system_prompt` without a guard:
```python
agent.system_prompt = memory_context + "\n\n---\n\n" + agent.system_prompt
```
On a second `run()` call (common in the watcher, which reuses orchestrator instances), the agent's `system_prompt` becomes `memory + sep + memory + sep + original` — duplicating context and wasting tokens.

Skills and repo-tree injection already use `_original_system_prompts` as the base. Memory injection must do the same.

**Fix:**
```python
original = self._original_system_prompts.get(agent_name, agent.system_prompt)
agent.system_prompt = memory_context + "\n\n---\n\n" + original
```

**Tests:** Add `test_memory_context_not_duplicated_on_second_run` — call `run()` twice on the same orchestrator, assert the memory prefix appears exactly once in the resulting system prompt.

---

## Architecture Notes

- All fixes are surgical (1–5 lines each); no structural changes to the orchestrator's pipeline model.
- Tasks 1 and 2 are truly isolated one-liners. Tasks 3–6 each touch one method.
- No new dependencies introduced.
- Each task includes at minimum one targeted test to lock in the fix.

---

## Success Criteria

- All 20+ previously-failing tests in `test_pipeline_modes.py` / `test_pipeline_yaml.py` pass after Task 1.
- `test_collect_issue_prior_context_logs_on_exception` passes without NameError after Task 2.
- `estimate_tokens("hi", ...)` returns ≥ 1 for both prompt and completion after Task 3.
- `test_parallel_budget_exceeded_calls_finish` passes and `_finish()` is confirmed called after Task 4.
- `test_get_open_prs_raises_on_api_error` passes with `RuntimeError` after Task 5.
- `test_memory_context_not_duplicated_on_second_run` passes after Task 6.
- Full test suite: zero new failures introduced.
