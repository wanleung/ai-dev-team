"""Tests for orchestrator revision helpers."""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from orchestrator import Orchestrator


@pytest.fixture
def orch(tmp_path):
    """Minimal orchestrator with no real API calls."""
    o = Orchestrator.__new__(Orchestrator)
    o.max_revisions = 3
    o.github = MagicMock()
    o.target_github = MagicMock()
    o._github_token = "tok"
    return o


# ── _get_revision_number ──────────────────────────────────────────────────────

def test_get_revision_number_none(orch):
    assert orch._get_revision_number([]) == 0

def test_get_revision_number_single(orch):
    assert orch._get_revision_number(["ai-generated", "ai-revision-2"]) == 2

def test_get_revision_number_highest(orch):
    assert orch._get_revision_number(["ai-revision-1", "ai-revision-3", "ai-revision-2"]) == 3


# ── _extract_issue_number ─────────────────────────────────────────────────────

def test_extract_issue_number_closes(orch):
    assert orch._extract_issue_number("Some text\nCloses #42\nmore") == 42

def test_extract_issue_number_related(orch):
    assert orch._extract_issue_number("Related to #7") == 7

def test_extract_issue_number_none(orch):
    assert orch._extract_issue_number("No reference here") is None


# ── _collect_pr_feedback ──────────────────────────────────────────────────────

def test_collect_pr_feedback_filters_bot(orch):
    orch.target_github.get_pr_review_comments.return_value = [
        {"user": {"login": "alice"}, "body": "Fix the import", "path": "src/main.py", "line": 10},
        {"user": {"login": "github-actions[bot]"}, "body": "Bot comment", "path": "src/main.py", "line": 1},
    ]
    orch.target_github.get_pr_reviews.return_value = [
        {"user": {"login": "bob"}, "body": "Please add tests", "state": "CHANGES_REQUESTED"},
        {"user": {"login": "github-actions[bot]"}, "body": "Bot review", "state": "COMMENTED"},
    ]
    orch.target_github.get_issue_comments.return_value = []
    feedback = orch._collect_pr_feedback(pr_number=1)
    assert len(feedback) == 2
    assert all(f["author"] != "github-actions[bot]" for f in feedback)
    bodies = [f["body"] for f in feedback]
    assert "Fix the import" in bodies
    assert "Please add tests" in bodies


def test_collect_pr_feedback_empty_when_all_bot(orch):
    orch.target_github.get_pr_review_comments.return_value = [
        {"user": {"login": "github-actions[bot]"}, "body": "Bot", "path": "a.py", "line": 1},
    ]
    orch.target_github.get_pr_reviews.return_value = []
    orch.target_github.get_issue_comments.return_value = []
    assert orch._collect_pr_feedback(1) == []


def test_collect_pr_feedback_includes_regular_comments(orch):
    """Regular PR issue comments (e.g. test failure reports) should be included."""
    orch.target_github.get_pr_review_comments.return_value = []
    orch.target_github.get_pr_reviews.return_value = []
    orch.target_github.get_issue_comments.return_value = [
        {"user": {"login": "wanleung"}, "body": "## 🏃 Test Run Results\n\nSome tests failed: TypeError: ..."},
        {"user": {"login": "github-actions[bot]"}, "body": "CI passed"},
    ]
    feedback = orch._collect_pr_feedback(1)
    assert len(feedback) == 1
    assert feedback[0]["author"] == "wanleung"
    assert "Test Run Results" in feedback[0]["body"]
    assert feedback[0]["location"] == "comment"


def test_collect_pr_feedback_includes_copilot_pr_reviewer(orch):
    """copilot-pull-request-reviewer posts useful suggestions and must NOT be filtered out."""
    orch.target_github.get_pr_review_comments.return_value = []
    orch.target_github.get_pr_reviews.return_value = [
        {"user": {"login": "copilot-pull-request-reviewer"}, "body": "requirements-test.txt has markdown that breaks pip"},
    ]
    orch.target_github.get_issue_comments.return_value = []
    feedback = orch._collect_pr_feedback(1)
    assert len(feedback) == 1
    assert feedback[0]["author"] == "copilot-pull-request-reviewer"


# ── _format_feedback ──────────────────────────────────────────────────────────

