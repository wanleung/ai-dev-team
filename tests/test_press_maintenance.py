"""Tests for scripts/press_maintenance.py's pipeline-status detection.

Regression coverage for a real production incident: issue #6276 on
ai-it-press got re-triggered 8 times over 8 consecutive hours by this
script's own stuck-complete recovery job, because _pipeline_comment_status()
checked the FIRST '## 🤖 Pipeline Progress' comment it found (oldest, since
GitHub returns issue comments oldest-first) instead of the most recent one.
A fresh dispatch has no checkpoint to resume, so ProgressTracker creates a
brand-new comment rather than editing an old one — meaning any issue ever
retried accumulates multiple progress comments over its history. Checking
the oldest one meant a single failed attempt anywhere in an issue's past
marked it "failed" forever, even after a later run succeeded and reached
agent-complete correctly — so this job kept stripping agent-complete and
re-adding the trigger label, forever, once per hour.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import press_maintenance as pm  # noqa: E402


def _progress_comment(body: str) -> dict:
    return {"body": body}


def _resp(status_code: int, json_body: object = None, text: str = "{}") -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.text = text
    r.json.return_value = json_body if json_body is not None else {}
    if status_code >= 400:
        r.raise_for_status.side_effect = requests.HTTPError(f"{status_code} error", response=r)
    return r


class TestRequestRetry:
    """Regression coverage for a real production incident: a single 502 from
    GitHub mid-way through auto-merge's PR loop (issue #6538 on ai-it-press)
    killed the whole job with an unhandled HTTPError, leaving every PR after
    it in the list unchecked for that run. _get/_post/_put/_delete had no
    retry at all, unlike github_client.py's GitHubClient._request.
    """

    def setup_method(self):
        pm.GITHUB_TOKEN = "test-token"

    def test_get_retries_on_502_then_succeeds(self):
        responses = [_resp(502, text="Bad Gateway"), _resp(200, {"ok": True})]
        with patch.object(pm.requests, "request", side_effect=responses) as mock_req, \
             patch.object(pm.time, "sleep") as mock_sleep:
            result = pm._get("/repos/owner/repo/pulls/1")
        assert result == {"ok": True}
        assert mock_req.call_count == 2
        mock_sleep.assert_called_once()

    def test_get_raises_after_exhausting_retries(self):
        responses = [_resp(502, text="Bad Gateway")] * pm._MAX_RETRIES
        with patch.object(pm.requests, "request", side_effect=responses), \
             patch.object(pm.time, "sleep"):
            with pytest.raises(requests.HTTPError):
                pm._get("/repos/owner/repo/pulls/1")

    def test_get_does_not_retry_on_404(self):
        with patch.object(pm.requests, "request", return_value=_resp(404, text="Not Found")) as mock_req, \
             patch.object(pm.time, "sleep") as mock_sleep:
            with pytest.raises(requests.HTTPError):
                pm._get("/repos/owner/repo/pulls/1")
        assert mock_req.call_count == 1
        mock_sleep.assert_not_called()

    def test_delete_retries_on_503_then_treats_404_as_success(self):
        responses = [_resp(503, text="Service Unavailable"), _resp(404, text="Not Found")]
        with patch.object(pm.requests, "request", side_effect=responses), \
             patch.object(pm.time, "sleep") as mock_sleep:
            pm._delete("/repos/owner/repo/issues/1/labels/press")  # must not raise
        mock_sleep.assert_called_once()


SUCCESS_BODY = """## 🤖 Pipeline Progress

- ✅ 🗞️  Editorial Triage
- ✅ 💬 Discuss: News Analysis
- ✅ ✍️  News Writer
- ✅ 💬 Discuss: News Draft
- ✅ 📝 News Editor
- ✅ 🀄 Translate (Traditional Chinese)
- ✅ 🔍 News Reviewer
- ✅ 📨 News Article PR"""

FAILED_BODY = """## 🤖 Pipeline Progress

- ✅ 🗞️  Editorial Triage
- ✅ 💬 Discuss: News Analysis
- ✅ ✍️  News Writer
- ✅ 💬 Discuss: News Draft
- ✅ 📝 News Editor
- ✅ 🀄 Translate (Traditional Chinese)
- ❌ 🔍 News Reviewer — [ERROR] some failure
- ⬜ 📨 News Article PR"""


class TestPipelineCommentStatus:
    def test_success_when_only_comment_succeeded(self):
        with patch.object(pm, "get_issue_comments", return_value=[_progress_comment(SUCCESS_BODY)]):
            assert pm._pipeline_comment_status(1) == "success"

    def test_failed_when_only_comment_failed(self):
        with patch.object(pm, "get_issue_comments", return_value=[_progress_comment(FAILED_BODY)]):
            assert pm._pipeline_comment_status(1) == "failed"

    def test_unknown_when_no_progress_comment_at_all(self):
        with patch.object(pm, "get_issue_comments", return_value=[{"body": "just a regular comment"}]):
            assert pm._pipeline_comment_status(1) == "unknown"

    def test_regression_later_success_overrides_earlier_failure(self):
        """The exact production bug: an old failed attempt followed by a
        later successful retry must read as 'success', not 'failed'.
        GitHub returns comments oldest-first, so the failed one comes
        before the successful one in the list passed to the function.
        """
        comments = [_progress_comment(FAILED_BODY), _progress_comment(SUCCESS_BODY)]
        with patch.object(pm, "get_issue_comments", return_value=comments):
            assert pm._pipeline_comment_status(1) == "success"

    def test_later_failure_after_earlier_success_still_reads_as_failed(self):
        """The mirror case: if the MOST RECENT attempt failed, that must
        win even though an earlier attempt in the same issue succeeded
        (e.g. a stale multi_run label triggered a second, broken pass)."""
        comments = [_progress_comment(SUCCESS_BODY), _progress_comment(FAILED_BODY)]
        with patch.object(pm, "get_issue_comments", return_value=comments):
            assert pm._pipeline_comment_status(1) == "failed"

    def test_ignores_non_progress_comments_when_finding_the_latest(self):
        """A triage/editorial-score comment posted after the progress
        comment must not be mistaken for it, or cause a false 'unknown'."""
        comments = [
            _progress_comment(FAILED_BODY),
            _progress_comment(SUCCESS_BODY),
            {"body": "**Editorial Score: 9.1/10**"},
        ]
        with patch.object(pm, "get_issue_comments", return_value=comments):
            assert pm._pipeline_comment_status(1) == "success"

    def test_comments_fetch_error_returns_unknown_not_raise(self):
        with patch.object(pm, "get_issue_comments", side_effect=RuntimeError("network down")):
            assert pm._pipeline_comment_status(1) == "unknown"
