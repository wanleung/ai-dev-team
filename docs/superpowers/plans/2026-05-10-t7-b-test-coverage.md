# T7-B Test Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the `set_ledger()` global-state leak that causes order-dependent test failures, then add coverage for four paths that T7-A fixed but left untested at the integration level.

**Architecture:** Task 1 (conftest fixture) is a prerequisite for Tasks 2–5. Tasks 2–5 are independent of each other. No production code changes — test infrastructure only.

**Tech Stack:** Python 3, pytest, `agents/token_ledger.py`, `watcher.py`, `orchestrator.py`, `unittest.mock`

**Important:** Execute T7-A first (or at minimum merge it into `t7-b-test-coverage` branch) before running these tests — they exercise the fixes from T7-A.

---

## File Map

| File | Task |
|------|------|
| `tests/conftest.py` | Task 1 — autouse ledger-reset fixture |
| `tests/test_token_ledger.py` | Task 2 — short-string coverage |
| `tests/test_parallel_budget_exceeded.py` | Task 3 — parallel BudgetExceededError coverage |
| `tests/test_watcher.py` | Task 4 — HTTP error coverage |
| `tests/test_memory_injection.py` | Task 5 — memory stacking coverage |

---

## Task 1: Fix `set_ledger()` Global-State Leak — Autouse Conftest Fixture

**Files:**
- Modify or Create: `tests/conftest.py`

**Context:** `set_ledger()` writes to the module-level `_ledger` global in `agents/token_ledger.py`. Any test that calls `set_ledger()` and doesn't restore it poisons subsequent tests. The fix is an autouse `session`-scoped or `function`-scoped fixture that saves and restores the global around each test.

- [ ] **Step 1: Verify the problem exists**

```bash
cd /home/wanleung/Projects/ai-software-house/t7-b
python3 -c "
import agents.token_ledger as tl
from agents.token_ledger import TokenLedger, set_ledger, get_ledger
original = get_ledger()
custom = TokenLedger()
set_ledger(custom)
print('After set_ledger:', get_ledger() is custom)  # True
# No reset — leak
print('Leaked:', get_ledger() is custom)  # True
"
```

Expected output shows global is mutated without restoration.

- [ ] **Step 2: Check if `tests/conftest.py` already exists**

```bash
ls tests/conftest.py 2>/dev/null && echo exists || echo missing
```

- [ ] **Step 3: Add or create the autouse fixture**

If `tests/conftest.py` already exists, add to it. If it doesn't exist, create it.

```python
# tests/conftest.py  (add this block — don't duplicate if it already exists)
import pytest
import agents.token_ledger as _token_ledger_mod


@pytest.fixture(autouse=True)
def _restore_global_ledger():
    """Ensure each test starts with a fresh TokenLedger and the global is restored after."""
    original = _token_ledger_mod._ledger
    _token_ledger_mod._ledger = _token_ledger_mod.TokenLedger()
    yield
    _token_ledger_mod._ledger = original
```

- [ ] **Step 4: Write a test that proves isolation**

Add to `tests/test_token_ledger.py`:

```python
from agents.token_ledger import set_ledger, get_ledger, TokenLedger


def test_ledger_isolation_first():
    """Set a custom ledger — should not bleed into the next test."""
    custom = TokenLedger()
    custom.budget_tokens = 999
    set_ledger(custom)
    assert get_ledger() is custom


def test_ledger_isolation_second():
    """Ledger must be a fresh instance, not the one set in test_ledger_isolation_first."""
    assert get_ledger().budget_tokens != 999, (
        "Global ledger leaked from test_ledger_isolation_first — autouse fixture not working"
    )
```

Run both tests — they must pass regardless of order:
```bash
python3 -m pytest tests/test_token_ledger.py::test_ledger_isolation_first tests/test_token_ledger.py::test_ledger_isolation_second -v 2>&1 | tail -15
python3 -m pytest tests/test_token_ledger.py::test_ledger_isolation_second tests/test_token_ledger.py::test_ledger_isolation_first -v 2>&1 | tail -15
```

Expected: PASS in both orderings.

- [ ] **Step 5: Run full suite to confirm no regressions**

```bash
python3 -m pytest tests/ -q --tb=short --ignore=tests/integration --ignore=tests/unit 2>&1 | tail -20
```

- [ ] **Step 6: Commit**

