"""Tests for Orchestrator helper methods: _safe_project_slug, _checkpoint_and_advance, _run_revision_loop."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from orchestrator import Orchestrator, PipelineResult, ProgressStage


def _make_orchestrator(**overrides) -> Orchestrator:
    """Create a minimal Orchestrator with mocked dependencies."""
    orch = Orchestrator.__new__(Orchestrator)
    orch.workspace_dir = MagicMock()
    orch.github = None
    orch._tracker = MagicMock()
    orch._save_checkpoint = MagicMock()
    orch._run_stage = MagicMock()
    orch._pause_for_clarification = MagicMock()
    orch.max_prd_revisions = 3
    orch.max_design_revisions = 3
    orch.stop_on_prd_issues = False
    orch.stop_on_design_issues = False
    orch.__dict__.update(overrides)
    return orch


def _make_result(stages: list[str] | None = None) -> PipelineResult:
    """Create a PipelineResult with optional pre-completed stages."""
    r = PipelineResult(requirement="test")
    for s in (stages or []):
        r.add_completed_stage(s)
    return r


# ── _safe_project_slug ──────────────────────────────────────────────────────

class TestSafeProjectSlug:
    def test_simple_name(self):
        assert Orchestrator._safe_project_slug("MyProject") == "myproject"

    def test_with_spaces(self):
        assert Orchestrator._safe_project_slug("My Cool App") == "my_cool_app"

    def test_with_special_chars(self):
        assert Orchestrator._safe_project_slug("app@v2.0!") == "app_v2_0_"

    def test_preserves_hyphens(self):
        assert Orchestrator._safe_project_slug("my-app") == "my-app"

    def test_preserves_underscores(self):
        assert Orchestrator._safe_project_slug("my_app") == "my_app"

    def test_empty_string(self):
        assert Orchestrator._safe_project_slug("") == ""

    def test_only_special_chars(self):
        assert Orchestrator._safe_project_slug("@#$%") == "____"

    def test_already_slug(self):
        assert Orchestrator._safe_project_slug("my-cool-app") == "my-cool-app"


# ── _checkpoint_and_advance ─────────────────────────────────────────────────

class TestCheckpointAndAdvance:
    def test_marks_done_and_saves(self):
        o = _make_orchestrator()
        r = _make_result()

        o._checkpoint_and_advance("pm", r)

        assert "pm" in r.completed_stages
        o._tracker.mark_done.assert_called_once_with("pm")
        o._save_checkpoint.assert_called_once_with(r)

    def test_stamps_progress_comment_id(self):
        o = _make_orchestrator()
        o._tracker.comment_id = 42
        r = _make_result()

        o._checkpoint_and_advance("engineer", r)

        assert r.progress_comment_id == 42


# ── _run_revision_loop ──────────────────────────────────────────────────────

class TestRunRevisionLoop:
    def test_immediate_approval(self):
        """When reviewer approves on first pass, loop exits without revisions."""
        o = _make_orchestrator(max_prd_revisions=3)
        r = _make_result(stages=["pm"])
        r.prd_verdict = "APPROVED"  # Not NEEDS_REVISION

        ok = o._run_revision_loop(
            r,
            agent_stage_key="pm",
            agent_label="📋 PM",
            agent_desc="Writing PRD...",
            agent_fn=lambda rn=0: None,
            agent_output_fields=["prd"],
            reviewer_stage_key="pm_reviewer",
            reviewer_label="📝 Reviewer",
            reviewer_desc="Reviewing...",
            reviewer_fn=lambda: setattr(r, "prd_verdict", "APPROVED"),
            reviewer_output_fields=["prd_review", "prd_verdict"],
            max_revisions=3,
            revision_key_prefix="prd_revision",
            verdict_attr="prd_verdict",
            expected_verdict_value="NEEDS_REVISION",
            stop_on_issues=False,
            loop_label="pm_review_loop",
            revision_label="PRD Revision",
            halt_comment_tpl="Max reached {max_revisions}",
        )

        assert ok is True
        assert "pm_review_loop" in r.completed_stages

    def test_revisions_disabled(self):
        """When max_revisions=0, skip loop entirely."""
        o = _make_orchestrator()
        r = _make_result(stages=["pm", "pm_reviewer"])

        ok = o._run_revision_loop(
            r,
            agent_stage_key="pm",
            agent_label="📋 PM",
            agent_desc="Writing PRD...",
            agent_fn=lambda rn=0: None,
            agent_output_fields=["prd"],
            reviewer_stage_key="pm_reviewer",
            reviewer_label="📝 Reviewer",
            reviewer_desc="Reviewing...",
            reviewer_fn=lambda: None,
            reviewer_output_fields=["prd_review", "prd_verdict"],
            max_revisions=0,
            revision_key_prefix="prd_revision",
            verdict_attr="prd_verdict",
            expected_verdict_value="NEEDS_REVISION",
            stop_on_issues=False,
            loop_label="pm_review_loop",
            revision_label="PRD Revision",
            halt_comment_tpl="Max reached {max_revisions}",
        )

        assert ok is True
        assert "pm_review_loop" in r.completed_stages

    def test_halts_on_max_revisions_with_stop(self):
        """When stop_on_issues=True and max rounds exhausted, returns False."""
        o = _make_orchestrator()
        r = _make_result(stages=["pm", "pm_reviewer"])
        r.prd_verdict = "NEEDS_REVISION"  # Never changes

        def reviewer_sets_verdict():
            pass  # Verdict stays NEEDS_REVISION

        ok = o._run_revision_loop(
            r,
            agent_stage_key="pm",
            agent_label="📋 PM",
            agent_desc="Writing PRD...",
            agent_fn=lambda rn=0: None,
            agent_output_fields=["prd"],
            reviewer_stage_key="pm_reviewer",
            reviewer_label="📝 Reviewer",
            reviewer_desc="Reviewing...",
            reviewer_fn=reviewer_sets_verdict,
            reviewer_output_fields=["prd_review", "prd_verdict"],
            max_revisions=2,
            revision_key_prefix="prd_revision",
            verdict_attr="prd_verdict",
            expected_verdict_value="NEEDS_REVISION",
            stop_on_issues=True,
            loop_label="pm_review_loop",
            revision_label="PRD Revision",
            halt_comment_tpl="Max reached {max_revisions}",
        )

        assert ok is False
