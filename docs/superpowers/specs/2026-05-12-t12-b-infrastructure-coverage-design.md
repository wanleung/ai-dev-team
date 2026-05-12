# T12-B Design: Infrastructure Coverage — github_client, check.py, Doc Pipeline, Orchestrator run()

**Date:** 2026-05-12
**Branch:** `t12-b-infrastructure-coverage`
**PR target:** `master`

---

## Problem Statement

Four infrastructure areas have significant untested code paths:

| Area | Coverage | Key gaps |
|---|---|---|
| `github_client.py` | 62% | PR read methods, `get_full_tree`, `merge_base_into_branch` 409 path |
| `check.py` | 41% | `validate_config` schema checks, `test_github` error paths |
| Doc pipeline stages | ~0% | `_stage_doc_generate`, `_stage_doc_commit_pr` never exercised |
| `orchestrator.py run()` | ~66% | Real multi-stage dispatch path never tested |

The orchestrator gap (H2) is the highest risk: stage ordering, context propagation, and checkpoint save/resume are all unvalidated in CI.

---

## Task 1: `github_client.py` PR/Tree API Coverage

**File:** `tests/test_github_client_extended.py` (new, or add to existing `test_github_client.py`)

All tests use `responses` library (already a test dependency) to mock HTTP calls.

**PR read methods:**

1. `test_get_pr_review_comments` — mock GET `/repos/{owner}/{repo}/pulls/{pr}/comments`; verify returns list of comment dicts with `body`, `path`, `line`
2. `test_get_pr_reviews` — mock GET `/repos/{owner}/{repo}/pulls/{pr}/reviews`; verify returns list with `state` field
3. `test_get_pr_files` — mock GET `/repos/{owner}/{repo}/pulls/{pr}/files`; verify returns list with `filename` and `patch`

**Tree/content methods:**

4. `test_get_file_content_returns_decoded` — mock GET content endpoint with base64-encoded body; verify decoded string returned
5. `test_get_file_content_not_found_raises` — 404 response; verify `FileNotFoundError` or equivalent raised
6. `test_get_full_tree_returns_flat_list` — mock recursive tree endpoint; verify flat list of file paths returned
7. `test_get_full_tree_handles_truncated_response` — `truncated: true` in response; verify warning logged

**Merge/conflict path:**

8. `test_merge_base_into_branch_success` — mock MERGE endpoint returns 201; verify returns merge commit SHA
9. `test_merge_base_into_branch_conflict_409` — mock returns 409; verify raises `MergeConflictError` (or whatever exception the implementation uses — check source)
10. `test_search_files_returns_matches` — mock code search endpoint; verify returns list of file paths

---

## Task 2: `check.py` Validation Coverage

**File:** `tests/test_check_extended.py` (new, or add to existing `test_check.py`)

Use `click.testing.CliRunner` for CLI invocation.

**`validate_config` command:**

1. `test_validate_config_valid_file` — pass a well-formed repos config; assert exit code 0 and success message
2. `test_validate_config_missing_required_field` — config missing required key; assert exit code non-zero and error mentions missing field
3. `test_validate_config_invalid_yaml` — malformed YAML; assert exit code non-zero
4. `test_validate_config_file_not_found` — non-existent path; assert exit code non-zero

**`test_github` command:**

5. `test_test_github_success` — mock `GithubClient` to return successfully; assert exit code 0 and "connected" in output
6. `test_test_github_auth_failure` — mock raises `401 Unauthorized`; assert exit code non-zero and error message shown
7. `test_test_github_network_error` — mock raises `ConnectionError`; assert exit code non-zero

**Error reporting:**

8. `test_validate_config_shows_field_path_in_error` — error message includes the dotted path of the failing field, not just "invalid"

---

## Task 3: Documentation Pipeline Stage Tests

**File:** `tests/test_doc_orchestrator.py` (new)

Tests exercise `Orchestrator._stage_doc_generate()` and `Orchestrator._stage_doc_commit_pr()` directly, with `DocumentationAgent` mocked.

