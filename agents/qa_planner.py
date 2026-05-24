"""
QAPlannerAgent: produces a structured test plan (acceptance criteria, test strategy,
module scenarios) that guides the QA Engineer's implementation.
"""
from __future__ import annotations

from tools import builtin_tools, ToolRegistry

from .base_agent import BaseAgent


class QAPlannerAgent(BaseAgent):
    """QA Planner — Henry.

    Input:  PRD + system design + generated code files
    Output: Structured Test Plan markdown (acceptance criteria, test strategy, module scenarios)

    Tools used:
        search_github_issues — searches for existing issues/tickets to avoid duplicate
                               test coverage and find related acceptance criteria.
    """

    role_name = "qa_planner"

    def __init__(self, *args, tool_registry: "ToolRegistry | None" = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._tool_registry = tool_registry if tool_registry is not None else builtin_tools

    def run(
        self,
        prd: str,
        design: str,
        files: dict[str, str],
        project_name: str = "Project",
        repo: str = "",
    ) -> dict:
        """Produce a test plan from PRD + design + code.

        Args:
            prd: PRD markdown
            design: System design markdown
            files: Implementation files dict
            project_name: Human-readable project name
            repo: GitHub repo identifier for issue search

        Returns:
            dict with 'test_plan' (str), 'acceptance_criteria' (list), 'success' (bool)
        """
        files_summary = self._build_files_summary(files)
        prompt = self._build_planner_prompt(project_name, repo, prd, design, files_summary)
        response = self.call_with_tools(prompt, tools=self._tool_registry)
        acceptance_criteria = self._extract_ac_ids(response)

        return {
            "test_plan": response,
            "acceptance_criteria": acceptance_criteria,
            "success": "TEST PLAN COMPLETE" in response.upper(),
        }

    def _build_files_summary(self, files: dict[str, str]) -> str:
        """Build a truncated summary of implementation files."""
        truncated = self.truncate_files(files, max_chars=8_000)
        return "\n".join(
            f"### {fname}\n```\n{content[:500]}{'…' if len(content) > 500 else ''}\n```"
            for fname, content in list(truncated.items())[:10]
        )

    def _build_planner_prompt(
        self, project_name: str, repo: str, prd: str, design: str, files_summary: str
    ) -> str:
        """Build the test planning prompt."""
        repo_hint = (
            f"\nYou can use the search_github_issues tool to search repo '{repo}' "
            f"for related existing issues or acceptance criteria.\n"
            if repo else ""
        )
        return (
            f"Project: **{project_name}**\n{repo_hint}\n"
            f"## PRD\n{prd}\n\n"
            f"## System Design\n{design}\n\n"
            f"## Implemented Code (summary)\n{files_summary}\n\n"
            "Please produce the full Test Plan following your role instructions."
        )

    def run_with_github(
        self,
        prd: str,
        design: str,
        files: dict[str, str],
        project_name: str,
        github_client,
        issue_number: int,
        pr_number: int | None = None,
    ) -> dict:
        """Produce the test plan and post it as a GitHub comment."""
        repo = github_client.repo if hasattr(github_client, "repo") else ""
        result = self.run(prd, design, files, project_name, repo=repo)

        status = "✅" if result["success"] else "⚠️"
        ac_count = len(result["acceptance_criteria"])
        summary = f"{status} **{ac_count} acceptance criteria identified**" if ac_count else status

        comment_body = f"## 📋 Test Plan ({summary})\n\n{result['test_plan']}"

        # Post to PR if available, otherwise to issue
        if pr_number:
            github_client.add_pr_comment(pr_number, comment_body)
        else:
            github_client.add_issue_comment(issue_number, comment_body)

        return result

    @staticmethod
    def _extract_ac_ids(test_plan: str) -> list[str]:
        """Extract acceptance criteria IDs (AC-01, AC-02, …) from the plan."""
        import re
        return re.findall(r"\bAC-\d+\b", test_plan)
