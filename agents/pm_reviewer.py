"""
PMReviewerAgent: reviews a PRD and optionally revises it before architecture begins.
"""
from __future__ import annotations

from .base_agent import BaseAgent


class PMReviewerAgent(BaseAgent):
    """PM Reviewer — reviews the Product Manager's PRD.

    Input:  PRD markdown + original requirement
    Output: review report, verdict, and optionally a revised PRD
    """

    role_name = "pm_reviewer"

    VERDICT_APPROVED = "PRD APPROVED"
    VERDICT_SUGGESTIONS = "PRD APPROVED WITH SUGGESTIONS"
    VERDICT_REVISION = "PRD NEEDS REVISION"

    def run(self, prd: str, requirement: str, project_name: str = "Project") -> dict:
        """Review a PRD document.

        Args:
            prd: PRD markdown from ProductManagerAgent.
            requirement: Original raw requirement (for completeness check).
            project_name: Project name for context.

        Returns:
            dict with keys:
                - review (str): Full review markdown
                - verdict (str): One of the three VERDICT_* constants
                - needs_revision (bool): True when verdict is PRD NEEDS REVISION
                - revised_prd (str | None): Updated PRD if revision was produced
                - revised_project_name (str): Re-extracted project name (or original)
        """
        prompt = self._build_review_prompt(prd, requirement, project_name)
        response = self.call(prompt)
        verdict = self._extract_verdict(response)
        revised_prd = self._extract_revised_prd(response)
        revised_project_name = self._extract_project_name(revised_prd) if revised_prd else project_name

        return {
            "review": response,
            "verdict": verdict,
            "needs_revision": verdict == self.VERDICT_REVISION,
            "revised_prd": revised_prd,
            "revised_project_name": revised_project_name,
        }

    def _build_review_prompt(self, prd: str, requirement: str, project_name: str) -> str:
        """Build the prompt for reviewing a PRD."""
        return (
            f"Please review the following PRD for the project '{project_name}'.\n\n"
            f"**Original client requirement:**\n---\n{requirement}\n---\n\n"
            f"**PRD to review:**\n---\n{prd}\n---\n\n"
            f"Provide a thorough PRD review following your role instructions."
        )

    def run_with_github(
        self,
        prd: str,
        requirement: str,
        project_name: str,
        github_client,
        issue_number: int,
    ) -> dict:
        """Review the PRD and post the review as a GitHub Issue comment."""
        result = self.run(prd, requirement, project_name)

        verdict_emoji = {
            self.VERDICT_APPROVED: "✅",
            self.VERDICT_SUGGESTIONS: "💡",
            self.VERDICT_REVISION: "🔄",
        }.get(result["verdict"], "🔍")

        github_client.add_issue_comment(
            issue_number,
            f"## {verdict_emoji} PRD Review (PMReviewer)\n\n{result['review']}",
        )
        return result

    @staticmethod
    def _extract_verdict(review: str) -> str:
        """Parse the verdict line from the review."""
        review_upper = review.upper()
        if "PRD NEEDS REVISION" in review_upper:
            return PMReviewerAgent.VERDICT_REVISION
        if "PRD APPROVED WITH SUGGESTIONS" in review_upper:
            return PMReviewerAgent.VERDICT_SUGGESTIONS
        if "PRD APPROVED" in review_upper:
            return PMReviewerAgent.VERDICT_APPROVED
        return PMReviewerAgent.VERDICT_SUGGESTIONS  # safe default

    @staticmethod
    def _extract_revised_prd(review: str) -> str | None:
        """Extract the '## Revised PRD' section if present."""
        lines = review.splitlines()
        revised_lines: list[str] = []
        in_section = False

        for line in lines:
            if line.strip().lower().startswith("## revised prd"):
                in_section = True
                continue
            if in_section and line.startswith("## ") and "revised prd" not in line.lower():
                break
            if in_section and any(v in line.upper() for v in (
                "PRD APPROVED", "PRD NEEDS REVISION"
            )):
                break
            if in_section:
                revised_lines.append(line)

        revised = "\n".join(revised_lines).strip()
        return revised if revised else None

    @staticmethod
    def _extract_project_name(prd: str) -> str:
        """Extract project name from the PRD title line."""
        for line in prd.splitlines():
            stripped = line.strip()
            if stripped.startswith("# PRD:"):
                return stripped.removeprefix("# PRD:").strip()
            if stripped.startswith("# "):
                return stripped.removeprefix("# ").strip()
        return "Project"
