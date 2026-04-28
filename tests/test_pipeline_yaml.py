# tests/test_pipeline_yaml.py
"""Tests for pipeline.yaml custom stage flow: parser, validator, loop execution, GUI registry."""
from __future__ import annotations
import pathlib
import tempfile
import pytest
import yaml as _yaml
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
    o.stop_on_review_issues = False
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


# T1: last_verdict survives checkpoint round-trip
def test_pipeline_result_last_verdict_round_trips():
    from orchestrator import PipelineResult
    r = PipelineResult(requirement="test")
    r.last_verdict = "APPROVED"
    d = r.to_dict()
    assert d["last_verdict"] == "APPROVED"
    r2 = PipelineResult.from_dict(d)
    assert r2.last_verdict == "APPROVED"


def _write_pipeline_yaml(content: str) -> str:
    """Write content to a temp pipeline.yaml and return path to its parent dir."""
    tmpdir = tempfile.mkdtemp()
    path = pathlib.Path(tmpdir) / "pipeline.yaml"
    path.write_text(content)
    # also write a dummy config.yaml so _load_pipeline_yaml can locate it
    (pathlib.Path(tmpdir) / "config.yaml").write_text("llm:\n  model: gpt-4.1\n")
    return str(pathlib.Path(tmpdir) / "config.yaml")


# Helper to get a minimal orch with all agent stubs
def _make_orch_full():
    o = _make_orch()
    for attr in ("pm", "pm_reviewer", "architect", "architect_reviewer",
                 "engineer", "junior_engineer", "senior_engineer", "reviewer",
                 "qa", "qa_planner", "deployment_tester", "tier_reviewer"):
        setattr(o, attr, MagicMock())
    return o


# T2: Valid flat stage list parses correctly
def test_load_pipeline_yaml_flat_list():
    o = _make_orch_full()
    cfg_path = _write_pipeline_yaml("stages:\n  - pm\n  - architect\n  - junior_engineer\n")
    stages = o._load_pipeline_yaml(cfg_path)
    assert stages is not None
    assert [s.name for s in stages] == ["pm", "architect", "junior_engineer"]


# T2: Valid loop block parses and expands
def test_load_pipeline_yaml_loop_block():
    o = _make_orch_full()
    cfg_path = _write_pipeline_yaml("""
stages:
  - loop:
      max: 3
      until: APPROVED
      stages:
        - pm
        - pm_reviewer
  - architect
""")
    stages = o._load_pipeline_yaml(cfg_path)
    assert stages is not None
    assert len(stages) == 2
    loop_stage = stages[0]
    assert loop_stage.loop_stages == ["pm", "pm_reviewer"]
    assert loop_stage.loop_max == 3
    assert loop_stage.loop_until == "APPROVED"
    assert stages[1].name == "architect"


# T2: Returns None when pipeline.yaml absent
def test_load_pipeline_yaml_returns_none_when_absent():
    o = _make_orch_full()
    tmpdir = tempfile.mkdtemp()
    cfg_path = str(pathlib.Path(tmpdir) / "config.yaml")
    pathlib.Path(cfg_path).write_text("llm:\n  model: gpt-4.1\n")
    result = o._load_pipeline_yaml(cfg_path)
    assert result is None


# T2: Unknown stage name raises ValueError
def test_load_pipeline_yaml_unknown_stage_raises():
    o = _make_orch_full()
    cfg_path = _write_pipeline_yaml("stages:\n  - pm\n  - nonexistent_stage\n")
    with pytest.raises(ValueError, match="nonexistent_stage"):
        o._load_pipeline_yaml(cfg_path)


# T2: Missing stages key raises ValueError
def test_load_pipeline_yaml_missing_stages_raises():
    o = _make_orch_full()
    cfg_path = _write_pipeline_yaml("mode: custom\n")
    with pytest.raises(ValueError, match="stages"):
        o._load_pipeline_yaml(cfg_path)


