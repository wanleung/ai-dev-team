"""Tests for new PR read methods and label management on GitHubClient."""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call
import base64

import pytest

from github_client import GitHubClient


@pytest.fixture
def client():
    return GitHubClient(repo="owner/repo", github_token="tok")


def _mock_request(client, return_value):
    """Patch _request to return a fixed value."""
    client._request = MagicMock(return_value=return_value)


# ── get_pr ────────────────────────────────────────────────────────────────────

def test_get_pr_calls_correct_endpoint(client):
    _mock_request(client, {"number": 42, "head": {"ref": "feature/x"}})
    result = client.get_pr(42)
    client._request.assert_called_once_with("GET", "/repos/owner/repo/pulls/42")
    assert result["number"] == 42


# ── get_pr_review_comments ────────────────────────────────────────────────────

def test_get_pr_review_comments_returns_list(client):
    _mock_request(client, [{"id": 1, "body": "Fix this"}, {"id": 2, "body": "Also this"}])
    result = client.get_pr_review_comments(7)
    client._request.assert_called_once_with("GET", "/repos/owner/repo/pulls/7/comments")
    assert len(result) == 2


def test_get_pr_review_comments_empty(client):
    _mock_request(client, [])
    assert client.get_pr_review_comments(7) == []


# ── get_pr_reviews ────────────────────────────────────────────────────────────

def test_get_pr_reviews_returns_list(client):
    _mock_request(client, [{"id": 10, "body": "LGTM", "state": "APPROVED"}])
    result = client.get_pr_reviews(7)
    client._request.assert_called_once_with("GET", "/repos/owner/repo/pulls/7/reviews")
    assert result[0]["state"] == "APPROVED"


# ── get_pr_files ──────────────────────────────────────────────────────────────

def test_get_pr_files_returns_list(client):
    _mock_request(client, [{"filename": "src/main.py", "status": "modified"}])
    result = client.get_pr_files(7)
    client._request.assert_called_once_with("GET", "/repos/owner/repo/pulls/7/files")
    assert result[0]["filename"] == "src/main.py"


# ── get_file_content ──────────────────────────────────────────────────────────

def test_get_file_content_decodes_base64(client):
    encoded = base64.b64encode(b"print('hello')").decode()
    _mock_request(client, {"content": encoded + "\n", "encoding": "base64"})
    result = client.get_file_content("src/main.py", ref="feature/x")
    client._request.assert_called_once_with(
        "GET", "/repos/owner/repo/contents/src/main.py", params={"ref": "feature/x"}
    )
    assert result == "print('hello')"


def test_get_file_content_returns_none_on_error(client):
    client._request = MagicMock(side_effect=RuntimeError("404"))
    result = client.get_file_content("missing.py", ref="main")
    assert result is None


# ── get_issue_comments ────────────────────────────────────────────────────────

def test_get_issue_comments_returns_list(client):
    _mock_request(client, [{"id": 5, "body": "## 🏗️ System Design\n\nDesign here", "user": {"login": "bot"}}])
    result = client.get_issue_comments(3)
    client._request.assert_called_once_with("GET", "/repos/owner/repo/issues/3/comments")
    assert result[0]["user"]["login"] == "bot"


# ── add_pr_label ──────────────────────────────────────────────────────────────

def test_add_pr_label_posts_to_issues_endpoint(client):
    _mock_request(client, [{"name": "ai-revision-1"}])
    client.add_pr_label(42, "ai-revision-1")
    client._request.assert_called_once_with(
        "POST", "/repos/owner/repo/issues/42/labels", json={"labels": ["ai-revision-1"]}
    )


# ── remove_pr_label ───────────────────────────────────────────────────────────

def test_remove_pr_label_calls_delete(client):
    _mock_request(client, {})
    client.remove_pr_label(42, "ai-revision-1")
    client._request.assert_called_once_with(
        "DELETE", "/repos/owner/repo/issues/42/labels/ai-revision-1"
    )


def test_remove_pr_label_ignores_404(client):
    client._request = MagicMock(side_effect=RuntimeError("Label does not exist"))
    client.remove_pr_label(42, "ai-revision-99")  # should not raise


# ── get_repo_languages ────────────────────────────────────────────────────────

def test_get_repo_languages_returns_lowercase_list(client):
    """get_repo_languages returns lowercase language names."""
    _mock_request(client, {"Dart": 12345, "Python": 5678})
    result = client.get_repo_languages("owner/repo")
    client._request.assert_called_once_with("GET", "/repos/owner/repo/languages")
    assert set(result) == {"dart", "python"}
    assert isinstance(result, list)


def test_get_repo_languages_returns_empty_on_error(client):
    """get_repo_languages returns [] on any API error."""
    client._request = MagicMock(side_effect=RuntimeError("API Error"))
    result = client.get_repo_languages("owner/repo")
    assert result == []
