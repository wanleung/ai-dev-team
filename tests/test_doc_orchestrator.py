"""Tests for documentation pipeline stages in orchestrator (_stage_doc_*)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call
import pytest

from orchestrator import Orchestrator, PipelineResult


def _make_orchestrator():
    """Build a minimal Orchestrator for testing doc stages."""
    orch = Orchestrator.__new__(Orchestrator)
    orch.model = "test-model"
    orch._github_token = "test-token"
    orch.ollama_url = None
    orch.github = MagicMock()
    orch.target_github = None
    return orch


def _make_result():
    """Build a minimal PipelineResult for testing."""
    r = PipelineResult.__new__(PipelineResult)
    r.errors = []
    r.add_error = lambda msg: r.errors.append(msg)
    r.all_files = {}
    r.requirement = "Test requirement"
    r.project_name = "test-project"
    r.issue_number = 42
    r.pr_number = None
    r.pr_url = None
    r.branch = None
    return r


# ── _stage_doc_generate tests ────────────────────────────────────────────


def test_stage_doc_generate_happy_path_writes_files_to_result():
    """_stage_doc_generate should call DocumentationAgent and store files."""
    orch = _make_orchestrator()
    result = _make_result()
    
    mock_agent = MagicMock()
    mock_agent.run.return_value = [
        {"path": "docs/README.md", "content": "# Docs\n"},
        {"path": "docs/api.md", "content": "# API\n"},
    ]
    
    with patch("agents.DocumentationAgent", return_value=mock_agent):
        orch._stage_doc_generate(result)
    
    # Check agent was called with correct args
    mock_agent.run.assert_called_once()
    call_kwargs = mock_agent.run.call_args[1]
    assert call_kwargs["issue_title"] == "test-project"
    assert call_kwargs["issue_body"] == "Test requirement"
    assert call_kwargs["github_client"] == orch.github
    
    # Check files stored in result
    assert "docs/README.md" in result.all_files
    assert "docs/api.md" in result.all_files
    assert result.all_files["docs/README.md"] == "# Docs\n"
    assert result.all_files["docs/api.md"] == "# API\n"
    assert result.errors == []


def test_stage_doc_generate_no_github_adds_error():
    """_stage_doc_generate should fail gracefully when no GitHub client."""
    orch = _make_orchestrator()
    orch.github = None
    orch.target_github = None
    result = _make_result()
    
    orch._stage_doc_generate(result)
    
    assert len(result.errors) == 1
    assert "doc_generate requires a GitHub connection" in result.errors[0]
    assert result.all_files == {}


def test_stage_doc_generate_uses_target_github_when_available():
    """_stage_doc_generate should prefer target_github over github."""
    orch = _make_orchestrator()
    orch.target_github = MagicMock()
    result = _make_result()
    
    mock_agent = MagicMock()
    mock_agent.run.return_value = []
    
    with patch("agents.DocumentationAgent", return_value=mock_agent):
        orch._stage_doc_generate(result)
    
    # Should use target_github, not github
    call_kwargs = mock_agent.run.call_args[1]
    assert call_kwargs["github_client"] == orch.target_github


def test_stage_doc_generate_agent_returns_none():
    """_stage_doc_generate should handle agent returning None."""
    orch = _make_orchestrator()
    result = _make_result()
    
    mock_agent = MagicMock()
    mock_agent.run.return_value = None
    
    with patch("agents.DocumentationAgent", return_value=mock_agent):
        orch._stage_doc_generate(result)
    
    assert result.all_files == {}
    assert result.errors == []


def test_stage_doc_generate_agent_returns_empty_list():
    """_stage_doc_generate should handle agent returning empty list."""
    orch = _make_orchestrator()
    result = _make_result()
    
    mock_agent = MagicMock()
    mock_agent.run.return_value = []
    
    with patch("agents.DocumentationAgent", return_value=mock_agent):
        orch._stage_doc_generate(result)
    
    assert result.all_files == {}
    assert result.errors == []


def test_stage_doc_generate_skips_files_with_empty_path():
    """_stage_doc_generate should skip file writes with empty path."""
    orch = _make_orchestrator()
    result = _make_result()
    
    mock_agent = MagicMock()
    mock_agent.run.return_value = [
        {"path": "docs/good.md", "content": "# Good\n"},
        {"path": "", "content": "# Bad\n"},
        {"content": "# No path key\n"},
    ]
    
    with patch("agents.DocumentationAgent", return_value=mock_agent):
        orch._stage_doc_generate(result)
    
    # Only the file with a valid path should be stored
    assert "docs/good.md" in result.all_files
    assert len(result.all_files) == 1


def test_stage_doc_generate_uses_issue_number_fallback_title():
    """_stage_doc_generate should use issue_number fallback when no project_name."""
    orch = _make_orchestrator()
    result = _make_result()
    result.project_name = None
    result.issue_number = 99
    
    mock_agent = MagicMock()
    mock_agent.run.return_value = []
    
    with patch("agents.DocumentationAgent", return_value=mock_agent):
        orch._stage_doc_generate(result)
    
    call_kwargs = mock_agent.run.call_args[1]
    assert call_kwargs["issue_title"] == "docs-99"


def test_stage_doc_generate_uses_empty_fallback_title():
    """_stage_doc_generate should use empty fallback when no project_name or issue_number."""
    orch = _make_orchestrator()
    result = _make_result()
    result.project_name = None
    result.issue_number = None
    
    mock_agent = MagicMock()
    mock_agent.run.return_value = []
    
    with patch("agents.DocumentationAgent", return_value=mock_agent):
        orch._stage_doc_generate(result)
    
    call_kwargs = mock_agent.run.call_args[1]
    assert call_kwargs["issue_title"] == "docs-"


def test_stage_doc_generate_agent_raises_exception():
    """_stage_doc_generate should propagate agent exceptions (caught by orchestrator)."""
    orch = _make_orchestrator()
    result = _make_result()
    
    mock_agent = MagicMock()
    mock_agent.run.side_effect = ValueError("Agent failed")
    
    with patch("agents.DocumentationAgent", return_value=mock_agent):
        with pytest.raises(ValueError, match="Agent failed"):
            orch._stage_doc_generate(result)


# ── _stage_doc_commit_pr tests ────────────────────────────────────────────


def test_stage_doc_commit_pr_happy_path_calls_helper():
    """_stage_doc_commit_pr should call _commit_and_open_pr with doc params."""
    orch = _make_orchestrator()
    orch._commit_and_open_pr = MagicMock()
    result = _make_result()
    result.all_files = {"docs/README.md": "# Docs\n"}
    
    orch._stage_doc_commit_pr(result)
    
    orch._commit_and_open_pr.assert_called_once()
    call_args = orch._commit_and_open_pr.call_args
    assert call_args[0][0] == result
    assert call_args[1]["branch_prefix"] == "docs/agent"
    assert call_args[1]["title_prefix"] == "docs"
    assert call_args[1]["body_header"] == "## 📚 Documentation Update"
    assert call_args[1]["commit_msg_prefix"] == "docs"


def test_stage_doc_commit_pr_no_files_skips_commit():
    """_stage_doc_commit_pr should do nothing when all_files is empty."""
    orch = _make_orchestrator()
    orch._commit_and_open_pr = MagicMock()
    result = _make_result()
    result.all_files = {}
    
    orch._stage_doc_commit_pr(result)
    
    orch._commit_and_open_pr.assert_not_called()


def test_stage_doc_commit_pr_none_files_skips_commit():
    """_stage_doc_commit_pr should do nothing when all_files is None."""
    orch = _make_orchestrator()
    orch._commit_and_open_pr = MagicMock()
    result = _make_result()
    result.all_files = None
    
    orch._stage_doc_commit_pr(result)
    
    orch._commit_and_open_pr.assert_not_called()


def test_stage_doc_commit_pr_no_all_files_attr_skips():
    """_stage_doc_commit_pr should handle missing all_files attribute."""
    orch = _make_orchestrator()
    orch._commit_and_open_pr = MagicMock()
    result = _make_result()
    delattr(result, "all_files")
    
    orch._stage_doc_commit_pr(result)
    
    orch._commit_and_open_pr.assert_not_called()


# ── Integration: doc generate → commit_pr propagation ─────────────────────


def test_doc_pipeline_context_propagation():
    """Files from _stage_doc_generate should be available to _stage_doc_commit_pr."""
    orch = _make_orchestrator()
    orch._commit_and_open_pr = MagicMock()
    result = _make_result()
    
    mock_agent = MagicMock()
    mock_agent.run.return_value = [
        {"path": "docs/guide.md", "content": "# Guide\n"},
    ]
    
    with patch("agents.DocumentationAgent", return_value=mock_agent):
        # Stage 1: generate docs
        orch._stage_doc_generate(result)
        
        # Stage 2: commit and PR
        orch._stage_doc_commit_pr(result)
    
    # Verify propagation
    assert "docs/guide.md" in result.all_files
    orch._commit_and_open_pr.assert_called_once()
    call_args = orch._commit_and_open_pr.call_args
    assert call_args[0][0] == result


def test_doc_pipeline_multiple_files():
    """_stage_doc_generate should handle multiple file writes correctly."""
    orch = _make_orchestrator()
    orch._commit_and_open_pr = MagicMock()
    result = _make_result()
    
    mock_agent = MagicMock()
    mock_agent.run.return_value = [
        {"path": "docs/README.md", "content": "# README\n"},
        {"path": "docs/api.md", "content": "# API\n"},
        {"path": "docs/guide.md", "content": "# Guide\n"},
    ]
    
    with patch("agents.DocumentationAgent", return_value=mock_agent):
        orch._stage_doc_generate(result)
        orch._stage_doc_commit_pr(result)
    
    assert len(result.all_files) == 3
    assert "docs/README.md" in result.all_files
    assert "docs/api.md" in result.all_files
    assert "docs/guide.md" in result.all_files
    orch._commit_and_open_pr.assert_called_once()


# ── Error handling tests ──────────────────────────────────────────────────


def test_stage_doc_generate_handles_malformed_agent_output():
    """_stage_doc_generate crashes on malformed output (caught by orchestrator's stage wrapper)."""
    orch = _make_orchestrator()
    result = _make_result()
    
    mock_agent = MagicMock()
    # Agent returns non-dict items - will crash when trying to call .get()
    mock_agent.run.return_value = ["string", 123, None]
    
    with patch("agents.DocumentationAgent", return_value=mock_agent):
        # Should raise AttributeError - orchestrator's stage wrapper will catch this
        with pytest.raises(AttributeError):
            orch._stage_doc_generate(result)


def test_stage_doc_commit_pr_helper_adds_pr_info_to_result():
    """_stage_doc_commit_pr should update result with PR info from helper."""
    orch = _make_orchestrator()
    result = _make_result()
    result.all_files = {"docs/test.md": "# Test\n"}
    
    def mock_commit_pr(res, **kwargs):
        # Simulate successful PR creation
        res.pr_number = 123
        res.pr_url = "https://github.com/test/repo/pull/123"
        res.branch = "docs/agent/42-test-project"
    
    orch._commit_and_open_pr = mock_commit_pr
    
    orch._stage_doc_commit_pr(result)
    
    assert result.pr_number == 123
    assert result.pr_url == "https://github.com/test/repo/pull/123"
    assert result.branch == "docs/agent/42-test-project"