# T2: Loop block missing 'max' raises ValueError
def test_load_pipeline_yaml_loop_missing_max_raises():
    o = _make_orch_full()
    cfg_path = _write_pipeline_yaml("""
stages:
  - loop:
      until: APPROVED
      stages:
        - pm
""")
    with pytest.raises(ValueError, match="max"):
        o._load_pipeline_yaml(cfg_path)


# T2: Loop block with max <= 0 raises ValueError
def test_load_pipeline_yaml_loop_max_zero_raises():
    o = _make_orch_full()
    cfg_path = _write_pipeline_yaml("""
stages:
  - loop:
      max: 0
      until: APPROVED
      stages:
        - pm
""")
    with pytest.raises(ValueError, match="max"):
        o._load_pipeline_yaml(cfg_path)


# T2: Empty loop stages raises ValueError
def test_load_pipeline_yaml_empty_loop_stages_raises():
    o = _make_orch_full()
    cfg_path = _write_pipeline_yaml("""
stages:
  - loop:
      max: 3
      until: APPROVED
      stages: []
""")
    with pytest.raises(ValueError, match="non-empty"):
        o._load_pipeline_yaml(cfg_path)


# T2: Unknown stage name inside loop raises ValueError
def test_load_pipeline_yaml_loop_unknown_inner_stage_raises():
    o = _make_orch_full()
    cfg_path = _write_pipeline_yaml("""
stages:
  - loop:
      max: 2
      until: APPROVED
      stages:
        - pm
        - nonexistent_inner_stage
""")
    with pytest.raises(ValueError, match="nonexistent_inner_stage"):
        o._load_pipeline_yaml(cfg_path)


# T2: Invalid YAML syntax raises YAMLError
def test_load_pipeline_yaml_invalid_yaml_raises():
    o = _make_orch_full()
    cfg_path = _write_pipeline_yaml("stages:\n  - [unclosed bracket\n")
    with pytest.raises(_yaml.YAMLError):
        o._load_pipeline_yaml(cfg_path)


# T2: Empty until string raises ValueError
def test_load_pipeline_yaml_loop_empty_until_raises():
    o = _make_orch_full()
    cfg_path = _write_pipeline_yaml("""
stages:
  - loop:
      max: 3
      until: ""
      stages:
        - pm
""")
    with pytest.raises(ValueError, match="non-empty string"):
        o._load_pipeline_yaml(cfg_path)




import os


def _make_full_orch_with_pipeline_yaml(yaml_content: str):
    """Write pipeline.yaml, call from_config, return orchestrator."""
    import tempfile, pathlib
    from orchestrator import Orchestrator

    tmpdir = tempfile.mkdtemp()
    cfg = pathlib.Path(tmpdir) / "config.yaml"
    cfg.write_text("llm:\n  model: gpt-4.1\ngithub:\n  repo: ''\n")
    (pathlib.Path(tmpdir) / "pipeline.yaml").write_text(yaml_content)

    with patch.dict(os.environ, {"GITHUB_TOKEN": "tok"}):
        orch = Orchestrator.from_config(str(cfg), github_token="tok")
    return orch


# T3: from_config sets _pipeline_yaml_stages when pipeline.yaml present
def test_from_config_loads_pipeline_yaml_stages():
    orch = _make_full_orch_with_pipeline_yaml(
        "stages:\n  - junior_engineer\n  - reviewer\n"
    )
    assert orch._pipeline_yaml_stages is not None
    assert [s.name for s in orch._pipeline_yaml_stages] == ["junior_engineer", "reviewer"]


# T3: _build_stage_list uses pipeline_yaml_stages when set
def test_build_stage_list_uses_pipeline_yaml():
    orch = _make_full_orch_with_pipeline_yaml(
        "stages:\n  - junior_engineer\n  - reviewer\n"
    )
    stages = orch._build_stage_list()
    assert [s.name for s in stages] == ["junior_engineer", "reviewer"]


