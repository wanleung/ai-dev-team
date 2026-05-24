"""
QAEngineerAgent: writes tests for generated code and produces a validation report.
"""
from __future__ import annotations

from typing import Optional

from .base_agent import BaseAgent


class QAEngineerAgent(BaseAgent):
    """QA Engineer Agent — writes pytest tests and validates acceptance criteria.

    Input:  dict of {filepath: content} + PRD (for acceptance criteria)
    Output: test files + test plan summary markdown
    """

    role_name = "qa_engineer"

    def __init__(self, *args, tool_registry: "ToolRegistry | None" = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._tool_registry = tool_registry

    def run(self, files: dict[str, str], prd: str, project_name: str = "Project",
            test_plan: str = "", write_only: bool = False) -> dict:
        """Generate tests for the implemented code (or write-first tests in TDD mode).

        Args:
            files: dict of {filepath: file_content} from EngineerAgent. Pass {} in TDD mode.
            prd: PRD markdown for acceptance criteria.
            project_name: Project name for context.
            test_plan: Optional structured Test Plan from QAPlannerAgent.
            write_only: If True (TDD mode), write tests that define expected behaviour without
                        running them. Prompt changes to test-first perspective.

        Returns:
            dict with keys:
                - test_files (dict): {filepath: test_content} for all test files
                - test_plan (str): Test plan summary markdown
                - raw_response (str): Full LLM response
                - tests_ran (bool): False only when write_only=True
        """
        prompt = self._build_qa_prompt(prd, project_name, test_plan, write_only, files)
        response = self._call_llm_with_tools(prompt, write_only)
        test_files = self._parse_test_files(response)
        extracted_plan = self._extract_test_plan(response)
        return {
            "test_files": test_files,
            "test_plan": extracted_plan,
            "raw_response": response,
            "tests_ran": not write_only,
        }

    def run_with_github(
        self,
        files: dict[str, str],
        prd: str,
        project_name: str,
        github_client,
        branch: str,
        pr_number: int,
        issue_number: Optional[int] = None,
        tracker_github_client=None,
        test_plan: str = "",
    ) -> dict:
        """Run QA, commit test files to the feature branch, and post a report on the PR.

        Args:
            files: Generated code files.
            prd: PRD markdown.
            project_name: Project name.
            github_client: GitHubClient for the target project (commits, PR comments).
            branch: Feature branch to commit tests to.
            pr_number: PR number to comment on (in target project).
            issue_number: Tracker issue number to close when done. Optional — if omitted,
                the orchestrator is responsible for closing the tracker issue.
            tracker_github_client: GitHubClient for the tracker repo (e.g. ai-software-house).
                If provided and different from github_client, issue_number is closed here.
                Falls back to github_client when not provided.

        Returns:
            Same as run() result.
        """
        tracker = tracker_github_client or github_client
        result = self.run(files, prd, project_name, test_plan=test_plan)
        self._commit_test_files(github_client, result["test_files"], branch, project_name)
        self._post_test_plan_comment(github_client, pr_number, result["test_plan"])
        if issue_number is not None:
            self._close_tracker_issue(tracker, issue_number, project_name, len(files), len(result["test_files"]))
        return result

    @staticmethod
    def _parse_test_files(response: str) -> dict[str, str]:
        """Parse '### FILE: tests/...' sections from the QA response.
        Also captures conftest.py and requirements-test.txt.
        """
        files, current_path, current_lines = {}, None, []
        in_code_block = False
        for line in response.splitlines():
            if line.strip().startswith("### FILE:"):
                if current_path and current_lines:
                    files[current_path] = "\n".join(current_lines).strip()
                current_path = line.strip().removeprefix("### FILE:").strip()
                current_lines, in_code_block = [], False
                continue
            if current_path is not None:
                if line.strip().startswith("```"):
                    in_code_block = not in_code_block
                    continue
                current_lines.append(line)
        if current_path and current_lines:
            files[current_path] = "\n".join(current_lines).strip()
        return QAEngineerAgent._normalize_test_paths(files)

    @staticmethod
    def _extract_test_plan(response: str) -> str:
        """Extract the '# Test Plan' section from the QA response."""
        lines = response.splitlines()
        plan_lines: list[str] = []
        in_plan = False

        for line in lines:
            if line.strip().startswith("# Test Plan"):
                in_plan = True
            if in_plan:
                plan_lines.append(line)

        return "\n".join(plan_lines).strip() if plan_lines else response.strip()

    def _build_qa_prompt(
        self, prd: str, project_name: str, test_plan: str, 
        write_only: bool, files: dict[str, str]
    ) -> str:
        """Build the QA prompt based on mode (TDD write-only or normal)."""
        plan_section = (
            f"\n\n**Test Plan from QA Planner (implement these test cases):**\n---\n{test_plan[:4000]}\n---"
            if test_plan else ""
        )
        if write_only:
            return (
                f"You are writing tests for the project '{project_name}' BEFORE the code is implemented.\n\n"
                f"**PRD (acceptance criteria that define the expected behavior):**\n---\n{prd}\n---"
                f"{plan_section}\n\n"
                f"Write pytest tests that define the expected behavior of each module. "
                f"These tests will be given to engineers as a specification — they must write code to make them pass.\n"
                f"Focus on interface contracts, inputs/outputs, and acceptance criteria. "
                f"Use '### FILE: tests/test_xxx.py' format for each test file."
            )
        files_for_qa = self.truncate_files(files, max_chars=10_000)
        code_section = "\n\n".join(
            f"### FILE: {path}\n```python\n{content}\n```" for path, content in files_for_qa.items()
        )
        return (
            f"You are writing tests for the project '{project_name}'.\n\n"
            f"**PRD (acceptance criteria to validate):**\n---\n{prd}\n---"
            f"{plan_section}\n\n"
            f"**Implemented code:**\n\n{code_section}\n\n"
            f"Write comprehensive pytest tests following your role instructions. "
            f"Use '### FILE: tests/test_xxx.py' format for each test file."
        )

    def _call_llm_with_tools(self, prompt: str, write_only: bool) -> str:
        """Call LLM with optional tool registry support."""
        if self._tool_registry is not None and not write_only:
            rag_hint = (
                "\n\nYou have access to the `search_codebase` RAG tool. "
                "Use it to find relevant existing code patterns before writing tests."
            )
            try:
                return self.call_with_tools(prompt + rag_hint, tools=self._tool_registry)
            except NotImplementedError:
                return self.call(prompt)
        return self.call(prompt)

    @staticmethod
    def _normalize_test_paths(files: dict[str, str]) -> dict[str, str]:
        """Normalise paths: test files → tests/, special files stay as-is."""
        normalized: dict[str, str] = {}
        for path, content in files.items():
            if path in ("requirements-test.txt", "conftest.py"):
                normalized[path] = content
            elif path.endswith("conftest.py") or path.endswith("requirements-test.txt"):
                normalized[path] = content
            elif not path.startswith("tests/"):
                normalized[f"tests/{path}"] = content
            else:
                normalized[path] = content
        return normalized

    @staticmethod
    def _commit_test_files(
        github_client, test_files: dict[str, str], branch: str, project_name: str
    ) -> None:
        """Commit test files to the feature branch in the target project."""
        for filepath, content in test_files.items():
            github_client.commit_file(
                path=filepath,
                content=content,
                message=f"test: add QA tests for {project_name}",
                branch=branch,
            )

    @staticmethod
    def _post_test_plan_comment(github_client, pr_number: int, test_plan: str) -> None:
        """Post test plan as PR comment in the target project."""
        github_client.add_pr_comment(
            pr_number,
            f"## 🧪 QA Test Plan (QAEngineerAgent)\n\n{test_plan}",
        )

    @staticmethod
    def _close_tracker_issue(
        tracker_client, issue_number: int, project_name: str, 
        file_count: int, test_file_count: int
    ) -> None:
        """Close the tracker issue with a completion summary."""
        tracker_client.close_issue(
            issue_number,
            comment=(
                f"## ✅ Implementation Complete\n\n"
                f"All pipeline stages finished for **{project_name}**:\n"
                f"- 📋 PRD created\n"
                f"- 🏗️ System design complete\n"
                f"- 💻 Code implemented ({file_count} files)\n"
                f"- 🔍 Code review complete\n"
                f"- 🧪 Tests written ({test_file_count} test files)\n\n"
                f"See PR for full implementation."
            ),
        )
