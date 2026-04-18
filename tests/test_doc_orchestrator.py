"""Unit tests for DocOrchestrator."""
from __future__ import annotations

import unittest.mock
from unittest.mock import MagicMock, call, patch

import pytest

from doc_orchestrator import DocOrchestrator, DocResult


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_orchestrator(**kwargs) -> DocOrchestrator:
    """Return a DocOrchestrator wired to a mock GitHubClient."""
    orch = DocOrchestrator(
        model="gpt-4.1",
        github_repo="owner/tracker",
        github_token="fake-token",
        **kwargs,
    )
    orch.github = MagicMock()
    orch.github.repo = "owner/tracker"
    return orch


def _mock_issue(title: str = "Update README", body: str = "Please update the docs.") -> dict:
    return {"title": title, "body": body}


def _file_writes() -> list[dict]:
    return [
        {"path": "README.md", "content": "# Updated\n", "action": "update"},
        {"path": "docs/guide.md", "content": "# Guide\n", "action": "create"},
    ]


# ── Branch naming ─────────────────────────────────────────────────────────────

def test_branch_name_slug():
    """Verify slug format: lowercase, hyphenated, max 60 chars, correct prefix."""
    orch = DocOrchestrator(branch_prefix="doc")
    name = orch._make_branch_name(42, "Update README Installation Guide")
    assert name.startswith("doc/42-")
    assert " " not in name
    assert name == name.lower()
    assert len(name) <= 60


def test_branch_name_special_chars():
    """Titles with special characters produce a clean slug."""
    orch = DocOrchestrator(branch_prefix="doc")
    name = orch._make_branch_name(7, "Fix docs: add (new) API & examples!")
    assert " " not in name
    assert "(" not in name
    assert "&" not in name
    assert "!" not in name
    assert ":" not in name
    assert len(name) <= 60
    assert name.startswith("doc/7-")


def test_branch_name_very_long_title():
    """Very long issue titles are truncated so total length stays ≤ 60."""
    orch = DocOrchestrator(branch_prefix="doc")
    long_title = "A" * 200
    name = orch._make_branch_name(1, long_title)
    assert len(name) <= 60


def test_branch_name_custom_prefix():
    """Custom branch_prefix is respected."""
    orch = DocOrchestrator(branch_prefix="docs/update")
    name = orch._make_branch_name(10, "My feature")
    assert name.startswith("docs/update/10-")


# ── run() happy path ──────────────────────────────────────────────────────────

def test_run_creates_pr():
    """Full happy-path: agent returns writes, PR is created, issue is closed."""
    orch = _make_orchestrator()
    orch.github.get_issue.return_value = _mock_issue()
    orch.github.create_branch.return_value = "doc/1-update-readme"
    orch.github.create_pull_request.return_value = {
        "number": 99,
        "html_url": "https://github.com/owner/tracker/pull/99",
    }

    with patch("doc_orchestrator.DocumentationAgent") as MockAgent:
        MockAgent.return_value.run.return_value = _file_writes()
        result = orch.run(issue_number=1)

    assert result.pr_number == 99
    assert result.pr_url == "https://github.com/owner/tracker/pull/99"
    assert len(result.committed_files) == 2
    assert "README.md" in result.committed_files
    assert "docs/guide.md" in result.committed_files
    orch.github.close_issue.assert_called_once()
    assert result.errors == []


def test_run_uses_target_repo():
    """When issue body has 'Target repo: other/repo', target gh client uses that repo."""
    orch = _make_orchestrator()
    body = "Please update docs.\n\nTarget repo: other/project"
    orch.github.get_issue.return_value = _mock_issue(body=body)
    orch.github.create_branch.return_value = "doc/5-update-readme"

    with patch("doc_orchestrator.GitHubClient") as MockGH, \
         patch("doc_orchestrator.DocumentationAgent") as MockAgent:
        target_gh_instance = MagicMock()
        target_gh_instance.repo = "other/project"
        target_gh_instance.create_pull_request.return_value = {"number": 10, "html_url": "http://pr"}
        MockGH.return_value = target_gh_instance
        MockAgent.return_value.run.return_value = _file_writes()

        result = orch.run(issue_number=5)

    # GitHubClient should be constructed for the target repo
    MockGH.assert_called_once_with(repo="other/project", github_token="fake-token")
    # Agent is called with the target GitHubClient
    MockAgent.return_value.run.assert_called_once()
    call_kwargs = MockAgent.return_value.run.call_args
    assert call_kwargs[1]["github_client"] is target_gh_instance or \
           call_kwargs[0][2] is target_gh_instance

    # Tracker issue must be closed via tracker client, not target repo client
    orch.github.close_issue.assert_called_once_with(5, comment=unittest.mock.ANY)
    target_gh_instance.close_issue.assert_not_called()


