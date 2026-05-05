# PR Watcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable the watcher to monitor open PRs for failures (via label or comment pattern) and automatically invoke `run_revision()` to push fixes, with a configurable retry cap.

**Architecture:** A new `_watch_prs()` function is added to `watcher.py` that runs each cycle alongside issue watching. It scans open PRs in each enabled repo (when `watch_prs: true`), detects failures via label OR comment pattern, and dispatches a new `_run_pr_revision()` function that instantiates an Orchestrator and calls `run_revision(pr_number)`. The orchestrator already handles engineer→reviewer→QA and pushing commits. The watcher adds `agent-running`/`agent-complete`/`agent-failed` labels to the PR to track state.

**Tech Stack:** Python 3.11+, `watcher.py`, `orchestrator.py` (unchanged), GitHub REST API (`requests`), `pytest` + `monkeypatch` for tests.

---

## File Map

| File | Change |
|---|---|
| `watcher.py` | Add `get_open_prs()`, `get_pr_comments()`, `_pr_attempt_count()`, `_should_fix_pr()`, `_run_pr_revision()`, `_watch_prs()`; wire into `watch()` |
| `config.yaml` | Add `watch_prs`, `pr_fix_label`, `pr_failure_pattern`, `max_pr_retries`, `watch_draft_prs` defaults under `pipeline:` |
| `repos-available/*.yaml` | Document how to set per-repo PR watcher settings (docs only, no logic change needed) |
| `tests/test_watcher_prs.py` | New test file: 9 tests covering all PR watcher behaviour |
| `docs/operations-guide.md` | Add "PR Watcher" section |

---

## Task 1: GitHub API helpers — `get_open_prs()` and `get_pr_comments()`

**Files:**
- Modify: `watcher.py` (add after `get_open_issues()` at ~line 113)
- Test: `tests/test_watcher_prs.py` (new file)

The watcher needs two new API helpers that use the module-level `_gh_headers()` (same as `get_open_issues()`):

- `get_open_prs(repo, skip_drafts=True)` — fetches open PRs for the repo, optionally excluding drafts. Returns list of PR dicts.
- `get_pr_comments(repo, pr_number)` — fetches all conversation comments on a PR (issue comments endpoint). Returns list of comment dicts.

- [ ] **Step 1: Write failing tests**

Create `tests/test_watcher_prs.py`:

```python
"""Tests for PR watcher helpers and logic."""
from __future__ import annotations
import pytest
from unittest.mock import patch, MagicMock


# ── API helper tests ──────────────────────────────────────────────────────────

def _mock_response(json_data, status_code=200):
    m = MagicMock()
    m.ok = status_code < 400
    m.status_code = status_code
    m.json.return_value = json_data
    m.text = str(json_data)
    return m


def test_get_open_prs_returns_non_draft(monkeypatch):
    """get_open_prs filters out draft PRs when skip_drafts=True."""
    from watcher import get_open_prs
    prs = [
        {"number": 1, "draft": False, "title": "Real PR", "labels": []},
        {"number": 2, "draft": True, "title": "Draft PR", "labels": []},
    ]
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    with patch("watcher.requests.get", return_value=_mock_response(prs)):
        result = get_open_prs("owner/repo", skip_drafts=True)
    assert len(result) == 1
    assert result[0]["number"] == 1


def test_get_open_prs_includes_draft_when_disabled(monkeypatch):
    """get_open_prs includes drafts when skip_drafts=False."""
    from watcher import get_open_prs
    prs = [
        {"number": 1, "draft": False, "title": "Real PR", "labels": []},
        {"number": 2, "draft": True, "title": "Draft PR", "labels": []},
    ]
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    with patch("watcher.requests.get", return_value=_mock_response(prs)):
        result = get_open_prs("owner/repo", skip_drafts=False)
    assert len(result) == 2


def test_get_pr_comments_returns_list(monkeypatch):
    """get_pr_comments returns list of comment dicts."""
    from watcher import get_pr_comments
    comments = [{"id": 1, "body": "❌ Tests failed", "user": {"login": "bot"}}]
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    with patch("watcher.requests.get", return_value=_mock_response(comments)):
        result = get_pr_comments("owner/repo", 42)
    assert result == comments
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/wanleung/Projects/ai-software-house
source venv/bin/activate
pytest tests/test_watcher_prs.py -v 2>&1 | head -30
```

