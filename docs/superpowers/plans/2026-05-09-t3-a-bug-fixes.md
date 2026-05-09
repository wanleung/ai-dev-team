# T3-A: Bug Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two concrete bugs discovered in the post-T2 analysis: (1) the watcher can double-process the same GitHub issue in parallel within the same process due to missing in-memory deduplication; (2) the `stage_name` field in `DLQEntry` is hardcoded to `"pipeline"` so retry operators cannot filter by which pipeline stage failed.

**Architecture:** Both fixes are surgical and independent. Task 1 adds a module-level `_ACTIVE_ISSUES` dict (guarded by a threading.Lock) to watcher.py so each issue number is only processed once at a time. Task 2 extends `DLQEntry` with a `stage_name: str` field (default `"pipeline"` for backwards compat), threads the failing stage name through `run_pipeline()`, and updates `_cmd_list_dlq` to show it.

**Tech Stack:** Python 3.11+, `threading.Lock`, pytest.

**Branch:** `t3-a-bug-fixes` (from master)

---

### Task 1: Per-issue in-memory dedup lock in watcher.py

**Files:**
- Modify: `watcher.py` (lines ~30-40 for module vars; ~316 `run_pipeline` signature; ~440-465 DLQ enqueue; ~1325-1355 executor loop)
- Test: `tests/test_watcher_issue_dedup.py` (new)

**Context:** `watch()` builds `by_repo` from the GitHub API and submits each task to a `ThreadPoolExecutor`. If the GitHub API returns the same issue twice (pagination edge case) or if two concurrent scans overlap, the same issue can be processed simultaneously. Fix: maintain a process-level `dict[int, threading.Lock]` (`_ACTIVE_ISSUES`). Before processing, try to acquire the per-issue lock non-blocking; skip if already held.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_watcher_issue_dedup.py
"""Verify that the same issue number is never processed twice concurrently."""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import watcher


def test_duplicate_issue_skipped_while_active():
    """If issue #42 is currently being processed, a second submission is skipped."""
    call_log: list[int] = []
    barrier = threading.Barrier(2, timeout=2.0)

    def slow_pipeline(issue, *args, **kwargs):
        call_log.append(issue["number"])
        try:
            barrier.wait()  # wait for second thread to arrive (or time out)
        except threading.BrokenBarrierError:
            pass
        time.sleep(0.05)

    issue = {"number": 42, "title": "Test Issue", "body": ""}
    tracker_repo = "owner/tracker"

    # Simulate two concurrent calls for the same issue
    with patch("watcher._ACTIVE_ISSUES_LOCK", threading.Lock()):
        with patch.dict("watcher._ACTIVE_ISSUES", {}, clear=True):
            threads = []
            for _ in range(2):
                t = threading.Thread(
                    target=watcher._run_with_issue_lock,
                    args=(slow_pipeline, issue, tracker_repo, "owner/target",
                          "ai-task", "gpt-4.1", 2, "/tmp", False, MagicMock()),
                )
                threads.append(t)
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=3.0)

    # Barrier timeout means one thread couldn't reach it — i.e., it was skipped
    assert len(call_log) == 1, f"Expected 1 call, got {len(call_log)}: {call_log}"


def test_issue_lock_released_after_completion():
    """After processing completes, the issue lock is removed from _ACTIVE_ISSUES."""
    call_log: list[int] = []

    def fast_pipeline(issue, *args, **kwargs):
        call_log.append(issue["number"])

    issue = {"number": 99, "title": "Another", "body": ""}

    with patch("watcher._ACTIVE_ISSUES_LOCK", threading.Lock()):
        with patch.dict("watcher._ACTIVE_ISSUES", {}, clear=True):
            watcher._run_with_issue_lock(
                fast_pipeline, issue, "owner/tracker", "owner/target",
                "ai-task", "gpt-4.1", 2, "/tmp", False, MagicMock(),
            )
            import watcher as w
            assert 99 not in w._ACTIVE_ISSUES, "Lock entry should be cleaned up after run"

    assert call_log == [99]
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd /home/wanleung/Projects/ai-software-house
python3 -m pytest tests/test_watcher_issue_dedup.py -v
```

Expected: `AttributeError: module 'watcher' has no attribute '_ACTIVE_ISSUES'`

- [ ] **Step 3: Add module-level dedup state and `_run_with_issue_lock` helper to watcher.py**

Add immediately after the existing module-level `_log = logging.getLogger(__name__)` line (around line 55):

```python
# ── Per-issue dedup lock ──────────────────────────────────────────────────────
# Prevents the same GitHub issue from being processed twice concurrently within
# this process (e.g. duplicate API results, overlapping watch() cycles).
_ACTIVE_ISSUES: dict[int, threading.Lock] = {}
_ACTIVE_ISSUES_LOCK = threading.Lock()