def test_run_no_file_writes():
    """When agent returns [], no files committed, no PR, error recorded."""
    orch = _make_orchestrator()
    orch.github.get_issue.return_value = _mock_issue()
    orch.github.create_branch.return_value = "doc/2-update-readme"

    with patch("doc_orchestrator.DocumentationAgent") as MockAgent:
        MockAgent.return_value.run.return_value = []
        result = orch.run(issue_number=2)

    assert result.committed_files == []
    assert result.pr_number is None
    assert len(result.errors) >= 1


def test_run_handles_stage_error():
    """When commit_file raises, error is captured in result.errors."""
    orch = _make_orchestrator()
    orch.github.get_issue.return_value = _mock_issue()
    orch.github.create_branch.return_value = "doc/3-update-readme"
    orch.github.commit_file.side_effect = RuntimeError("Network error")

    with patch("doc_orchestrator.DocumentationAgent") as MockAgent:
        MockAgent.return_value.run.return_value = _file_writes()
        result = orch.run(issue_number=3)

    assert any("Network error" in e or "Failed to commit" in e for e in result.errors)


# ── run() error cases ─────────────────────────────────────────────────────────

def test_run_raises_without_github():
    """DocOrchestrator.run() raises EnvironmentError when no GitHub client is set."""
    orch = DocOrchestrator(model="gpt-4.1")  # no github_repo
    with pytest.raises(EnvironmentError, match="GitHub integration is required"):
        orch.run(issue_number=1)


def test_run_branch_creation_failure_aborts():
    """If branch creation fails, run() returns early with an error and no PR."""
    orch = _make_orchestrator()
    orch.github.get_issue.return_value = _mock_issue()
    orch.github.create_branch.side_effect = RuntimeError("Branch conflict")

    with patch("doc_orchestrator.DocumentationAgent") as MockAgent:
        result = orch.run(issue_number=4)

    assert result.pr_number is None
    assert any("Branch creation failed" in e for e in result.errors)
    MockAgent.return_value.run.assert_not_called()


def test_run_ack_comment_posted():
    """Acknowledgement comment is posted at the start of run()."""
    orch = _make_orchestrator()
    orch.github.get_issue.return_value = _mock_issue()
    orch.github.create_branch.return_value = "doc/6-update-readme"
    orch.github.create_pull_request.return_value = {"number": 1, "html_url": "http://pr/1"}

    with patch("doc_orchestrator.DocumentationAgent") as MockAgent:
        MockAgent.return_value.run.return_value = _file_writes()
        orch.run(issue_number=6)

    orch.github.add_issue_comment.assert_called_once()
    comment_body = orch.github.add_issue_comment.call_args[0][1]
    assert "Documentation pipeline started" in comment_body


def test_run_returns_docresult():
    """run() must return a DocResult instance."""
    orch = _make_orchestrator()
    orch.github.get_issue.return_value = _mock_issue()
    orch.github.create_branch.return_value = "doc/7-update-readme"
    orch.github.create_pull_request.return_value = {"number": 2, "html_url": "http://pr/2"}

    with patch("doc_orchestrator.DocumentationAgent") as MockAgent:
        MockAgent.return_value.run.return_value = _file_writes()
        result = orch.run(issue_number=7)

    assert isinstance(result, DocResult)
    assert result.issue_number == 7
    assert result.duration_seconds > 0


def test_run_pr_title_includes_issue_title():
    """The PR title must follow 'docs: {issue_title}' format."""
    orch = _make_orchestrator()
    orch.github.get_issue.return_value = _mock_issue(title="Add API reference")
    orch.github.create_branch.return_value = "doc/8-add-api-reference"
    orch.github.create_pull_request.return_value = {"number": 3, "html_url": "http://pr/3"}

    with patch("doc_orchestrator.DocumentationAgent") as MockAgent:
        MockAgent.return_value.run.return_value = _file_writes()
        orch.run(issue_number=8)

    create_pr_call = orch.github.create_pull_request.call_args
    pr_title = create_pr_call[1].get("title") or create_pr_call[0][0]
    assert pr_title == "docs: Add API reference"


def test_run_agent_exception_captured():
    """If DocumentationAgent.run() raises, error is captured and pipeline continues gracefully."""
    orch = _make_orchestrator()
    orch.github.get_issue.return_value = _mock_issue()
    orch.github.create_branch.return_value = "doc/9-update-readme"

    with patch("doc_orchestrator.DocumentationAgent") as MockAgent:
        MockAgent.return_value.run.side_effect = ValueError("Agent exploded")
        result = orch.run(issue_number=9)

    assert result.pr_number is None
    assert any("Agent exploded" in e or "Documentation Agent" in e for e in result.errors)


# ── from_config ───────────────────────────────────────────────────────────────

def test_from_config_loads_model():
    """from_config reads model from config.yaml."""
    config_content = {
        "llm": {"model": "gpt-4o"},
        "github": {"repo": "owner/repo"},
        "pipeline": {},
    }
    with patch("builtins.open", new_callable=MagicMock), \
         patch("doc_orchestrator.yaml.safe_load", return_value=config_content):
        orch = DocOrchestrator.from_config("config.yaml", github_token="tok")

    assert orch.model == "gpt-4o"
