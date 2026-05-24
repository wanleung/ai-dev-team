"""
CodeReviewerAgent: reviews generated code and provides structured feedback.
"""
from __future__ import annotations

from tools import builtin_tools, ToolRegistry

from .base_agent import BaseAgent


class CodeReviewerAgent(BaseAgent):
    """Code Reviewer Agent — reviews code files for correctness, security, and quality.

    Input:  dict of {filepath: content} + PRD acceptance criteria
    Output: structured review markdown + review verdict

    Tools used:
        run_linter — runs ruff on each Python file before writing the review,
                     so lint results are included as concrete evidence.
    """

    role_name = "code_reviewer"

    VERDICT_APPROVE = "APPROVED"
    VERDICT_MINOR = "APPROVED WITH MINOR COMMENTS"
    VERDICT_CHANGES = "CHANGES REQUESTED"

    def __init__(self, *args, tool_registry: "ToolRegistry | None" = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._tool_registry = tool_registry if tool_registry is not None else builtin_tools

    def run(self, files: dict[str, str], prd: str, project_name: str = "Project") -> dict:
        """Review all generated code files.

        Args:
            files: dict of {filepath: file_content} from EngineerAgent.
            prd: PRD markdown for acceptance criteria reference.
            project_name: Project name for context.

        Returns:
            dict with keys:
                - review (str): Full review markdown
                - verdict (str): One of APPROVED / APPROVED WITH MINOR COMMENTS / CHANGES REQUESTED
                - has_critical_issues (bool): True if changes are required
        """
        files_to_review = self.truncate_files(files, max_chars=80_000, max_per_file=8_000)
        prompt = self._build_review_prompt(files_to_review, prd, project_name)
        review = self.call_with_tools(prompt, tools=self._tool_registry)
        verdict = self._extract_verdict(review)

        return {
            "review": review,
            "verdict": verdict,
            "has_critical_issues": verdict == self.VERDICT_CHANGES,
        }

    def _build_review_prompt(
        self, files_to_review: dict[str, str], prd: str, project_name: str
    ) -> str:
        """Build the prompt for code review."""
        code_section = "\n\n".join(
            f"### FILE: {path}\n```\n{content}\n```" for path, content in files_to_review.items()
        )
        return (
            f"Please review the following code for the project '{project_name}'.\n\n"
            f"**PRD (for acceptance criteria reference):**\n---\n{prd}\n---\n\n"
            f"**Code to review:**\n\n{code_section}\n\n"
            f"Use the run_linter tool on any Python files you want to check for lint errors, "
            f"then provide a thorough code review following your role instructions."
        )

    def run_with_github(
        self,
        files: dict[str, str],
        prd: str,
        project_name: str,
        github_client,
        pr_number: int,
    ) -> dict:
        """Run code review and post results as a GitHub PR review.

        Args:
            files: Generated code files.
            prd: PRD markdown.
            project_name: Project name.
            github_client: GitHubClient instance.
            pr_number: PR number to post the review on.

        Returns:
            Same as run() result.
        """
        result = self.run(files, prd, project_name)

        # GitHub doesn't allow APPROVE or REQUEST_CHANGES on your own PR.
        # Always use COMMENT so the review body is still posted regardless of who opens the PR.
        github_client.add_pr_review(
            pr_number,
            body=f"## 🔍 Code Review (CodeReviewerAgent)\n\n{result['review']}",
            event="COMMENT",
        )
        return result

    @staticmethod
    def _extract_verdict(review: str) -> str:
        """Parse the verdict line from the review summary."""
        review_upper = review.upper()
        if "CHANGES REQUESTED" in review_upper:
            return CodeReviewerAgent.VERDICT_CHANGES
        if "APPROVED WITH MINOR" in review_upper:
            return CodeReviewerAgent.VERDICT_MINOR
        if "APPROVED" in review_upper:
            return CodeReviewerAgent.VERDICT_APPROVE
        # Default: treat as comment-only
        return CodeReviewerAgent.VERDICT_MINOR