def _run_with_issue_lock(fn, issue: dict, *args, **kwargs) -> None:
    """Acquire a per-issue lock and call fn(issue, *args, **kwargs).

    If the lock is already held (issue already being processed), logs a debug
    message and returns immediately without calling fn.
    """
    issue_number = issue["number"]
    with _ACTIVE_ISSUES_LOCK:
        if issue_number in _ACTIVE_ISSUES:
            _log.debug(
                "[Watcher] Issue #%d already being processed — skipping duplicate",
                issue_number,
            )
            return
        lock = threading.Lock()
        lock.acquire()
        _ACTIVE_ISSUES[issue_number] = lock

    try:
        fn(issue, *args, **kwargs)
    finally:
        with _ACTIVE_ISSUES_LOCK:
            _ACTIVE_ISSUES.pop(issue_number, None)
```

- [ ] **Step 4: Wire `_run_with_issue_lock` into the executor loop**

Find the block in `watch()` that submits tasks (around line 1350). Replace the direct `_run_with_global_cap` submission:

**Before:**
```python
fut = ex.submit(
    ctx.run,
    _run_with_global_cap,
    t["issue"], t["tracker_repo"], t["default_target"],
    t["label"], t.get("model", "gpt-4.1"), t.get("num_engineers", 2), log_dir, dry_run, logger,
)
```

**After:**
```python
fut = ex.submit(
    ctx.run,
    _run_with_issue_lock,
    _run_with_global_cap,
    t["issue"], t["tracker_repo"], t["default_target"],
    t["label"], t.get("model", "gpt-4.1"), t.get("num_engineers", 2), log_dir, dry_run, logger,
)
```

- [ ] **Step 5: Run tests**

```bash
python3 -m pytest tests/test_watcher_issue_dedup.py tests/test_watcher_dlq_cli.py -v
```

Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add watcher.py tests/test_watcher_issue_dedup.py
git commit -m "fix(watcher): add per-issue dedup lock to prevent double-processing"
```

---

### Task 2: Add `stage_name` to `DLQEntry` and thread it through `run_pipeline`

**Files:**
- Modify: `core/dead_letter.py` (DLQEntry dataclass ~line 42)
- Modify: `watcher.py` (run_pipeline signature ~line 316; DLQ enqueue ~line 447)
- Test: `tests/test_dead_letter.py` (add one test)

**Context:** `DLQEntry.error` always has `stage="pipeline"` hardcoded (watcher.py line 459). When operators use `--list-dlq` or write retry scripts, they cannot filter "only retry failed PRD stages" vs "only retry failed implementation stages". Fix: add `stage_name: str = "pipeline"` to `DLQEntry` and thread the actual failing stage through from the exception context.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_dead_letter.py`:

```python
def test_dlq_entry_stage_name_field():
    """DLQEntry accepts and stores a stage_name field."""
    from core.dead_letter import DLQEntry
    entry = DLQEntry(
        id="test-1",
        issue_number=1,
        tracker_repo="owner/tracker",
        label="ai-task",
        model="gpt-4.1",
        num_engineers=2,
        failed_at="2026-05-09T00:00:00Z",
        error={"code": "STAGE_ERROR", "message": "boom"},
        stage_name="architect",
    )
    assert entry.stage_name == "architect"


