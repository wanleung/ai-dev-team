"""Tests for NewsWriterAgent and NewsEditorAgent."""
from __future__ import annotations
from unittest.mock import MagicMock, patch
import pytest


def _make_agent(cls, role_name):
    """Create agent with a mocked LLM backend."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = "mock output"
    agent = cls.__new__(cls)
    agent.system_prompt = f"You are a {role_name}."
    agent._llm = mock_llm
    agent.role_name = role_name
    agent.max_api_retries = 1
    agent.retry_delay = 0
    agent.inter_call_delay = 0
    agent._token_ledger = None
    return agent


class TestNewsWriterAgent:
    def test_run_returns_article_draft(self):
        from agents.news_writer import NewsWriterAgent
        agent = _make_agent(NewsWriterAgent, "news_writer")
        with patch.object(agent, "call", return_value="# Draft Article\n\nContent here."):
            result = agent.run("https://example.com story about Linux")
        assert "article_draft" in result
        assert "Draft Article" in result["article_draft"]

    def test_run_injects_discussion_synthesis(self):
        from agents.news_writer import NewsWriterAgent
        agent = _make_agent(NewsWriterAgent, "news_writer")
        captured = {}
        def capture_call(prompt):
            captured["prompt"] = prompt
            return "# Article"
        with patch.object(agent, "call", side_effect=capture_call):
            agent.run("brief", discussion_synthesis="Key insight: AI is big")
        assert "Key insight: AI is big" in captured["prompt"]

    def test_run_without_synthesis_still_works(self):
        from agents.news_writer import NewsWriterAgent
        agent = _make_agent(NewsWriterAgent, "news_writer")
        with patch.object(agent, "call", return_value="# Article\nBody."):
            result = agent.run("Some news brief")
        assert result["article_draft"]


class TestNewsEditorAgent:
    def test_run_returns_article(self):
        from agents.news_editor import NewsEditorAgent
        agent = _make_agent(NewsEditorAgent, "news_editor")
        with patch.object(agent, "call", return_value="---\ntitle: Final\n---\n\nBody."):
            result = agent.run(article_draft="# Draft\nBody.", issue_body="Brief")
        assert "article" in result
        assert "Final" in result["article"]

    def test_run_injects_draft_review_synthesis(self):
        from agents.news_editor import NewsEditorAgent
        agent = _make_agent(NewsEditorAgent, "news_editor")
        captured = {}
        def capture_call(prompt):
            captured["prompt"] = prompt
            return "# Edited"
        with patch.object(agent, "call", side_effect=capture_call):
            agent.run("Draft text", discussion_synthesis="Fix the headline")
        assert "Fix the headline" in captured["prompt"]

    def test_exports_from_agents_package(self):
        from agents import NewsWriterAgent, NewsEditorAgent
        assert NewsWriterAgent
        assert NewsEditorAgent
