"""Tests for Milestone 4: Bootstrap — BootstrapPatternsAgent."""
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


def test_bootstrap_patterns_agent_has_role_name():
    from agents.bootstrap_patterns_agent import BootstrapPatternsAgent
    assert BootstrapPatternsAgent.role_name == "bootstrap_patterns_agent"


def test_bootstrap_patterns_agent_run_returns_agents_md_content():
    """run() returns markdown string containing ## Codebase Patterns."""
    from agents.bootstrap_patterns_agent import BootstrapPatternsAgent

    agent = BootstrapPatternsAgent.__new__(BootstrapPatternsAgent)
    agent.call = MagicMock(return_value=(
        "# AI Agent Codebase Patterns for testowner/myapp\n\n"
        "## Stack\n- Python: 3.11\n\n"
        "## Codebase Patterns\n\n### Entry points\n- Main: `main.py`\n\n"
        "## Anti-patterns\n\n<!-- placeholder -->\n"
    ))

    mock_gh = MagicMock()
    mock_gh.repo = "testowner/myapp"
    mock_gh.get_full_tree.return_value = [
        {"type": "blob", "path": "main.py"},
        {"type": "blob", "path": "requirements.txt"},
    ]
    mock_gh.get_file_content.return_value = "flask==3.0.0\n"
    mock_gh.get_default_branch.return_value = "main"

    result = agent.run(mock_gh)
    assert "## Codebase Patterns" in result
    assert "testowner/myapp" in result


def test_bootstrap_patterns_agent_commits_to_copilot_instructions():
    """run() commits .github/copilot-instructions.md to the target repo (GitHub standard)."""
    from agents.bootstrap_patterns_agent import BootstrapPatternsAgent

    agent = BootstrapPatternsAgent.__new__(BootstrapPatternsAgent)
    patterns_content = "# AI Agent Codebase Patterns\n\n## Codebase Patterns\n\n- Use Flask.\n"
    agent.call = MagicMock(return_value=patterns_content)

    mock_gh = MagicMock()
    mock_gh.repo = "testowner/myapp"
    mock_gh.get_full_tree.return_value = [{"type": "blob", "path": "app.py"}]
    mock_gh.get_file_content.return_value = None
    mock_gh.get_default_branch.return_value = "main"

    agent.run(mock_gh, commit=True)

    mock_gh.commit_file.assert_called_once_with(
        path=".github/copilot-instructions.md",
        content=patterns_content,
        message="chore: add AI agent codebase patterns [bootstrap]",
        branch="main",
    )


def test_bootstrap_pipeline_yaml_exists():
    pipeline = Path("pipelines/bootstrap-patterns.yaml")
    assert pipeline.exists()
    import yaml
    data = yaml.safe_load(pipeline.read_text())
    assert "stages" in data
    assert "bootstrap_patterns" in data["stages"]
