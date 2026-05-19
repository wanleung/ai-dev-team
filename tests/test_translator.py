"""Tests for TranslatorAgent."""
from __future__ import annotations
from unittest.mock import MagicMock, patch


def _make_agent(cls):
    mock_llm = MagicMock()
    mock_llm.chat.return_value = "mock output"
    agent = cls.__new__(cls)
    agent.system_prompt = "You are a translator."
    agent._llm = mock_llm
    agent.role_name = "translator"
    agent.max_api_retries = 1
    agent.retry_delay = 0
    agent.inter_call_delay = 0
    agent._token_ledger = None
    return agent


class TestTranslatorAgent:
    def test_run_returns_translated_article(self):
        from agents.translator import TranslatorAgent
        agent = _make_agent(TranslatorAgent)
        with patch.object(agent, "call", return_value="---\ntitle: 測試\n---\n\n內容。"):
            result = agent.run("---\ntitle: Test\n---\n\nContent.", target_language="cantonese")
        assert "translated_article" in result
        assert result["translated_article"] == "---\ntitle: 測試\n---\n\n內容。"

    def test_run_injects_target_language_in_prompt(self):
        from agents.translator import TranslatorAgent
        agent = _make_agent(TranslatorAgent)
        captured = {}
        def capture(prompt):
            captured["prompt"] = prompt
            return "# 翻譯"
        with patch.object(agent, "call", side_effect=capture):
            agent.run("# Article\n\nBody.", target_language="traditional_chinese")
        assert "Formal Traditional Chinese" in captured["prompt"] or "Traditional Chinese" in captured["prompt"]

    def test_run_injects_article_in_prompt(self):
        from agents.translator import TranslatorAgent
        agent = _make_agent(TranslatorAgent)
        captured = {}
        def capture(prompt):
            captured["prompt"] = prompt
            return "# 翻譯"
        with patch.object(agent, "call", side_effect=capture):
            agent.run("# My English Article\n\nSome content.", target_language="cantonese")
        assert "My English Article" in captured["prompt"]

    def test_exports_from_agents_package(self):
        from agents import TranslatorAgent
        assert TranslatorAgent

    def test_run_both_language_targets(self):
        from agents.translator import TranslatorAgent
        agent = _make_agent(TranslatorAgent)
        for lang in ("cantonese", "traditional_chinese"):
            with patch.object(agent, "call", return_value="# 翻譯"):
                result = agent.run("# Article", target_language=lang)
            assert "translated_article" in result
