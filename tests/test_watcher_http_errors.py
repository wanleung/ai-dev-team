"""Tests for watcher HTTP error handling contract.

Validates that get_open_prs(), get_pr_comments(), and get_open_issues() raise
RuntimeError (not HTTPError) when GitHub API calls fail, ensuring consistent
error handling across the module, while still allowing the @_retry_github
decorator to retry on 429/5xx via the inner ``_raw`` functions.
"""
from __future__ import annotations

import pytest
import requests
from unittest.mock import patch, MagicMock


def _mock_response(json_data, ok=True, status_code=200, text=None):
    """Helper to create mock responses matching requests.Response interface.

    When ok=False, configures raise_for_status() to raise requests.HTTPError
    so that the @_retry_github decorator receives the correct exception type.
    """
    m = MagicMock()
    m.ok = ok
    m.status_code = status_code
    m.json.return_value = json_data
    m.text = text if text is not None else str(json_data)
    if not ok:
        http_error = requests.HTTPError(response=m)
        m.raise_for_status.side_effect = http_error
    return m


def test_get_open_prs_raises_runtime_error_on_http_failure(monkeypatch):
    """get_open_prs raises RuntimeError on HTTP failure, not HTTPError.

    The inner _get_open_prs_raw uses raise_for_status() (so @_retry_github can
    intercept 429/5xx), and the outer get_open_prs wrapper converts the final
    HTTPError to RuntimeError for callers.
    """
    from watcher import get_open_prs

    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    error_response = _mock_response({"message": "Not Found"}, ok=False, status_code=404, text="Not Found")

    with patch("watcher.requests.get", return_value=error_response):
        with pytest.raises(RuntimeError, match=r"GitHub API error 404: Not Found"):
            get_open_prs("owner/repo")


def test_get_pr_comments_raises_runtime_error_on_http_failure(monkeypatch):
    """get_pr_comments raises RuntimeError on HTTP failure, not HTTPError.

    The inner _get_pr_comments_raw uses raise_for_status() (so @_retry_github
    can intercept 429/5xx), and the outer get_pr_comments wrapper converts the
    final HTTPError to RuntimeError for callers.
    """
    from watcher import get_pr_comments

    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    error_response = _mock_response({"message": "Not Found"}, ok=False, status_code=404, text="Not Found")

    with patch("watcher.requests.get", return_value=error_response):
        with pytest.raises(RuntimeError, match=r"GitHub API error 404: Not Found"):
            get_pr_comments("owner/repo", 1)


def test_get_open_issues_raises_runtime_error_on_http_failure(monkeypatch):
    """get_open_issues raises RuntimeError on HTTP failure, not HTTPError.

    The inner _get_open_issues_raw uses raise_for_status() (so @_retry_github
    can intercept 429/5xx), and the outer get_open_issues wrapper converts the
    final HTTPError to RuntimeError for callers.
    """
    from watcher import get_open_issues

    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    error_response = _mock_response({}, ok=False, status_code=403, text="Forbidden")

    with patch("watcher.requests.get", return_value=error_response):
        with pytest.raises(RuntimeError, match=r"GitHub API error 403: Forbidden"):
            get_open_issues("owner/repo", "ai-task")


def test_get_open_prs_returns_json_on_success(monkeypatch):
    """get_open_prs returns JSON response on successful HTTP call."""
    from watcher import get_open_prs

    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    pr_data = [{"number": 1, "title": "Test PR", "draft": False}]
    success_response = _mock_response(pr_data, ok=True, status_code=200)

    with patch("watcher.requests.get", return_value=success_response):
        result = get_open_prs("owner/repo")

    assert result == pr_data
