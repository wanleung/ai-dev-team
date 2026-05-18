"""
NewsWriterAgent: researches and writes a first-draft news article.

Input:  issue_body (str) — the news brief from the GitHub issue
Output: dict with 'article_draft' (markdown string with YAML frontmatter)
"""
from __future__ import annotations

from .base_agent import BaseAgent


class NewsWriterAgent(BaseAgent):
    """Write a first-draft news article from an issue brief and optional discussion synthesis."""

    role_name = "news_writer"

    def run(self, issue_body: str, discussion_synthesis: str = "") -> dict:
        """Write a news article draft.

        Args:
            issue_body: The GitHub issue body containing the news brief and source URL.
            discussion_synthesis: Optional synthesis from discuss_news_analysis stage.

        Returns:
            dict with key:
                - article_draft (str): Full markdown article with YAML frontmatter
        """
        synthesis_section = (
            f"A pre-write analysis of this story has been conducted.\n"
            f"Use the key insights below to guide your article — do not copy them verbatim.\n\n"
            f"---\n{discussion_synthesis}\n---\n\n"
            if discussion_synthesis.strip()
            else ""
        )
        prompt = (
            f"{synthesis_section}"
            f"Write a news article based on the following brief:\n\n"
            f"---\n{issue_body}\n---\n\n"
            f"Follow your role instructions. Output the full article in markdown with YAML frontmatter."
        )
        article_draft = self.call(prompt)
        return {"article_draft": article_draft}