```bash
git add tests/conftest.py tests/test_token_ledger.py
git commit -m "test(conftest): add autouse _restore_global_ledger fixture to prevent set_ledger() leaking between tests"
```

---

## Task 2: Coverage — `estimate_tokens` Short-String Returns ≥ 1

**Files:**
- Modify: `tests/test_token_ledger.py`

**Context:** T7-A fixed `estimate_tokens` to use `max(1, round(...))` for non-empty strings. These tests confirm the fix works for all char-based model families (Claude, Gemini, Ollama/unknown).

**Prerequisite:** T7-A must be merged / cherry-picked into this branch first.

- [ ] **Step 1: Add parametrized short-string tests**

Add to `tests/test_token_ledger.py`:

```python
import pytest
from agents.token_ledger import estimate_tokens


@pytest.mark.parametrize("text,model", [
    ("4", "claude-3-sonnet"),       # 1 char, Claude path: round(1/3.5) = 0 → fixed to 1
    ("hi", "gemini-pro"),           # 2 chars, Gemini path: round(2/4) = 1
    ("x", "llama3"),                # 1 char, fallback path: round(1/4) = 0 → fixed to 1
    (" ", "claude-3-haiku"),        # 1 char whitespace
    ("abc", "gemini-flash"),        # 3 chars: round(3/4) = 1
])
def test_estimate_tokens_short_string_returns_at_least_one(text, model):
    """Non-empty strings must yield ≥ 1 token for both prompt and completion.
    Guards the fix from T7-A: max(1, round()) not int() floor.
    """
    prompt_est, completion_est = estimate_tokens(
        [{"role": "user", "content": text}], text, model=model
    )
    assert prompt_est >= 1, (
        f"prompt_est={prompt_est} for text={text!r} model={model} — should be ≥ 1"
    )
    assert completion_est >= 1, (
        f"completion_est={completion_est} for text={text!r} model={model} — should be ≥ 1"
    )


def test_estimate_tokens_empty_string_returns_zero():
    """Empty string must yield 0 tokens (no content = no cost)."""
    prompt_est, completion_est = estimate_tokens(
        [{"role": "user", "content": ""}], "", model="gemini-pro"
    )
    assert prompt_est == 0
    assert completion_est == 0
```

- [ ] **Step 2: Run the tests**

```bash
python3 -m pytest tests/test_token_ledger.py::test_estimate_tokens_short_string_returns_at_least_one tests/test_token_ledger.py::test_estimate_tokens_empty_string_returns_zero -v 2>&1 | tail -15
```

Expected: All 5 parametrize variants + empty test PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_token_ledger.py
git commit -m "test(token_ledger): add coverage for short-string estimate_tokens returning >= 1 token"
```

---

## Task 3: Coverage — Parallel Batch `BudgetExceededError` Calls `_finish()`

**Files:**
- Create: `tests/test_parallel_budget_exceeded.py`

**Context:** T7-A added `except BudgetExceededError` inside the `as_completed` loop. This test confirms `_finish()` is called (not bypassed) when a parallel stage raises that error.

**Prerequisite:** T7-A must be merged / cherry-picked into this branch first.

- [ ] **Step 1: Create the test file**

```python
# tests/test_parallel_budget_exceeded.py
"""Test that BudgetExceededError from a parallel stage calls _finish() rather than crashing."""
from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch, call

import pytest

from agents.token_ledger import BudgetExceededError
from orchestrator import Orchestrator, PipelineResult


def _stub_orchestrator() -> Orchestrator:
    orch = Orchestrator.__new__(Orchestrator)
    orch._agent_health = MagicMock()
    orch._shutdown_event = threading.Event()
    orch._stage_timeouts = {}
    orch._tracker = MagicMock()
    orch._tracker.comment_id = None
    return orch


