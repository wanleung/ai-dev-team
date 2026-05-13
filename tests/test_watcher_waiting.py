# tests/test_watcher_waiting.py
"""Tests for watcher.check_waiting_issues()."""
import json
import os
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_checkpoint(workspace_dir: str, issue_number: int, pending_clarification: dict | None) -> str:
    """Write a minimal checkpoint JSON for the given issue and return its path.

    Only the 4 fields accessed by check_waiting_issues() are required;
    PipelineResult.from_dict() defaults missing keys to class attributes.
    """
    ckpt_dir = os.path.join(workspace_dir, f"issue_{issue_number}")
    os.makedirs(ckpt_dir, exist_ok=True)
    path = os.path.join(ckpt_dir, f"checkpoint_{issue_number}.json")
    data = {
        "requirement": "Build a feature",
        "issue_number": issue_number,
        "pending_clarification": pending_clarification,
        "clarification_history": [],
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
    remove_calls = []
    monkeypatch.setattr("watcher.remove_label", lambda r, n, l: remove_calls.append(l))
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
    remove_calls = []
    monkeypatch.setattr("watcher.remove_label", lambda r, n, l: remove_calls.append(l))
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
    remove_calls = []
    monkeypatch.setattr("watcher.remove_label", lambda r, n, l: remove_calls.append((n, l)))
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
