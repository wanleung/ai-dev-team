"""
QAEngineerAgent: writes tests for generated code and produces a validation report.
"""
from __future__ import annotations

from .base_agent import BaseAgent


class QAEngineerAgent(BaseAgent):
    """QA Engineer Agent — writes pytest tests and validates acceptance criteria.

    Input:  dict of {filepath: content} + PRD (for acceptance criteria)
    Output: test files + test plan summary markdown
    """

    role_name = "qa_engineer"

    def run(self, files: dict[str, str], prd: str, project_name: str = "Project") -> dict:
        """Generate tests for the implemented code.

        Args:
            files: dict of {filepath: file_content} from EngineerAgent.
            prd: PRD markdown for acceptance criteria.
            project_name: Project name for context.

        Returns:
            dict with keys:
                - test_files (dict): {filepath: test_content} for all test files
                - test_plan (str): Test plan summary markdown
                - raw_response (str): Full LLM response
        """
        code_section = "\n\n".join(
            f"### FILE: {path}\n```python\n{content}\n```" for path, content in files.items()
        )

        prompt = (
            f"You are writing tests for the project '{project_name}'.\n\n"
            f"**PRD (acceptance criteria to validate):**\n---\n{prd}\n---\n\n"
            f"**Implemented code:**\n\n{code_section}\n\n"
            f"Write comprehensive pytest tests following your role instructions. "
            f"Use '### FILE: tests/test_xxx.py' format for each test file."
        )

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
        issue_number: int,
    ) -> dict:
        """Run QA, commit test files to the feature branch, and post a report on the PR.

        Args:
            files: Generated code files.
            prd: PRD markdown.
            project_name: Project name.
            github_client: GitHubClient instance.
            branch: Feature branch to commit tests to.
            pr_number: PR number to comment on.
            issue_number: PRD issue number to close with final report.

        Returns:
            Same as run() result.
        """
        result = self.run(files, prd, project_name)

        # Commit test files to the feature branch
        for filepath, content in result["test_files"].items():
            github_client.commit_file(
                path=filepath,
                content=content,
                message=f"test: add QA tests for {project_name}",
                branch=branch,
            )

        # Post test plan as PR comment
        github_client.add_pr_comment(
            pr_number,
            f"## 🧪 QA Test Plan (QAEngineerAgent)\n\n{result['test_plan']}",
        )

        # Close the PRD issue with a completion summary
        github_client.close_issue(
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
        """Parse '### FILE: tests/...' sections from the QA response."""
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
                # Only capture lines within the tests/ path convention
                current_lines.append(line)

        if current_path and current_lines:
            files[current_path] = "\n".join(current_lines).strip()

        # Ensure test files are under tests/ directory
        normalized: dict[str, str] = {}
        for path, content in files.items():
            if not path.startswith("tests/"):
                path = f"tests/{path}"
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
