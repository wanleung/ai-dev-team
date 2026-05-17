"""Tests for Milestone 3: Learning — LearningAgent anti-pattern writer."""
import pytest
from pathlib import Path


def test_failure_record_has_required_fields():
    from agents.failure_record import FailureRecord
    from dataclasses import fields
    field_names = {f.name for f in fields(FailureRecord)}
    assert "agent_role" in field_names
    assert "error" in field_names
    assert "fix" in field_names
    assert "pipeline" in field_names
    assert "timestamp" in field_names
    assert "target_repo" in field_names


def test_failure_record_instantiation():
    from agents.failure_record import FailureRecord
    record = FailureRecord(
        agent_role="engineer",
        error="self.llm.generate() does not exist",
        fix="Use self.call(user_message) instead",
        pipeline="ai-feature",
        timestamp="2026-05-17T10:00:00",
    )
    assert record.agent_role == "engineer"
    assert record.error == "self.llm.generate() does not exist"
    assert record.target_repo is None


def test_learning_agent_has_role_name():
    from agents.learning_agent import LearningAgent
    assert LearningAgent.role_name == "learning_agent"


def test_learning_agent_appends_antipattern_to_role_file(tmp_path):
    """When target_repo=None, LearningAgent writes to roles/{agent_role}.md."""
    from agents.learning_agent import LearningAgent
    from agents.failure_record import FailureRecord
    from unittest.mock import patch, MagicMock

    role_file = tmp_path / "roles" / "engineer.md"
    role_file.parent.mkdir()
    role_file.write_text("# Engineer\n\n## Anti-patterns\n\n<!-- placeholder -->\n")

    failure = FailureRecord(
        agent_role="engineer",
        error="self.llm.generate() AttributeError",
        fix="Use self.call(user_message) instead",
        pipeline="ai-feature",
        timestamp="2026-05-17T10:00:00",
        target_repo=None,
    )

    agent = LearningAgent.__new__(LearningAgent)
    agent.call = MagicMock(return_value="- DO NOT call self.llm.generate() — use self.call(user_message) instead. (2026-05-17)")

    with patch.object(LearningAgent, "_get_roles_dir", return_value=tmp_path / "roles"):
        agent.run(failure)

    updated = role_file.read_text()
    assert "DO NOT call self.llm.generate()" in updated
    assert "2026-05-17" in updated


def test_learning_agent_writes_to_repo_patterns_for_target_repo(tmp_path):
    """When target_repo is set, LearningAgent writes to repo-patterns/{slug}.md."""
    from agents.learning_agent import LearningAgent
    from agents.failure_record import FailureRecord
    from unittest.mock import patch, MagicMock

    patterns_dir = tmp_path / "repo-patterns"
    patterns_dir.mkdir()

    failure = FailureRecord(
        agent_role="engineer",
        error="Wrong ORM call",
        fix="Use Django ORM select_related()",
        pipeline="ai-feature",
        timestamp="2026-05-17T10:00:00",
        target_repo="wanleung/myapp",
    )

    agent = LearningAgent.__new__(LearningAgent)
    agent.call = MagicMock(return_value="- DO NOT use raw SQL — use Django ORM select_related(). (2026-05-17)")

    with patch.object(LearningAgent, "_get_repo_patterns_dir", return_value=patterns_dir):
        agent.run(failure)

    patterns_file = patterns_dir / "wanleung-myapp.md"
    assert patterns_file.exists()
    content = patterns_file.read_text()
    assert "DO NOT use raw SQL" in content
    assert "wanleung/myapp" in content


def test_learning_agent_creates_antipatterns_section_if_missing(tmp_path):
    """LearningAgent creates ## Anti-patterns section if absent from role file."""
    from agents.learning_agent import LearningAgent
    from agents.failure_record import FailureRecord
    from unittest.mock import patch, MagicMock

    role_file = tmp_path / "roles" / "engineer.md"
    role_file.parent.mkdir()
    role_file.write_text("# Engineer\n\nSome content.\n")

    failure = FailureRecord(
        agent_role="engineer",
        error="Bad path",
        fix="Use absolute path",
        pipeline="ai-feature",
        timestamp="2026-05-17T10:00:00",
    )

    agent = LearningAgent.__new__(LearningAgent)
    agent.call = MagicMock(return_value="- DO NOT use relative paths — use absolute paths. (2026-05-17)")

    with patch.object(LearningAgent, "_get_roles_dir", return_value=tmp_path / "roles"):
        agent.run(failure)

    updated = role_file.read_text()
    assert "## Anti-patterns" in updated
    assert "DO NOT use relative paths" in updated


def test_validation_gate_triggers_learning_agent_on_exhaustion():
    """After 2 retries, validation_gate should instantiate LearningAgent."""
    from orchestrator import Orchestrator, PipelineResult
    from unittest.mock import MagicMock, patch

    orch = Orchestrator.__new__(Orchestrator)
    orch._github_token = "fake"
    orch.model = "test-model"
    orch.ollama_url = "http://localhost:11434"
    orch._rag_registry = None
    orch.target_github = None

    with patch("orchestrator.LearningAgent") as MockLearning:
        mock_instance = MagicMock()
        MockLearning.return_value = mock_instance

        result = PipelineResult()
        result.validation_attempts = 2
        result.all_files = {"bad.py": "def broken(\n    pass\n"}
        result.project_name = "test"
        result.issue_number = 1

        orch._stage_validation_gate(result)

        assert result.pr_draft is True
        MockLearning.assert_called_once()
        mock_instance.run.assert_called_once()
