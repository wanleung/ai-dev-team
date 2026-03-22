"""
QAPlannerAgent: produces a structured test plan (acceptance criteria, test strategy,
module scenarios) that guides the QA Engineer's implementation.
"""
from __future__ import annotations

from tools import builtin_tools

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
            prd:          PRD markdown (from PM / PM Reviewer).
            design:       System design markdown (from Architect / Arch Reviewer).
            files:        Dict of {filename: content} from Engineers.
            project_name: Project name for context.
            repo:         Optional 'owner/repo' — enables search_github_issues tool.

        Returns:
            dict with keys:
                - test_plan (str): Full Test Plan markdown
                - acceptance_criteria (list[str]): extracted AC IDs for quick reference
                - success (bool): True when agent produced a complete plan
        """
        truncated = self.truncate_files(files, max_chars=8_000)
        files_summary = "\n".join(
            f"### {fname}\n```\n{content[:500]}{'…' if len(content) > 500 else ''}\n```"
            for fname, content in list(truncated.items())[:10]
        )

        repo_hint = (
            f"\nYou can use the search_github_issues tool to search repo '{repo}' "
            f"for related existing issues or acceptance criteria.\n"
            if repo else ""
        )

        prompt = (
            f"Project: **{project_name}**\n{repo_hint}\n"
            f"## PRD\n{prd}\n\n"
            f"## System Design\n{design}\n\n"
            f"## Implemented Code (summary)\n{files_summary}\n\n"
            "Please produce the full Test Plan following your role instructions."
        )

        response = self.call_with_tools(prompt, tools=builtin_tools)
        acceptance_criteria = self._extract_ac_ids(response)

        return {
            "test_plan": response,
            "acceptance_criteria": acceptance_criteria,
            "success": "TEST PLAN COMPLETE" in response.upper(),
        }

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
