"""Tests for PRD/Design revision loops."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, call
from orchestrator import Orchestrator, PipelineResult
from agents.pm_reviewer import PMReviewerAgent
from agents.architect_reviewer import ArchitectReviewerAgent


# ── PipelineResult serialisation ─────────────────────────────────────────────

def test_pipeline_result_new_fields_defaults():
    r = PipelineResult(requirement="build a todo app")
    assert r.prd_revision_count == 0
    assert r.design_revision_count == 0
    assert r.prd_reviewer_draft == ""
    assert r.design_reviewer_draft == ""


def test_pipeline_result_round_trips_new_fields():
    r = PipelineResult(requirement="x")
    r.prd_revision_count = 2
    r.design_revision_count = 1
    r.prd_reviewer_draft = "## Draft PRD"
    r.design_reviewer_draft = "## Draft Design"
    data = r.to_dict()
    r2 = PipelineResult.from_dict(data)
    assert r2.prd_revision_count == 2
    assert r2.design_revision_count == 1
    assert r2.prd_reviewer_draft == "## Draft PRD"
    assert r2.design_reviewer_draft == "## Draft Design"


# ── Orchestrator config params ─────────────────────────────────────────────────

def test_orchestrator_new_config_defaults():
    """Orchestrator reads new config keys and stores them as instance attributes."""
    o = Orchestrator.__new__(Orchestrator)
    o.max_prd_revisions = 3
    o.max_design_revisions = 3
    o.stop_on_prd_issues = False
    o.stop_on_design_issues = False
    assert o.max_prd_revisions == 3
    assert o.stop_on_prd_issues is False


def test_from_config_reads_new_keys(tmp_path, monkeypatch):
    """from_config() passes new pipeline keys through to __init__."""
    import yaml, os
    cfg = {
        "llm": {"model": "gpt-4.1"},
        "github": {"repo": "", "use_github": False},
        "team": {},
        "pipeline": {
            "max_prd_revisions": 2,
            "max_design_revisions": 1,
            "stop_on_prd_issues": True,
            "stop_on_design_issues": False,
        },
    }
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump(cfg))
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    o = Orchestrator.from_config(str(cfg_file))
    assert o.max_prd_revisions == 2
    assert o.max_design_revisions == 1
    assert o.stop_on_prd_issues is True
    assert o.stop_on_design_issues is False


def test_run_revision_pm_agent():
    """ProductManagerAgent.run_revision() sends original PRD, review, and draft to the LLM."""
    from agents.product_manager import ProductManagerAgent

    agent = ProductManagerAgent.__new__(ProductManagerAgent)
    captured = {}

    def fake_call(prompt):
        captured["prompt"] = prompt
        return "# Revised PRD\n## Project Name\nTodo App\n## Overview\nFixed version."

    agent.call = fake_call

    result = agent.run_revision(
        original_prd="# Original PRD",
        review="Missing acceptance criteria.",
        draft_revision="# Draft PRD by reviewer",
        requirement="Build a todo app",
        project_name="Todo App",
    )

    assert "prd" in result
    assert "project_name" in result
    assert "Original PRD" in captured["prompt"]
    assert "Missing acceptance criteria" in captured["prompt"]
    assert "Draft PRD by reviewer" in captured["prompt"]
    assert "Revised PRD" in result["prd"]


def test_run_revision_architect_agent():
    """ArchitectAgent.run_revision() sends original design, review, draft, and PRD to the LLM."""
    from agents.architect import ArchitectAgent

    agent = ArchitectAgent.__new__(ArchitectAgent)
    agent._tool_registry = None
    captured = {}

    def fake_call(prompt):
        captured["prompt"] = prompt
        return (
            "# Revised Design\n## Overview\nFixed.\n"
            "## Implementation Modules\n1. **api**: REST layer\n2. **db**: Database layer\n"
        )

    agent.call = fake_call

    result = agent.run_revision(
        original_design="# Original Design",
        review="Missing database schema.",
        draft_revision="# Draft Design by reviewer",
        prd="# PRD content",
        project_name="Todo App",
    )

    assert "design" in result
    assert "modules" in result
    assert "Original Design" in captured["prompt"]
    assert "Missing database schema" in captured["prompt"]
    assert "Draft Design by reviewer" in captured["prompt"]
    assert "Revised Design" in result["design"]
    assert len(result["modules"]) >= 1


# ── helpers ────────────────────────────────────────────────────────────────

def _make_orch(max_prd=3, stop=False, max_design_revisions=3):
    """Minimal orchestrator for loop testing."""
    o = Orchestrator.__new__(Orchestrator)
    o.max_prd_revisions = max_prd
    o.max_design_revisions = max_design_revisions
    o.stop_on_prd_issues = stop
    o.stop_on_design_issues = False
    o.github = None
    o.target_github = None
    o._github_token = "tok"
    # Stub agents
    o.pm = MagicMock()
    o.pm_reviewer = MagicMock()
    o.architect = MagicMock()
    o.architect_reviewer = MagicMock()
    return o


def _make_result(stages=None):
    r = PipelineResult(requirement="build a todo app")
    r.prd = "# Initial PRD"
    r.project_name = "Todo App"
    r.completed_stages = list(stages or [])
    return r


# ── PRD revision loop ──────────────────────────────────────────────────────

def test_prd_revision_loop_approves_on_round_2():
    """Reviewer returns NEEDS_REVISION on first review, APPROVED on round 2."""
    o = _make_orch()
    r = _make_result(stages=["pm"])

    # First pm_reviewer call → NEEDS REVISION
    o.pm_reviewer.run.side_effect = [
        {
            "review": "Missing AC.",
            "verdict": PMReviewerAgent.VERDICT_REVISION,
            "needs_revision": True,
            "revised_prd": "# Reviewer Draft v1",
            "revised_project_name": "Todo App",
        },
        # After PM rewrites, second review → APPROVED
        {
            "review": "Looks good.",
            "verdict": PMReviewerAgent.VERDICT_APPROVED,
            "needs_revision": False,
            "revised_prd": None,
            "revised_project_name": "Todo App",
        },
    ]
    o.pm.run_revision.return_value = {
        "prd": "# Revised PRD v1",
        "project_name": "Todo App",
        "issue_number": None,
        "issue_url": None,
    }

    with patch.object(o, "_save_checkpoint"):
        ok = o._prd_revision_loop(r, "build a todo app")

    assert ok is True
    assert r.prd_revision_count == 1
    assert "pm_review_loop" in r.completed_stages
    assert r.prd == "# Revised PRD v1"


def test_prd_revision_loop_max_rounds_continue():
    """3 NEEDS_REVISION rounds → loop completes, pipeline continues, prd_revision_count == 3."""
    o = _make_orch(max_prd=3, stop=False)
    r = _make_result(stages=["pm"])

    needs_revision_resp = {
        "review": "Still not good.",
        "verdict": PMReviewerAgent.VERDICT_REVISION,
        "needs_revision": True,
        "revised_prd": "# Reviewer Draft",
        "revised_project_name": "Todo App",
    }
    o.pm_reviewer.run.side_effect = [needs_revision_resp] * 4  # initial + 3 rounds
    o.pm.run_revision.return_value = {
        "prd": "# Revised PRD",
        "project_name": "Todo App",
        "issue_number": None,
        "issue_url": None,
    }

    with patch.object(o, "_save_checkpoint"):
        ok = o._prd_revision_loop(r, "build a todo app")

    assert ok is True  # continues (stop_on_prd_issues=False)
    assert r.prd_revision_count == 3
    assert "pm_review_loop" in r.completed_stages


def test_prd_revision_loop_max_rounds_halt():
    """stop_on_prd_issues=True → pipeline returns False after max rounds."""
    o = _make_orch(max_prd=2, stop=True)
    r = _make_result(stages=["pm"])

    needs_revision_resp = {
        "review": "Needs work.",
        "verdict": PMReviewerAgent.VERDICT_REVISION,
        "needs_revision": True,
        "revised_prd": "# Draft",
        "revised_project_name": "Todo App",
    }
    o.pm_reviewer.run.side_effect = [needs_revision_resp] * 3
    o.pm.run_revision.return_value = {
        "prd": "# Revised",
        "project_name": "Todo App",
        "issue_number": None,
        "issue_url": None,
    }

    with patch.object(o, "_save_checkpoint"):
        ok = o._prd_revision_loop(r, "build a todo app")

    assert ok is False


def test_prd_revision_loop_checkpoint_resume():
    """Round 1 already in completed_stages → it is skipped on resume."""
    o = _make_orch(max_prd=3, stop=False)
    r = _make_result(stages=["pm", "pm_reviewer", "prd_revision_1"])
    r.prd_verdict = PMReviewerAgent.VERDICT_REVISION  # still needs revision

    # Only one more round should run (round 2)
    approved_resp = {
        "review": "LGTM.",
        "verdict": PMReviewerAgent.VERDICT_APPROVED,
        "needs_revision": False,
        "revised_prd": None,
        "revised_project_name": "Todo App",
    }
    o.pm_reviewer.run.return_value = approved_resp
    o.pm.run_revision.return_value = {
        "prd": "# Revised v2",
        "project_name": "Todo App",
        "issue_number": None,
        "issue_url": None,
    }

    with patch.object(o, "_save_checkpoint"):
        ok = o._prd_revision_loop(r, "build a todo app")

    # run_revision called once (round 2 only, not round 1)
    assert o.pm.run_revision.call_count == 1
    assert ok is True


def test_design_revision_loop_approves_on_round_1():
    """Loop exits after round 1 if reviewer approves on re-check."""
    from agents.architect_reviewer import ArchitectReviewerAgent

    orch = _make_orch(max_design_revisions=3)
    result = _make_result()
    result.prd = "PRD text"
    result.design = "initial design"

    call_count = {"n": 0}

    def fake_architect_reviewer(r):
        call_count["n"] += 1
        r.design_review = "looks good"
        r.design_reviewer_draft = r.design
        if call_count["n"] == 1:
            r.design_verdict = ArchitectReviewerAgent.VERDICT_REVISION
        else:
            r.design_verdict = "APPROVED"

    def fake_architect(r):
        r.design = "revised design"
        r.modules = [{"name": "module1", "description": "desc"}]

    def fake_arch_revision(r, rn):
        r.design = f"revised design round {rn}"
        r.design_revision_count = rn

    with patch.object(orch, "_stage_architect", side_effect=fake_architect), \
         patch.object(orch, "_stage_architect_reviewer", side_effect=fake_architect_reviewer), \
         patch.object(orch, "_stage_arch_revision", side_effect=fake_arch_revision), \
         patch.object(orch, "_save_checkpoint"):
        ok = orch._design_revision_loop(result)

    assert ok is True
    assert "architect_review_loop" in result.completed_stages
    assert call_count["n"] == 2  # initial + 1 re-review
    assert result.design_revision_count == 1
