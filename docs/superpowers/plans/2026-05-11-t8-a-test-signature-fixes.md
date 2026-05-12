# T8-A: Test Signature Drift Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 12 failing tests caused by production signature additions in T6/T7 that broke three categories of test mocks.

**Architecture:** Pure test fixes — no production code changes. Three root causes in five files: (A) lambda mocks missing `**kwargs` for new keyword args on `_run_stage`/`_run_pr_revision`; (B) `test_call_routes_zen_gpt_to_openai` wires mock response outside the patch context AND creates agent with `stream=True` so calls go through `_stream_call` returning empty string; (C) OAuth error-message assertions match lowercase `'google'` but production raises `"Google ..."` (capital G).

**Tech Stack:** Python 3.11, pytest, `unittest.mock.MagicMock`, `pytest.MonkeyPatch`

---

## Pre-condition: confirm baseline failures

```bash
cd /home/wanleung/Projects/ai-software-house
python3 -m pytest tests/test_pipeline_modes.py tests/test_pipeline_yaml.py \
    tests/test_watcher_prs.py tests/test_opencode_zen.py tests/test_oauth_manager.py \
    -q --tb=line 2>&1 | tail -20
```

Expected: 12 FAILED.

---

## Task 1: Fix `_run_stage` lambda mocks in `test_pipeline_modes.py`

**Files:**
- Modify: `tests/test_pipeline_modes.py:435`

**Root cause:** `orchestrator.Orchestrator._run_stage` signature is:
```python
def _run_stage(self, name, description, result, fn,
               timeout_s=None, required_output_fields=None,
               cb_key=None, is_critical=False) -> None
```
The mock at line 435 uses `lambda label, desc, r, fn: fn()` which rejects any keyword argument.

- [ ] **Step 1: Update the lambda at line 435**

In `tests/test_pipeline_modes.py`, find this line (inside `_make_full_orch`):
```python
    o._run_stage = MagicMock(side_effect=lambda label, desc, r, fn: fn())
```
Replace with:
```python
    o._run_stage = MagicMock(side_effect=lambda label, desc, r, fn, **kw: fn())
```

- [ ] **Step 2: Run the 5 affected tests**

```bash
python3 -m pytest tests/test_pipeline_modes.py -q --tb=short
```
Expected: 5 passed (all `test_run_*_mode_*` and `test_run_reviewer_stop_*` tests).

- [ ] **Step 3: Commit**

```bash
git add tests/test_pipeline_modes.py
git commit -m "test(pipeline_modes): accept **kwargs in _run_stage mock lambda"
```

---

## Task 2: Fix `_run_stage` lambda mocks in `test_pipeline_yaml.py`

**Files:**
- Modify: `tests/test_pipeline_yaml.py` — 3 occurrences (lines ~392, ~420, ~448)

**Root cause:** `_run_loop_stage` calls `self._run_stage(lbl, desc, r, fn, timeout_s=...)` so the same lambda needs `**kw`.

- [ ] **Step 1: Update all three lambdas**

In `tests/test_pipeline_yaml.py`, find and replace all three occurrences of:
```python
side_effect=lambda lbl, desc, r, fn: fn()
```
with:
```python
side_effect=lambda lbl, desc, r, fn, **kw: fn()
```

There are exactly 3 such occurrences in this file — in `test_run_loop_stage_exits_early_on_verdict`, `test_run_loop_stage_returns_false_on_inner_error`, and `test_run_loop_stage_exhausts_without_verdict`. Make all 3 replacements.

- [ ] **Step 2: Run the 3 affected tests**

```bash
python3 -m pytest tests/test_pipeline_yaml.py::test_run_loop_stage_exits_early_on_verdict \
    tests/test_pipeline_yaml.py::test_run_loop_stage_returns_false_on_inner_error \
    tests/test_pipeline_yaml.py::test_run_loop_stage_exhausts_without_verdict \
    -q --tb=short
```
Expected: 3 passed.

- [ ] **Step 3: Run full `test_pipeline_yaml.py` to check no regressions**

