"""Tests for tracker_adapter.py — TriageItem, GitHubTrackerAdapter logic."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from tracker_adapter import (
    TRIAGE_COMMENT_MARKER,
    GitHubTrackerAdapter,
    TriageItem,
    TrackerAdapter,
)


def _make_item(**overrides) -> TriageItem:
    defaults = dict(
        id="42",
        title="Test Issue",
        body="Some body text",
        url="https://github.com/org/repo/issues/42",
        created_at=datetime(2026, 6, 20, 12, 0, 0, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return TriageItem(**defaults)


def _make_adapter(**overrides) -> GitHubTrackerAdapter:
    defaults = dict(repo="org/repo", token="ghp_test")
    defaults.update(overrides)
    return GitHubTrackerAdapter(**defaults)


# ── TriageItem ──────────────────────────────────────────────────────────────

class TestTriageItem:
    def test_basic_construction(self):
        item = _make_item()
        assert item.id == "42"
        assert item.title == "Test Issue"
        assert item.metadata == {}

    def test_metadata_default_factory(self):
        a = _make_item()
        b = _make_item()
        a.metadata["key"] = "value"
        assert "key" not in b.metadata  # Each instance gets its own dict

    def test_with_metadata(self):
        item = _make_item(metadata={"number": 42, "labels": ["triage-pending"]})
        assert item.metadata["number"] == 42


# ── TrackerAdapter ABC ──────────────────────────────────────────────────────

class TestTrackerAdapterABC:
    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            TrackerAdapter()  # type: ignore[abstract]


# ── GitHubTrackerAdapter ────────────────────────────────────────────────────

class TestGitHubTrackerAdapter:
    def test_construction_defaults(self):
        a = _make_adapter()
        assert a.repo == "org/repo"
        assert a.pending_label == "triage-pending"
        assert a.approved_label == "triage-approved"
        assert a.skipped_label == "triage-skipped"
        assert a.trigger_label == "press"

    def test_construction_custom_labels(self):
        a = _make_adapter(
            pending_label="needs-triage",
            approved_label="ready",
            skipped_label="wontfix",
            trigger_label="publish",
        )
        assert a.pending_label == "needs-triage"
        assert a.approved_label == "ready"
        assert a.skipped_label == "wontfix"
        assert a.trigger_label == "publish"

    def test_headers_include_token(self):
        a = _make_adapter()
        headers = a._headers()
        assert headers["Authorization"] == "Bearer ghp_test"
        assert "github+json" in headers["Accept"]

    @patch("tracker_adapter.requests.request")
    def test_api_raises_on_error(self, mock_request):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("403 Forbidden")
        mock_request.return_value = mock_resp

        a = _make_adapter()
        with pytest.raises(Exception, match="403 Forbidden"):
            a._api("GET", "/repos/org/repo/issues")

    @patch("tracker_adapter.requests.request")
    def test_api_builds_correct_url(self, mock_request):
        mock_resp = MagicMock()
        mock_request.return_value = mock_resp

        a = _make_adapter()
        a._api("POST", "/repos/org/repo/issues/1/comments", json={"body": "test"})

        mock_request.assert_called_once()
        call_args = mock_request.call_args
        assert call_args[0][0] == "POST"
        assert call_args[0][1] == "https://api.github.com/repos/org/repo/issues/1/comments"

    @patch("tracker_adapter.requests.get")
    def test_list_pending_skips_pull_requests(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"number": 1, "title": "Issue", "body": "x", "html_url": "", "created_at": "2026-06-20T00:00:00Z", "labels": []},
            {"number": 2, "title": "PR", "body": "y", "html_url": "", "created_at": "2026-06-20T00:00:00Z", "labels": [], "pull_request": {"url": "..."}},
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        a = _make_adapter()
        items = a.list_pending()

        assert len(items) == 1
        assert items[0].id == "1"

    @patch("tracker_adapter.requests.get")
    def test_list_pending_pagination(self, mock_get):
        """When a full page of 100 is returned, fetches next page."""
        page1 = MagicMock()
        page1.json.return_value = [{"number": i, "title": f"Issue {i}", "body": "", "html_url": "", "created_at": "2026-06-20T00:00:00Z", "labels": []} for i in range(100)]
        page1.raise_for_status = MagicMock()

        page2 = MagicMock()
        page2.json.return_value = []  # Empty page → stop
        page2.raise_for_status = MagicMock()

        mock_get.side_effect = [page1, page2]

        a = _make_adapter()
        items = a.list_pending()

        assert len(items) == 100
        assert mock_get.call_count == 2

    @patch("tracker_adapter.requests.request")
    def test_approve_posts_comment_and_labels(self, mock_request):
        mock_resp = MagicMock()
        mock_request.return_value = mock_resp

        a = _make_adapter()
        item = _make_item()
        a.approve(item, notes="Good story")

        calls = mock_request.call_args_list
        # First call: POST comment
        assert calls[0][0][0] == "POST"
        assert "comments" in calls[0][0][1]
        body = calls[0][1]["json"]["body"]
        assert TRIAGE_COMMENT_MARKER in body
        assert "PUBLISH" in body
        assert "Good story" in body
        # Second call: POST labels (approved + trigger)
        assert calls[1][0][0] == "POST"
        assert "labels" in calls[1][0][1]
        assert calls[1][1]["json"]["labels"] == ["triage-approved", "press"]

    @patch("tracker_adapter.requests.request")
    def test_skip_posts_comment_closes_issue(self, mock_request):
        mock_resp = MagicMock()
        mock_request.return_value = mock_resp

        a = _make_adapter()
        item = _make_item()
        a.skip(item, reason="Not relevant")

        calls = mock_request.call_args_list
        # First call: POST comment
        body = calls[0][1]["json"]["body"]
        assert "SKIP" in body
        assert "Not relevant" in body
        # Second call: POST labels (skipped)
        assert calls[1][1]["json"]["labels"] == ["triage-skipped"]
        # Third call: PATCH to close
        assert calls[2][0][0] == "PATCH"
        assert calls[2][1]["json"]["state"] == "closed"

    @patch("tracker_adapter.requests.get")
    def test_is_approved_returns_false_when_no_label(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"labels": [{"name": "other-label"}]}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        a = _make_adapter()
        approved, notes = a.is_approved("42")

        assert approved is False
        assert notes == ""

    @patch("tracker_adapter.requests.get")
    def test_is_approved_extracts_notes(self, mock_get):
        issue_resp = MagicMock()
        issue_resp.json.return_value = {"labels": [{"name": "triage-approved"}]}
        issue_resp.raise_for_status = MagicMock()

        comment_resp = MagicMock()
        comment_resp.json.return_value = [
            {"body": f"{TRIAGE_COMMENT_MARKER}\nVERDICT: PUBLISH\nNOTES: Great angle.\n\nstuff"},
        ]
        comment_resp.raise_for_status = MagicMock()

        mock_get.side_effect = [issue_resp, comment_resp]

        a = _make_adapter()
        approved, notes = a.is_approved("42")

        assert approved is True
        assert "Great angle" in notes


# ── add_score_label ─────────────────────────────────────────────────────────

class TestAddScoreLabel:
    @patch("tracker_adapter.requests.request")
    def test_creates_label_and_attaches(self, mock_request):
        """When label doesn't exist (404), creates it then attaches."""
        get_resp = MagicMock()
        get_resp.raise_for_status.side_effect = _make_http_error(404)

        post_create_resp = MagicMock()
        post_create_resp.raise_for_status = MagicMock()

        post_attach_resp = MagicMock()
        post_attach_resp.raise_for_status = MagicMock()

        mock_request.side_effect = [get_resp, post_create_resp, post_attach_resp]

        a = _make_adapter()
        item = _make_item()
        a.add_score_label(item, score=7.3)

        calls = mock_request.call_args_list
        # First: GET to check label exists
        assert calls[0][0][0] == "GET"
        assert "score-7" in calls[0][0][1]
        # Second: POST to create label
        assert calls[1][0][0] == "POST"
        assert "labels" in calls[1][0][1]
        # Third: POST to attach label
        assert calls[2][0][0] == "POST"
        assert "score-7" in str(calls[2][1]["json"]["labels"])

    @patch("tracker_adapter.requests.request")
    def test_skips_creation_when_label_exists(self, mock_request):
        """When label already exists (200), skips creation and attaches directly."""
        get_resp = MagicMock()
        get_resp.raise_for_status = MagicMock()  # No error → label exists

        post_attach_resp = MagicMock()
        post_attach_resp.raise_for_status = MagicMock()

        mock_request.side_effect = [get_resp, post_attach_resp]

        a = _make_adapter()
        item = _make_item()
        a.add_score_label(item, score=7.3)

        calls = mock_request.call_args_list
        assert len(calls) == 2  # GET + attach, no POST create
        assert calls[0][0][0] == "GET"
        assert calls[1][0][0] == "POST"

    @patch("tracker_adapter.requests.request")
    def test_score_rounding(self, mock_request):
        """Score 6.5 rounds to 7, score 6.4 rounds to 6."""
        get_resp = MagicMock()
        get_resp.raise_for_status = MagicMock()

        post_resp = MagicMock()
        post_resp.raise_for_status = MagicMock()

        mock_request.side_effect = [get_resp, post_resp]

        a = _make_adapter()
        item = _make_item()

        a.add_score_label(item, score=6.5)
        assert "score-7" in mock_request.call_args_list[1][1]["json"]["labels"]

        mock_request.reset_mock()
        get_resp2 = MagicMock()
        get_resp2.raise_for_status = MagicMock()
        post_resp2 = MagicMock()
        post_resp2.raise_for_status = MagicMock()
        mock_request.side_effect = [get_resp2, post_resp2]
        a.add_score_label(item, score=6.4)
        assert "score-6" in mock_request.call_args_list[1][1]["json"]["labels"]


def _make_http_error(status_code: int):
    """Create an HTTPError with a mock response."""
    import requests
    resp = MagicMock()
    resp.status_code = status_code
    exc = requests.HTTPError(response=resp)
    return exc
