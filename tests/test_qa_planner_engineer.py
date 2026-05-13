"""Tests for QAPlannerAgent and EngineerAgent."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agents.qa_planner import QAPlannerAgent
from agents.engineer import EngineerAgent


def _make_qa_planner(tool_registry=None) -> QAPlannerAgent:
    agent = QAPlannerAgent.__new__(QAPlannerAgent)
    agent._llm = MagicMock()
    agent.system_prompt = ""
    agent._history = []
    agent.model = "gpt-4"
    agent._tool_registry = tool_registry
    return agent


def _make_engineer(tool_registry=None) -> EngineerAgent:
    agent = EngineerAgent.__new__(EngineerAgent)
    agent._llm = MagicMock()
    agent.system_prompt = ""
    agent._history = []
    agent.model = "gpt-4"
    agent._tool_registry = tool_registry
    return agent


# ── QAPlannerAgent.run_with_github ────────────────────────────────────────────

class TestQAPlannerRunWithGithub:
    def _make_run_result(self) -> dict:
        return {
            "test_plan": "## Test Plan\n\n- AC-01: Login works",
            "acceptance_criteria": ["AC-01"],
            "success": True,
        }

    def test_posts_to_pr_when_pr_number_given(self, monkeypatch):
        """run_with_github() posts the test plan comment to the PR when pr_number given."""
        agent = _make_qa_planner()
        monkeypatch.setattr(agent, "run", MagicMock(return_value=self._make_run_result()))

        github_client = MagicMock()
        github_client.repo = "owner/repo"

        agent.run_with_github(
            prd="PRD text",
            design="Design text",
            files={"main.py": "x=1"},
            project_name="MyApp",
            github_client=github_client,
            issue_number=5,
            pr_number=12,
        )

        github_client.add_pr_comment.assert_called_once()
        github_client.add_issue_comment.assert_not_called()
        comment = github_client.add_pr_comment.call_args[0][1]
        assert "Test Plan" in comment

    def test_posts_to_issue_when_no_pr_number(self, monkeypatch):
        """run_with_github() posts to issue comment when pr_number is None."""
        agent = _make_qa_planner()
        monkeypatch.setattr(agent, "run", MagicMock(return_value=self._make_run_result()))

        github_client = MagicMock()
        github_client.repo = "owner/repo"

        agent.run_with_github(
            prd="PRD text",
            design="Design text",
            files={},
            project_name="MyApp",
            github_client=github_client,
            issue_number=5,
            pr_number=None,
        )

        github_client.add_issue_comment.assert_called_once()
        args = github_client.add_issue_comment.call_args[0]
        assert args[0] == 5  # correct issue_number passed
        github_client.add_pr_comment.assert_not_called()


# ── EngineerAgent.run_module with test_files (TDD mode) ───────────────────────

class TestEngineerRunModuleWithTestFiles:
    def test_run_module_injects_test_files_into_prompt(self, monkeypatch):
        """run_module with test_files includes test content in the LLM prompt."""
        agent = _make_engineer()
        mock_call = MagicMock(return_value="### FILE: src/auth.py\n```python\ndef login(): pass\n```")
        monkeypatch.setattr(agent, "call", mock_call)

        agent.run_module(
            design="## Auth module design",
            module={"name": "auth", "description": "handles login"},
            project_name="MyApp",
            test_files={"tests/test_auth.py": "def test_login(): assert login() is None"},
        )

        prompt = mock_call.call_args[0][0]
        assert "tests/test_auth.py" in prompt
        assert "test_login" in prompt

    def test_run_module_truncates_large_test_file(self, monkeypatch):
        """run_module truncates test file content exceeding 3000 chars."""
        agent = _make_engineer()
        mock_call = MagicMock(return_value="### FILE: main.py\n```python\nx=1\n```")
        monkeypatch.setattr(agent, "call", mock_call)

        big_test = "# test\n" + "x = 1\n" * 600  # >3000 chars
        agent.run_module(
            design="design",
            module={"name": "mod", "description": "desc"},
            project_name="Proj",
            test_files={"tests/big_test.py": big_test},
        )

        prompt = mock_call.call_args[0][0]
        assert "truncated" in prompt


# ── EngineerAgent.run_all_modules ─────────────────────────────────────────────

class TestEngineerRunAllModules:
    def test_run_all_modules_calls_run_module_for_each(self, monkeypatch):
        """run_all_modules calls run_module for each module in the list."""
        monkeypatch.setattr("agents.engineer.time.sleep", lambda _: None)
        agent = _make_engineer()
        mock_run_module = MagicMock(return_value={
            "module_name": "mod",
            "files": {"src/mod.py": "x=1"},
            "raw_response": "raw",
        })
        monkeypatch.setattr(agent, "run_module", mock_run_module)

        modules = [
            {"name": "auth", "description": "auth"},
            {"name": "api", "description": "api"},
        ]
        result = agent.run_all_modules(design="design", modules=modules, project_name="MyApp", max_workers=2)

        assert mock_run_module.call_count == 2
        assert "src/mod.py" in result["all_files"]
        assert len(result["modules"]) == 2

    def test_run_all_modules_merges_files(self, monkeypatch):
        """run_all_modules merges all module files into all_files dict."""
        monkeypatch.setattr("agents.engineer.time.sleep", lambda _: None)
        agent = _make_engineer()
        calls = [
            {"module_name": "auth", "files": {"src/auth.py": "auth code"}, "raw_response": ""},
            {"module_name": "api", "files": {"src/api.py": "api code"}, "raw_response": ""},
        ]
        monkeypatch.setattr(agent, "run_module", MagicMock(side_effect=calls))

        result = agent.run_all_modules(
            design="d",
            modules=[{"name": "auth", "description": ""}, {"name": "api", "description": ""}],
            project_name="P",
            max_workers=1,
        )

        assert "src/auth.py" in result["all_files"]
        assert "src/api.py" in result["all_files"]


# ── EngineerAgent.run_with_github ─────────────────────────────────────────────

class TestEngineerRunWithGithub:
    def test_creates_branch_and_commits_files(self, monkeypatch):
        """run_with_github creates the branch, commits each file, and opens a PR."""
        agent = _make_engineer()
        monkeypatch.setattr(agent, "run_all_modules", MagicMock(return_value={
            "modules": [],
            "all_files": {"src/main.py": "print('hello')", "src/utils.py": "pass"},
        }))

        github_client = MagicMock()
        github_client.create_pull_request.return_value = {
            "number": 99,
            "html_url": "https://github.com/owner/repo/pull/99",
        }

        result = agent.run_with_github(
            design="design",
            modules=[{"name": "main", "description": ""}],
            project_name="MyApp",
            github_client=github_client,
        )

        github_client.create_branch.assert_called_once()
        assert github_client.commit_file.call_count == 2
        github_client.create_pull_request.assert_called_once()
        assert result["pr_number"] == 99

    def test_pr_body_references_issue_when_given(self, monkeypatch):
        """run_with_github includes 'Closes #N' in PR body when issue_number given."""
        agent = _make_engineer()
        monkeypatch.setattr(agent, "run_all_modules", MagicMock(return_value={
            "modules": [],
            "all_files": {"src/x.py": "x=1"},
        }))

        github_client = MagicMock()
        github_client.create_pull_request.return_value = {"number": 5, "html_url": "http://x"}

        agent.run_with_github(
            design="d",
            modules=[],
            project_name="X",
            github_client=github_client,
            issue_number=42,
        )

        # Check the body kwarg in the create_pull_request call
        call_args, call_kwargs = github_client.create_pull_request.call_args
        body = call_kwargs.get("body", "")
        assert "Closes #42" in body


# ── EngineerAgent.fix_failures ────────────────────────────────────────────────

class TestEngineerFixFailures:
    def test_returns_empty_dict_when_no_file_markers(self, monkeypatch):
        """fix_failures returns {} when LLM response has no '### FILE:' markers."""
        agent = _make_engineer()
        monkeypatch.setattr(agent, "call", MagicMock(return_value="Here is my explanation only."))

        result = agent.fix_failures(
            failure_output="FAILED test_foo",
            all_files={"src/foo.py": "broken"},
            design="design",
        )

        assert result == {}

    def test_returns_parsed_files_when_markers_present(self, monkeypatch):
        """fix_failures returns parsed files when LLM response has FILE markers."""
        agent = _make_engineer()
        response = "### FILE: src/foo.py\n```python\ndef fixed(): pass\n```"
        monkeypatch.setattr(agent, "call", MagicMock(return_value=response))

        result = agent.fix_failures(
            failure_output="FAILED test_foo",
            all_files={"src/foo.py": "broken"},
            design="design",
        )

        assert "src/foo.py" in result
        assert "fixed" in result["src/foo.py"]


# ── EngineerAgent._parse_files ────────────────────────────────────────────────

class TestEngineerParseFiles:
    def test_fallback_wraps_plain_text_as_main_py(self):
        """_parse_files wraps plain response as main.py when no FILE markers."""
        result = EngineerAgent._parse_files("def hello(): pass")
        assert "main.py" in result
        assert "def hello(): pass" in result["main.py"]

    def test_strips_code_fences(self):
        """_parse_files removes opening/closing ``` fences from file content."""
        response = "### FILE: src/app.py\n```python\nx = 1\n```"
        result = EngineerAgent._parse_files(response)
        assert "src/app.py" in result
        assert "```" not in result["src/app.py"]
        assert "x = 1" in result["src/app.py"]

    def test_parses_multiple_files(self):
        """_parse_files handles multiple FILE sections correctly."""
        response = (
            "### FILE: src/a.py\n```python\na = 1\n```\n"
            "### FILE: src/b.py\n```python\nb = 2\n```"
        )
        result = EngineerAgent._parse_files(response)
        assert "src/a.py" in result
        assert "src/b.py" in result
