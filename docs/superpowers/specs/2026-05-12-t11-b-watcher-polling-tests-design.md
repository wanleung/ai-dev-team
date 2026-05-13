# T11-B Design: Watcher Polling Tests — check_waiting_issues + _process_resume_queue

**Date:** 2026-05-12
**Branch:** `t11-b-watcher-polling-tests`
**PR target:** `master`

---

## Problem Statement

`watcher.py` contains two critical production paths with 0% direct test coverage:

1. **`check_waiting_issues()`** (lines 1101–1184) — polls GitHub for issues labelled `agent-waiting`, finds human replies, writes resume trigger files, and swaps labels back to `agent-running`.
2. **`_process_resume_queue()`** (lines 1216–1280) — reads `.trigger` files from a queue directory, deserialises them, and returns pending tasks for the main dispatch loop.

These methods implement the entire clarification pause/resume flow. Bugs here would silently stall pipelines indefinitely.

---

## Task 1: `tests/test_watcher_waiting.py`

**File:** `tests/test_watcher_waiting.py` (new)

### Setup

Fixtures:
- `watcher_instance(tmp_path)` — constructs a `Watcher` with a real config pointing to `tmp_path`; monkeypatches `GithubClient` to return mock data
- `mock_github(monkeypatch)` — patches `watcher.GithubClient` with a `MagicMock` so no real HTTP is made

### Tests

**1. `test_check_waiting_issues_happy_path`**
- Setup: `list_issues_by_label` returns one issue with label `agent-waiting`; `get_issue_comments` returns two comments — the last one authored by a human (not the bot)
- Assert: `write_trigger_file` (or equivalent file write) is called with the issue data; `remove_label` called with `agent-waiting`; `add_label` called with `agent-running`

**2. `test_check_waiting_issues_no_waiting_issues`**
- Setup: `list_issues_by_label` returns empty list
- Assert: no trigger file written; no label changes

**3. `test_check_waiting_issues_no_human_reply`**
- Setup: issue has label `agent-waiting`; all comments are from the bot user
- Assert: no trigger file written; labels unchanged

**4. `test_check_waiting_issues_malformed_reply_skipped`**
- Setup: issue has a human reply but with empty body
- Assert: issue skipped (no trigger written, no label swap)

**5. `test_check_waiting_issues_multiple_issues`**
- Setup: two waiting issues, both with valid replies
- Assert: two trigger files written, both issues relabelled

### File I/O verification

Instead of mocking the file write, use `tmp_path` and verify actual `.trigger` file contents after calling `check_waiting_issues()`. This catches serialisation bugs that a mock would miss.

---

## Task 2: `tests/test_watcher_resume.py`

**File:** `tests/test_watcher_resume.py` (new)

### Setup

Fixtures:
- `resume_queue_dir(tmp_path)` — a directory path passed to the watcher as the trigger queue location
- `write_trigger(resume_queue_dir)` — helper that writes a valid `.trigger` JSON file atomically (via `os.replace`) and returns the path

### Tests

**1. `test_process_resume_queue_happy_path`**
- Setup: write one valid `.trigger` file with fields `issue_number`, `repo`, `pipeline`, `context`
- Call `_process_resume_queue()`
- Assert: returns list containing one task dict; trigger file is deleted after processing

**2. `test_process_resume_queue_empty_dir`**
- Setup: queue directory exists but is empty
- Assert: returns empty list; no exceptions

**3. `test_process_resume_queue_missing_dir`**
- Setup: queue directory does not exist
- Assert: returns empty list (no `FileNotFoundError` propagates)

**4. `test_process_resume_queue_malformed_trigger_skipped`**
- Setup: write a `.trigger` file with invalid JSON
- Assert: file is skipped (removed or left); no exception; returns empty list; `_log.warning` called

**5. `test_process_resume_queue_atomic_write_path`**
- Setup: simulate partial write by writing a temp file without calling `os.replace`
- Assert: incomplete temp file is not picked up by `_process_resume_queue()` (only `.trigger` extension files are processed)

**6. `test_process_resume_queue_multiple_triggers`**
- Setup: write three valid trigger files
- Assert: returns three tasks; all files removed

---

## Task 3: Final Verification

- Run the full test suite: all 1619 + new tests pass, 0 failures
- Run `pytest tests/test_watcher_waiting.py tests/test_watcher_resume.py -v` to confirm isolated pass

---

## Acceptance Criteria

- [ ] `check_waiting_issues()` has direct test coverage for happy path, no-issues, no-reply, malformed reply, multiple issues
- [ ] `_process_resume_queue()` has direct test coverage for happy path, empty dir, missing dir, malformed JSON, atomic write guard, multiple triggers
- [ ] Tests use real file I/O via `tmp_path` where relevant (not mocked writes)
- [ ] No existing tests broken
- [ ] Full suite: 0 failures