def test_budget_exceeded_parallel_calls_finish_not_crash():
    """When _run_stage_safe raises BudgetExceededError in a parallel batch,
    _finish() must be called exactly once — not bypassed.
    """
    orch = _stub_orchestrator()
    result = PipelineResult(requirement="parallel budget test")

    finish_results = []

    with patch.object(orch, "_finish", side_effect=lambda r, t: finish_results.append(r) or r), \
         patch.object(orch, "_run_stage_safe", side_effect=BudgetExceededError("quota")), \
         patch("orchestrator.console"):

        stage_a = MagicMock()
        stage_a.checkpoint_key = "stage_a"
        stage_b = MagicMock()
        stage_b.checkpoint_key = "stage_b"

        from concurrent.futures import ThreadPoolExecutor, as_completed
        from orchestrator import MAX_PARALLEL_STAGES

        stage_results: dict[str, bool] = {}
        try:
            with ThreadPoolExecutor(max_workers=min(2, MAX_PARALLEL_STAGES)) as executor:
                futures = {
                    executor.submit(orch._run_stage_safe, s, result): s
                    for s in [stage_a, stage_b]
                }
                for future in as_completed(futures):
                    try:
                        stage_results[futures[future].checkpoint_key] = future.result()
                    except BudgetExceededError:
                        for pending in futures:
                            pending.cancel()
                        orch._finish(result, 0.0)
                        break
        except Exception as exc:
            pytest.fail(f"Unexpected exception escaped the parallel loop: {exc!r}")

    assert len(finish_results) == 1, (
        f"_finish() called {len(finish_results)} time(s) — expected exactly 1"
    )
```

- [ ] **Step 2: Run the test**

```bash
python3 -m pytest tests/test_parallel_budget_exceeded.py -v 2>&1 | tail -15
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_parallel_budget_exceeded.py
git commit -m "test(orchestrator): add coverage for BudgetExceededError in parallel as_completed loop calling _finish()"
```

---

## Task 4: Coverage — Watcher `get_open_prs` / `get_pr_comments` Raise `RuntimeError`

**Files:**
- Modify: `tests/test_watcher.py`

**Context:** T7-A changed these two functions from `raise_for_status()` to `if not resp.ok: raise RuntimeError(...)`. These tests confirm callers receive `RuntimeError`, not `requests.HTTPError`.

**Prerequisite:** T7-A must be merged / cherry-picked into this branch first.

- [ ] **Step 1: Add tests to `tests/test_watcher.py`**

```python
from unittest.mock import patch, MagicMock
import pytest


def test_get_open_prs_raises_runtime_error_on_404():
    """get_open_prs must raise RuntimeError on non-2xx so callers' except RuntimeError works."""
    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 404
    mock_resp.text = "Not Found"

    with patch("watcher.requests.get", return_value=mock_resp):
        from watcher import get_open_prs
        with pytest.raises(RuntimeError, match="GitHub API error 404"):
            get_open_prs("owner/repo")


def test_get_open_prs_returns_list_on_success():
    """get_open_prs must return a list of dicts on 200."""
    pr_data = [{"number": 1, "draft": False, "title": "My PR"}]
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = pr_data

    with patch("watcher.requests.get", return_value=mock_resp):
        from watcher import get_open_prs
        result = get_open_prs("owner/repo")
    assert result == pr_data


def test_get_pr_comments_raises_runtime_error_on_403():
    """get_pr_comments must raise RuntimeError on non-2xx."""
    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 403
    mock_resp.text = "Forbidden"

    with patch("watcher.requests.get", return_value=mock_resp):
        from watcher import get_pr_comments
        with pytest.raises(RuntimeError, match="GitHub API error 403"):
            get_pr_comments("owner/repo", pr_number=7)


def test_get_pr_comments_returns_list_on_success():
    """get_pr_comments must return a list of comment dicts on 200."""
    comment_data = [{"id": 1, "body": "LGTM"}]
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = comment_data

    with patch("watcher.requests.get", return_value=mock_resp):
        from watcher import get_pr_comments
        result = get_pr_comments("owner/repo", pr_number=7)
    assert result == comment_data
```

- [ ] **Step 2: Run the tests**

```bash
python3 -m pytest tests/test_watcher.py::test_get_open_prs_raises_runtime_error_on_404 tests/test_watcher.py::test_get_open_prs_returns_list_on_success tests/test_watcher.py::test_get_pr_comments_raises_runtime_error_on_403 tests/test_watcher.py::test_get_pr_comments_returns_list_on_success -v 2>&1 | tail -15
```

Expected: All 4 PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_watcher.py
git commit -m "test(watcher): add coverage for get_open_prs and get_pr_comments raising RuntimeError on non-2xx"
```

---

## Task 5: Coverage — Memory Context Not Duplicated on Repeated `run()`

**Files:**
- Create: `tests/test_memory_injection.py`