def test_dlq_entry_stage_name_defaults_to_pipeline():
    """DLQEntry.stage_name defaults to 'pipeline' for backward compatibility."""
    from core.dead_letter import DLQEntry
    entry = DLQEntry(
        id="test-2",
        issue_number=2,
        tracker_repo="owner/tracker",
        label="ai-task",
        model="gpt-4.1",
        num_engineers=2,
        failed_at="2026-05-09T00:00:00Z",
        error={},
    )
    assert entry.stage_name == "pipeline"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python3 -m pytest tests/test_dead_letter.py::test_dlq_entry_stage_name_field tests/test_dead_letter.py::test_dlq_entry_stage_name_defaults_to_pipeline -v
```

Expected: `TypeError: DLQEntry.__init__() got an unexpected keyword argument 'stage_name'`

- [ ] **Step 3: Add `stage_name` field to `DLQEntry`**

In `core/dead_letter.py`, update the `DLQEntry` dataclass:

```python
@dataclass
class DLQEntry:
    """Represents a single failed pipeline task stored in the dead-letter queue."""

    id: str
    issue_number: int
    tracker_repo: str
    label: str
    model: str
    num_engineers: int
    failed_at: str
    error: dict[str, Any]
    target_repo: str = ""
    attempt_count: int = 1
    stage_name: str = "pipeline"  # which pipeline stage failed; "pipeline" = unknown/fatal
```

- [ ] **Step 4: Update watcher.py `run_pipeline` to capture stage_name**

In `watcher.py`, the `run_pipeline` function catches pipeline exceptions. The `PipelineError` already carries a `stage` field. Update the DLQ enqueue block (around line 444-465) to read it:

```python
if dlq is not None:
    from core.dead_letter import DLQEntry
    from core.errors import PipelineError
    _pipeline_error = PipelineError(
        code="AGENT_CRASH",
        stage="pipeline",
        message=_sanitise(str(exc), os.environ.get("GITHUB_TOKEN", "")),
        severity="fatal",
    )
    _dlq_entry = DLQEntry(
        id=str(uuid.uuid4()),
        issue_number=_issue_number,
        tracker_repo=tracker_repo,
        target_repo=_target_repo,
        label=label,
        model=model,
        num_engineers=num_engineers,
        failed_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        error=_pipeline_error.to_dict(),
        stage_name=getattr(exc, "stage", None) or "pipeline",
    )
```

- [ ] **Step 5: Update `_cmd_list_dlq` to show stage_name**

In `watcher.py` around line 1424 in `_cmd_list_dlq`, add `stage_name` to the table output:

```python
def _cmd_list_dlq(cfg: dict) -> None:
    # ... existing setup code ...
    for entry in entries:
        print(
            f"  #{entry.issue_number:5d}  "
            f"stage={entry.stage_name:<20s}  "
            f"attempts={entry.attempt_count}  "
            f"model={entry.model:<15s}  "
            f"failed={entry.failed_at}  "
            f"{entry.error.get('message', '')[:60]}"
        )
```

- [ ] **Step 6: Run all dead_letter and DLQ tests**

```bash
python3 -m pytest tests/test_dead_letter.py tests/test_watcher_dlq_cli.py -v
```

Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add core/dead_letter.py watcher.py tests/test_dead_letter.py
git commit -m "fix(dlq): add stage_name field to DLQEntry for retry filtering"
```

---

### Task 3: Branch, push, PR

- [ ] **Step 1: Create branch and push**

```bash
git checkout -b t3-a-bug-fixes master
# (cherry-pick or re-apply commits 1 and 2 if done on master, or develop directly on branch)
git push -u origin t3-a-bug-fixes
```

- [ ] **Step 2: Create PR**

```bash
gh pr create \
  --title "fix(bugs): T3-A — per-issue dedup lock and DLQ stage_name field" \
  --body "## Summary
- Add \`_run_with_issue_lock()\` to watcher to prevent same GitHub issue being processed twice concurrently (e.g. duplicate API results, overlapping watch cycles)
- Add \`stage_name: str = 'pipeline'\` field to \`DLQEntry\` so operators can filter retries by which stage failed
- Update \`_cmd_list_dlq\` to display \`stage_name\` in table output

## Test Plan
- [ ] \`tests/test_watcher_issue_dedup.py\` — barrier-based concurrency test verifies dedup
- [ ] \`tests/test_dead_letter.py\` — 2 new tests for stage_name field
- [ ] All existing watcher and DLQ tests still pass" \
  --base master
```