Expected: `ImportError` or `AttributeError` — `get_open_prs` and `get_pr_comments` don't exist yet.

- [ ] **Step 3: Implement `get_open_prs()` and `get_pr_comments()` in `watcher.py`**

Add after the `get_open_issues()` function (around line 113), before `post_comment()`:

```python
def get_open_prs(repo: str, skip_drafts: bool = True) -> list[dict]:
    """Return open pull requests for the repo, optionally excluding drafts."""
    url = f"https://api.github.com/repos/{repo}/pulls"
    params = {"state": "open", "per_page": 50}
    resp = requests.get(url, headers=_gh_headers(), params=params, timeout=10)
    if not resp.ok:
        raise RuntimeError(f"GitHub API error {resp.status_code}: {resp.text[:200]}")
    prs = resp.json()
    if skip_drafts:
        prs = [pr for pr in prs if not pr.get("draft", False)]
    return prs


def get_pr_comments(repo: str, pr_number: int) -> list[dict]:
    """Return all conversation comments on a pull request."""
    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    resp = requests.get(url, headers=_gh_headers(), params={"per_page": 100}, timeout=10)
    if not resp.ok:
        raise RuntimeError(f"GitHub API error {resp.status_code}: {resp.text[:200]}")
    return resp.json()
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_watcher_prs.py::test_get_open_prs_returns_non_draft tests/test_watcher_prs.py::test_get_open_prs_includes_draft_when_disabled tests/test_watcher_prs.py::test_get_pr_comments_returns_list -v
```

Expected: 3 PASSED

- [ ] **Step 5: Run all existing watcher tests to confirm no regression**

```bash
pytest tests/test_watcher.py tests/test_watcher_config.py tests/test_watcher_dispatch.py -v --tb=short 2>&1 | tail -20
```

Expected: all passing (same count as before)

- [ ] **Step 6: Commit**

```bash
git add watcher.py tests/test_watcher_prs.py
git commit -m "feat: add get_open_prs and get_pr_comments API helpers"
```

---

## Task 2: PR detection helpers — `_pr_attempt_count()` and `_should_fix_pr()`

**Files:**
- Modify: `watcher.py` (add after `get_pr_comments()`)
- Test: `tests/test_watcher_prs.py` (extend)

Two pure helper functions:

- `_pr_attempt_count(pr_labels: list[dict]) -> int` — counts `ai-pr-fix-N` labels on a PR. Returns the highest N found, or 0 if none.
- `_should_fix_pr(pr: dict, comments: list[dict], pr_fix_label: str, pr_failure_pattern: str, max_pr_retries: int) -> bool` — returns True if the PR needs a fix run. False if: already has `agent-running`/`agent-failed`, attempt count >= max_pr_retries, or neither trigger condition is met.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_watcher_prs.py`:

```python
# ── Detection helper tests ────────────────────────────────────────────────────

def test_pr_attempt_count_zero_when_no_labels():
    from watcher import _pr_attempt_count
    assert _pr_attempt_count([]) == 0


def test_pr_attempt_count_reads_highest_n():
    from watcher import _pr_attempt_count
    labels = [
        {"name": "ai-pr-fix-1"},
        {"name": "ai-pr-fix-3"},
        {"name": "ai-pr-fix-2"},
        {"name": "unrelated"},
    ]
    assert _pr_attempt_count(labels) == 3


def test_should_fix_pr_label_trigger():
    """PR with pr_fix_label triggers a fix."""
    from watcher import _should_fix_pr
    pr = {"number": 5, "labels": [{"name": "ai-fix"}], "draft": False}
    assert _should_fix_pr(pr, [], "ai-fix", r"❌|FAILED", 3) is True


