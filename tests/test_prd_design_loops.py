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
