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
    assert orch._collect_pr_feedback(1) == []


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
