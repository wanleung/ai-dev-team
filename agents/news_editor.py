"""
NewsEditorAgent: edits a news article draft to publication standard.

Input:  article_draft (str), issue_body (str), optional discussion_synthesis (str)
Output: dict with 'article' (final markdown string)
"""
from __future__ import annotations

from .base_agent import BaseAgent


class NewsEditorAgent(BaseAgent):
    """Edit and finalise a news article draft."""

    role_name = "news_editor"

    def run(
        self,
        article_draft: str,
        issue_body: str = "",
        discussion_synthesis: str = "",
        reviewer_notes: str = "",
    ) -> dict:
        """Edit and finalise the article.

        Args:
            article_draft: Draft article markdown
            issue_body: Original issue brief
            discussion_synthesis: Pre-write analysis synthesis
            reviewer_notes: Reviewer feedback requiring fixes

        Returns:
            dict with 'article' (final markdown str)
        """
        prompt = self._build_edit_prompt(
            article_draft, issue_body, discussion_synthesis, reviewer_notes
        )
        article = self.call(prompt)
        return {"article": self._validate_frontmatter(article, article_draft)}

    def _build_edit_prompt(
        self,
        article_draft: str,
        issue_body: str,
        discussion_synthesis: str,
        reviewer_notes: str,
    ) -> str:
        """Build the editing prompt from all input sections."""
        reviewer_section = (
            f"A reviewer found the following issues that must be fixed:\n\n"
            f"---\n{reviewer_notes}\n---\n\n"
            if reviewer_notes.strip()
            else ""
        )
        synthesis_section = (
            f"A draft review discussion has been conducted. Key feedback:\n\n"
            f"---\n{discussion_synthesis}\n---\n\n"
            if discussion_synthesis.strip()
            else ""
        )
        original_brief = f"Original brief:\n---\n{issue_body}\n---\n\n" if issue_body.strip() else ""
        return (
            f"{reviewer_section}"
            f"{synthesis_section}"
            f"{original_brief}"
            f"Please edit and finalise the following news article draft:\n\n"
            f"---\n{article_draft}\n---\n\n"
            f"Follow your role instructions. Output the final article only."
        )

    def _validate_frontmatter(self, article: str, fallback: str) -> str:
        """Validate article has YAML frontmatter, fallback to original if missing."""
        if "---" not in article:
            import logging
            logging.getLogger("news_editor").warning(
                "news_editor output missing frontmatter — using original draft as fallback"
            )
            return fallback
        return article
