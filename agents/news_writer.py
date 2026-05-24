"""
NewsWriterAgent: researches and writes a first-draft news article.

Input:  issue_body (str) — the news brief from the GitHub issue
Output: dict with 'article_draft' (markdown string with YAML frontmatter)
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .base_agent import BaseAgent

if TYPE_CHECKING:
    from tools.registry import ToolRegistry


class NewsWriterAgent(BaseAgent):
    """Write a first-draft news article from an issue brief and optional discussion synthesis."""

    role_name = "news_writer"
    _tool_registry: "ToolRegistry | None" = None

    def __init__(self, *args, tool_registry: "ToolRegistry | None" = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._tool_registry = tool_registry

    def run(self, issue_body: str, discussion_synthesis: str = "") -> dict:
        """Write a news article draft.

        Args:
            issue_body: News brief from GitHub issue
            discussion_synthesis: Pre-write analysis synthesis

        Returns:
            dict with 'article_draft' (markdown str with YAML frontmatter)
        """
        prompt = self._build_writer_prompt(issue_body, discussion_synthesis)
        article_draft = self._call_writer(prompt)
        return {"article_draft": article_draft}

    def _build_writer_prompt(self, issue_body: str, discussion_synthesis: str) -> str:
        """Build the writing prompt from issue body and optional discussion synthesis."""
        synthesis_section = (
            f"A pre-write analysis of this story has been conducted.\n"
            f"Use the key insights below to guide your article — do not copy them verbatim.\n\n"
            f"---\n{discussion_synthesis}\n---\n\n"
            if discussion_synthesis.strip()
            else ""
        )
        research_instruction = (
            "Use google_fetch_page or google_search tools to research the source URL "
            "and any related stories before writing. "
            if self._tool_registry is not None
            else ""
        )
        return (
            f"{synthesis_section}"
            f"Write a news article based on the following brief:\n\n"
            f"---\n{issue_body}\n---\n\n"
            f"{research_instruction}"
            f"Follow your role instructions. "
            f"Output ONLY the complete article in markdown with YAML frontmatter, starting with '---'. "
            f"Do NOT describe what you are doing, mention file paths, or say the article was written anywhere. "
            f"Your entire response must be the article itself."
        )

    def _call_writer(self, prompt: str) -> str:
        """Call the LLM with or without tools depending on registry availability."""
        if self._tool_registry is not None:
            return self.call_with_tools(prompt, self._tool_registry)
        return self.call(prompt)
