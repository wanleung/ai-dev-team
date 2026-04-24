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