def test_should_fix_pr_comment_trigger():
    """PR with matching comment triggers a fix even without label."""
    from watcher import _should_fix_pr
    pr = {"number": 5, "labels": [], "draft": False}
    comments = [{"body": "❌ Tests failed: 3 errors", "user": {"login": "bot"}}]
    assert _should_fix_pr(pr, comments, "ai-fix", r"❌|FAILED", 3) is True


def test_should_fix_pr_skip_agent_running():
    """PR with agent-running label is skipped."""
    from watcher import _should_fix_pr
    pr = {"number": 5, "labels": [{"name": "ai-fix"}, {"name": "agent-running"}], "draft": False}
    assert _should_fix_pr(pr, [], "ai-fix", r"❌|FAILED", 3) is False


def test_should_fix_pr_skip_agent_failed():
    """PR with agent-failed label is skipped."""
    from watcher import _should_fix_pr
    pr = {"number": 5, "labels": [{"name": "ai-fix"}, {"name": "agent-failed"}], "draft": False}
    assert _should_fix_pr(pr, [], "ai-fix", r"❌|FAILED", 3) is False


def test_should_fix_pr_skip_max_retries():
    """PR at max retries is skipped."""
    from watcher import _should_fix_pr
    pr = {
        "number": 5,
        "labels": [{"name": "ai-fix"}, {"name": "ai-pr-fix-3"}],
        "draft": False,
    }
    assert _should_fix_pr(pr, [], "ai-fix", r"❌|FAILED", 3) is False


def test_should_fix_pr_no_trigger():
    """PR with no trigger label and no matching comments is not flagged."""
    from watcher import _should_fix_pr
    pr = {"number": 5, "labels": [{"name": "enhancement"}], "draft": False}
    comments = [{"body": "Looks good!", "user": {"login": "alice"}}]
    assert _should_fix_pr(pr, comments, "ai-fix", r"❌|FAILED", 3) is False
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_watcher_prs.py -k "attempt_count or should_fix" -v 2>&1 | head -20
```

Expected: `ImportError` — helpers don't exist yet.

- [ ] **Step 3: Implement helpers in `watcher.py`**

Add after `get_pr_comments()`:

```python
def _pr_attempt_count(pr_labels: list[dict]) -> int:
    """Return the highest N from any 'ai-pr-fix-N' label, or 0 if none."""
    import re
    highest = 0
    for lbl in pr_labels:
        m = re.match(r"^ai-pr-fix-(\d+)$", lbl.get("name", ""))
        if m:
            highest = max(highest, int(m.group(1)))
    return highest


def _should_fix_pr(
    pr: dict,
    comments: list[dict],
    pr_fix_label: str,
    pr_failure_pattern: str,
    max_pr_retries: int,
) -> bool:
    """Return True if this PR should receive an automated fix run.

    Skips if: agent-running/agent-failed label present, or attempt count
    has reached max_pr_retries, or neither trigger condition is met.
    """
    import re
    pr_label_names = {lbl["name"] for lbl in pr.get("labels", [])}

    # Skip if already being processed or gave up
    if pr_label_names & {"agent-running", "agent-failed"}:
        return False

    # Skip if retry cap reached
    if _pr_attempt_count(list(pr.get("labels", []))) >= max_pr_retries:
        return False

    # Trigger 1: explicit fix label on the PR
    if pr_fix_label in pr_label_names:
        return True

    # Trigger 2: comment matching failure pattern
    pattern = re.compile(pr_failure_pattern, re.IGNORECASE)
    for comment in comments:
        if pattern.search(comment.get("body", "")):
            return True

    return False
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_watcher_prs.py -v --tb=short 2>&1 | tail -20
```

Expected: all tests in `test_watcher_prs.py` passing so far.

- [ ] **Step 5: Commit**

```bash
git add watcher.py tests/test_watcher_prs.py
git commit -m "feat: add _pr_attempt_count and _should_fix_pr detection helpers"
```

---

## Task 3: PR fix dispatcher — `_run_pr_revision()`

**Files:**
- Modify: `watcher.py` (add after `_run_pipeline_in_process()`, around line 380)
- Test: `tests/test_watcher_prs.py` (extend)

`_run_pr_revision()` mirrors `run_pipeline()`: instantiates an Orchestrator and calls `run_revision(pr_number)`. Handles all label state transitions on the PR (add `agent-running`, add attempt label, then `agent-complete` or `agent-failed`).

Signature:
```python
def _run_pr_revision(
    pr: dict,
    tracker_repo: str,
    target_repo: str,
    model: str,
    num_engineers: int,
    log_dir: Path,
    logger: logging.Logger,
) -> None:
```

- [ ] **Step 1: Write failing test**

Append to `tests/test_watcher_prs.py`:

```python
# ── _run_pr_revision tests ────────────────────────────────────────────────────

