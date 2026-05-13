"""Tests for ArchitectReviewerAgent, PMReviewerAgent, CodeReviewerAgent."""
from unittest.mock import MagicMock
import pytest


class TestArchitectReviewer:
    """Tests for ArchitectReviewerAgent."""

    def _make_agent(self):
        from agents.architect_reviewer import ArchitectReviewerAgent
        agent = ArchitectReviewerAgent.__new__(ArchitectReviewerAgent)
        agent._backend = MagicMock()
        agent.model = "gpt-4"
        agent.config = {}
        return agent

    def test_extract_verdict_approved(self):
        """Test verdict extraction for DESIGN APPROVED."""
        from agents.architect_reviewer import ArchitectReviewerAgent
        review = "The design looks good. **Verdict: DESIGN APPROVED**"
        verdict = ArchitectReviewerAgent._extract_verdict(review)
        assert verdict == ArchitectReviewerAgent.VERDICT_APPROVED

    def test_extract_verdict_suggestions(self):
        """Test verdict extraction for DESIGN APPROVED WITH SUGGESTIONS."""
        from agents.architect_reviewer import ArchitectReviewerAgent
        review = "Some minor improvements needed. **Verdict: DESIGN APPROVED WITH SUGGESTIONS**"
        verdict = ArchitectReviewerAgent._extract_verdict(review)
        assert verdict == ArchitectReviewerAgent.VERDICT_SUGGESTIONS

    def test_extract_verdict_revision(self):
        """Test verdict extraction for DESIGN NEEDS REVISION."""
        from agents.architect_reviewer import ArchitectReviewerAgent
        review = "Major issues found. **Verdict: DESIGN NEEDS REVISION**"
        verdict = ArchitectReviewerAgent._extract_verdict(review)
        assert verdict == ArchitectReviewerAgent.VERDICT_REVISION

    def test_extract_verdict_unknown_defaults_to_suggestions(self):
        """Test that unknown verdict defaults to SUGGESTIONS."""
        from agents.architect_reviewer import ArchitectReviewerAgent
        review = "Some review text without a clear verdict."
        verdict = ArchitectReviewerAgent._extract_verdict(review)
        assert verdict == ArchitectReviewerAgent.VERDICT_SUGGESTIONS

    def test_run_returns_needs_revision_false_on_approval(self, monkeypatch):
        """Test that run() returns needs_revision=False for DESIGN APPROVED."""
        from agents.architect_reviewer import ArchitectReviewerAgent
        agent = self._make_agent()
        
        mock_response = "**Verdict: DESIGN APPROVED**\nGreat design!"
        monkeypatch.setattr(ArchitectReviewerAgent, "call", lambda self, prompt: mock_response)
        
        result = agent.run(design="# Design", prd="# PRD", project_name="Test")
        
        assert result["verdict"] == ArchitectReviewerAgent.VERDICT_APPROVED
        assert result["needs_revision"] is False
        assert result["review"] == mock_response

    def test_run_returns_needs_revision_true_on_revision(self, monkeypatch):
        """Test that run() returns needs_revision=True for DESIGN NEEDS REVISION."""
        from agents.architect_reviewer import ArchitectReviewerAgent
        agent = self._make_agent()
        
        mock_response = "**Verdict: DESIGN NEEDS REVISION**\nMajor issues found."
        monkeypatch.setattr(ArchitectReviewerAgent, "call", lambda self, prompt: mock_response)
        
        result = agent.run(design="# Design", prd="# PRD", project_name="Test")
        
        assert result["verdict"] == ArchitectReviewerAgent.VERDICT_REVISION
        assert result["needs_revision"] is True

    def test_run_includes_context_in_call(self, monkeypatch):
        """Test that run() includes PRD and design in the prompt."""
        from agents.architect_reviewer import ArchitectReviewerAgent
        agent = self._make_agent()
        
        captured_prompts = []
        
        def mock_call(self, prompt):
            captured_prompts.append(prompt)
            return "**Verdict: DESIGN APPROVED**"
        
        monkeypatch.setattr(ArchitectReviewerAgent, "call", mock_call)
        
        agent.run(design="# My Design", prd="# My PRD", project_name="TestProject")
        
        assert len(captured_prompts) == 1
        prompt = captured_prompts[0]
        assert "TestProject" in prompt
        assert "# My Design" in prompt
        assert "# My PRD" in prompt

    def test_extract_revised_design(self):
        """Test extraction of revised design section."""
        from agents.architect_reviewer import ArchitectReviewerAgent
        review = """
Some review text.

## Revised Design

# Updated System Design
This is the revised design content.

## Another Section
This should not be included.
"""
        revised = ArchitectReviewerAgent._extract_revised_design(review)
        assert revised is not None
        assert "Updated System Design" in revised
        assert "Another Section" not in revised

    def test_extract_revised_design_returns_none_when_missing(self):
        """Test that _extract_revised_design returns None when no revised section exists."""
        from agents.architect_reviewer import ArchitectReviewerAgent
        review = "Just some review text without a revised design."
        revised = ArchitectReviewerAgent._extract_revised_design(review)
        assert revised is None

    def test_parse_revised_modules(self):
        """Test parsing of revised module list."""
        from agents.architect_reviewer import ArchitectReviewerAgent
        review = """
## Revised Module List

1. **auth**: User authentication module
2. **api**: REST API endpoints
3. **database**: Database layer
"""
        modules = ArchitectReviewerAgent._parse_revised_modules(review)
        assert len(modules) == 3
        assert modules[0]["name"] == "auth"
        assert "authentication" in modules[0]["description"]
        assert modules[1]["name"] == "api"
        assert modules[2]["name"] == "database"


