"""
ProductManagerAgent: translates a raw requirement into a PRD and creates a GitHub Issue.
"""
from __future__ import annotations

from typing import Optional

from .base_agent import BaseAgent


class ProductManagerAgent(BaseAgent):
    """PM Agent — produces a Product Requirements Document (PRD).

    Input:  raw requirement string from user
    Output: PRD markdown string + GitHub Issue number (if GitHub client provided)
    """

    role_name = "product_manager"

    def run(self, requirement: str) -> dict:
        """Analyze a requirement and produce a PRD.

        Args:
            requirement: The raw user requirement (e.g. "Build a task manager API").

        Returns:
            dict with keys:
                - prd (str): Full PRD markdown text
                - project_name (str): Inferred project name
                - issue_number (int | None): GitHub issue number if created
                - issue_url (str | None): GitHub issue URL if created
        """
        prompt = (
            f"A client has submitted the following software requirement:\n\n"
            f"---\n{requirement}\n---\n\n"
            f"Please analyze this requirement and produce a detailed PRD following your role instructions."
        )

        prd = self.call(prompt)
        project_name = self._extract_project_name(prd)

        return {
            "prd": prd,
            "project_name": project_name,
            "issue_number": None,
            "issue_url": None,
        }

    def run_with_github(self, requirement: str, github_client) -> dict:
        """Run and also create a GitHub Issue with the PRD.

        Args:
            requirement: The raw user requirement.
            github_client: A GitHubClient instance.

        Returns:
            Same as run() but with issue_number and issue_url populated.
        """
        result = self.run(requirement)

        issue = github_client.create_issue(
            title=f"[PRD] {result['project_name']}",
            body=f"## Original Requirement\n\n> {requirement}\n\n---\n\n{result['prd']}",
            labels=["prd", "requirements"],
        )
        result["issue_number"] = issue["number"]
        result["issue_url"] = issue["html_url"]
        return result

    def run_revision(
        self,
        original_prd: str,
        review: str,
        draft_revision: str,
        requirement: str,
        project_name: str,
    ) -> dict:
        """Rewrite the PRD incorporating reviewer feedback and the reviewer's draft suggestion.

        Args:
            original_prd: The PRD that was reviewed.
            review: Reviewer's feedback text.
            draft_revision: Reviewer's suggested rewrite (use as direction, not copy-paste).
            requirement: Original client requirement (for context).
            project_name: Current project name.

        Returns:
            dict with keys:
                - prd (str): Improved PRD markdown
                - project_name (str): Re-extracted project name
                - issue_number (None): Unchanged — GitHub issue was already created
                - issue_url (None): Unchanged
        """
        prompt = (
            f"You previously wrote a PRD for the project '{project_name}' that was reviewed "
            f"and needs improvement.\n\n"
            f"## Original Client Requirement\n---\n{requirement}\n---\n\n"
            f"## Your Original PRD\n---\n{original_prd}\n---\n\n"
            f"## Reviewer Feedback\n---\n{review}\n---\n\n"
            f"## Reviewer's Suggested Draft (use as direction, not copy-paste)\n"
            f"---\n{draft_revision}\n---\n\n"
            f"Rewrite the PRD addressing the reviewer's concerns. Preserve all requirements "
            f"that were already correct. Output a complete, improved PRD following your role instructions."
        )

        prd = self.call(prompt)
        new_project_name = self._extract_project_name(prd) or project_name

        return {
            "prd": prd,
            "project_name": new_project_name,
            "issue_number": None,
            "issue_url": None,
        }

    @staticmethod
    def _extract_project_name(prd: str) -> str:
        """Extract the project name from a PRD heading."""
        for line in prd.splitlines():
            line = line.strip()
            if line.startswith("# PRD:"):
                return line.removeprefix("# PRD:").strip()
            if line.startswith("# "):
                return line.lstrip("# ").strip()
        return "Software Project"