def test_run_pr_revision_success(monkeypatch, tmp_path):
    """Successful revision adds agent-complete, removes agent-running."""
    from watcher import _run_pr_revision
    import types

    pr = {"number": 7, "labels": [{"name": "ai-fix"}], "title": "Fix me"}

    calls = {"add": [], "remove": []}

    def fake_add_label(repo, num, label):
        calls["add"].append(label)

    def fake_remove_label(repo, num, label):
        calls["remove"].append(label)

    def fake_post_comment(repo, num, body):
        pass

    def fake_ensure_label(repo, name, colour):
        pass

    fake_revision_result = {"status": "ok", "revision": 1}

    class FakeOrch:
        def __init__(self, **kwargs):
            pass
        def run_revision(self, pr_number):
            return fake_revision_result

    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    monkeypatch.setattr("watcher.add_label", fake_add_label)
    monkeypatch.setattr("watcher.remove_label", fake_remove_label)
    monkeypatch.setattr("watcher.post_comment", fake_post_comment)
    monkeypatch.setattr("watcher.ensure_label", fake_ensure_label)

    import sys
    fake_orchestrator_mod = types.ModuleType("orchestrator")
    fake_orchestrator_mod.Orchestrator = FakeOrch
    monkeypatch.setitem(sys.modules, "orchestrator", fake_orchestrator_mod)

    import logging
    _run_pr_revision(pr, "owner/tracker", "owner/target", "gpt-4.1", 2, tmp_path, logging.getLogger("test"))

    assert "agent-running" in calls["add"]
    assert "agent-complete" in calls["add"]
    assert "agent-running" in calls["remove"]