class TestPMReviewer:
    """Tests for PMReviewerAgent."""

    def _make_agent(self):
        from agents.pm_reviewer import PMReviewerAgent
        agent = PMReviewerAgent.__new__(PMReviewerAgent)
        agent._backend = MagicMock()
        agent.model = "gpt-4"
        agent.config = {}
        return agent

    def test_extract_verdict_approved(self):
        """Test verdict extraction for PRD APPROVED."""
        from agents.pm_reviewer import PMReviewerAgent
        review = "The PRD is complete. **Verdict: PRD APPROVED**"
        verdict = PMReviewerAgent._extract_verdict(review)
        assert verdict == PMReviewerAgent.VERDICT_APPROVED

    def test_extract_verdict_suggestions(self):
        """Test verdict extraction for PRD APPROVED WITH SUGGESTIONS."""
        from agents.pm_reviewer import PMReviewerAgent
        review = "Some minor improvements. **Verdict: PRD APPROVED WITH SUGGESTIONS**"
        verdict = PMReviewerAgent._extract_verdict(review)
        assert verdict == PMReviewerAgent.VERDICT_SUGGESTIONS

    def test_extract_verdict_revision(self):
        """Test verdict extraction for PRD NEEDS REVISION."""
        from agents.pm_reviewer import PMReviewerAgent
        review = "Critical gaps found. **Verdict: PRD NEEDS REVISION**"
        verdict = PMReviewerAgent._extract_verdict(review)
        assert verdict == PMReviewerAgent.VERDICT_REVISION

    def test_extract_verdict_unknown_defaults_to_suggestions(self):
        """Test that unknown verdict defaults to SUGGESTIONS."""
        from agents.pm_reviewer import PMReviewerAgent
        review = "Some review text without a clear verdict."
        verdict = PMReviewerAgent._extract_verdict(review)
        assert verdict == PMReviewerAgent.VERDICT_SUGGESTIONS

    def test_run_needs_revision_false_on_approved(self, monkeypatch):
        """Test that run() returns needs_revision=False for PRD APPROVED."""
        from agents.pm_reviewer import PMReviewerAgent
        agent = self._make_agent()
        
        mock_response = "**Verdict: PRD APPROVED**\nExcellent PRD!"
        monkeypatch.setattr(PMReviewerAgent, "call", lambda self, prompt: mock_response)
        
        result = agent.run(prd="# PRD", requirement="Build an app", project_name="Test")
        
        assert result["verdict"] == PMReviewerAgent.VERDICT_APPROVED
        assert result["needs_revision"] is False
        assert result["review"] == mock_response

    def test_run_needs_revision_true_on_revision(self, monkeypatch):
        """Test that run() returns needs_revision=True for PRD NEEDS REVISION."""
        from agents.pm_reviewer import PMReviewerAgent
        agent = self._make_agent()
        
        mock_response = "**Verdict: PRD NEEDS REVISION**\nCritical issues."
        monkeypatch.setattr(PMReviewerAgent, "call", lambda self, prompt: mock_response)
        
        result = agent.run(prd="# PRD", requirement="Build an app", project_name="Test")
        
        assert result["verdict"] == PMReviewerAgent.VERDICT_REVISION
        assert result["needs_revision"] is True

    def test_run_includes_context_in_call(self, monkeypatch):
        """Test that run() includes requirement and PRD in the prompt."""
        from agents.pm_reviewer import PMReviewerAgent
        agent = self._make_agent()
        
        captured_prompts = []
        
        def mock_call(self, prompt):
            captured_prompts.append(prompt)
            return "**Verdict: PRD APPROVED**"
        
        monkeypatch.setattr(PMReviewerAgent, "call", mock_call)
        
        agent.run(prd="# My PRD", requirement="Build a web app", project_name="MyProject")
        
        assert len(captured_prompts) == 1
        prompt = captured_prompts[0]
        assert "MyProject" in prompt
        assert "# My PRD" in prompt
        assert "Build a web app" in prompt

    def test_extract_revised_prd(self):
        """Test extraction of revised PRD section."""
        from agents.pm_reviewer import PMReviewerAgent
        review = """
Some review text.

## Revised PRD

# PRD: Updated Project
This is the revised PRD content.

## Another Section
This should not be included.
"""
        revised = PMReviewerAgent._extract_revised_prd(review)
        assert revised is not None
        assert "Updated Project" in revised
        assert "Another Section" not in revised

    def test_extract_revised_prd_returns_none_when_missing(self):
        """Test that _extract_revised_prd returns None when no revised section exists."""
        from agents.pm_reviewer import PMReviewerAgent
        review = "Just some review text without a revised PRD."
        revised = PMReviewerAgent._extract_revised_prd(review)
        assert revised is None

    def test_extract_project_name(self):
        """Test project name extraction from PRD."""
        from agents.pm_reviewer import PMReviewerAgent
        prd = "# PRD: My Awesome Project\n\nContent here..."
        name = PMReviewerAgent._extract_project_name(prd)
        assert name == "My Awesome Project"

    def test_extract_project_name_without_prd_prefix(self):
        """Test project name extraction from title without 'PRD:' prefix."""
        from agents.pm_reviewer import PMReviewerAgent
        prd = "# Simple Project\n\nContent here..."
        name = PMReviewerAgent._extract_project_name(prd)
        assert name == "Simple Project"

    def test_extract_project_name_defaults_to_project(self):
        """Test that project name defaults to 'Project' when no title found."""
        from agents.pm_reviewer import PMReviewerAgent
        prd = "No title here, just content."
        name = PMReviewerAgent._extract_project_name(prd)
        assert name == "Project"