def test_format_feedback_includes_all_items(orch):
    items = [
        {"author": "alice", "body": "Fix the import", "location": "src/main.py line 10"},
        {"author": "bob", "body": "Add docstring", "location": "review"},
    ]
    md = orch._format_feedback(items)
    assert "Fix the import" in md
    assert "Add docstring" in md
    assert "alice" in md
    assert "bob" in md


# ── _parse_merge_directives ───────────────────────────────────────────────────

def test_parse_merge_directives_explicit_directive(orch):
    feedback = [
        {"author": "wanleung", "body": "merge-branch: feature/agent/1-static-blog-platform", "location": "comment"},
    ]
    result = orch._parse_merge_directives(feedback)
    assert result == ["feature/agent/1-static-blog-platform"]


def test_parse_merge_directives_backtick_branch(orch):
    feedback = [
        {"author": "wanleung", "body": "Please incorporate tests from branch `feature/agent/1-static-blog-platform` before fixing.", "location": "comment"},
    ]
    result = orch._parse_merge_directives(feedback)
    assert result == ["feature/agent/1-static-blog-platform"]


def test_parse_merge_directives_pr_number(orch):
    orch.target_github.get_pr.return_value = {"head": {"ref": "feature/agent/1-static-blog-platform"}}
    feedback = [
        {"author": "wanleung", "body": "merge from PR #2 before fixing tests", "location": "comment"},
    ]
    result = orch._parse_merge_directives(feedback)
    orch.target_github.get_pr.assert_called_once_with(2)
    assert result == ["feature/agent/1-static-blog-platform"]


def test_parse_merge_directives_deduplicates(orch):
    feedback = [
        {"author": "alice", "body": "merge-branch: feature/tests", "location": "comment"},
        {"author": "bob", "body": "merge-branch: feature/tests", "location": "comment"},
    ]
    assert orch._parse_merge_directives(feedback) == ["feature/tests"]


def test_parse_merge_directives_empty_when_no_directives(orch):
    feedback = [
        {"author": "alice", "body": "Please fix the import error on line 10", "location": "comment"},
    ]
    assert orch._parse_merge_directives(feedback) == []


# ── _fetch_design_from_issue ──────────────────────────────────────────────────

def test_fetch_design_from_issue_finds_architect_comment(orch):
    orch.github.get_issue_comments.return_value = [
        {"body": "## 📋 PRD\n\nSome product doc", "user": {"login": "github-actions[bot]"}},
        {"body": "## 🏗️ System Design (Architect)\n\nThe full architecture here", "user": {"login": "github-actions[bot]"}},
        {"body": "Random human comment", "user": {"login": "alice"}},
    ]
    design = orch._fetch_design_from_issue(issue_number=5)
    assert "System Design" in design
    assert "architecture here" in design


def test_fetch_design_from_issue_returns_empty_string_when_not_found(orch):
    orch.github.get_issue_comments.return_value = [
        {"body": "Just a comment", "user": {"login": "alice"}},
    ]
    assert orch._fetch_design_from_issue(5) == ""


# ── run_revision ──────────────────────────────────────────────────────────────

def test_run_revision_exits_when_max_revisions_reached(orch):
    orch.target_github.get_pr.return_value = {
        "head": {"ref": "feature/my-app"},
        "body": "Closes #3",
        "labels": [{"name": "ai-generated"}, {"name": "ai-revision-3"}],
        "title": "My App",
    }
    result = orch.run_revision(pr_number=10)
    assert result["status"] == "max_revisions_reached"
    orch.target_github.add_pr_comment.assert_called_once()
    comment_body = orch.target_github.add_pr_comment.call_args[0][1]
    assert "Max revisions reached" in comment_body
    orch.target_github.get_pr_files.assert_not_called()
    orch.target_github.commit_file.assert_not_called()


def test_run_revision_exits_when_no_human_feedback(orch):
    orch.target_github.get_pr.return_value = {
        "head": {"ref": "feature/my-app"},
        "body": "Closes #3",
        "labels": [{"name": "ai-generated"}],
        "title": "My App",
    }
    orch.target_github.get_pr_review_comments.return_value = []
    orch.target_github.get_pr_reviews.return_value = []
    result = orch.run_revision(pr_number=10)
    assert result["status"] == "no_feedback"
    orch.target_github.get_pr_files.assert_not_called()
    orch.target_github.commit_file.assert_not_called()
    orch.target_github.add_pr_comment.assert_not_called()