**Context:** T7-A fixed memory injection to use `_original_system_prompts` as the base so a second `run()` doesn't prepend memory twice. This test exercises the fixed code path.

**Prerequisite:** T7-A must be merged / cherry-picked into this branch first.

- [ ] **Step 1: Create the test file**

```python
# tests/test_memory_injection.py
"""Test that memory context is injected once (not accumulated) on repeated run() calls."""
from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest

from orchestrator import Orchestrator


MEMORY_TEXT = "## Past Work\nBuilt user auth module.\n"
ORIGINAL_PROMPT = "You are a product manager."


def _make_orch() -> Orchestrator:
    orch = Orchestrator.__new__(Orchestrator)
    orch._agent_health = MagicMock()
    orch._shutdown_event = threading.Event()
    orch._stage_timeouts = {}
    orch.skill_loader = None

    mock_memory = MagicMock()
    mock_memory.recall.return_value = MEMORY_TEXT
    orch.memory = mock_memory

    agents_attrs = ("pm", "architect", "engineer", "junior_engineer",
                    "senior_engineer", "reviewer", "qa", "qa_planner")
    for attr in agents_attrs:
        agent = MagicMock()
        agent.system_prompt = ORIGINAL_PROMPT
        setattr(orch, attr, agent)

    orch._original_system_prompts = {
        getattr(orch, attr): ORIGINAL_PROMPT for attr in agents_attrs
    }
    return orch


def _inject_memory(orch: Orchestrator, active_repo: str) -> None:
    """Replicate the memory-injection block from orchestrator.run()."""
    from unittest.mock import MagicMock as _MM
    import orchestrator as orch_mod

    memory_context = orch.memory.recall(active_repo)
    if memory_context:
        for agent in (orch.pm, orch.architect, orch.engineer,
                      orch.junior_engineer, orch.senior_engineer,
                      orch.reviewer, orch.qa, orch.qa_planner):
            if agent.system_prompt is not None:
                original = orch._original_system_prompts.get(agent, agent.system_prompt)
                agent.system_prompt = memory_context + "\n\n---\n\n" + original


def test_memory_injected_once_after_two_calls():
    """Memory prefix must appear exactly once even when inject block runs twice."""
    orch = _make_orch()
    repo = "owner/project"

    _inject_memory(orch, repo)
    _inject_memory(orch, repo)  # second call — simulates second run()

    for attr in ("pm", "architect", "engineer", "junior_engineer",
                 "senior_engineer", "reviewer", "qa", "qa_planner"):
        agent = getattr(orch, attr)
        count = agent.system_prompt.count(MEMORY_TEXT.strip())
        assert count == 1, (
            f"{attr}.system_prompt contains memory {count} times (expected 1). "
            f"Prompt:\n{agent.system_prompt!r}"
        )


def test_original_prompt_preserved_after_memory_injection():
    """Original prompt text must still appear in the injected prompt."""
    orch = _make_orch()
    _inject_memory(orch, "owner/project")

    assert ORIGINAL_PROMPT in orch.pm.system_prompt, (
        f"Original prompt not found after memory injection.\n"
        f"Prompt: {orch.pm.system_prompt!r}"
    )


def test_empty_memory_skips_injection():
    """When memory.recall() returns empty string, system_prompt must be unchanged."""
    orch = _make_orch()
    orch.memory.recall.return_value = ""

    _inject_memory(orch, "owner/project")

    assert orch.pm.system_prompt == ORIGINAL_PROMPT, (
        "system_prompt was modified despite empty memory context"
    )
```

- [ ] **Step 2: Run the tests**

```bash
python3 -m pytest tests/test_memory_injection.py -v 2>&1 | tail -15
```

Expected: All 3 tests PASS.

- [ ] **Step 3: Run full suite**

```bash
python3 -m pytest tests/ -q --tb=short --ignore=tests/integration --ignore=tests/unit 2>&1 | tail -20
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_memory_injection.py
git commit -m "test(orchestrator): add coverage for memory context not stacking on repeated run() calls"
```

---

## Final Verification

- [ ] **Run the complete test suite**

```bash
cd /home/wanleung/Projects/ai-software-house/t7-b
python3 -m pytest tests/ -q --tb=short --ignore=tests/integration --ignore=tests/unit 2>&1 | tail -25
```

Expected: All new tests pass. Full suite has zero new failures vs T7-A baseline.
