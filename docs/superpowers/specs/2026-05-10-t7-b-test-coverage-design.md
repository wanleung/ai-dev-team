# T7-B Design: Test Infrastructure — Ledger Isolation, Coverage for Fixed Paths

**Date:** 2026-05-10
**Branch:** `t7-b-test-coverage`
**PR target:** `master`

---

## Problem Statement

Two test infrastructure issues remain after T7-A: a global `TokenLedger` singleton that leaks between tests causing flaky suite runs, and missing coverage for the paths fixed in T7-A (parallel budget exhaustion, watcher HTTP errors, memory stacking, token estimation edge cases).

---

## Task 1: Fix `TokenLedger` Singleton Leak Between Tests

**File:** `tests/conftest.py` (create or extend)

**Problem:** `set_ledger()` sets a module-global `_global_ledger`. Tests that call `set_ledger()` do not restore the original, so subsequent tests may run with a wrong/dirty ledger. This causes `test_token_backend_emission.py` to pass in isolation but fail in full-suite runs.

**Fix:** Add an `autouse` session-scoped (or function-scoped) fixture to `conftest.py`:
```python
import pytest
from agents.token_ledger import set_ledger, _global_ledger as _orig

@pytest.fixture(autouse=True)
def _reset_token_ledger():
    yield
    set_ledger(_orig)  # restore after every test
```

If `_global_ledger` is not directly importable, use `monkeypatch` to patch `agents.token_ledger._global_ledger` back to its original value.

**Verification:** Run `pytest tests/ -x` twice in different orders; no ledger-related failures should appear.

---

## Task 2: Coverage — `estimate_tokens` Short-String Edge Cases

**File:** `tests/test_token_ledger.py` (extend existing)

**Problem:** No test exercises the short-string floor-division zero-count path that Task 3 of T7-A fixes.

**Tests to add:**
```python
@pytest.mark.parametrize("text", ["4", "hi", " ", "x"])
def test_estimate_tokens_short_string_returns_at_least_one(text):
    prompt_est, completion_est = estimate_tokens(
        [{"role": "user", "content": text}], text, model="gpt-4"
    )
    assert prompt_est >= 1
    assert completion_est >= 1
```

---

## Task 3: Coverage — Parallel `BudgetExceededError` Calls `_finish()`

**File:** `tests/test_parallel_budget_exceeded.py` (new)

**Problem:** The fix in T7-A Task 4 wraps the parallel batch in `try/except BudgetExceededError`. No test verifies that `_finish()` is actually called (checkpoint saved, GitHub cleanup runs) when budget is exhausted mid-parallel-batch.

**Tests:**
```python
def test_parallel_budget_exceeded_triggers_finish(monkeypatch):
    """BudgetExceededError from a parallel stage must call _finish(), not crash."""
    orch = _make_orchestrator()
    result = PipelineResult(requirement="budget test")
    
    # Mock one stage to raise BudgetExceededError
    # Assert _finish() is called (monkeypatch it to track calls)
    finish_calls = []
    original_finish = orch._finish
    
    def tracked_finish(*args, **kwargs):
        finish_calls.append(True)
        return original_finish(*args, **kwargs)
    
    monkeypatch.setattr(orch, "_finish", tracked_finish)
    
    # Run parallel batch with a stage that raises BudgetExceededError
    # (exact wiring depends on how parallel stages are invoked)
    ...
    assert len(finish_calls) == 1, "_finish() must be called exactly once on budget exhaustion"
```

The exact test implementation should read the parallel batch method to understand how to inject the error.

---

## Task 4: Coverage — Watcher HTTP Error Contract

**File:** `tests/test_watcher.py` (extend existing)

**Problem:** After T7-A Task 5, `get_open_prs()` and `get_pr_comments()` raise `RuntimeError` on HTTP errors. The existing test mock was broken (no-op `raise_for_status`). New tests should use `requests_mock` or `unittest.mock` to simulate 404/429 responses and assert `RuntimeError` is raised.

**Tests:**
```python
def test_get_open_prs_raises_runtime_error_on_404(requests_mock):
    requests_mock.get(..., status_code=404)
    with pytest.raises(RuntimeError, match="GitHub API error 404"):
        get_open_prs(...)

def test_get_pr_comments_raises_runtime_error_on_403(requests_mock):
    requests_mock.get(..., status_code=403)
    with pytest.raises(RuntimeError, match="GitHub API error 403"):
        get_pr_comments(...)
```

---

## Task 5: Coverage — Memory Context Not Duplicated on Second `run()`

**File:** `tests/test_memory_injection.py` (new) or extend `test_orchestrator_*.py`

**Problem:** After T7-A Task 6, memory injection uses `_original_system_prompts` as the base. A test should confirm that calling `run()` twice does not double-inject memory.

**Tests:**
```python
def test_memory_context_not_duplicated_on_second_run():
    orch = _make_orchestrator()
    # Inject memory context once, simulate second run
    # Assert memory prefix appears exactly once in the resulting system prompt
    ...
    prefix_count = result_prompt.count(memory_marker)
    assert prefix_count == 1, f"Memory injected {prefix_count} times, expected 1"
```

---

## Architecture Notes

- T7-B is entirely test-only — no production code changes.
- All tests in T7-B validate fixes introduced in T7-A; T7-B branch should be based on master after T7-A merges.
- `conftest.py` autouse fixture (Task 1) benefits the entire suite immediately with no test changes required.

---

## Success Criteria

- Full test suite passes in any order (no ledger-related flakiness).
- `test_estimate_tokens_short_string_returns_at_least_one` passes for all 4 parametrize values.
- `test_parallel_budget_exceeded_triggers_finish` passes and confirms `_finish()` call.
- `test_get_open_prs_raises_runtime_error_on_404` and `test_get_pr_comments_raises_runtime_error_on_403` pass.
- `test_memory_context_not_duplicated_on_second_run` passes.
- Zero regressions in existing suite.