```bash
python3 -m pytest tests/test_pipeline_yaml.py -q --tb=short
```
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_pipeline_yaml.py
git commit -m "test(pipeline_yaml): accept **kwargs in _run_stage mock lambdas"
```

---

## Task 3: Fix `_run_pr_revision` lambda mock in `test_watcher_prs.py`

**Files:**
- Modify: `tests/test_watcher_prs.py:303-307`

**Root cause:** `watcher._run_pr_revision` now accepts `conflict_resolver_model: Optional[str] = None` (added in T7-A). The mock lambda at line 305 does not accept it.

Current mock (lines 303–307):
```python
monkeypatch.setattr(
    "watcher._run_pr_revision",
    lambda pr, tracker, target, model, num_eng, log_dir, logger, pr_fix_label="ai-fix", update_branch_enabled=False:
        dispatched.append((pr["number"], tracker, target, model, num_eng, pr_fix_label)),
)
```

- [ ] **Step 1: Add `conflict_resolver_model=None` and `**kw` to the lambda**

Replace the mock with:
```python
monkeypatch.setattr(
    "watcher._run_pr_revision",
    lambda pr, tracker, target, model, num_eng, log_dir, logger,
           pr_fix_label="ai-fix", update_branch_enabled=False,
           conflict_resolver_model=None, **kw:
        dispatched.append((pr["number"], tracker, target, model, num_eng, pr_fix_label)),
)
```

- [ ] **Step 2: Run the affected test**

```bash
python3 -m pytest tests/test_watcher_prs.py::test_watch_prs_dispatches_when_label_trigger -q --tb=short
```
Expected: 1 passed.

- [ ] **Step 3: Run full `test_watcher_prs.py`**

```bash
python3 -m pytest tests/test_watcher_prs.py -q --tb=short
```
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_watcher_prs.py
git commit -m "test(watcher_prs): add conflict_resolver_model kwarg to _run_pr_revision mock"
```

---

## Task 4: Fix `test_call_routes_zen_gpt_to_openai` in `test_opencode_zen.py`

**Files:**
- Modify: `tests/test_opencode_zen.py:148-162`

**Root cause:** Two bugs:
1. `agent = BaseAgent(model="opencode-zen/gpt-5.3-codex")` is created with `opencode_stream=True` (default). `OpenCodeZenBackend._oai_backend` is created with `stream=True`. When `agent.call()` runs, `OpenAICompatibleBackend.call()` routes through `_stream_call()` which iterates over a streaming response. The mock sets a plain `.return_value` (not a streaming iterator), so `_stream_call` collects no chunks → returns `""`.
2. `mock_response` is configured outside the `with patch(...)` block, then `agent.call()` is called outside the block. The env var is no longer set, but more importantly the stream issue is the actual failure.

**Fix:** Add `opencode_stream=False` to force the non-streaming path, and move `mock_response` setup + `agent.call()` inside the patch context so the mock is still active.

Current code (lines 148–162):
```python
def test_call_routes_zen_gpt_to_openai():
    """call() routes opencode_zen non-Claude models through OpenAI-compatible path."""
    with patch.dict("os.environ", {"OPENCODE_ZEN_API_KEY": "zen-test-key"}):
        with patch("agents.backends.opencode_zen.OpenAI") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            from agents.base_agent import BaseAgent
            agent = BaseAgent(model="opencode-zen/gpt-5.3-codex")

    mock_response = MagicMock()
    mock_response.choices[0].message.content = "zen gpt reply"
    agent.client.chat.completions.create.return_value = mock_response

    result = agent.call("test prompt")
    assert result == "zen gpt reply"
```

- [ ] **Step 1: Restructure the test**