def test_run_pr_revision_max_revisions_reached(monkeypatch, tmp_path):
    """When orchestrator returns max_revisions_reached, agent-failed is added."""
    from watcher import _run_pr_revision
    import types

    pr = {"number": 8, "labels": [{"name": "ai-fix"}], "title": "Stuck"}
    calls = {"add": [], "remove": []}

    class FakeOrch:
        def __init__(self, **kwargs):
            pass
        def run_revision(self, pr_number):
            return {"status": "max_revisions_reached"}

    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    monkeypatch.setattr("watcher.add_label", lambda r, n, l: calls["add"].append(l))
    monkeypatch.setattr("watcher.remove_label", lambda r, n, l: calls["remove"].append(l))
    monkeypatch.setattr("watcher.post_comment", lambda *a: None)
    monkeypatch.setattr("watcher.ensure_label", lambda *a: None)

    import sys
    fake_mod = types.ModuleType("orchestrator")
    fake_mod.Orchestrator = FakeOrch
    monkeypatch.setitem(sys.modules, "orchestrator", fake_mod)

    import logging
    _run_pr_revision(pr, "owner/tracker", "owner/target", "gpt-4.1", 2, tmp_path, logging.getLogger("test"))

    assert "agent-failed" in calls["add"]
    assert "agent-running" not in calls["add"] or "agent-running" in calls["remove"]
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_watcher_prs.py -k "run_pr_revision" -v 2>&1 | head -20
```

Expected: `ImportError` — `_run_pr_revision` not defined.

- [ ] **Step 3: Implement `_run_pr_revision()` in `watcher.py`**

Add after `_resolve_next_label()` (around line 480):

```python
def _run_pr_revision(
    pr: dict,
    tracker_repo: str,
    target_repo: str,
    model: str,
    num_engineers: int,
    log_dir: Path,
    logger: logging.Logger,
) -> None:
    """Instantiate an Orchestrator and run run_revision() for a failing PR.

    Manages agent-running / agent-complete / agent-failed labels on the PR.
    The attempt count label (ai-pr-fix-N) is added before calling run_revision().
    """
    pr_number = pr["number"]
    attempt = _pr_attempt_count(pr.get("labels", [])) + 1
    attempt_label = f"ai-pr-fix-{attempt}"

    token = os.environ.get("GITHUB_TOKEN", "")
    pipeline_cfg = _load_pipeline_config()
    llm_cfg = pipeline_cfg.get("llm", {})
    pipe_cfg = pipeline_cfg.get("pipeline", {})
    cfg_model = llm_cfg.get("model", "") or ""
    effective_model = cfg_model if cfg_model and cfg_model != "gpt-4.1" else model
    model_overrides = llm_cfg.get("overrides", {})
    ollama_url = llm_cfg.get("ollama_url", "http://localhost:11434")
    nvidia_nim_api_key = llm_cfg.get("nvidia_nim_api_key") or os.environ.get("NVIDIA_API_KEY")
    nvidia_nim_base_url = llm_cfg.get("nvidia_nim_base_url") or os.environ.get("NVIDIA_NIM_BASE_URL")
    retry_delay = pipe_cfg.get("retry_delay", 15)
    max_api_retries = pipe_cfg.get("max_api_retries", 5)
    inter_call_delay = pipe_cfg.get("inter_call_delay", 0)

    log_file = log_dir / f"pr-revision-{pr_number}-attempt{attempt}.log"

    logger.info("  🔄 PR #%d: starting fix attempt %d", pr_number, attempt)

    # Mark as running and record attempt number
    ensure_label(tracker_repo, "agent-running", LABEL_COLOURS.get(LABEL_RUNNING, "0075ca"))
    ensure_label(tracker_repo, attempt_label, "c5def5")
    add_label(tracker_repo, pr_number, LABEL_RUNNING)
    add_label(tracker_repo, pr_number, attempt_label)

    with open(log_file, "w", encoding="utf-8") as fh:
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = fh
        try:
            from orchestrator import Orchestrator
            from github_client import GitHubClient

            orch = Orchestrator(
                model=effective_model,
                model_overrides=model_overrides,
                github_token=token,
                github_repo=tracker_repo,
                target_repo=target_repo,
                num_engineers=num_engineers,
                use_github=True,
                ollama_url=ollama_url,
                nvidia_nim_api_key=nvidia_nim_api_key,
                nvidia_nim_base_url=nvidia_nim_base_url,
                retry_delay=retry_delay,
                max_api_retries=max_api_retries,
                inter_call_delay=inter_call_delay,
            )

            result = orch.run_revision(pr_number)
            status = result.get("status", "ok")

            if status in ("max_revisions_reached", "error"):
                add_label(tracker_repo, pr_number, LABEL_FAILED)
                remove_label(tracker_repo, pr_number, LABEL_RUNNING)
                post_comment(
                    tracker_repo, pr_number,
                    f"❌ PR fix attempt {attempt} could not complete "
                    f"(status: `{status}`). Log: `{log_file}`\n\n"
                    "Remove `agent-failed` to retry manually.",
                )
                logger.info("  ❌ PR #%d fix attempt %d: %s", pr_number, attempt, status)
            else:
                add_label(tracker_repo, pr_number, LABEL_COMPLETE)
                remove_label(tracker_repo, pr_number, LABEL_RUNNING)
                # Remove trigger label so next cycle doesn't re-trigger
                remove_label(tracker_repo, pr_number, "ai-fix")
                logger.info("  ✅ PR #%d fix attempt %d complete", pr_number, attempt)

        except Exception as exc:  # noqa: BLE001
            logger.error("  ❌ PR #%d fix attempt %d unhandled error: %s", pr_number, attempt, exc)
            add_label(tracker_repo, pr_number, LABEL_FAILED)
            remove_label(tracker_repo, pr_number, LABEL_RUNNING)
            post_comment(
                tracker_repo, pr_number,
                f"❌ PR fix attempt {attempt} failed with error: `{exc}`\n"
                f"Log: `{log_file}`\n\nRemove `agent-failed` to retry.",
            )
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_watcher_prs.py -v --tb=short 2>&1 | tail -20
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add watcher.py tests/test_watcher_prs.py
git commit -m "feat: add _run_pr_revision dispatcher for PR fix pipeline"
```

---

## Task 4: Wire `_watch_prs()` into `watch()` and add config defaults

**Files:**
- Modify: `watcher.py` (add `_watch_prs()`, call from `watch()`)
- Modify: `config.yaml` (add PR watcher defaults)
- Test: `tests/test_watcher_prs.py` (extend with `_watch_prs` integration test)

`_watch_prs()` iterates watchers, checks `watch_prs` setting, fetches open PRs, calls `_should_fix_pr()` for each, and dispatches `_run_pr_revision()` for any that need fixing.

- [ ] **Step 1: Write failing test**

Append to `tests/test_watcher_prs.py`:

```python
# ── _watch_prs integration tests ─────────────────────────────────────────────

