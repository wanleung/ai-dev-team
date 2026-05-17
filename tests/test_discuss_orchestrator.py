# tests/test_discuss_orchestrator.py
"""Tests for discussion stage orchestrator integration."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from orchestrator import PipelineResult


class TestPipelineResultDiscussionFields:
    def test_discussion_transcript_default_empty(self):
        r = PipelineResult(requirement="test")
        assert r.discussion_transcript == ""

    def test_discussion_synthesis_default_empty(self):
        r = PipelineResult(requirement="test")
        assert r.discussion_synthesis == ""

    def test_discussion_fields_in_to_dict(self):
        r = PipelineResult(requirement="test")
        r.discussion_transcript = "ANALYST: hello"
        r.discussion_synthesis = "Summary: good idea"
        d = r.to_dict()
        assert d["discussion_transcript"] == "ANALYST: hello"
        assert d["discussion_synthesis"] == "Summary: good idea"

    def test_discussion_fields_round_trip(self):
        r = PipelineResult(requirement="test")
        r.discussion_transcript = "ANALYST: hello"
        r.discussion_synthesis = "Summary"
        r2 = PipelineResult.from_dict(r.to_dict())
        assert r2.discussion_transcript == "ANALYST: hello"
        assert r2.discussion_synthesis == "Summary"


class TestDiscussStageDiscovery:
    def _write_preset(self, tmp_path: Path, name: str) -> Path:
        discussions = tmp_path / "discussions"
        discussions.mkdir(exist_ok=True)
        p = discussions / f"{name}.yaml"
        p.write_text(yaml.dump({
            "participants": [{"role": "analyst", "persona": "You are an analyst."}],
            "max_rounds": 1,
            "output_mode": "transcript",
        }), encoding="utf-8")
        return p

    def test_discuss_stage_registered_from_yaml(self, tmp_path):
        from orchestrator import Orchestrator
        self._write_preset(tmp_path, "brainstorm")

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

        registry = orch._make_stage_registry()
        assert "discuss_brainstorm" in registry
        stage = registry["discuss_brainstorm"]
        assert "💬" in stage.label
        assert "brainstorm" in stage.label.lower()

    def test_no_discussions_dir_no_error(self, tmp_path):
        from orchestrator import Orchestrator
        orch = Orchestrator.__new__(Orchestrator)
        orch._stage_skips = {}
        orch._pipeline_yaml_stages = None
        orch._mode = "standard"
        orch.model = "gpt-4.1"
        orch._github_token = None
        orch.ollama_url = "http://localhost:11434"
        orch.stop_on_review_issues = False
        orch._discussions_dir = tmp_path / "nonexistent"
        for attr in ("pm", "pm_reviewer", "architect", "architect_reviewer",
                     "engineer", "junior_engineer", "senior_engineer", "reviewer",
                     "qa", "qa_planner", "deployment_tester", "tier_reviewer"):
            setattr(orch, attr, None)

        registry = orch._make_stage_registry()
        assert not any(k.startswith("discuss_") for k in registry)


def test_stage_discuss_passes_memory_to_agent(tmp_path):
    """_stage_discuss() passes self.memory to DiscussionAgent.run()."""
    from unittest.mock import MagicMock, patch
    from orchestrator import Orchestrator

    orch = Orchestrator.__new__(Orchestrator)
    orch._discussions_dir = tmp_path / "discussions"
    orch._discussions_dir.mkdir()
    orch.memory = MagicMock()
    orch.model = "gpt-4.1"
    orch._github_token = None
    orch.ollama_url = "http://localhost:11434"

    # Create a minimal discussion YAML
    disc_yaml = orch._discussions_dir / "test_disc.yaml"
    disc_yaml.write_text(
        "participants:\n  - role: analyst\n    persona: You are an analyst.\nmax_rounds: 1\nhomework_round: false\n"
    )

    result = PipelineResult(requirement="hello world")

    with patch("agents.discussion_agent.DiscussionAgent.run") as mock_run:
        mock_run.return_value = MagicMock()  # return value unused by _stage_discuss
        orch._stage_discuss(result, str(disc_yaml))

    # Verify memory_store was passed
    call_kwargs = mock_run.call_args.kwargs
    assert "memory_store" in call_kwargs
    assert call_kwargs["memory_store"] is orch.memory
    assert "repo" in call_kwargs
