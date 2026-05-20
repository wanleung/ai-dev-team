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
            article_draft: The draft article from NewsWriterAgent (or discuss_news_draft synthesis).
            issue_body: The original brief for reference.
            discussion_synthesis: Optional synthesis from discuss_news_draft stage.
            reviewer_notes: Optional reviewer feedback to address in this edit.

        Returns:
            dict with key:
                - article (str): Final publication-ready markdown article
        """
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
        prompt = (
            f"{reviewer_section}"
            f"{synthesis_section}"
            f"{original_brief}"
            f"Please edit and finalise the following news article draft:\n\n"
            f"---\n{article_draft}\n---\n\n"
            f"Follow your role instructions. Output the final article only."
        )
        article = self.call(prompt)

        # Guard: if the model returned commentary instead of the article
        # (no YAML frontmatter fence), fall back to the original draft.
        if "---" not in article:
            import logging
            logging.getLogger("news_editor").warning(
                "news_editor output missing frontmatter — using original draft as fallback"
            )
            article = article_draft

        return {"article": article}
