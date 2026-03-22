"""
CodeReviewerAgent: reviews generated code and provides structured feedback.
"""
from __future__ import annotations

from .base_agent import BaseAgent


class CodeReviewerAgent(BaseAgent):
    """Code Reviewer Agent — reviews code files for correctness, security, and quality.

    Input:  dict of {filepath: content} + PRD acceptance criteria
    Output: structured review markdown + review verdict
    """

    role_name = "code_reviewer"

    VERDICT_APPROVE = "APPROVED"
    VERDICT_MINOR = "APPROVED WITH MINOR COMMENTS"
    VERDICT_CHANGES = "CHANGES REQUESTED"

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
        # Truncate to fit within model token limits
        files_to_review = self.truncate_files(files, max_chars=10_000)

        code_section = "\n\n".join(
            f"### FILE: {path}\n```\n{content}\n```" for path, content in files_to_review.items()
        )

        prompt = (
            f"Please review the following code for the project '{project_name}'.\n\n"
            f"**PRD (for acceptance criteria reference):**\n---\n{prd}\n---\n\n"
            f"**Code to review:**\n\n{code_section}\n\n"
            f"Provide a thorough code review following your role instructions."
        )

        review = self.call(prompt)
        verdict = self._extract_verdict(review)

        return {
            "review": review,
            "verdict": verdict,
            "has_critical_issues": verdict == self.VERDICT_CHANGES,
        }

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
