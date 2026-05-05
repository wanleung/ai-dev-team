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


# ── Error handling tests (API helpers) ───────────────────────────────────────

def test_get_open_prs_raises_on_api_error(monkeypatch):
    """get_open_prs raises RuntimeError on API error."""
    from watcher import get_open_prs
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    error_response = _mock_response({"message": "Not Found"}, status_code=404)
    with patch("watcher.requests.get", return_value=error_response):
        with pytest.raises(RuntimeError, match="GitHub API error 404"):
            get_open_prs("owner/repo")


def test_get_pr_comments_raises_on_api_error(monkeypatch):
    """get_pr_comments raises RuntimeError on API error."""
    from watcher import get_pr_comments
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    error_response = _mock_response({"message": "Not Found"}, status_code=404)
    with patch("watcher.requests.get", return_value=error_response):
        with pytest.raises(RuntimeError, match="GitHub API error 404"):
            get_pr_comments("owner/repo", 42)


def test_get_open_prs_handles_missing_draft_field(monkeypatch):
    """get_open_prs handles PRs without draft field (treats as non-draft)."""
    from watcher import get_open_prs
    prs = [{"number": 1, "title": "No draft field", "labels": []}]
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    with patch("watcher.requests.get", return_value=_mock_response(prs)):
        result = get_open_prs("owner/repo", skip_drafts=True)
    assert len(result) == 1


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
