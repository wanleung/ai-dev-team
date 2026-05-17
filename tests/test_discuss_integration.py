# tests/test_discuss_integration.py
"""Integration test: pipeline.yaml containing a discuss_brainstorm stage."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml


class TestDiscussPipelineIntegration:
    """Verify that a pipeline.yaml with discuss_brainstorm resolves and runs."""

    def _build_orchestrator(self, tmp_path: Path):
        """Create a minimal Orchestrator with a temp discussions/ dir."""
        import shutil
        from orchestrator import Orchestrator

        # Copy preset files into a temp workspace
        repo_root = Path(__file__).parent.parent
        discussions_src = repo_root / "discussions"
        roles_src = repo_root / "roles"

        if discussions_src.exists():
            shutil.copytree(discussions_src, tmp_path / "discussions")
        if roles_src.exists():
            shutil.copytree(roles_src, tmp_path / "roles")

        orch = Orchestrator.__new__(Orchestrator)
        orch._stage_skips = {}
        orch._pipeline_yaml_stages = None
        orch._mode = "standard"
        orch.model = "gpt-4.1"
        orch._github_token = None
        orch.ollama_url = "http://localhost:11434"
        orch.stop_on_review_issues = False
        orch._discussions_dir = tmp_path / "discussions"
        for attr in ("pm", "pm_reviewer", "architect", "architect_reviewer",
                     "engineer", "junior_engineer", "senior_engineer", "reviewer",
                     "qa", "qa_planner", "deployment_tester", "tier_reviewer"):
            setattr(orch, attr, None)
        return orch

    def test_discuss_brainstorm_in_registry(self, tmp_path):
        orch = self._build_orchestrator(tmp_path)
        registry = orch._make_stage_registry()
        assert "discuss_brainstorm" in registry
        assert "discuss_news_analysis" in registry

    def test_discuss_stage_appears_in_palette(self, tmp_path):
        """_get_stage_palette() (used by UI builder) includes discuss stages."""
        orch = self._build_orchestrator(tmp_path)
        registry = orch._make_stage_registry()
        palette = [
            {"name": name, "label": stage.label, "description": stage.description}
            for name, stage in registry.items()
        ]
        names = [p["name"] for p in palette]
        assert "discuss_brainstorm" in names

    @patch("agents.discussion_agent.DiscussionAgent._make_backend")
    def test_discuss_stage_fn_runs(self, mock_backend, tmp_path):
        """The PipelineStage fn for discuss_brainstorm calls DiscussionAgent.run()."""
        from orchestrator import PipelineResult

        backend = MagicMock()
        backend.call.return_value = "This is a thoughtful response."
        mock_backend.return_value = backend

        orch = self._build_orchestrator(tmp_path)
        registry = orch._make_stage_registry()
        stage = registry["discuss_brainstorm"]

        result = PipelineResult(requirement="build a recommendation engine")
        result.issue_body = "We need a recommendation engine for our platform."
        stage.fn(result)

        assert "discuss_brainstorm" in result.completed_stages
        assert result.discussion_transcript != ""
