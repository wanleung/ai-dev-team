# tests/test_pipeline_yaml.py
"""Tests for pipeline.yaml custom stage flow: parser, validator, loop execution, GUI registry."""
from __future__ import annotations
import pytest
from unittest.mock import MagicMock, patch


def _make_orch() -> "Orchestrator":
    from orchestrator import Orchestrator
    o = Orchestrator.__new__(Orchestrator)
    o.model = "gpt-4.1"
    o._github_token = "tok"
    o.github = None
    o.target_github = None
    o._mode = "standard"
    o._stage_skips = {}
    o._pipeline_yaml_stages = None
    o.max_prd_revisions = 3
    o.max_design_revisions = 3
    return o


# T1: PipelineStage has loop fields
def test_pipeline_stage_has_loop_fields():
    from orchestrator import PipelineStage
    s = PipelineStage(
        name="loop_0", label="🔁 Loop", description="looping",
        checkpoint_key="loop_0", fn=lambda r: None,
        loop_stages=["pm", "pm_reviewer"], loop_max=3, loop_until="APPROVED",
    )
    assert s.loop_stages == ["pm", "pm_reviewer"]
    assert s.loop_max == 3
    assert s.loop_until == "APPROVED"


# T1: PipelineStage loop fields default to empty/zero (non-loop stages unaffected)
def test_pipeline_stage_loop_fields_default_empty():
    from orchestrator import PipelineStage
    s = PipelineStage(
        name="tier_review", label="🏷️ Tier", description="tier",
        checkpoint_key="tier_review", fn=lambda r: None,
    )
    assert s.loop_stages == []
    assert s.loop_max == 1
    assert s.loop_until == ""


# T1: PipelineResult has last_verdict field
def test_pipeline_result_has_last_verdict():
    from orchestrator import PipelineResult
    r = PipelineResult(requirement="test")
    assert r.last_verdict == ""
    r.last_verdict = "APPROVED"
    assert r.last_verdict == "APPROVED"


# T1: Registry includes pm, pm_reviewer, architect, architect_reviewer
def test_registry_includes_pm_and_architect_stages():
    o = _make_orch()
    # Provide stubs so registry can build fn lambdas
    o.pm = MagicMock()
    o.pm_reviewer = MagicMock()
    o.architect = MagicMock()
    o.architect_reviewer = MagicMock()
    o.engineer = MagicMock()
    o.junior_engineer = MagicMock()
    o.senior_engineer = MagicMock()
    o.reviewer = MagicMock()
    o.qa = MagicMock()
    o.qa_planner = MagicMock()
    o.deployment_tester = MagicMock()
    o.tier_reviewer = MagicMock()
    registry = o._make_stage_registry()
    for name in ("pm", "pm_reviewer", "architect", "architect_reviewer"):
        assert name in registry, f"Expected {name!r} in registry"