def test_watch_prs_dispatches_when_label_trigger(monkeypatch, tmp_path):
    """_watch_prs calls _run_pr_revision when PR has the fix label."""
    from watcher import _watch_prs
    import logging

    pr = {
        "number": 10,
        "title": "Bad PR",
        "labels": [{"name": "ai-fix"}],
        "draft": False,
        "head": {"repo": {"full_name": "owner/target"}},
    }
    watchers = [{
        "tracker_repo": "owner/tracker",
        "default_target": "owner/target",
        "enabled": True,
        "_settings": {"watch_prs": True, "pr_fix_label": "ai-fix",
                      "pr_failure_pattern": r"❌|FAILED", "max_pr_retries": 3,
                      "watch_draft_prs": False},
    }]

    dispatched = []

    monkeypatch.setattr("watcher.get_open_prs", lambda repo, skip_drafts=True: [pr])
    monkeypatch.setattr("watcher.get_pr_comments", lambda repo, num: [])
    monkeypatch.setattr("watcher._run_pr_revision", lambda pr, tracker, target, model, num_eng, log_dir, logger: dispatched.append(pr["number"]))

    _watch_prs(watchers, {"model": "gpt-4.1", "num_engineers": 2}, tmp_path, False, logging.getLogger("test"))

    assert 10 in dispatched


def test_watch_prs_skips_when_disabled(monkeypatch, tmp_path):
    """_watch_prs does not scan PRs when watch_prs is False."""
    from watcher import _watch_prs
    import logging

    watchers = [{
        "tracker_repo": "owner/tracker",
        "default_target": "owner/target",
        "enabled": True,
        "_settings": {"watch_prs": False},
    }]

    get_open_prs_called = []
    monkeypatch.setattr("watcher.get_open_prs", lambda *a, **k: get_open_prs_called.append(True) or [])

    _watch_prs(watchers, {"model": "gpt-4.1", "num_engineers": 2}, tmp_path, False, logging.getLogger("test"))

    assert get_open_prs_called == []


