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
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import press_maintenance as pm  # noqa: E402


def _progress_comment(body: str) -> dict:
    return {"body": body}


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