**Setup fixture:**
```python
@pytest.fixture
def doc_orch(tmp_path, monkeypatch):
    orch = Orchestrator(workspace_dir=str(tmp_path), ...)
    monkeypatch.setattr("orchestrator.DocumentationAgent", MockDocAgent)
    return orch
```

**Tests:**

1. `test_stage_doc_generate_calls_agent` — calls `_stage_doc_generate(context)`; verify `DocumentationAgent.run()` was called with context containing the spec text
2. `test_stage_doc_generate_returns_doc_content` — mock agent returns doc string; verify stage returns it in context
3. `test_stage_doc_generate_handles_agent_failure` — mock agent raises; verify stage propagates or wraps the exception (per actual implementation)
4. `test_stage_doc_commit_pr_creates_pr` — mock `GithubClient.create_pr()`; call `_stage_doc_commit_pr(context)`; verify PR created with correct branch name and body
5. `test_stage_doc_commit_pr_commits_files` — verify doc files are committed to the PR branch before PR creation
6. `test_stage_doc_commit_pr_skips_on_no_docs` — if stage context has no generated docs, no PR created

---

## Task 4: Orchestrator `run()` Functional Test

**File:** `tests/test_orchestrator_run_functional.py` (new)

**Approach:** Parametrised functional test — mock LLM backend and GitHub calls; exercise real stage dispatch through `Orchestrator.run()` with a minimal pipeline.

**Pipeline under test:** A 2-stage pipeline `[pm, architect]` loaded from a temporary YAML:
```yaml
pipeline:
  - stage: pm
  - stage: architect
```

**Fixtures:**
- `mock_llm_backend(monkeypatch)` — patches `BaseAgent._call_backend` to return a fixed string without real HTTP
- `mock_github(monkeypatch)` — patches `GithubClient` to return a mock issue, mock repo, and accept commits/PRs
- `functional_orchestrator(tmp_path, mock_llm_backend, mock_github)` — `Orchestrator` constructed with `workspace_dir=str(tmp_path)` and a real but minimal pipeline config

**Tests:**

1. `test_run_executes_stages_in_order`
   - Run the 2-stage pipeline
   - Assert: PM stage executed first, architect stage second (verify via call order on mocked backend or context keys set sequentially)

2. `test_run_propagates_context_between_stages`
   - PM stage returns context with key `pm_output`
   - Assert: architect stage receives a prompt containing `pm_output` value

3. `test_run_checkpoint_save_and_resume`
   - Run pipeline; interrupt after PM stage (raise in architect mock on first call)
   - Verify checkpoint file written with PM output
   - Reconstruct orchestrator from checkpoint; run again (architect mock succeeds on second call)
   - Assert: PM stage NOT re-run (loaded from checkpoint); architect stage completes with PM context intact

4. `test_run_raises_on_stage_failure`
   - Mock architect to raise `RuntimeError`
   - Assert: `Orchestrator.run()` propagates the error (does not silently swallow)

5. `test_run_clarification_needed_pauses_pipeline`
   - Mock PM stage to raise `ClarificationNeeded("What is the budget?", ["< $1k", "> $1k"])`
   - Assert: orchestrator sets issue label `agent-waiting`; pipeline does not proceed to architect stage
   - Assert: clarification data written to trigger file

---

## Task 5: Final Verification

- Run each new test file in isolation: all pass
- Run full suite: 0 failures, no new warnings
- Verify `orchestrator.py` coverage increase with `pytest --cov=orchestrator --cov-report=term-missing tests/test_orchestrator_run_functional.py`

---

## Acceptance Criteria

- [ ] `github_client.py` PR read + tree + merge conflict path all have passing tests
- [ ] `check.py` `validate_config` + `test_github` paths tested end-to-end via CLI runner
- [ ] `_stage_doc_generate` and `_stage_doc_commit_pr` exercised via mocked `DocumentationAgent`
- [ ] `Orchestrator.run()` functional test covers stage ordering, context propagation, checkpoint save/resume, failure propagation, and `ClarificationNeeded` pausing
- [ ] Full suite: 0 failures