class TestCodeReviewer:
    """Tests for CodeReviewerAgent."""

    def _make_agent(self):
        from agents.code_reviewer import CodeReviewerAgent
        agent = CodeReviewerAgent.__new__(CodeReviewerAgent)
        agent._backend = MagicMock()
        agent.model = "gpt-4"
        agent.config = {}
        agent._tool_registry = MagicMock()
        return agent

    def test_extract_verdict_approved(self):
        """Test verdict extraction for APPROVED."""
        from agents.code_reviewer import CodeReviewerAgent
        review = "Code looks good. **Verdict: APPROVED**"
        verdict = CodeReviewerAgent._extract_verdict(review)
        assert verdict == CodeReviewerAgent.VERDICT_APPROVE

    def test_extract_verdict_minor(self):
        """Test verdict extraction for APPROVED WITH MINOR COMMENTS."""
        from agents.code_reviewer import CodeReviewerAgent
        review = "Minor improvements needed. **Verdict: APPROVED WITH MINOR COMMENTS**"
        verdict = CodeReviewerAgent._extract_verdict(review)
        assert verdict == CodeReviewerAgent.VERDICT_MINOR

    def test_extract_verdict_changes_requested(self):
        """Test verdict extraction for CHANGES REQUESTED."""
        from agents.code_reviewer import CodeReviewerAgent
        review = "Critical issues found. **Verdict: CHANGES REQUESTED**"
        verdict = CodeReviewerAgent._extract_verdict(review)
        assert verdict == CodeReviewerAgent.VERDICT_CHANGES

    def test_extract_verdict_unknown_defaults_to_minor(self):
        """Test that unknown verdict defaults to MINOR."""
        from agents.code_reviewer import CodeReviewerAgent
        review = "Some review text without a clear verdict."
        verdict = CodeReviewerAgent._extract_verdict(review)
        assert verdict == CodeReviewerAgent.VERDICT_MINOR

    def test_run_approved(self, monkeypatch):
        """Test that run() returns has_critical_issues=False for APPROVED."""
        from agents.code_reviewer import CodeReviewerAgent
        agent = self._make_agent()
        
        mock_response = "**Verdict: APPROVED**\nCode looks great!"
        monkeypatch.setattr(CodeReviewerAgent, "call_with_tools", lambda self, prompt, tools: mock_response)
        
        result = agent.run(files={"main.py": "print('hi')"}, prd="# PRD", project_name="Test")
        
        assert result["verdict"] == CodeReviewerAgent.VERDICT_APPROVE
        assert result["has_critical_issues"] is False
        assert result["review"] == mock_response

    def test_run_changes_requested(self, monkeypatch):
        """Test that run() returns has_critical_issues=True for CHANGES REQUESTED."""
        from agents.code_reviewer import CodeReviewerAgent
        agent = self._make_agent()
        
        mock_response = "**Verdict: CHANGES REQUESTED**\nCritical security flaw."
        monkeypatch.setattr(CodeReviewerAgent, "call_with_tools", lambda self, prompt, tools: mock_response)
        
        result = agent.run(files={"main.py": "print('hi')"}, prd="# PRD", project_name="Test")
        
        assert result["verdict"] == CodeReviewerAgent.VERDICT_CHANGES
        assert result["has_critical_issues"] is True

    def test_run_includes_files_in_prompt(self, monkeypatch):
        """Test that run() includes file contents in the prompt."""
        from agents.code_reviewer import CodeReviewerAgent
        agent = self._make_agent()
        
        captured_prompts = []
        
        def mock_call_with_tools(self, prompt, tools):
            captured_prompts.append(prompt)
            return "**Verdict: APPROVED**"
        
        monkeypatch.setattr(CodeReviewerAgent, "call_with_tools", mock_call_with_tools)
        
        files = {
            "app.py": "def main(): pass",
            "utils.py": "def helper(): return 42"
        }
        agent.run(files=files, prd="# My PRD", project_name="MyApp")
        
        assert len(captured_prompts) == 1
        prompt = captured_prompts[0]
        assert "MyApp" in prompt
        assert "# My PRD" in prompt
        assert "app.py" in prompt
        assert "utils.py" in prompt
        assert "def main" in prompt
        assert "def helper" in prompt

    def test_run_truncates_large_files(self, monkeypatch):
        """Test that run() handles large files without error."""
        from agents.code_reviewer import CodeReviewerAgent
        agent = self._make_agent()
        
        # Mock call_with_tools to verify the method runs end-to-end
        def mock_call_with_tools(self, prompt, tools):
            # Verify the prompt was built (files were processed)
            assert "app.py" in prompt
            return "**Verdict: APPROVED**"
        
        monkeypatch.setattr(CodeReviewerAgent, "call_with_tools", mock_call_with_tools)
        
        # Create a file larger than per-file limit to test truncation path
        large_file = "x" * 100_000
        result = agent.run(files={"app.py": large_file}, prd="# PRD", project_name="Test")
        
        assert result["verdict"] == CodeReviewerAgent.VERDICT_APPROVE
        assert result["has_critical_issues"] is False
