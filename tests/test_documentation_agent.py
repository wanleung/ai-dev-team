"""Unit tests for DocumentationAgent."""
import json
from unittest.mock import MagicMock, patch
import pytest
from agents.documentation_agent import DocumentationAgent


def _make_agent():
    """Create a DocumentationAgent with mocked internals (no real API calls)."""
    agent = DocumentationAgent(model="gpt-4.1", github_token="tok")
    return agent


def _make_mock_gh():
    """Return a MagicMock standing in for a GitHubClient."""
    return MagicMock()


def test_parse_doc_targets_from_body():
    agent = _make_agent()
    body = "Fix the docs.\n\n**Docs:** README.md, docs/api.md"
    result = agent._parse_doc_targets(body)
    assert result == ["README.md", "docs/api.md"]


def test_parse_doc_targets_missing():
    agent = _make_agent()
    result = agent._parse_doc_targets("Just update everything.")
    assert result == []


def test_parse_doc_targets_plain_format():
    """Plain 'Docs: file1, file2' format (no asterisks) should be parsed."""
    agent = _make_agent()
    body = "Please update the docs.\n\nDocs: README.md, docs/api.md"
    result = agent._parse_doc_targets(body)
    assert result == ["README.md", "docs/api.md"]


def test_run_returns_file_writes():
    file_writes = [
        {"path": "README.md", "content": "# Updated\n", "action": "update"}
    ]
    mock_gh = _make_mock_gh()
    with patch("agents.documentation_agent.LocalToolRegistry"), \
         patch.object(DocumentationAgent, "call_with_tools", return_value=json.dumps(file_writes)):
        agent = DocumentationAgent(model="gpt-4.1", github_token="tok")
        result = agent.run(
            issue_title="Update README",
            issue_body="Please update the README.\n\n**Docs:** README.md",
            github_client=mock_gh,
        )
    assert isinstance(result, list)
    assert result[0]["path"] == "README.md"
    assert result[0]["action"] == "update"


def test_run_raises_on_empty_writes():
    mock_gh = _make_mock_gh()
    with patch("agents.documentation_agent.LocalToolRegistry"), \
         patch.object(DocumentationAgent, "call_with_tools", return_value="[]"):
        agent = DocumentationAgent(model="gpt-4.1", github_token="tok")
        with pytest.raises(ValueError, match="no file writes"):
            agent.run(
                issue_title="Update README",
                issue_body="Please update the README.",
                github_client=mock_gh,
            )


def test_run_parses_json_embedded_in_text():
    """Agent sometimes wraps JSON in text — verify extraction still works."""
    file_writes = [{"path": "docs/guide.md", "content": "# Guide\n", "action": "create"}]
    raw = f"Here are the updates:\n\n{json.dumps(file_writes)}\n\nDone!"
    mock_gh = _make_mock_gh()
    with patch("agents.documentation_agent.LocalToolRegistry"), \
         patch.object(DocumentationAgent, "call_with_tools", return_value=raw):
        agent = DocumentationAgent(model="gpt-4.1", github_token="tok")
        result = agent.run(
            issue_title="Add guide",
            issue_body="Add a new guide.",
            github_client=mock_gh,
        )
    assert result[0]["path"] == "docs/guide.md"


def test_run_returns_empty_on_unparseable_response():
    """When call_with_tools returns garbage, run() should return []."""
    mock_gh = _make_mock_gh()
    with patch("agents.documentation_agent.LocalToolRegistry"), \
         patch.object(DocumentationAgent, "call_with_tools", return_value="totally unparseable garbage!!!"):
        agent = DocumentationAgent(model="gpt-4.1", github_token="tok")
        result = agent.run(
            issue_title="Some issue",
            issue_body="Some body.",
            github_client=mock_gh,
        )
    assert result == []


def test_system_prompt_set():
    agent = _make_agent()
    assert "list_files" in agent.system_prompt
    assert "read_file" in agent.system_prompt
    assert "search_files" in agent.system_prompt
    assert "JSON array" in agent.system_prompt


def test_target_hint_injected_into_prompt():
    """Verify that doc targets parsed from issue body appear in the prompt passed to call_with_tools."""
    file_writes = [{"path": "README.md", "content": "# Updated\n", "action": "update"}]
    mock_gh = _make_mock_gh()
    with patch("agents.documentation_agent.LocalToolRegistry"), \
         patch.object(
             DocumentationAgent,
             "call_with_tools",
             return_value=json.dumps(file_writes),
         ) as mock_call:
        agent = DocumentationAgent(model="gpt-4.1", github_token="tok")
        agent.run(
            issue_title="T",
            issue_body="Body\n\n**Docs:** README.md",
            github_client=mock_gh,
        )

    # The first positional argument to call_with_tools is the user_message
    _, call_kwargs = mock_call.call_args
    user_message = mock_call.call_args[1].get("user_message") or mock_call.call_args[0][0]
    assert "Explicit documentation targets" in user_message
    assert "README.md" in user_message