Replace the entire `test_call_routes_zen_gpt_to_openai` function with:
```python
def test_call_routes_zen_gpt_to_openai():
    """call() routes opencode_zen non-Claude models through OpenAI-compatible path."""
    with patch.dict("os.environ", {"OPENCODE_ZEN_API_KEY": "zen-test-key"}):
        with patch("agents.backends.opencode_zen.OpenAI") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_response = MagicMock()
            mock_response.choices[0].message.content = "zen gpt reply"
            mock_client.chat.completions.create.return_value = mock_response
            from agents.base_agent import BaseAgent
            agent = BaseAgent(model="opencode-zen/gpt-5.3-codex", opencode_stream=False)
            result = agent.call("test prompt")
    assert result == "zen gpt reply"
```

- [ ] **Step 2: Run the test**

```bash
python3 -m pytest tests/test_opencode_zen.py::test_call_routes_zen_gpt_to_openai -q --tb=short
```
Expected: 1 passed.

- [ ] **Step 3: Run full `test_opencode_zen.py`**

```bash
python3 -m pytest tests/test_opencode_zen.py -q --tb=short
```
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_opencode_zen.py
git commit -m "test(opencode_zen): move mock setup inside patch context, disable stream for routing test"
```

---

## Task 5: Fix OAuth error-message case assertions in `test_oauth_manager.py`

**Files:**
- Modify: `tests/test_oauth_manager.py:288,309`

**Root cause:** Production `AuthenticationError` messages begin with `"Google ..."` (capital G). Tests assert `assert 'google' in str(exc_info.value)` (lowercase), which is case-sensitive.

- [ ] **Step 1: Fix both assertions**

In `tests/test_oauth_manager.py`, find and replace both occurrences of:
```python
assert "google" in str(exc_info.value)
```
with:
```python
assert "google" in str(exc_info.value).lower()
```

There are exactly 2 occurrences — at lines 288 and 309.

- [ ] **Step 2: Run the 2 affected tests**

```bash
python3 -m pytest "tests/test_oauth_manager.py::TestRefreshToken::test_refresh_google_token_http_error" \
    "tests/test_oauth_manager.py::TestRefreshToken::test_refresh_google_token_network_error" \
    -q --tb=short
```
Expected: 2 passed.

- [ ] **Step 3: Run full `test_oauth_manager.py`**

```bash
python3 -m pytest tests/test_oauth_manager.py -q --tb=short
```
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_oauth_manager.py
git commit -m "test(oauth_manager): use .lower() for case-insensitive error-message assertions"
```

---

## Task 6: Final verification and PR

- [ ] **Step 1: Run all 5 target test files together**

```bash
python3 -m pytest tests/test_pipeline_modes.py tests/test_pipeline_yaml.py \
    tests/test_watcher_prs.py tests/test_opencode_zen.py tests/test_oauth_manager.py \
    -q --tb=short
```
Expected: 0 failed (12 tests that were failing now pass).

- [ ] **Step 2: Run broader suite for regressions**

```bash
python3 -m pytest tests/ -q --tb=no \
    --ignore=tests/integration --ignore=tests/unit \
    --ignore=tests/test_event_normalizer.py --ignore=tests/test_rate_limiter.py \
    --ignore=tests/test_models.py --ignore=tests/test_deployment.py \
    2>&1 | tail -5
```
Expected: 0 failures beyond the pre-existing baseline.

- [ ] **Step 3: Push and open PR**

```bash
git push -u origin <branch-name>
gh pr create --title "test(T8-A): fix 12 test failures from mock signature drift" \
  --body "$(cat <<'EOF'
## Summary
- **test_pipeline_modes/yaml**: Add \`**kw\` to \`_run_stage\` mock lambdas — production added \`timeout_s\`, \`required_output_fields\`, and other kwargs in T6/T7
- **test_watcher_prs**: Add \`conflict_resolver_model=None, **kw\` to \`_run_pr_revision\` mock lambda
- **test_opencode_zen**: Move mock setup and \`agent.call()\` inside patch context; add \`opencode_stream=False\` — stream=True path uses iterator protocol that MagicMock doesn't satisfy
- **test_oauth_manager**: Use \`.lower()\` for case-insensitive error-message assertions

## Test Plan
- 0 failed across all 5 target files (was 12)
EOF
)"
```
