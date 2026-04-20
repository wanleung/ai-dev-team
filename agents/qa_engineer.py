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

    def run(self, files: dict[str, str], prd: str, project_name: str = "Project", test_plan: str = "") -> dict:
        """Generate tests for the implemented code.

        Args:
            files: dict of {filepath: file_content} from EngineerAgent.
            prd: PRD markdown for acceptance criteria.
            project_name: Project name for context.
            test_plan: Optional structured Test Plan from QAPlannerAgent. When provided,
                Edward uses it to prioritise which tests to write.

        Returns:
            dict with keys:
                - test_files (dict): {filepath: test_content} for all test files
                - test_plan (str): Test plan summary markdown
                - raw_response (str): Full LLM response
        """
        # Truncate to fit within model token limits
        files_for_qa = self.truncate_files(files, max_chars=10_000)

        code_section = "\n\n".join(
            f"### FILE: {path}\n```python\n{content}\n```" for path, content in files_for_qa.items()
        )

        plan_section = (
            f"\n\n**Test Plan from QA Planner (implement these test cases):**\n---\n{test_plan[:4000]}\n---"
            if test_plan
            else ""
        )

        prompt = (
            f"You are writing tests for the project '{project_name}'.\n\n"
            f"**PRD (acceptance criteria to validate):**\n---\n{prd}\n---"
            f"{plan_section}\n\n"
            f"**Implemented code:**\n\n{code_section}\n\n"
            f"Write comprehensive pytest tests following your role instructions. "
            f"Use '### FILE: tests/test_xxx.py' format for each test file."
        )

        if self._tool_registry is not None:
            rag_hint = (
                "\n\nYou have access to the `search_codebase` RAG tool. "
                "Use it to find relevant existing code patterns before writing tests."
            )
            try:
                response = self.call_with_tools(prompt + rag_hint, tools=self._tool_registry)
            except NotImplementedError:
                response = self.call(prompt)
        else:
            response = self.call(prompt)
        test_files = self._parse_test_files(response)
        test_plan = self._extract_test_plan(response)

        return {
            "test_files": test_files,
            "test_plan": test_plan,
            "raw_response": response,
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

        # Commit test files to the feature branch in the target project
        for filepath, content in result["test_files"].items():
            github_client.commit_file(
                path=filepath,
                content=content,
                message=f"test: add QA tests for {project_name}",
                branch=branch,
            )

        # Post test plan as PR comment in the target project
        github_client.add_pr_comment(
            pr_number,
            f"## 🧪 QA Test Plan (QAEngineerAgent)\n\n{result['test_plan']}",
        )

        # Close the tracker issue with a completion summary (if an issue number is provided)
        if issue_number is not None:
            tracker.close_issue(
                issue_number,
                comment=(
                    f"## ✅ Implementation Complete\n\n"
                    f"All pipeline stages finished for **{project_name}**:\n"
                    f"- 📋 PRD created\n"
                    f"- 🏗️ System design complete\n"
                    f"- 💻 Code implemented ({len(files)} files)\n"
                    f"- 🔍 Code review complete\n"
                    f"- 🧪 Tests written ({len(result['test_files'])} test files)\n\n"
                    f"See PR for full implementation."
                ),
            )
        return result

    @staticmethod
    def _parse_test_files(response: str) -> dict[str, str]:
        """Parse '### FILE: tests/...' sections from the QA response.
        Also captures conftest.py and requirements-test.txt.
        """
        files: dict[str, str] = {}
        current_path: str | None = None
        current_lines: list[str] = []
        in_code_block = False

        for line in response.splitlines():
            if line.strip().startswith("### FILE:"):
                if current_path and current_lines:
                    files[current_path] = "\n".join(current_lines).strip()
                current_path = line.strip().removeprefix("### FILE:").strip()
                current_lines = []
                in_code_block = False
                continue

            if current_path is not None:
                if line.strip().startswith("```"):
                    in_code_block = not in_code_block
                    continue
                current_lines.append(line)

        if current_path and current_lines:
            files[current_path] = "\n".join(current_lines).strip()

        # Normalise paths: test files → tests/, special files stay as-is
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