# T3: _build_stage_list falls back to MODES when pipeline.yaml absent
def test_build_stage_list_falls_back_to_modes_when_no_pipeline_yaml():
    import tempfile, pathlib
    from orchestrator import Orchestrator
    tmpdir = tempfile.mkdtemp()
    cfg = pathlib.Path(tmpdir) / "config.yaml"
    cfg.write_text("llm:\n  model: gpt-4.1\ngithub:\n  repo: ''\n")
    with patch.dict(os.environ, {"GITHUB_TOKEN": "tok"}):
        orch = Orchestrator.from_config(str(cfg), github_token="tok")
    assert orch._pipeline_yaml_stages is None
    stages = orch._build_stage_list()
    # standard mode: starts with tier_review
    assert stages[0].name == "tier_review"


# T3: pipeline_yaml_stages respects stage_skips
def test_pipeline_yaml_stages_respects_skips():
    orch = _make_full_orch_with_pipeline_yaml(
        "stages:\n  - junior_engineer\n  - reviewer\n"
    )
    orch._stage_skips = {"reviewer": True}
    stages = orch._build_stage_list()
    assert [s.name for s in stages] == ["junior_engineer"]


# T3: reviewer stages set last_verdict
def test_pm_reviewer_sets_last_verdict():
    from orchestrator import Orchestrator, PipelineResult

    orch = Orchestrator.__new__(Orchestrator)
    mock_pm_rev = MagicMock()
    mock_pm_rev.run.return_value = {
        "review": "Looks good",
        "verdict": "APPROVED",
        "needs_revision": False,
        "revised_prd": None,
        "revised_project_name": "proj",
    }
    orch.pm_reviewer = mock_pm_rev
    orch.github = None
    orch.max_prd_revisions = 3

    result = PipelineResult(requirement="req", prd="some prd", project_name="proj")
    orch._stage_pm_reviewer(result, "req")

    assert result.last_verdict == "APPROVED"


def test_architect_reviewer_sets_last_verdict():
    from orchestrator import Orchestrator, PipelineResult

    orch = Orchestrator.__new__(Orchestrator)
    mock_arch_rev = MagicMock()
    mock_arch_rev.run.return_value = {
        "review": "Design ok",
        "verdict": "APPROVED",
        "needs_revision": False,
        "revised_design": None,
        "revised_modules": [],
    }
    orch.architect_reviewer = mock_arch_rev
    orch.github = None
    orch.max_design_revisions = 3

    result = PipelineResult(requirement="req", prd="prd", design="design", modules=[])
    orch._stage_architect_reviewer(result)

    assert result.last_verdict == "APPROVED"


# T3: _run_loop_stage exits early when loop_until verdict is met
def test_run_loop_stage_exits_early_on_verdict():
    from orchestrator import Orchestrator, PipelineResult, PipelineStage
    orch = _make_orch_full()

    call_log = []

    def fake_pm_stage(r):
        call_log.append("pm")
        r.last_verdict = "APPROVED"

    registry = orch._make_stage_registry()
    registry["pm"] = PipelineStage(
        name="pm", label="PM", description="",
        checkpoint_key="pm", fn=fake_pm_stage,
    )

    loop_stage = PipelineStage(
        name="loop_0", label="🔁 Loop", description="",
        checkpoint_key="loop_0", fn=lambda r: None,
        loop_stages=["pm"], loop_max=3, loop_until="APPROVED",
    )

    result = PipelineResult(requirement="req")

    with patch.object(orch, '_make_stage_registry', return_value=registry), \
         patch.object(orch, '_run_stage', side_effect=lambda lbl, desc, r, fn: fn()):
        ok = orch._run_loop_stage(loop_stage, result)

    assert ok is True
    assert len(call_log) == 1        # stopped after first APPROVED
    assert result.last_verdict == "APPROVED"
