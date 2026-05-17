"""Tests for Milestone 1: Prevention — role file cheatsheets and context injection."""
import pytest
from pathlib import Path


def test_engineer_role_has_codebase_patterns_section():
    """Engineer role file must have a ## Codebase Patterns section."""
    role = Path("roles/engineer.md").read_text()
    assert "## Codebase Patterns" in role


def test_engineer_role_documents_self_call():
    """Engineer role file must document self.call() as the correct LLM method."""
    role = Path("roles/engineer.md").read_text()
    assert "self.call(" in role
    assert "self.llm.generate" not in role.split("## Codebase Patterns")[1]


def test_engineer_role_documents_stage_registry():
    """Engineer role file must explain _make_stage_registry() wiring."""
    role = Path("roles/engineer.md").read_text()
    assert "_make_stage_registry" in role


def test_engineer_role_documents_repos_yaml_rule():
    """Engineer role file must warn against rewriting repos.yaml."""
    role = Path("roles/engineer.md").read_text()
    assert "repos.yaml" in role


def test_engineer_role_documents_role_name():
    """Engineer role file must document the role_name class attribute requirement."""
    role = Path("roles/engineer.md").read_text()
    assert "role_name" in role


def test_build_engineer_context_tier_a_base_agent():
    """Tier A: when task mentions BaseAgent, context includes base_agent.py snippet."""
    from orchestrator import Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    ctx = orch._build_engineer_context("Create a new BaseAgent subclass for X")
    assert "base_agent.py" in ctx.lower() or "BaseAgent" in ctx


def test_build_engineer_context_tier_a_repos_yaml():
    """Tier A: when task mentions repos.yaml, context includes current file contents."""
    from orchestrator import Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    ctx = orch._build_engineer_context("Add a new entry to repos.yaml")
    assert "watchers:" in ctx or "repos.yaml" in ctx.lower()


def test_build_engineer_context_tier_a_stage_registry():
    """Tier A: when task mentions pipeline stage, context includes _make_stage_registry."""
    from orchestrator import Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    ctx = orch._build_engineer_context("Add a new pipeline stage to _make_stage_registry")
    assert "_make_stage_registry" in ctx or "PipelineStage" in ctx


def test_build_engineer_context_tier_a_empty_for_unrelated():
    """Tier A: unrelated task with no target_gh gets empty context."""
    from orchestrator import Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    ctx = orch._build_engineer_context("Write a markdown README for the project")
    assert ctx == "" or len(ctx) < 100


def test_build_engineer_context_tier_b_uses_local_fallback(tmp_path):
    """Tier B: if all remote files absent, falls back to repo-patterns/{slug}.md."""
    from orchestrator import Orchestrator
    from unittest.mock import MagicMock, patch

    orch = Orchestrator.__new__(Orchestrator)

    mock_gh = MagicMock()
    mock_gh.repo = "testowner/myapp"
    mock_gh.get_file_content.return_value = None  # all remote lookups return None

    patterns_dir = tmp_path / "repo-patterns"
    patterns_dir.mkdir()
    fallback = patterns_dir / "testowner-myapp.md"
    fallback.write_text("## Codebase Patterns\n\n- Use Django ORM, never raw SQL.\n")

    with patch.object(Orchestrator, "_get_repo_patterns_dir", return_value=patterns_dir):
        ctx = orch._build_engineer_context("Fix the login bug", target_gh=mock_gh)

    assert "Django ORM" in ctx
    assert "testowner/myapp" in ctx or "testowner-myapp" in ctx


def test_build_engineer_context_tier_b_prefers_copilot_instructions():
    """Tier B: .github/copilot-instructions.md is checked first."""
    from orchestrator import Orchestrator
    from unittest.mock import MagicMock, call

    orch = Orchestrator.__new__(Orchestrator)

    mock_gh = MagicMock()
    mock_gh.repo = "testowner/myapp"

    def fake_get_file_content(path):
        if path == ".github/copilot-instructions.md":
            return "## Codebase Patterns\n\n- Always use TypeScript strict mode.\n"
        return None

    mock_gh.get_file_content.side_effect = fake_get_file_content

    ctx = orch._build_engineer_context("Add a new API endpoint", target_gh=mock_gh)

    assert "TypeScript strict mode" in ctx
    assert mock_gh.get_file_content.call_args_list[0] == call(
        ".github/copilot-instructions.md"
    )


def test_build_engineer_context_tier_b_falls_through_to_claude_md():
    """Tier B: falls through to CLAUDE.md if copilot-instructions.md is absent."""
    from orchestrator import Orchestrator
    from unittest.mock import MagicMock

    orch = Orchestrator.__new__(Orchestrator)

    mock_gh = MagicMock()
    mock_gh.repo = "testowner/myapp"

    def fake_get_file_content(path):
        if path == "CLAUDE.md":
            return "## Codebase Patterns\n\n- Use async/await, not callbacks.\n"
        return None

    mock_gh.get_file_content.side_effect = fake_get_file_content

    ctx = orch._build_engineer_context("Fix the bug", target_gh=mock_gh)

    assert "async/await" in ctx
