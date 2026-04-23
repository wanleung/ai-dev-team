# Test & Deploy Retry Loop — Design Spec
_Date: 2026-04-21_

## Problem

When the pipeline runs tests (unit or deployment), failures are reported but the pipeline
stops. There is no automatic feedback loop to send failures back to the engineer for
targeted fixes. A human must manually inspect failures, fix code, and re-run — defeating
the purpose of an automated software house.

## Proposed Solution

Add an automatic retry loop: on test failure, the engineer agent is called with the
failure output and all current project files, produces targeted patches, and the tests
are re-run. This repeats up to `max_test_retries` times (configurable, default 5). If
all retries are exhausted, the current state is committed and a human-review flag is
posted on the PR.

The same loop applies to deployment smoke tests, but only if unit tests have already
passed (no point fixing docker issues if the app code is broken).

---

## Architecture

### 1. `EngineerAgent.fix_failures()` — New method

**Location:** `agents/engineer.py`

**Signature:**
```python
def fix_failures(
    self,
    failure_output: str,
    all_files: dict[str, str],      # {filepath: content} — all files currently on disk
    design: str,
    project_name: str = "Project",
    framework_context: str = "",
) -> dict[str, str]:
    """Produce targeted code fixes for failing tests.

    Returns: {filepath: content} of files that need to be created or overwritten.
    Only files that need to change should be returned; unchanged files may be omitted.
    """
```

**Prompt design:**
- Prepends framework context section if present (same as `run_module`)
- Provides the full failure output verbatim
- Provides ALL current project files, formatted as `## File: {path}\n\n{content}`
- Instructions: "Read the test failure output carefully. Identify the root cause.
  Fix ONLY the broken code files. Return the fixed files using the same
  `## File: path` block format. Do not return files that don't need to change."
- Parses the response with the existing `_parse_files()` static method

**Returns:** `dict[str, str]` — `{filepath: new_content}`. May be a subset of all files
(only patched files). If the LLM returns nothing parseable, returns `{}`.

---

### 2. `_stage_test_fix_loop()` — New orchestrator method

**Location:** `orchestrator.py`

**Signature:**
```python
def _stage_test_fix_loop(self, result: PipelineResult) -> None:
```

**Behaviour:**
1. Run `_stage_test_runner(result)` for the first attempt.
2. If `result.tests_passed is True` → return immediately (no retry needed).
3. For `attempt` in `range(1, max_test_retries + 1)`:
   a. Log: `"🔁 Test fix attempt {attempt}/{max_test_retries}…"`
   b. Collect `all_files` by reading every file under `project_dir` (recursively, skipping
      `.git/`, `__pycache__/`, `*.pyc`, `node_modules/`).
   c. Call `self.engineer.fix_failures(failure_output=result.test_results, all_files=all_files, design=result.design, project_name=result.project_name, framework_context=…)`.
   d. If the returned patch dict is empty → log warning and break (LLM couldn't fix).
   e. Write patched files to `project_dir` (overwrite).
   f. `git add -A && git commit -m "fix(auto): test retry {attempt}/{max_test_retries}"` on
      the PR branch. If `target_github` is set, push.
   g. Append summary to `result.test_fix_history`: `"Attempt {attempt}: {n} files patched"`.
   h. Increment `result.test_retry_count`.
   i. Re-run `_stage_test_runner(result)`.
   j. If `result.tests_passed is True` → log success and return.
4. If loop exhausted and still failing:
   - Log: `"⚠️ All {max_test_retries} fix attempts failed."`
   - If `target_github` and `result.pr_number` set, post PR comment:
     ```
     ## ⚠️ Automatic Test Fix Exhausted
     After {n} attempts, tests are still failing. Human review required.

     ### Fix History
     - Attempt 1: 3 files patched
     - Attempt 2: 2 files patched
     ...

     ### Final Failure Output
     ```{output}```
     ```

---

### 3. `_stage_deploy_fix_loop()` — New orchestrator method

**Location:** `orchestrator.py`

**Same pattern as `_stage_test_fix_loop`** but:
- Runs `_stage_deploy_test_runner(result)` instead of `_stage_test_runner`
- Uses `result.deploy_tests_passed`, `result.deploy_test_results`, `result.deploy_retry_count`, `result.deploy_fix_history`
- Uses `max_deploy_retries` from config
- Only called if `result.tests_passed is True` (unit tests must pass first)

---

### 4. Pipeline wiring

**Replace in `run()`:**
```python
# Before (Stage 6):
self._run_stage("🏃 Test Runner", "Executing tests...", result, lambda: self._stage_test_runner(result))

# After:
self._run_stage("🏃 Test Runner + Fix Loop", "Executing tests (with auto-fix)...", result, lambda: self._stage_test_fix_loop(result))
```

```python
# Before (Stage 8):
self._run_stage("🐳 Deploy Test Runner", "Running docker smoke tests...", result, lambda: self._stage_deploy_test_runner(result))

# After:
self._run_stage("🐳 Deploy Test Runner + Fix Loop", "Running deployment tests (with auto-fix)...", result, lambda: self._stage_deploy_fix_loop(result))
```

The `completed_stages` checkpoint keys remain `"test_runner"` and `"deploy_test_runner"` (no breaking change to existing checkpoints).

---

### 5. `PipelineResult` additions

```python
test_retry_count: int = 0
test_fix_history: list[str] = field(default_factory=list)
deploy_retry_count: int = 0
deploy_fix_history: list[str] = field(default_factory=list)
```

Serialised in `to_dict()` under `"test_retry_count"`, `"test_fix_history"`,
`"deploy_retry_count"`, `"deploy_fix_history"`.

---

### 6. `config.yaml` additions

```yaml
pipeline:
  # ... existing keys ...

  # Maximum number of automatic engineer fix attempts when tests fail.
  # Set to 0 to disable the retry loop.
  max_test_retries: 5

  # Maximum automatic fix attempts for deployment smoke test failures.
  max_deploy_retries: 5
```

---

## Error Handling

| Situation | Behaviour |
|---|---|
| LLM returns no parseable files | Log warning, break retry loop early, leave `tests_passed = False` |
| git commit fails (no changes) | Log warning, break (engineer returned same files — would loop forever) |
| `project_dir` doesn't exist | `_stage_test_runner` already handles this; fix loop won't be reached |
| Timeout in `_stage_test_runner` | `result.tests_passed = False` already set; retry loop proceeds |
| max_test_retries = 0 | Loop body never executes; behaves as current (single run, no retry) |

---

## Testing

- `tests/test_engineer_fix.py` — unit tests for `fix_failures()`:
  - Parses patched files from LLM response
  - Returns `{}` when LLM response has no file blocks
  - Prompt includes failure output verbatim
  - Prompt includes all provided files
  - Framework context prepended when non-empty
- `tests/test_test_fix_loop.py` — unit tests for `_stage_test_fix_loop()`:
  - Returns immediately when tests pass on first run
  - Calls fix_failures + re-runs tests on failure
  - Stops loop when tests pass mid-way
  - Exhausts all retries and posts PR comment
  - Handles empty patch dict (LLM returned nothing) gracefully
  - `test_retry_count` incremented correctly
  - `test_fix_history` populated with one entry per attempt

---

## Out of Scope

- Retrying the QA engineer stage (only fix failing tests, not rewrite them)
- Retrying the code reviewer stage
- Smart file-filtering to reduce LLM context (all files always sent for simplicity)
- Async parallel fix attempts
