"""
ArchitectReviewerAgent: reviews a system design and optionally revises it before engineering starts.
"""
from __future__ import annotations

from .base_agent import BaseAgent


class ArchitectReviewerAgent(BaseAgent):
    """Architect Reviewer — reviews the Architect's system design.

    Input:  system design markdown + PRD (for coverage check)
    Output: review report, verdict, and optionally a revised design + modules
    """

    role_name = "architect_reviewer"

    VERDICT_APPROVED = "DESIGN APPROVED"
    VERDICT_SUGGESTIONS = "DESIGN APPROVED WITH SUGGESTIONS"
    VERDICT_REVISION = "DESIGN NEEDS REVISION"

    def run(self, design: str, prd: str, project_name: str = "Project") -> dict:
        """Review a system design document.

        Args:
            design: System design markdown from ArchitectAgent.
            prd: PRD markdown for coverage validation.
            project_name: Project name for context.

        Returns:
            dict with keys:
                - review (str): Full review markdown
                - verdict (str): One of the three VERDICT_* constants
                - needs_revision (bool): True when verdict is DESIGN NEEDS REVISION
                - revised_design (str | None): Updated design if revision was produced
                - revised_modules (list[dict]): Re-parsed modules from revised design (or [])
        """
        prompt = self._build_review_prompt(design, prd, project_name)
        response = self.call(prompt)
        verdict = self._extract_verdict(response)
        revised_design = self._extract_revised_design(response)
        revised_modules = self._parse_revised_modules(response) if revised_design else []

        return {
            "review": response,
            "verdict": verdict,
            "needs_revision": verdict == self.VERDICT_REVISION,
            "revised_design": revised_design,
            "revised_modules": revised_modules,
        }

    def _build_review_prompt(self, design: str, prd: str, project_name: str) -> str:
        """Build the prompt for reviewing a system design."""
        return (
            f"Please review the following system design for the project '{project_name}'.\n\n"
            f"**PRD (acceptance criteria to validate coverage against):**\n---\n{prd}\n---\n\n"
            f"**System Design to review:**\n---\n{design}\n---\n\n"
            f"Provide a thorough design review following your role instructions."
        )

    def run_with_github(
        self,
        design: str,
        prd: str,
        project_name: str,
        github_client,
        issue_number: int,
    ) -> dict:
        """Review the design and post the review as a GitHub Issue comment."""
        result = self.run(design, prd, project_name)

        verdict_emoji = {
            self.VERDICT_APPROVED: "✅",
            self.VERDICT_SUGGESTIONS: "💡",
            self.VERDICT_REVISION: "🔄",
        }.get(result["verdict"], "🔍")

        github_client.add_issue_comment(
            issue_number,
            f"## {verdict_emoji} Design Review (ArchitectReviewer)\n\n{result['review']}",
        )
        return result

    @staticmethod
    def _extract_verdict(review: str) -> str:
        """Parse the verdict line from the review."""
        review_upper = review.upper()
        if "DESIGN NEEDS REVISION" in review_upper:
            return ArchitectReviewerAgent.VERDICT_REVISION
        if "DESIGN APPROVED WITH SUGGESTIONS" in review_upper:
            return ArchitectReviewerAgent.VERDICT_SUGGESTIONS
        if "DESIGN APPROVED" in review_upper:
            return ArchitectReviewerAgent.VERDICT_APPROVED
        return ArchitectReviewerAgent.VERDICT_SUGGESTIONS  # safe default

    @staticmethod
    def _extract_revised_design(review: str) -> str | None:
        """Extract the '## Revised Design' section if present."""
        lines = review.splitlines()
        revised_lines: list[str] = []
        in_section = False

        for line in lines:
            if line.strip().lower().startswith("## revised design"):
                in_section = True
                continue
            # Stop at next top-level heading (but not sub-headings within the design)
            if in_section and line.startswith("## ") and "revised design" not in line.lower():
                break
            # Stop at verdict line
            if in_section and any(v in line.upper() for v in (
                "DESIGN APPROVED", "DESIGN NEEDS REVISION"
            )):
                break
            if in_section:
                revised_lines.append(line)

        revised = "\n".join(revised_lines).strip()
        return revised if revised else None

    @staticmethod
    def _parse_revised_modules(review: str) -> list[dict]:
        """Extract revised module list from '## Revised Module List' section."""
        modules = []
        in_section = False

        for line in review.splitlines():
            stripped = line.strip()
            if "revised module list" in stripped.lower():
                in_section = True
                continue
            if in_section and stripped.startswith("## "):
                break
            if in_section and stripped and stripped[0].isdigit():
                content = stripped.split(". ", 1)[-1] if ". " in stripped else stripped
                if "**" in content and "**:" in content:
                    parts = content.split("**:", 1)
                    name = parts[0].strip("* ").strip()
                    desc = parts[1].strip() if len(parts) > 1 else ""
                elif ":" in content:
                    name, _, desc = content.partition(":")
                    name = name.strip("* ").strip()
                    desc = desc.strip()
                else:
                    name = content.strip("* ").strip()
                    desc = ""
                if name:
                    modules.append({"name": name, "description": desc})

        return modules
