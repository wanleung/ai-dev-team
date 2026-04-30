"""Tests for the unified Orchestrator stage registry."""
import pytest


def test_bug_fix_stages_registered():
    """Bug-fix stages should be available in the unified registry."""
    from orchestrator import Orchestrator

    orch = Orchestrator(model="gpt-4.1", use_github=False, github_token=None, github_repo=None, target_repo=None)
    registry = orch._make_stage_registry()
    assert "diagnose" in registry
    assert "bug_fix" in registry


def test_doc_stages_registered():
    """Documentation stages should be available in the unified registry."""
    from orchestrator import Orchestrator

    orch = Orchestrator(model="gpt-4.1", use_github=False, github_token=None, github_repo=None, target_repo=None)
    registry = orch._make_stage_registry()
    assert "doc_generate" in registry
    assert "doc_commit_pr" in registry


def test_existing_stages_still_present():
    """Original stages must not be removed by this refactor."""
    from orchestrator import Orchestrator

    orch = Orchestrator(model="gpt-4.1", use_github=False, github_token=None, github_repo=None, target_repo=None)
    registry = orch._make_stage_registry()
    for name in ("pm", "architect", "engineer", "reviewer", "qa_engineer", "test_fix", "deploy_tester"):
        assert name in registry, f"Existing stage {name!r} disappeared"


def test_load_pipeline_for_label_finds_builtin(tmp_path, monkeypatch):
    """Orchestrator can load pipelines/<label>.yaml from the script dir."""
    from orchestrator import Orchestrator

    orch = Orchestrator(model="gpt-4.1", use_github=False, github_token=None, github_repo=None, target_repo=None)
    stages = orch.load_pipeline_for_label("ai-feature")
    assert stages is not None
    assert isinstance(stages, list)
    assert len(stages) > 0


def test_load_pipeline_for_label_unknown_returns_none():
    from orchestrator import Orchestrator

    orch = Orchestrator(model="gpt-4.1", use_github=False, github_token=None, github_repo=None, target_repo=None)
    assert orch.load_pipeline_for_label("no-such-label") is None


def test_load_pipeline_for_label_project_overrides_builtin(tmp_path):
    """A pipeline.yaml at the project root takes priority over pipelines/<label>.yaml."""
    from orchestrator import Orchestrator

    project = tmp_path / "myproject"
    project.mkdir()
    (project / "pipeline.yaml").write_text(
        "stages:\n  - pm\n  - engineer\n", encoding="utf-8"
    )
    orch = Orchestrator(
        model="gpt-4.1", use_github=False,
        github_token=None, github_repo=None, target_repo=None,
    )
    stages = orch.load_pipeline_for_label("ai-feature", project_dir=str(project))
    # Project pipeline.yaml wins
    assert stages == ["pm", "engineer"]
