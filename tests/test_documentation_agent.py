"""Unit tests for DocumentationAgent."""
import json
from unittest.mock import MagicMock, patch
import pytest
from agents.documentation_agent import DocumentationAgent


def _make_agent():
    """Create a DocumentationAgent with mocked internals (no real API calls)."""
    with patch("agents.documentation_agent.GitHubClient"):
        agent = DocumentationAgent(model="gpt-4.1", github_token="tok")
    return agent


def test_parse_doc_targets_from_body():
    agent = _make_agent()
    body = "Fix the docs.\n\n**Docs:** README.md, docs/api.md"
    result = agent._parse_doc_targets(body)
    assert result == ["README.md", "docs/api.md"]


def test_parse_doc_targets_missing():
    agent = _make_agent()
    result = agent._parse_doc_targets("Just update everything.")
    assert result == []


def test_run_returns_file_writes():
    file_writes = [
        {"path": "README.md", "content": "# Updated\n", "action": "update"}
    ]
    with patch("agents.documentation_agent.GitHubClient"), \
         patch("agents.documentation_agent.LocalToolRegistry"), \
         patch.object(DocumentationAgent, "call_with_tools", return_value=json.dumps(file_writes)):
        agent = DocumentationAgent(model="gpt-4.1", github_token="tok")
        result = agent.run(
            issue_title="Update README",
            issue_body="Please update the README.\n\n**Docs:** README.md",
            target_repo="owner/repo",
            github_token="tok",
        )
    assert isinstance(result, list)
    assert result[0]["path"] == "README.md"
    assert result[0]["action"] == "update"


def test_run_raises_on_empty_writes():
    with patch("agents.documentation_agent.GitHubClient"), \
         patch("agents.documentation_agent.LocalToolRegistry"), \
         patch.object(DocumentationAgent, "call_with_tools", return_value="[]"):
        agent = DocumentationAgent(model="gpt-4.1", github_token="tok")
        with pytest.raises(ValueError, match="no file writes"):
            agent.run(
                issue_title="Update README",
                issue_body="Please update the README.",
                target_repo="owner/repo",
                github_token="tok",
            )


def test_run_parses_json_embedded_in_text():
    """Agent sometimes wraps JSON in text — verify extraction still works."""
    file_writes = [{"path": "docs/guide.md", "content": "# Guide\n", "action": "create"}]
    raw = f"Here are the updates:\n\n{json.dumps(file_writes)}\n\nDone!"
    with patch("agents.documentation_agent.GitHubClient"), \
         patch("agents.documentation_agent.LocalToolRegistry"), \
         patch.object(DocumentationAgent, "call_with_tools", return_value=raw):
        agent = DocumentationAgent(model="gpt-4.1", github_token="tok")
        result = agent.run(
            issue_title="Add guide",
            issue_body="Add a new guide.",
            target_repo="owner/repo",
            github_token="tok",
        )
    assert result[0]["path"] == "docs/guide.md"


def test_system_prompt_set():
    agent = _make_agent()
    assert "list_files" in agent.system_prompt
    assert "read_file" in agent.system_prompt
    assert "search_files" in agent.system_prompt
    assert "JSON array" in agent.system_prompt
