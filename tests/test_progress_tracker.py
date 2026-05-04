"""Tests for ProgressTracker."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, call
from orchestrator import ProgressStage, ProgressTracker


# ── ProgressStage ──────────────────────────────────────────────────────────────

def test_progress_stage_defaults():
    s = ProgressStage(key="pm", label="📋 Product Manager")
    assert s.status == "pending"


# ── ProgressTracker — off mode ────────────────────────────────────────────────

def test_tracker_off_mode_is_noop():
    gh = MagicMock()
    t = ProgressTracker(github=gh, issue_number=1, mode="off")
    t.set_stages([ProgressStage("pm", "📋 PM")])
    t.mark_in_progress("pm")
    t.mark_done("pm")
    t.mark_failed("pm", "some error")
    t.mark_skipped("pm")
    gh.add_issue_comment.assert_not_called()
    gh.delete_issue_comment.assert_not_called()


# ── ProgressTracker — no github ───────────────────────────────────────────────

def test_tracker_none_github_is_noop():
    t = ProgressTracker(github=None, issue_number=1, mode="summary")
    t.set_stages([ProgressStage("pm", "📋 PM")])
    t.mark_done("pm")   # must not raise


def test_tracker_none_issue_number_is_noop():
    gh = MagicMock()
    t = ProgressTracker(github=gh, issue_number=None, mode="summary")
    t.set_stages([ProgressStage("pm", "📋 PM")])
    t.mark_done("pm")
    gh.add_issue_comment.assert_not_called()


# ── ProgressTracker — summary mode ───────────────────────────────────────────

def _make_tracker(mode="summary"):
    gh = MagicMock()
    gh.add_issue_comment.return_value = {"id": 42}
    t = ProgressTracker(github=gh, issue_number=7, mode=mode)
    stages = [
        ProgressStage("pm", "📋 Product Manager"),
        ProgressStage("architect", "🏗️ Architect"),
    ]
    t.set_stages(stages)
    return t, gh


def test_summary_set_stages_posts_initial_comment():
    t, gh = _make_tracker()
    gh.add_issue_comment.assert_called_once()
    body = gh.add_issue_comment.call_args[0][1]
    assert "⬜ 📋 Product Manager" in body
    assert "⬜ 🏗️ Architect" in body
    assert t.comment_id == 42


def test_summary_mark_in_progress_updates_comment():
    t, gh = _make_tracker()
    gh.add_issue_comment.reset_mock()
    gh.add_issue_comment.return_value = {"id": 43}
    t.mark_in_progress("pm")
    body = gh.add_issue_comment.call_args[0][1]
    assert "🔄 📋 Product Manager" in body
    gh.delete_issue_comment.assert_called_once_with(42)
    assert t.comment_id == 43


def test_summary_mark_done_shows_checkmark():
    t, gh = _make_tracker()
    gh.add_issue_comment.return_value = {"id": 44}
    t.mark_done("pm")
    body = gh.add_issue_comment.call_args[0][1]
    assert "✅ 📋 Product Manager" in body


def test_summary_mark_failed_shows_error():
    t, gh = _make_tracker()
    gh.add_issue_comment.return_value = {"id": 45}
    t.mark_failed("architect", "LLM returned empty")
    body = gh.add_issue_comment.call_args[0][1]
    assert "❌ 🏗️ Architect" in body
    assert "LLM returned empty" in body


def test_summary_mark_skipped_shows_skip_icon():
    t, gh = _make_tracker()
    gh.add_issue_comment.return_value = {"id": 46}
    t.mark_skipped("pm")
    body = gh.add_issue_comment.call_args[0][1]
    assert "⏭️ 📋 Product Manager" in body


def test_summary_unknown_key_is_noop():
    """mark_* with an unknown stage key must not raise."""
    t, gh = _make_tracker()
    t.mark_done("nonexistent_key")   # should not raise or post


def test_summary_add_stage_appended_to_list():
    t, gh = _make_tracker()
    gh.add_issue_comment.return_value = {"id": 50}
    t.add_stage(ProgressStage("design_revision_1", "🔄 Design Revision 1"))
    body = gh.add_issue_comment.call_args[0][1]
    assert "⬜ 🔄 Design Revision 1" in body


def test_summary_restore_sets_comment_id_without_posting():
    t, gh = _make_tracker()
    gh.add_issue_comment.reset_mock()
    t.restore(99)
    assert t.comment_id == 99
    gh.add_issue_comment.assert_not_called()


# ── ProgressTracker — verbose mode ───────────────────────────────────────────

def test_verbose_mark_in_progress_posts_starting_comment():
    t, gh = _make_tracker(mode="verbose")
    gh.add_issue_comment.reset_mock()
    t.mark_in_progress("pm")
    body = gh.add_issue_comment.call_args[0][1]
    assert "🔄" in body
    assert "Product Manager" in body


def test_verbose_mark_done_posts_done_comment():
    t, gh = _make_tracker(mode="verbose")
    gh.add_issue_comment.reset_mock()
    t.mark_done("pm")
    body = gh.add_issue_comment.call_args[0][1]
    assert "✅" in body
    assert "Product Manager" in body


def test_verbose_mark_failed_posts_failed_comment():
    t, gh = _make_tracker(mode="verbose")
    gh.add_issue_comment.reset_mock()
    t.mark_failed("pm", "out of memory")
    body = gh.add_issue_comment.call_args[0][1]
    assert "❌" in body
    assert "out of memory" in body


def test_verbose_does_not_delete_comments():
    t, gh = _make_tracker(mode="verbose")
    t.mark_in_progress("pm")
    t.mark_done("pm")
    gh.delete_issue_comment.assert_not_called()


# ── Error resilience ──────────────────────────────────────────────────────────

def test_summary_github_error_does_not_raise():
    """A GitHub error during post must be silently swallowed."""
    gh = MagicMock()
    gh.add_issue_comment.side_effect = RuntimeError("502 Server Error")
    t = ProgressTracker(github=gh, issue_number=7, mode="summary")
    t.set_stages([ProgressStage("pm", "📋 PM")])   # must not raise
    t.mark_done("pm")                               # must not raise
