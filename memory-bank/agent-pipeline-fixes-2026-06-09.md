# Agent Pipeline Fixes — 2026-06-09

## What Changed
- Hardened generated pytest validation for TDD pipeline output.
- Added `tools/test_validation.py` checks for forbidden `conftest.py` imports.
- Extended the validator to catch direct calls to pytest fixtures defined in generated `tests/conftest.py`.
- Updated QA Engineer and TDD Reviewer agents to retry once when generated tests violate deterministic pytest rules.
- Updated QA/TDD role prompts to require helpers in `tests/helpers.py`, fixtures as pytest parameters, and no direct fixture calls.
- Updated the orchestrator test stage to run `pytest --collect-only -q` before full pytest and comment collection failures on PRs.
- Updated PR revision wording to "Pushed" and clarified that watcher revisions do not prove tests passed.
- Updated EngineerAgent's test-fix prompt so generated test files can be modified only when pytest failures show invalid generated tests; normal app-code failures still keep tests locked.

## Diagnosis
- The failing `wanleung/q-test` PR #2 is not only a model-strength issue.
- Current generated tests contain invalid pytest patterns such as `from tests.conftest import ...`, `from conftest import ...`, and direct fixture calls like `make_user(...)` / `configure_db(...)`.
- Local validation of the generated q-test workspace found 56 deterministic generated-test issues.
- After collection issues are fixed, some remaining failures are real app/auth/dependency behavior failures.

## Verification
- `pytest tests/test_engineer_fix.py tests/test_generated_test_validation.py tests/test_pipeline_modes.py tests/test_revision.py tests/test_tdd_reviewer.py tests/test_qa_planner_engineer.py tests/test_test_fix_loop.py tests/test_after_write_integration.py tests/test_validate_function_sizes.py -q`
- Result: `138 passed`
- `ruff check agents/engineer.py tools/test_validation.py tests/test_generated_test_validation.py tests/test_engineer_fix.py`
- Result: passed

## Notes
- Updated agents: QA Engineer, TDD Reviewer, EngineerAgent.
- Updated role prompts: `roles/qa_engineer.md`, `roles/tdd_reviewer.md`.
- No skill files were changed in this commit.
