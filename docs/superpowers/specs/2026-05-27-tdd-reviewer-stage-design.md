# TDD Reviewer Stage — Design Spec

**Date:** 2026-05-27  
**Status:** Approved  
**Scope:** ai-software-house — TDD pipeline only

---

## Problem

When `QAEngineerAgent` writes test files in TDD mode, those tests can contain correctness problems (direct conftest imports, `MockModel` defined in the wrong scope, bad import paths) and quality problems (missing coverage of PRD requirements, trivially-true tests). These problems are only discovered when the test-fix loop runs, exhausting all retry attempts before a human has to intervene.

Root cause of the cue-test PR #3 failure: tests did `from conftest import MockModel` but pytest resolved `conftest` to the root `conftest.py` which had no `MockModel`. A reviewer reading the test files against a known pytest model would have caught this immediately.

---

## Solution

Add a **TDD Reviewer stage** between `qa_write` (test file generation) and `test_fix` (test execution). The reviewer uses an LLM to read the generated test files alongside the PRD and fix both correctness and quality issues before tests are committed or run.

---

## Architecture

### Pipeline Position

```
qa_planner → qa_write → [tdd_review] → test_fix → validation_gate
```

The `tdd_review` stage only runs when `result.test_files` is non-empty (same guard as `test_fix`).

### New Agent: `TDDReviewerAgent`

**File:** `agents/tdd_reviewer.py`  
**Base class:** `BaseAgent`

**Responsibilities:**
- Receive: `test_files: dict[str, str]`, `prd: str`, `project_name: str`
- Perform a two-pass LLM review (single LLM call combining both passes)
- Return: revised `test_files` dict + `review_summary: str`

**Two-pass review in one LLM call:**

1. **Correctness pass** — the LLM checks for:
   - `from conftest import X` — direct imports from conftest; utility classes/helpers must live in `conftest.py` at the root, not imported directly
   - `MockModel` or similar helpers defined in `tests/conftest.py` but used via root-level `from conftest import` — move to root conftest
   - Syntax errors (already caught by `_fix_syntax_errors` in `QAEngineerAgent`, but re-validated here as a guard)
   - Import paths assuming a specific directory layout that may not match the generated project structure (e.g. `from app.main import app` when no `app/main.py` is guaranteed)

2. **Quality pass** — the LLM checks against the PRD for:
   - Missing coverage: are all major features/endpoints in the PRD covered by at least one test?
   - Trivially-true tests: `assert True`, `assert response is not None` with no status check, etc.
   - Happy-path-only tests: every feature should have at least one error/edge-case test
   - Fixture misuse: tests that create their own mocks inline instead of using shared conftest fixtures

**Output format:** the LLM responds with revised `### FILE:` blocks (same format as `QAEngineerAgent`) plus a `### REVIEW SUMMARY:` section. The agent parses both.

**Retry:** if revised files still have syntax errors (checked via `ast.parse`), one retry with the syntax error details appended.

**Never blocks:** if the LLM fails or the retry fails, the original test files are returned with a warning log. Progress > perfection.

### New Pipeline Stage: `tdd_review`

**Added to:** `_build_engineering_stages_test()` in `orchestrator.py`

```python
stages["tdd_review"] = PipelineStage(
    name="tdd_review",
    label="🔬 TDD Reviewer",
    description="Reviewing test files for correctness and PRD coverage...",
    checkpoint_key="tdd_review",
    fn=lambda r: self._stage_tdd_review(r),
    skip_if=lambda r: not r.test_files,
)
```

Inserted **after** `qa_write` and **before** `test_fix`.

### New `_stage_tdd_review()` Method

```python
def _stage_tdd_review(self, result: PipelineResult) -> None:
    revised_files, summary = self.tdd_reviewer.run(
        result.test_files, result.prd or "", result.project_name
    )
    result.test_files = revised_files
    result.tdd_review_summary = summary
    # Re-save locally so test_fix picks up the revised files
    self._save_files_locally(result.test_files, result.project_name)
    # If tdd_commit_tests, update the already-opened branch with revised files
    if self.tdd_commit_tests and result.branch and (self.target_github or self.github):
        self._update_tdd_branch_with_reviewed_files(result)
```

### New `PipelineResult` Field

`tdd_review_summary: str = ""` — stored in checkpoint JSON, included in the TDD PR body as a collapsible `<details>` block so engineers can see what the reviewer changed.

### `TDDReviewerAgent` — Agent Instantiation

The orchestrator creates `self.tdd_reviewer = TDDReviewerAgent(...)` alongside `self.qa` in `_init_agents()`. Uses the same model/backend as the QA engineer (inherits from `BaseAgent` so model routing works automatically).

---

## Prompt Design

The LLM prompt structure:

```
You are a senior Python test engineer reviewing TDD test files before implementation begins.

## Project: {project_name}
## PRD:
{prd}

## Test Files to Review:
{test_files_formatted}

## Your Task
Perform TWO passes:

### Pass 1 — Correctness
Fix any issues that would prevent pytest from running:
- `from conftest import X` patterns: if X is a class/helper (not a fixture), 
  add it to the root conftest.py instead of tests/conftest.py
- Import paths that assume app structure not guaranteed by the PRD
- Any syntax errors

### Pass 2 — Quality  
Check coverage against the PRD:
- Every major feature/endpoint should have at least one test
- Every test should have a meaningful assertion (not just `assert True`)
- Every feature should have at least one error/edge-case test
- Add missing tests where needed

## Output Format
First output all files using ### FILE: format (including conftest.py if changed).
Then output:

### REVIEW SUMMARY:
- Correctness fixes: [list what was fixed]
- Quality additions: [list what was added/improved]
- Remaining concerns: [anything the engineer should know]
```

---

## Data Flow

```
qa_write result.test_files
       ↓
TDDReviewerAgent.run(test_files, prd, project_name)
       ↓ (single LLM call + optional retry)
revised_test_files, review_summary
       ↓
result.test_files = revised_test_files          (overwrite)
result.tdd_review_summary = review_summary      (new field)
_save_files_locally(revised_test_files)         (overwrite local disk)
       ↓
test_fix stage (runs pytest against revised files)
```

---

## Error Handling

| Scenario | Behaviour |
|----------|-----------|
| LLM call fails | Log warning, return original `test_files`, empty summary |
| Revised files have syntax errors | Retry once with error details; if still failing, return original |
| LLM returns no `### FILE:` blocks | Log warning, return original |
| `tdd_review_summary` missing from LLM response | Store empty string, continue |
| `tdd_commit_tests=true` branch update fails | Log warning, continue (tests still run locally) |

---

## Files Changed

| File | Change |
|------|--------|
| `agents/tdd_reviewer.py` | New file — `TDDReviewerAgent` class |
| `orchestrator.py` | Add `tdd_review` stage, `_stage_tdd_review()`, `tdd_reviewer` agent init, `tdd_review_summary` field on `PipelineResult` |

No changes to `qa_engineer.py`, `engineer.py`, or any existing agent.

---

## Out of Scope

- Reviewing implementation code (that's `CodeReviewerAgent`)
- Blocking the pipeline if coverage is insufficient (advisory only; auto-fix only)
- Running the tests during review (that's `test_fix`)
- Supporting non-TDD pipelines (quality-after-implementation path uses existing `qa_engineer` stage)
