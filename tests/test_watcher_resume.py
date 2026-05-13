# tests/test_watcher_resume.py
"""Tests for watcher._process_resume_queue()."""
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_kwargs(workspace: str) -> dict:
    """Return default arguments for _process_resume_queue()."""
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


def _write_trigger(workspace_dir: str, issue_number: int, issue_title: str = "Test issue") -> str:
    """Write a minimal resume trigger JSON and return its path."""
    trigger_dir = os.path.join(workspace_dir, "resume_queue")
    os.makedirs(trigger_dir, exist_ok=True)
    trigger_path = os.path.join(trigger_dir, f"resume_{issue_number}.json")
    with open(trigger_path, "w") as f:
        json.dump({
            "issue_number": issue_number,
            "issue_title": issue_title,
        }, f)
    return trigger_path


def _make_issue_response(number: int, title: str = "Test issue") -> dict:
    """Create a mock GitHub issue API response."""
    return {
        "number": number,
        "title": title,
        "body": "Issue body",
        "html_url": f"https://github.com/owner/repo/issues/{number}",
        "labels": [{"name": "ai-feature", "color": "0e8a16"}],
        "state": "open",
        "pull_request": None,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_happy_path_returns_task_and_deletes_trigger(tmp_path, monkeypatch):
    """Valid trigger → task returned, trigger file deleted."""
    workspace = str(tmp_path)
    issue_number = 42
    trigger_path = _write_trigger(workspace, issue_number, "Build a feature")

    # Mock successful GitHub fetch
    mock_response = Mock()
    mock_response.ok = True
    mock_response.json.return_value = _make_issue_response(issue_number, "Build a feature")
    monkeypatch.setattr("watcher.requests.get", lambda *args, **kwargs: mock_response)

    from watcher import _process_resume_queue
    tasks = _process_resume_queue(**_default_kwargs(workspace))

    # Task returned with expected fields
    assert len(tasks) == 1
    task = tasks[0]
    assert task["issue"]["number"] == issue_number
    assert task["tracker_repo"] == "owner/repo"
    assert task["default_target"] == "main"
    assert task["label"] == "ai-feature"
    assert task["model"] == "gpt-4"
    assert task["num_engineers"] == 1

    # Trigger file deleted
    assert not os.path.isfile(trigger_path), "Trigger file should be deleted after successful processing"


def test_empty_resume_queue_returns_empty_list(tmp_path):
    """Queue dir exists but empty → []."""
    workspace = str(tmp_path)
    # Create empty resume_queue directory
    os.makedirs(os.path.join(workspace, "resume_queue"))

    from watcher import _process_resume_queue
    tasks = _process_resume_queue(**_default_kwargs(workspace))

    assert tasks == []


def test_missing_resume_queue_dir_returns_empty_list(tmp_path):
    """Queue dir doesn't exist → []."""
    workspace = str(tmp_path)
    # Don't create resume_queue directory

    from watcher import _process_resume_queue
    tasks = _process_resume_queue(**_default_kwargs(workspace))

    assert tasks == []


def test_malformed_json_trigger_is_skipped(tmp_path, caplog):
    """Invalid JSON trigger → [], warning logged."""
    workspace = str(tmp_path)
    trigger_dir = os.path.join(workspace, "resume_queue")
    os.makedirs(trigger_dir, exist_ok=True)
    
    # Write invalid JSON
    trigger_path = os.path.join(trigger_dir, "resume_99.json")
    with open(trigger_path, "w") as f:
        f.write("{invalid json")

    from watcher import _process_resume_queue
    tasks = _process_resume_queue(**_default_kwargs(workspace))

    assert tasks == []
    # Trigger file should still exist (not deleted due to error)
    assert os.path.isfile(trigger_path)
    # Check warning was logged
    assert "Could not load watcher entry" in caplog.text


def test_incomplete_trigger_not_picked_up(tmp_path):
    """.tmp file (not .json) not processed → []."""
    workspace = str(tmp_path)
    trigger_dir = os.path.join(workspace, "resume_queue")
    os.makedirs(trigger_dir, exist_ok=True)
    
    # Write a .tmp file (incomplete trigger)
    tmp_path_file = os.path.join(trigger_dir, "resume_42.tmp")
    with open(tmp_path_file, "w") as f:
        json.dump({"issue_number": 42, "issue_title": "Test"}, f)

    from watcher import _process_resume_queue
    tasks = _process_resume_queue(**_default_kwargs(workspace))

    assert tasks == []
    # .tmp file should still exist (wasn't touched)
    assert os.path.isfile(tmp_path_file)


def test_multiple_triggers_all_processed(tmp_path, monkeypatch):
    """3 triggers → 3 tasks, all files deleted."""
    workspace = str(tmp_path)
    
    # Write 3 triggers
    trigger_paths = []
    for issue_num in [10, 20, 30]:
        trigger_paths.append(_write_trigger(workspace, issue_num, f"Feature {issue_num}"))

    # Mock successful GitHub fetch for all issues
    def mock_get(url, *args, **kwargs):
        # Extract issue number from URL
        issue_num = int(url.split("/")[-1])
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = _make_issue_response(issue_num, f"Feature {issue_num}")
        return mock_response
    
    monkeypatch.setattr("watcher.requests.get", mock_get)

    from watcher import _process_resume_queue
    tasks = _process_resume_queue(**_default_kwargs(workspace))

    # All 3 tasks returned
    assert len(tasks) == 3
    issue_numbers = [task["issue"]["number"] for task in tasks]
    assert sorted(issue_numbers) == [10, 20, 30]

    # All trigger files deleted
    for trigger_path in trigger_paths:
        assert not os.path.isfile(trigger_path), f"Trigger {trigger_path} should be deleted"


def test_github_fetch_failure_keeps_trigger_for_retry(tmp_path, monkeypatch, caplog):
    """GitHub 503 → trigger file kept."""
    workspace = str(tmp_path)
    issue_number = 42
    trigger_path = _write_trigger(workspace, issue_number, "Flaky feature")

    # Mock GitHub fetch failure (503 Service Unavailable)
    mock_response = Mock()
    mock_response.ok = False
    mock_response.status_code = 503
    monkeypatch.setattr("watcher.requests.get", lambda *args, **kwargs: mock_response)

    from watcher import _process_resume_queue
    tasks = _process_resume_queue(**_default_kwargs(workspace))

    # No tasks returned (fetch failed)
    assert tasks == []

    # Trigger file kept for retry
    assert os.path.isfile(trigger_path), "Trigger file should be kept after GitHub fetch failure"
    
    # Warning logged about keeping trigger
    assert "keeping trigger for retry" in caplog.text
