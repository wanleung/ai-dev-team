"""Tests for ProductManagerAgent and SummaryAgent."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agents.product_manager import ProductManagerAgent
from agents.summariser import SummaryAgent


def _make_pm() -> ProductManagerAgent:
    """Create ProductManagerAgent without calling BaseAgent.__init__."""
    agent = ProductManagerAgent.__new__(ProductManagerAgent)
    agent._llm = MagicMock()
    agent.system_prompt = ""
    agent._history = []
    agent.model = "gpt-4"
    agent.memory_store = None
    return agent


def _make_summariser() -> SummaryAgent:
    """Create SummaryAgent without calling BaseAgent.__init__."""
    agent = SummaryAgent.__new__(SummaryAgent)
    agent._llm = MagicMock()
    agent.system_prompt = ""
    agent._history = []
    agent.model = "gpt-4"
    agent.memory_store = None
    return agent


# ── ProductManagerAgent.run ───────────────────────────────────────────────────

class TestProductManagerRun:
    def test_run_returns_prd_and_project_name(self, monkeypatch):
        """run() returns dict with prd text and extracted project name."""
        agent = _make_pm()
        monkeypatch.setattr(agent, "call", MagicMock(return_value="# PRD: Task Manager\n\nFeatures..."))

        result = agent.run("Build a task manager API")

        assert result["prd"] == "# PRD: Task Manager\n\nFeatures..."
        assert result["project_name"] == "Task Manager"
        assert result["issue_number"] is None
        assert result["issue_url"] is None

    def test_run_calls_llm_with_requirement_in_prompt(self, monkeypatch):
        """run() passes the requirement text into the LLM prompt."""
        agent = _make_pm()
        mock_call = MagicMock(return_value="# PRD: Foo\n")
        monkeypatch.setattr(agent, "call", mock_call)

        agent.run("Build a login system")

        prompt = mock_call.call_args[0][0]
        assert "Build a login system" in prompt


# ── ProductManagerAgent.run_with_github ───────────────────────────────────────

class TestProductManagerRunWithGithub:
    def test_run_with_github_creates_issue_and_returns_number(self, monkeypatch):
        """run_with_github() creates a GitHub issue and populates issue_number/url."""
        agent = _make_pm()
        monkeypatch.setattr(agent, "call", MagicMock(return_value="# PRD: My App\n\nDetails"))

        github_client = MagicMock()
        github_client.create_issue.return_value = {
            "number": 17,
            "html_url": "https://github.com/owner/repo/issues/17",
        }

        result = agent.run_with_github("Build My App", github_client)

        assert result["issue_number"] == 17
        assert result["issue_url"] == "https://github.com/owner/repo/issues/17"
        github_client.create_issue.assert_called_once()
        _, kwargs = github_client.create_issue.call_args
        assert "My App" in kwargs.get("title", "") or "My App" in str(github_client.create_issue.call_args)

    def test_run_with_github_passes_labels(self, monkeypatch):
        """run_with_github() creates the issue with 'prd' and 'requirements' labels."""
        agent = _make_pm()
        monkeypatch.setattr(agent, "call", MagicMock(return_value="# PRD: X\n"))

        github_client = MagicMock()
        github_client.create_issue.return_value = {"number": 1, "html_url": "http://example.com/1"}

        agent.run_with_github("Build X", github_client)

        call_kwargs = github_client.create_issue.call_args[1]
        assert "prd" in call_kwargs.get("labels", [])


# ── ProductManagerAgent.run_revision ─────────────────────────────────────────

class TestProductManagerRunRevision:
    def test_run_revision_returns_updated_prd(self, monkeypatch):
        """run_revision() returns an updated PRD incorporating reviewer feedback."""
        agent = _make_pm()
        revised_prd = "# PRD: Task Manager v2\n\nImproved scope."
        monkeypatch.setattr(agent, "call", MagicMock(return_value=revised_prd))

        result = agent.run_revision(
            original_prd="# PRD: Task Manager\n\nOld scope.",
            review="Scope too narrow.",
            draft_revision="Consider adding...",
            requirement="Build a task manager",
            project_name="Task Manager",
        )

        assert result["prd"] == revised_prd
        assert "Task Manager" in result["project_name"]
        assert result["issue_number"] is None

    def test_run_revision_includes_original_and_feedback_in_prompt(self, monkeypatch):
        """run_revision() passes original PRD, review, and draft to LLM."""
        agent = _make_pm()
        mock_call = MagicMock(return_value="# PRD: X\n")
        monkeypatch.setattr(agent, "call", mock_call)

        agent.run_revision(
            original_prd="ORIGINAL_PRD",
            review="REVIEWER_FEEDBACK",
            draft_revision="DRAFT_REVISION",
            requirement="REQUIREMENT",
            project_name="X",
        )

        prompt = mock_call.call_args[0][0]
        assert "ORIGINAL_PRD" in prompt
        assert "REVIEWER_FEEDBACK" in prompt
        assert "DRAFT_REVISION" in prompt


# ── _extract_project_name ─────────────────────────────────────────────────────

class TestExtractProjectName:
    def test_extracts_from_prd_prefix(self):
        """_extract_project_name reads '# PRD: Name' format."""
        name = ProductManagerAgent._extract_project_name("# PRD: Task Manager\n\nContent")
        assert name == "Task Manager"

    def test_extracts_from_plain_h1(self):
        """_extract_project_name falls back to first '# Heading'."""
        name = ProductManagerAgent._extract_project_name("# My Project\n\nContent")
        assert name == "My Project"

    def test_returns_default_when_no_heading(self):
        """_extract_project_name returns fallback when no H1 exists."""
        name = ProductManagerAgent._extract_project_name("Just plain text, no heading.")
        assert name == "Software Project"


# ── SummaryAgent.summarise ────────────────────────────────────────────────────

class TestSummaryAgentSummarise:
    def test_summarise_calls_llm_and_returns_string(self, monkeypatch):
        """summarise() passes all inputs to LLM and returns the result."""
        agent = _make_summariser()
        mock_call = MagicMock(return_value="Compact memory entry.")
        monkeypatch.setattr(agent, "call", mock_call)

        result = agent.summarise(
            repo="owner/repo",
            requirement="Build auth",
            prd="# PRD: Auth\n\nDetails.",
            design="## Architecture\n\nUse JWT.",
            review="Looks good.",
            mode="feature",
        )

        assert result == "Compact memory entry."
        mock_call.assert_called_once()

    def test_summarise_includes_repo_in_prompt(self, monkeypatch):
        """summarise() includes the repo name in the LLM prompt."""
        agent = _make_summariser()
        mock_call = MagicMock(return_value="summary")
        monkeypatch.setattr(agent, "call", mock_call)

        agent.summarise(
            repo="myorg/myrepo",
            requirement="req",
            prd="prd",
            design="design",
            review="review",
        )

        prompt = mock_call.call_args[0][0]
        assert "myorg/myrepo" in prompt

    def test_summarise_default_mode_is_feature(self, monkeypatch):
        """summarise() uses 'feature' as default mode when not specified."""
        agent = _make_summariser()
        mock_call = MagicMock(return_value="summary")
        monkeypatch.setattr(agent, "call", mock_call)

        agent.summarise(repo="r", requirement="r", prd="p", design="d", review="rv")

        prompt = mock_call.call_args[0][0]
        assert "feature" in prompt