def test_watch_prs_dry_run_does_not_dispatch(monkeypatch, tmp_path):
    """_watch_prs does not dispatch in dry-run mode."""
    from watcher import _watch_prs
    import logging

    pr = {
        "number": 11,
        "title": "PR",
        "labels": [{"name": "ai-fix"}],
        "draft": False,
        "head": {"repo": {"full_name": "owner/target"}},
    }
    watchers = [{
        "tracker_repo": "owner/tracker",
        "default_target": "owner/target",
        "enabled": True,
        "_settings": {"watch_prs": True, "pr_fix_label": "ai-fix",
                      "pr_failure_pattern": r"❌|FAILED", "max_pr_retries": 3,
                      "watch_draft_prs": False},
    }]

    dispatched = []
    monkeypatch.setattr("watcher.get_open_prs", lambda *a, **k: [pr])
    monkeypatch.setattr("watcher.get_pr_comments", lambda *a: [])
    monkeypatch.setattr("watcher._run_pr_revision", lambda *a, **k: dispatched.append(True))

    _watch_prs(watchers, {"model": "gpt-4.1", "num_engineers": 2}, tmp_path, dry_run=True, logger=logging.getLogger("test"))

    assert dispatched == []
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_watcher_prs.py -k "watch_prs" -v 2>&1 | head -20
```

Expected: `ImportError` — `_watch_prs` not defined.

- [ ] **Step 3: Implement `_watch_prs()` in `watcher.py`**

Add after `_run_pr_revision()`:

```python
def _watch_prs(
    watchers: list[dict],
    global_settings: dict,
    log_dir: Path,
    dry_run: bool,
    logger: logging.Logger,
) -> None:
    """Scan open PRs across all enabled watchers and dispatch fix runs as needed.

    Only runs for watchers with watch_prs: true in their settings.
    Per-watcher settings override global_settings (same _settings merge as watch()).
    """
    for w in watchers:
        if not w.get("enabled", True):
            continue
        _w_settings = {**global_settings, **w.get("_settings", {})}
        if not _w_settings.get("watch_prs", False):
            continue

        tracker_repo = w["tracker_repo"]
        target_repo = w.get("default_target") or tracker_repo
        model = _w_settings.get("model", "gpt-4.1")
        num_engineers = _w_settings.get("num_engineers", 2)
        pr_fix_label = _w_settings.get("pr_fix_label", "ai-fix")
        pr_failure_pattern = _w_settings.get("pr_failure_pattern", r"❌|FAILED|tests? failed|test suite failed")
        max_pr_retries = int(_w_settings.get("max_pr_retries", 3))
        skip_drafts = not _w_settings.get("watch_draft_prs", False)

        logger.info("Checking PRs in %s …", tracker_repo)
        try:
            prs = get_open_prs(target_repo, skip_drafts=skip_drafts)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to fetch PRs from %s: %s", target_repo, exc)
            continue

        for pr in prs:
            pr_number = pr["number"]
            try:
                comments = get_pr_comments(target_repo, pr_number)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not fetch comments for PR #%d: %s", pr_number, exc)
                comments = []

            if not _should_fix_pr(pr, comments, pr_fix_label, pr_failure_pattern, max_pr_retries):
                continue

            logger.info("  🔧 PR #%d needs fixing (%s)", pr_number, pr.get("title", ""))

            if dry_run:
                logger.info("    [dry-run] Would run PR fix for #%d", pr_number)
                continue

            _run_pr_revision(pr, tracker_repo, target_repo, model, num_engineers, log_dir, logger)
```

- [ ] **Step 4: Call `_watch_prs()` from `watch()`**

In `watch()`, after the issue dispatch block (after `check_waiting_issues()` and before collecting issue tasks), add:

```python
    # Watch PRs for failures and dispatch fix runs
    _watch_prs(watchers, global_settings, log_dir, dry_run, logger)
```

Find the line `check_waiting_issues(github_token, tracker_repos, workspace_dir, bot_login)` and add the `_watch_prs()` call immediately after it:

```python
    if not dry_run:
        check_waiting_issues(github_token, tracker_repos, workspace_dir, bot_login)

    # Watch PRs for failures and dispatch fix runs
    _watch_prs(watchers, global_settings, log_dir, dry_run, logger)
