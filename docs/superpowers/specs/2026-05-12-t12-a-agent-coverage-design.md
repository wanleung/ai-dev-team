# T12-A Design: Core Agent Class Coverage + Memory Store

**Date:** 2026-05-12
**Branch:** `t12-a-agent-coverage`
**PR target:** `master`

---

## Problem Statement

Seven core agents have critically low test coverage, with reviewer agents at 19–27%:

| Agent | Current Coverage | Risk |
|---|---|---|
| `agents/deployment_tester.py` | 19% | Deploy test loop completely blind |
| `agents/architect_reviewer.py` | 21% | Review verdict path untested |
| `agents/pm_reviewer.py` | 27% | PRD revision trigger untested |
| `agents/qa_planner.py` | 39% | Test plan generation blind |
| `agents/memory_bank_updater.py` | 46% | Memory write path untested |
| `agents/code_reviewer.py` | 47% | Review tool-call paths missing |
| `agents/senior_engineer.py` | 50% | Context injection from junior missing |

Additionally, `memory_store.py` sits at 44% coverage and uses the deprecated `datetime.utcnow()` (produces `DeprecationWarning` in test output).

---

## Approach

All agents extend `BaseAgent`. Tests mock the LLM backend via `agents/backends/` so no real HTTP is made. Key paths to cover per agent:

1. **Verdict path** (reviewer agents) — `VERDICT_APPROVED` vs `VERDICT_REVISION` in parsed LLM output → correct return value / exception raised
2. **Tool-call dispatch** — agents that call tools (e.g. `deployment_tester` running test commands) have the tool path exercised
3. **Context injection** — `senior_engineer` receives context from `junior_engineer` output
4. **Memory write** — `memory_bank_updater` serialises and writes to `memory_store`

---

## Task 1: Reviewer Agent Tests

**Files:** `tests/test_architect_reviewer.py`, `tests/test_pm_reviewer.py`, `tests/test_code_reviewer.py` (new)

For each reviewer agent, write tests covering:

**`test_<agent>_returns_approved_on_approval_verdict`**
- Mock LLM response contains `VERDICT: APPROVED` (or equivalent)
- Assert: `run()` / `review()` returns approved result without raising

**`test_<agent>_raises_on_revision_verdict`**
- Mock LLM response contains `VERDICT: REVISION`
- Assert: appropriate exception or revision-flagging return value

**`test_<agent>_includes_context_in_prompt`**
- Verify that the input context (e.g. PRD text, code diff) appears in the constructed prompt sent to the LLM backend mock

**`test_<agent>_handles_malformed_llm_response`**
- Mock LLM returns a response with no verdict marker
- For `ArchitectReviewer`: assert returns `VERDICT_SUGGESTIONS` (the safe default per source)
- For `PMReviewer`/`CodeReviewer`: assert returns their respective safe default (check source)

Reviewer agents: `ArchitectReviewer`, `PMReviewer`, `CodeReviewer`.

---

## Task 2: Execution Agent Tests

**Files:** `tests/test_deployment_tester.py`, `tests/test_qa_planner.py`, `tests/test_memory_bank_updater.py`, `tests/test_senior_engineer.py` (new)

**`deployment_tester.py` (19%)**
- `test_deployment_tester_runs_test_command` — mock subprocess call; verify test command is executed and output is returned
- `test_deployment_tester_returns_failure_on_nonzero_exit` — mock subprocess returning exit code 1; verify failure is communicated
- `test_deployment_tester_passes_workspace_to_command` — verify workspace path is included in command args

**`qa_planner.py` (39%)**
- `test_qa_planner_returns_test_plan` — mock LLM response with a test plan structure; verify it's parsed and returned
- `test_qa_planner_includes_spec_in_prompt` — spec content appears in prompt
- `test_qa_planner_handles_empty_llm_response` — graceful handling

**`memory_bank_updater.py` (46%)**
- `test_memory_bank_updater_writes_to_store` — mock `memory_store.write()`; verify called with correct entry
- `test_memory_bank_updater_includes_agent_output_in_entry` — entry contains agent output text
- `test_memory_bank_updater_handles_store_write_failure` — store raises; verify logged and not re-raised (or re-raised, per actual behaviour)

**`senior_engineer.py` (50%)**
- `test_senior_engineer_injects_junior_context` — junior output is present in the prompt built for LLM
- `test_senior_engineer_returns_merged_output` — verify final result combines senior + junior contribution
- `test_senior_engineer_handles_missing_junior_context` — no junior context provided → sensible default

---

## Task 3: `memory_store.py` Coverage + `utcnow()` Fix

**File:** `memory_store.py`

**Fix:** Replace all `datetime.utcnow()` calls with `datetime.now(timezone.utc)` (add `from datetime import timezone` if not present). This removes the `DeprecationWarning` from test output.

**File:** `tests/test_memory_store.py` (new or expand existing)

Cover the currently-untested methods (lines 80, 149–199, 213–260, 288–360+):

1. `test_write_and_read_entry` — write an entry; `get(id)` returns it with correct fields
2. `test_search_by_keyword` — write 3 entries; `search("keyword")` returns only matching ones
3. `test_consolidate_old_memories` — write 10 entries; consolidation reduces count or merges; verify result is still readable
4. `test_sqlite_backend_persistence` — with SQLite backend, write entry, reconstruct `MemoryStore`, read back
5. `test_file_backend_roundtrip` — with file backend, write entry, verify file exists, read back
6. `test_write_failure_propagates_or_logs` — backend raises on write; verify behaviour matches actual implementation

---

## Task 4: Final Verification

- Run `pytest tests/test_architect_reviewer.py tests/test_pm_reviewer.py tests/test_code_reviewer.py tests/test_deployment_tester.py tests/test_qa_planner.py tests/test_memory_bank_updater.py tests/test_senior_engineer.py tests/test_memory_store.py -v`
- Run full suite: 0 failures, `DeprecationWarning` for `utcnow` eliminated

---

## Acceptance Criteria

- [ ] All 7 agents have test coverage for verdict/result path, context injection, and error handling
- [ ] `memory_store.py` covered for read, write, search, consolidate, both backends
- [ ] `datetime.utcnow()` replaced with `datetime.now(timezone.utc)` throughout `memory_store.py`
- [ ] No `DeprecationWarning` from datetime in test output
- [ ] Full suite: 0 failures
