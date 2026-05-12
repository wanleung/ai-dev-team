# T11-B: Watcher Polling Tests — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Write direct tests for `check_waiting_issues()` and `_process_resume_queue()` in `watcher.py`, covering the full happy path and all error branches.

**Architecture:** Both functions are module-level (not methods). Tests mock GitHub HTTP calls via `monkeypatch` on `watcher._get_issues_by_label`, `watcher._get_issue_comments`, `watcher.remove_label`, and `watcher.add_label`. File I/O for checkpoints and trigger files uses `tmp_path` (real filesystem) so serialisation bugs are caught.

**Tech Stack:** `pytest`, `pytest-mock` / `monkeypatch`, `tmp_path` fixture, `json`, `fcntl` (stdlib).

---

### Task 1: Tests for `check_waiting_issues()`

**Files:**
- Create: `tests/test_watcher_waiting.py`

- [ ] **Step 1: Create the test file**

  ```python
  # tests/test_watcher_waiting.py
  """Tests for watcher.check_waiting_issues()."""
  import json
  import os
  from pathlib import Path
  from unittest.mock import MagicMock

  import pytest


  # ---------------------------------------------------------------------------
  # Helpers
  # ---------------------------------------------------------------------------

  def _write_checkpoint(workspace_dir: str, issue_number: int, pending_clarification: dict | None) -> str:
      """Write a minimal checkpoint JSON for the given issue and return its path."""
      ckpt_dir = os.path.join(workspace_dir, f"issue_{issue_number}")
      os.makedirs(ckpt_dir, exist_ok=True)
      path = os.path.join(ckpt_dir, f"checkpoint_{issue_number}.json")
      data = {
          "requirement": "Build a feature",
          "issue_number": issue_number,
          "pending_clarification": pending_clarification,
          "clarification_history": [],
          "project_name": "test-project",
          "errors": [],
          "stages_completed": [],
          "current_stage": None,
          "pr_url": None,
          "branch_name": None,
          "design_doc_path": None,
          "checklist_path": None,
          "summary": None,
      }
      with open(path, "w") as f:
          json.dump(data, f)
      return path


  def _make_issue(number: int, title: str = "Test issue") -> dict:
      return {"number": number, "title": title}


  def _make_comment(comment_id: int, body: str, login: str = "human-user") -> dict:
      return {"id": comment_id, "body": body, "user": {"login": login}}


  # ---------------------------------------------------------------------------
  # Tests
  # ---------------------------------------------------------------------------

  def test_happy_path_writes_trigger_and_relabels(tmp_path, monkeypatch):
      """Issue with pending clarification + human reply → trigger written, label swapped."""
      workspace = str(tmp_path)
      issue_number = 42
      question_comment_id = 100
      pending = {
          "stage": "pm",
          "questions": ["What is the budget?"],
          "qa_rounds": 1,
          "question_comment_id": question_comment_id,
      }
      _write_checkpoint(workspace, issue_number, pending)

      monkeypatch.setattr(
          "watcher._get_issues_by_label",
          lambda repo, label, token: [_make_issue(issue_number)],
      )
      monkeypatch.setattr(
          "watcher._get_issue_comments",
          lambda repo, num, token: [
              _make_comment(question_comment_id, "Bot question", login="bot"),  # the question
              _make_comment(101, "My answer is $10k", login="human-user"),       # human reply
          ],
      )
      remove_calls = []
      add_calls = []
      monkeypatch.setattr("watcher.remove_label", lambda repo, num, label: remove_calls.append(label))
      monkeypatch.setattr("watcher.add_label", lambda repo, num, label: add_calls.append(label))

      from watcher import check_waiting_issues
      check_waiting_issues(
          github_token="fake-token",
          tracker_repos=["owner/repo"],
          workspace_dir=workspace,
          bot_login="bot",
      )

      # Trigger file written
      trigger_path = os.path.join(workspace, "resume_queue", f"resume_{issue_number}.json")
      assert os.path.isfile(trigger_path), "resume trigger file should be created"
      trigger_data = json.loads(Path(trigger_path).read_text())
      assert trigger_data["issue_number"] == issue_number

      # Labels swapped
      assert "agent-waiting" in remove_calls
      assert "agent-running" in add_calls

      # Checkpoint updated: clarification_history has one entry, pending_clarification is None
      ckpt_path = os.path.join(workspace, f"issue_{issue_number}", f"checkpoint_{issue_number}.json")
      ckpt = json.loads(Path(ckpt_path).read_text())
      assert ckpt["pending_clarification"] is None
      assert len(ckpt["clarification_history"]) == 1
      assert ckpt["clarification_history"][0]["answers"] == ["My answer is $10k"]


  def test_no_waiting_issues_does_nothing(tmp_path, monkeypatch):
      """No agent-waiting issues → no trigger files, no label changes."""
      monkeypatch.setattr("watcher._get_issues_by_label", lambda repo, label, token: [])
      remove_calls = []
      add_calls = []
      monkeypatch.setattr("watcher.remove_label", lambda r, n, l: remove_calls.append(l))
      monkeypatch.setattr("watcher.add_label", lambda r, n, l: add_calls.append(l))

      from watcher import check_waiting_issues
      check_waiting_issues("tok", ["owner/repo"], str(tmp_path), "bot")

      resume_dir = os.path.join(str(tmp_path), "resume_queue")
      trigger_count = len(os.listdir(resume_dir)) if os.path.isdir(resume_dir) else 0
      assert trigger_count == 0
      assert remove_calls == []
      assert add_calls == []


  def test_issue_with_no_human_reply_is_skipped(tmp_path, monkeypatch):
      """Issue has pending clarification but all comments are from the bot → skipped."""
      workspace = str(tmp_path)
      issue_number = 7
      pending = {"stage": "pm", "questions": ["Q?"], "qa_rounds": 1, "question_comment_id": 200}
      _write_checkpoint(workspace, issue_number, pending)

      monkeypatch.setattr(
          "watcher._get_issues_by_label",
          lambda r, l, t: [_make_issue(issue_number)],
      )
      monkeypatch.setattr(
          "watcher._get_issue_comments",
          lambda r, n, t: [
              _make_comment(200, "What is the budget?", login="bot"),
              # no human reply follows
          ],
      )
      add_calls = []
      monkeypatch.setattr("watcher.remove_label", MagicMock())
      monkeypatch.setattr("watcher.add_label", lambda r, n, l: add_calls.append(l))

      from watcher import check_waiting_issues
      check_waiting_issues("tok", ["owner/repo"], workspace, "bot")

      trigger_path = os.path.join(workspace, "resume_queue", f"resume_{issue_number}.json")
      assert not os.path.isfile(trigger_path)
      assert "agent-running" not in add_calls


  def test_issue_without_checkpoint_is_skipped(tmp_path, monkeypatch):
      """Issue labelled agent-waiting but no checkpoint found → silently skipped."""
      monkeypatch.setattr(
          "watcher._get_issues_by_label",
          lambda r, l, t: [_make_issue(99)],
      )
      add_calls = []
      monkeypatch.setattr("watcher.remove_label", MagicMock())
      monkeypatch.setattr("watcher.add_label", lambda r, n, l: add_calls.append(l))

      from watcher import check_waiting_issues
      check_waiting_issues("tok", ["owner/repo"], str(tmp_path), "bot")

      assert "agent-running" not in add_calls


  def test_multiple_waiting_issues_all_processed(tmp_path, monkeypatch):
      """Two issues with human replies → two triggers written, both relabelled."""
      workspace = str(tmp_path)
      for num, qid in [(10, 300), (11, 301)]:
          _write_checkpoint(workspace, num, {
              "stage": "pm", "questions": ["Q?"], "qa_rounds": 1, "question_comment_id": qid,
          })

      monkeypatch.setattr(
          "watcher._get_issues_by_label",
          lambda r, l, t: [_make_issue(10), _make_issue(11)],
      )

      def fake_comments(repo, num, token):
          qid = 300 if num == 10 else 301
          return [
              _make_comment(qid, "Bot Q", login="bot"),
              _make_comment(qid + 100, "Human reply", login="human"),
          ]

      monkeypatch.setattr("watcher._get_issue_comments", fake_comments)
      add_calls = []
      monkeypatch.setattr("watcher.remove_label", MagicMock())
      monkeypatch.setattr("watcher.add_label", lambda r, n, l: add_calls.append((n, l)))

      from watcher import check_waiting_issues
      check_waiting_issues("tok", ["owner/repo"], workspace, "bot")

      for num in [10, 11]:
          trigger = os.path.join(workspace, "resume_queue", f"resume_{num}.json")
          assert os.path.isfile(trigger), f"trigger for issue #{num} should exist"
      assert sum(1 for _, l in add_calls if l == "agent-running") == 2


  def test_github_api_error_on_list_issues_continues(tmp_path, monkeypatch, caplog):
      """If listing issues fails for one repo, watcher logs warning and continues."""
      import logging
      call_count = {"n": 0}

      def flaky_list(repo, label, token):
          call_count["n"] += 1
          if call_count["n"] == 1:
              raise RuntimeError("GitHub 503")
          return []

      monkeypatch.setattr("watcher._get_issues_by_label", flaky_list)

      from watcher import check_waiting_issues
      with caplog.at_level(logging.WARNING, logger="watcher"):
          check_waiting_issues("tok", ["bad/repo", "ok/repo"], str(tmp_path), "bot")

      assert any("Could not list" in r.message or "503" in r.message for r in caplog.records)
  ```

