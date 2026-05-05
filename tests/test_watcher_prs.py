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
