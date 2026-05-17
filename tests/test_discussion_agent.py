# tests/test_discussion_agent.py
"""Unit tests for DiscussionAgent and DiscussionConfig."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from agents.discussion_agent import (
    DiscussionAgent,
    DiscussionConfig,
    Participant,
    Turn,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _write_preset(tmp_path: Path, data: dict) -> Path:
    """Write a discussions/*.yaml preset file and return its path."""
    p = tmp_path / "discussions" / "test_preset.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.dump(data), encoding="utf-8")
    return p


def _write_persona_file(tmp_path: Path, name: str, content: str) -> Path:
    roles = tmp_path / "roles"
    roles.mkdir(exist_ok=True)
    p = roles / name
    p.write_text(content, encoding="utf-8")
    return p


# ── DiscussionConfig.from_yaml ─────────────────────────────────────────────

class TestDiscussionConfigFromYaml:
    def test_loads_inline_persona(self, tmp_path):
        preset = _write_preset(tmp_path, {
            "participants": [
                {"role": "analyst", "persona": "You are an analyst."},
                {"role": "skeptic", "persona": "You are a skeptic."},
            ],
            "max_rounds": 2,
            "output_mode": "transcript",
        })
        cfg = DiscussionConfig.from_yaml(str(preset))
        assert len(cfg.participants) == 2
        assert cfg.participants[0].role == "analyst"
        assert cfg.participants[0].persona == "You are an analyst."
        assert cfg.max_rounds == 2
        assert cfg.output_mode == "transcript"

    def test_loads_persona_file(self, tmp_path):
        _write_persona_file(tmp_path, "analyst.md", "You are a deep analyst.")
        preset = _write_preset(tmp_path, {
            "participants": [
                {"role": "analyst", "persona_file": "roles/analyst.md"},
            ],
        })
        cfg = DiscussionConfig.from_yaml(str(preset))
        assert cfg.participants[0].persona == "You are a deep analyst."

    def test_raises_on_missing_persona(self, tmp_path):
        preset = _write_preset(tmp_path, {
            "participants": [{"role": "analyst"}],
        })
        with pytest.raises(ValueError, match="persona"):
            DiscussionConfig.from_yaml(str(preset))

    def test_raises_on_missing_persona_file(self, tmp_path):
        preset = _write_preset(tmp_path, {
            "participants": [
                {"role": "analyst", "persona_file": "roles/nonexistent.md"},
            ],
        })
        with pytest.raises((FileNotFoundError, OSError)):
            DiscussionConfig.from_yaml(str(preset))

    def test_max_rounds_minimum_one(self, tmp_path):
        preset = _write_preset(tmp_path, {
            "participants": [{"role": "a", "persona": "p"}],
            "max_rounds": 0,
        })
        cfg = DiscussionConfig.from_yaml(str(preset))
        assert cfg.max_rounds == 1

    def test_defaults(self, tmp_path):
        preset = _write_preset(tmp_path, {
            "participants": [{"role": "a", "persona": "p"}],
        })
        cfg = DiscussionConfig.from_yaml(str(preset))
        assert cfg.homework_round is False
        assert cfg.max_rounds == 3
        assert cfg.early_exit == "CONSENSUS_REACHED"
        assert cfg.output_mode == "both"
        assert cfg.context_fields == ["issue_body"]
        assert cfg.moderator is None

    def test_optional_moderator_loaded(self, tmp_path):
        preset = _write_preset(tmp_path, {
            "participants": [{"role": "a", "persona": "p"}],
            "moderator": {"persona": "You synthesise."},
        })
        cfg = DiscussionConfig.from_yaml(str(preset))
        assert cfg.moderator is not None
        assert cfg.moderator.persona == "You synthesise."

    def test_llm_override_per_participant(self, tmp_path):
        preset = _write_preset(tmp_path, {
            "participants": [
                {"role": "a", "persona": "p", "llm": "opencode-go/qwen3.6-plus"},
            ],
        })
        cfg = DiscussionConfig.from_yaml(str(preset))
        assert cfg.participants[0].llm == "opencode-go/qwen3.6-plus"

    def test_config_name_derived_from_filename(self, tmp_path):
        p = tmp_path / "discussions" / "news_analysis.yaml"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(yaml.dump({"participants": [{"role": "a", "persona": "p"}]}), encoding="utf-8")
        cfg = DiscussionConfig.from_yaml(str(p))
        assert cfg.name == "news_analysis"


    def test_raises_on_non_dict_yaml(self, tmp_path):
        p = tmp_path / "discussions" / "bad.yaml"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("just a string", encoding="utf-8")
        with pytest.raises(ValueError, match="YAML mapping"):
            DiscussionConfig.from_yaml(str(p))

    def test_raises_on_participants_not_list(self, tmp_path):
        p = tmp_path / "discussions" / "bad.yaml"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("participants: bad_string", encoding="utf-8")
        with pytest.raises(ValueError, match="participants"):
            DiscussionConfig.from_yaml(str(p))

    def test_raises_on_participant_missing_role(self, tmp_path):
        preset = _write_preset(tmp_path, {
            "participants": [{"persona": "no role here"}],
        })
        with pytest.raises(ValueError, match="role"):
            DiscussionConfig.from_yaml(str(preset))

    def test_raises_on_invalid_output_mode(self, tmp_path):
        preset = _write_preset(tmp_path, {
            "participants": [{"role": "a", "persona": "p"}],
            "output_mode": "invalid_value",
        })
        with pytest.raises(ValueError, match="output_mode"):
            DiscussionConfig.from_yaml(str(preset))


class TestDiscussionAgentStub:
    def test_stub_instantiates(self, tmp_path):
        preset = _write_preset(tmp_path, {
            "participants": [{"role": "a", "persona": "p"}],
        })
        cfg = DiscussionConfig.from_yaml(str(preset))
        agent = DiscussionAgent(cfg, model="gpt-4.1", github_token=None)
        assert agent.config is cfg


class TestDiscussionAgentHelpers:
    def _make_agent(self, tmp_path: Path) -> DiscussionAgent:
        preset = _write_preset(tmp_path, {
            "participants": [
                {"role": "analyst", "persona": "You are an analyst."},
                {"role": "skeptic", "persona": "You are a skeptic."},
            ],
        })
        cfg = DiscussionConfig.from_yaml(str(preset))
        return DiscussionAgent(cfg, model="gpt-4.1", github_token=None)

    def test_build_context_uses_issue_body(self, tmp_path):
        from orchestrator import PipelineResult
        agent = self._make_agent(tmp_path)
        result = PipelineResult(requirement="build a blog")
        result.issue_body = "User wants a fast blog."
        context = agent._build_context(result)
        assert "User wants a fast blog." in context

    def test_build_context_fallback_to_requirement(self, tmp_path):
        from orchestrator import PipelineResult
        agent = self._make_agent(tmp_path)
        result = PipelineResult(requirement="build a blog")
        context = agent._build_context(result)
        assert "build a blog" in context

    def test_format_full_transcript_no_homework(self, tmp_path):
        agent = self._make_agent(tmp_path)
        turns = [
            Turn(role="analyst", content="This is a good idea.", round_num=1),
            Turn(role="skeptic", content="I doubt it.", round_num=1),
        ]
        out = agent._format_full_transcript(turns, "test")
        assert "=== Discussion: test ===" in out
        assert "[Round 1]" in out
        assert "ANALYST: This is a good idea." in out
        assert "SKEPTIC: I doubt it." in out

    def test_format_full_transcript_with_homework(self, tmp_path):
        preset = _write_preset(tmp_path, {
            "participants": [
                {"role": "analyst", "persona": "p"},
                {"role": "skeptic", "persona": "p"},
            ],
            "homework_round": True,
        })
        cfg = DiscussionConfig.from_yaml(str(preset))
        agent = DiscussionAgent(cfg, model="gpt-4.1", github_token=None)
        turns = [
            Turn(role="analyst", content="Homework.", round_num=0),
            Turn(role="skeptic", content="Homework too.", round_num=0),
            Turn(role="analyst", content="Now discuss.", round_num=1),
        ]
        out = agent._format_full_transcript(turns, "test")
        assert "[Round 0 — Homework]" in out
        assert "[Round 1]" in out


class TestDiscussionAgentRun:
    def _make_cfg(self, tmp_path: Path, **overrides) -> DiscussionConfig:
        data = {
            "participants": [
                {"role": "analyst", "persona": "You are an analyst."},
                {"role": "skeptic", "persona": "You are a skeptic."},
            ],
            "max_rounds": 1,
            "output_mode": "both",
        }
        data.update(overrides)
        preset = _write_preset(tmp_path, data)
        return DiscussionConfig.from_yaml(str(preset))

    def _make_result(self):
        from orchestrator import PipelineResult
        r = PipelineResult(requirement="build a news analyser")
        r.issue_body = "We need to analyse tech news."
        return r

    @patch("agents.discussion_agent.DiscussionAgent._make_backend")
    def test_run_writes_transcript(self, mock_backend, tmp_path):
        backend = MagicMock()
        backend.call.return_value = "My analysis."
        mock_backend.return_value = backend

        cfg = self._make_cfg(tmp_path)
        agent = DiscussionAgent(cfg, model="gpt-4.1")
        result = self._make_result()
        agent.run(result)

        assert "ANALYST" in result.discussion_transcript
        assert "SKEPTIC" in result.discussion_transcript

    @patch("agents.discussion_agent.DiscussionAgent._make_backend")
    def test_run_writes_synthesis(self, mock_backend, tmp_path):
        backend = MagicMock()
        backend.call.return_value = "My analysis."
        mock_backend.return_value = backend

        cfg = self._make_cfg(tmp_path)
        agent = DiscussionAgent(cfg, model="gpt-4.1")
        result = self._make_result()
        agent.run(result)

        assert result.discussion_synthesis == "My analysis."

    @patch("agents.discussion_agent.DiscussionAgent._make_backend")
    def test_early_exit_stops_rounds(self, mock_backend, tmp_path):
        backend = MagicMock()
        # Analyst triggers early exit on first turn
        backend.call.side_effect = ["I agree CONSENSUS_REACHED", "Should not be called"]
        mock_backend.return_value = backend

        cfg = self._make_cfg(tmp_path, max_rounds=5)
        agent = DiscussionAgent(cfg, model="gpt-4.1")
        result = self._make_result()
        agent.run(result)

        # backend.call should have been called only twice (analyst triggers exit,
        # synthesis still called once for moderator = last participant)
        assert backend.call.call_count == 2   # analyst (exit) + synthesis moderator

    @patch("agents.discussion_agent.DiscussionAgent._make_backend")
    def test_transcript_only_output_mode(self, mock_backend, tmp_path):
        backend = MagicMock()
        backend.call.return_value = "Response."
        mock_backend.return_value = backend

        cfg = self._make_cfg(tmp_path, output_mode="transcript")
        agent = DiscussionAgent(cfg, model="gpt-4.1")
        result = self._make_result()
        agent.run(result)

        assert result.discussion_transcript != ""
        assert result.discussion_synthesis == ""

    @patch("agents.discussion_agent.DiscussionAgent._make_backend")
    def test_homework_round_runs_parallel(self, mock_backend, tmp_path):
        backend = MagicMock()
        backend.call.return_value = "Homework done."
        mock_backend.return_value = backend

        cfg = self._make_cfg(tmp_path, homework_round=True)
        agent = DiscussionAgent(cfg, model="gpt-4.1")
        result = self._make_result()
        agent.run(result)

        assert "[Round 0 — Homework]" in result.discussion_transcript
