"""
TranslatorAgent: translates a finalised news article into a target language.

Input:  article (str) — full markdown with YAML frontmatter (English)
        target_language (str) — "cantonese" | "traditional_chinese"
Output: dict with 'translated_article' (str)
"""
from __future__ import annotations

from typing import Literal

from .base_agent import BaseAgent

_LANGUAGE_LABELS = {
    "cantonese": "Written Cantonese (zh-hk)",
    "traditional_chinese": "Formal Traditional Chinese (zh-tw)",
}


class TranslatorAgent(BaseAgent):
    """Translate a news article into Written Cantonese or Traditional Chinese."""

    role_name = "translator"

    def run(self, article: str, target_language: Literal["cantonese", "traditional_chinese"]) -> dict:
        """Translate the article.

        Args:
            article: Full markdown article with YAML frontmatter (English source).
            target_language: "cantonese" for Written Cantonese (zh-hk),
                             "traditional_chinese" for Formal Traditional Chinese (zh-tw).

        Returns:
            dict with key:
                - translated_article (str): Full translated markdown with frontmatter
        """
        label = _LANGUAGE_LABELS.get(target_language, target_language)
        prompt = (
            f"Translate the following news article to {label}.\n\n"
            f"Follow your role instructions exactly.\n\n"
            f"<ARTICLE>\n{article}\n</ARTICLE>\n\n"
            f"Output the translated article only."
        )
        translated_article = self.call(prompt)
        return {"translated_article": translated_article}