```

- [ ] **Step 5: Add PR watcher defaults to `config.yaml`**

In `config.yaml`, find the `pipeline:` section (around the `chaining:` block) and add:

```yaml
  # ── PR watching ──────────────────────────────────────────────────────────────
  # When enabled, the watcher also scans open PRs for failures and auto-fixes them.
  # Enable per-repo in repos-available/<repo>.yaml under settings:
  #   settings:
  #     watch_prs: true
  #     pr_fix_label: "ai-fix"
  #     pr_failure_pattern: "❌|FAILED|tests? failed"
  #     max_pr_retries: 3
  #     watch_draft_prs: false
  watch_prs: false                          # disabled globally; opt-in per repo
  pr_fix_label: "ai-fix"
  pr_failure_pattern: "❌|FAILED|tests? failed|test suite failed"
  max_pr_retries: 3
  watch_draft_prs: false
```

- [ ] **Step 6: Run all tests**

```bash
pytest tests/test_watcher_prs.py tests/test_watcher.py tests/test_watcher_config.py -v --tb=short 2>&1 | tail -30
```

Expected: all tests passing.

- [ ] **Step 7: Commit**

```bash
git add watcher.py config.yaml tests/test_watcher_prs.py
git commit -m "feat: add _watch_prs() and wire into watch() cycle with config defaults"
```

---

## Task 5: Update docs and enable for custom-cms

**Files:**
- Modify: `docs/operations-guide.md` (add PR Watcher section)
- Modify: `repos-available/custom-cms.yaml` (enable PR watching)

- [ ] **Step 1: Add PR Watcher section to `docs/operations-guide.md`**

Find the existing "Repo Watcher Config" section and add after it:

```markdown
## PR Watcher

The watcher can also monitor open pull requests for failures and automatically
run `run_revision()` to push fixes.

### Enable per repo

In `repos-available/<repo>.yaml`, add under `settings:`:

```yaml
settings:
  watch_prs: true              # enable PR watching for this repo
  pr_fix_label: "ai-fix"      # label on PR that triggers a fix run
  pr_failure_pattern: "❌|FAILED|tests? failed"  # regex matched against comments
  max_pr_retries: 3           # stop after this many fix attempts
  watch_draft_prs: false      # set true to also watch draft PRs
```

### How it works

On each watcher cycle, for repos with `watch_prs: true`, the watcher:

1. Fetches all open PRs in the target repo
2. For each PR, checks:
   - Does it have the `pr_fix_label` (e.g. `ai-fix`)? **OR**
   - Does any comment body match `pr_failure_pattern`?
3. Skips PRs that have `agent-running`, `agent-failed`, or have exhausted `max_pr_retries`
4. Runs `run_revision()` — re-runs engineer → reviewer → QA, pushes commits to the PR branch
5. Labels the PR `agent-complete` on success, or `agent-failed` if retries are exhausted

### Retry tracking

Each fix attempt adds an `ai-pr-fix-N` label to the PR. When N reaches `max_pr_retries`, the watcher stops and adds `agent-failed`.

To reset and retry: remove all `ai-pr-fix-N` labels and `agent-failed` from the PR.
```

- [ ] **Step 2: Enable PR watching for custom-cms**

Edit `repos-available/custom-cms.yaml` to add `watch_prs: true`:

```yaml
settings:
  watch_prs: true
  pr_fix_label: "ai-fix"
  max_pr_retries: 3
```

Check the current content of `repos-available/custom-cms.yaml` first and add the `settings:` block if it doesn't already have one, or extend it if it does.

- [ ] **Step 3: Run full test suite**

```bash
pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add docs/operations-guide.md repos-available/custom-cms.yaml
git commit -m "docs: add PR watcher docs and enable for custom-cms"
```

---

## Final verification

- [ ] Run full test suite one last time:

```bash
pytest tests/ --tb=short 2>&1 | tail -10
```

- [ ] Push both remotes:

```bash
git push origin master
git push public master
```