- [ ] **Step 2: Run tests**

  ```bash
  pytest tests/test_watcher_waiting.py -v
  ```
  Expected: All 6 tests pass. If any fail, read the error and fix the helper functions (e.g., `_write_checkpoint` may need additional fields that `PipelineResult.from_dict()` requires — check `orchestrator.py:482` for all required keys).

- [ ] **Step 3: Commit**

  ```bash
  git add tests/test_watcher_waiting.py
  git commit -m "test: add direct tests for check_waiting_issues() in watcher.py"
  ```

---

### Task 2: Tests for `_process_resume_queue()`

**Files:**
- Create: `tests/test_watcher_resume.py`

- [ ] **Step 1: Create the test file**

  ```python
  # tests/test_watcher_resume.py
  """Tests for watcher._process_resume_queue()."""
  import fcntl
  import glob
  import json
  import logging
  import os
  from pathlib import Path
  from unittest.mock import MagicMock

  import pytest


  # ---------------------------------------------------------------------------
  # Helpers
  # ---------------------------------------------------------------------------

  def _make_trigger(workspace: str, issue_number: int, extra: dict | None = None) -> str:
      """Write a valid resume trigger file atomically; return its path."""
      trigger_dir = os.path.join(workspace, "resume_queue")
      os.makedirs(trigger_dir, exist_ok=True)
      trigger_path = os.path.join(trigger_dir, f"resume_{issue_number}.json")
      tmp = trigger_path + ".tmp"
      payload = {
          "issue_number": issue_number,
          "issue_title": f"Feature #{issue_number}",
          "requirement": f"Implement feature {issue_number}",
          **(extra or {}),
      }
      with open(tmp, "w") as f:
          json.dump(payload, f)
      os.replace(tmp, trigger_path)
      return trigger_path


  def _default_kwargs(workspace: str) -> dict:
      from pathlib import Path
      return dict(
          workspace_dir=workspace,
          tracker_repos=["owner/repo"],
          default_targets={"owner/repo": "main"},
          model="gpt-4",
          num_engineers=1,
          log_dir=Path(workspace) / "logs",
          dry_run=False,
          logger=MagicMock(),
      )


  # ---------------------------------------------------------------------------
  # Tests
  # ---------------------------------------------------------------------------

  def test_happy_path_returns_task_and_deletes_trigger(tmp_path, monkeypatch):
      """Valid trigger file → task returned, file deleted."""
      workspace = str(tmp_path)
      trigger_path = _make_trigger(workspace, 42)

      # Mock GitHub fetch of the issue
      fake_issue = {"number": 42, "title": "Build X", "body": "Details"}
      mock_resp = MagicMock()
      mock_resp.ok = True
      mock_resp.json.return_value = fake_issue
      monkeypatch.setattr("watcher.requests.get", lambda *a, **kw: mock_resp)

      from watcher import _process_resume_queue
      tasks = _process_resume_queue(**_default_kwargs(workspace))

      assert len(tasks) == 1
      assert tasks[0]["issue"]["number"] == 42
      assert tasks[0]["tracker_repo"] == "owner/repo"
      assert not os.path.isfile(trigger_path), "trigger file should be deleted after processing"


  def test_empty_resume_queue_returns_empty_list(tmp_path, monkeypatch):
      """No trigger files → empty list, no errors."""
      workspace = str(tmp_path)
      os.makedirs(os.path.join(workspace, "resume_queue"))

      from watcher import _process_resume_queue
      tasks = _process_resume_queue(**_default_kwargs(workspace))

      assert tasks == []


  def test_missing_resume_queue_dir_returns_empty_list(tmp_path, monkeypatch):
      """Queue directory doesn't exist → empty list, no FileNotFoundError."""
      workspace = str(tmp_path)  # resume_queue subdir NOT created

      from watcher import _process_resume_queue
      tasks = _process_resume_queue(**_default_kwargs(workspace))

      assert tasks == []


  def test_malformed_json_trigger_is_skipped(tmp_path, monkeypatch, caplog):
      """Trigger file with invalid JSON is skipped; warning logged; no exception."""
      workspace = str(tmp_path)
      trigger_dir = os.path.join(workspace, "resume_queue")
      os.makedirs(trigger_dir)
      bad_path = os.path.join(trigger_dir, "resume_999.json")
      with open(bad_path, "w") as f:
          f.write("NOT VALID JSON {{{")

      from watcher import _process_resume_queue
      with caplog.at_level(logging.WARNING, logger="watcher"):
          tasks = _process_resume_queue(**_default_kwargs(workspace))

      assert tasks == []


  def test_incomplete_trigger_not_picked_up(tmp_path, monkeypatch):
      """A .tmp file (partial write before os.replace) is not processed."""
      workspace = str(tmp_path)
      trigger_dir = os.path.join(workspace, "resume_queue")
      os.makedirs(trigger_dir)
      # Write only the .tmp file, NOT the final .json
      tmp_path_file = os.path.join(trigger_dir, "resume_55.json.tmp")
      with open(tmp_path_file, "w") as f:
          json.dump({"issue_number": 55, "issue_title": "Incomplete"}, f)

      from watcher import _process_resume_queue
      tasks = _process_resume_queue(**_default_kwargs(workspace))

      assert tasks == []


  def test_multiple_triggers_all_processed(tmp_path, monkeypatch):
      """Three valid trigger files → three tasks returned, all files deleted."""
      workspace = str(tmp_path)
      for num in [1, 2, 3]:
          _make_trigger(workspace, num)

      def fake_get(url, headers=None, timeout=None):
          issue_num = int(url.split("/")[-1])
          resp = MagicMock()
          resp.ok = True
          resp.json.return_value = {"number": issue_num, "title": f"Issue {issue_num}"}
          return resp

      monkeypatch.setattr("watcher.requests.get", fake_get)

      from watcher import _process_resume_queue
      tasks = _process_resume_queue(**_default_kwargs(workspace))

      assert len(tasks) == 3
      trigger_dir = os.path.join(workspace, "resume_queue")
      remaining = glob.glob(os.path.join(trigger_dir, "resume_*.json"))
      assert remaining == [], "all trigger files should be deleted"


  def test_github_fetch_failure_keeps_trigger_for_retry(tmp_path, monkeypatch, caplog):
      """If GitHub fetch fails, trigger file is kept for next cycle."""
      workspace = str(tmp_path)
      trigger_path = _make_trigger(workspace, 77)

      mock_resp = MagicMock()
      mock_resp.ok = False
      mock_resp.status_code = 503
      monkeypatch.setattr("watcher.requests.get", lambda *a, **kw: mock_resp)

      from watcher import _process_resume_queue
      with caplog.at_level(logging.WARNING, logger="watcher"):
          tasks = _process_resume_queue(**_default_kwargs(workspace))

      assert tasks == []
      assert os.path.isfile(trigger_path), "trigger should be retained on fetch failure"
  ```

- [ ] **Step 2: Run tests**

  ```bash
  pytest tests/test_watcher_resume.py -v
  ```
  Expected: All 7 tests pass. If `_process_resume_queue` uses `requests.get` with a different import path (e.g., `import requests` at module level), adjust the monkeypatch target to `watcher.requests.get`.

- [ ] **Step 3: Commit**

  ```bash
  git add tests/test_watcher_resume.py
  git commit -m "test: add direct tests for _process_resume_queue() in watcher.py"
  ```

---

### Task 3: Final Verification

- [ ] **Step 1: Run all new tests together**

  ```bash
  pytest tests/test_watcher_waiting.py tests/test_watcher_resume.py -v
  ```
  Expected: All 13 tests pass.

- [ ] **Step 2: Run full suite**

  ```bash
  pytest --tb=short -q
  ```
  Expected: 0 failures.

- [ ] **Step 3: Push branch**

  ```bash
  git push origin t11-b-watcher-polling-tests
  ```
