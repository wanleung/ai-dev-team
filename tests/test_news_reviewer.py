"""Tests for NewsReviewerAgent."""
from __future__ import annotations
from unittest.mock import MagicMock, patch
import pytest


def _make_agent(cls, role_name):
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


PASS_OUTPUT = """VERDICT: PASS
ISSUES:
CONFIDENCE: high"""

NEEDS_REVISION_ENGLISH = """VERDICT: NEEDS_REVISION
ISSUES:
- [FACT] Wrong version: article says "3.2" but source says "3.1"
- [WORDING] Awkward phrasing in paragraph 2
CONFIDENCE: high"""

NEEDS_REVISION_ZH_HK = """VERDICT: NEEDS_REVISION
ISSUES:
- [ZH_HK] Simplified character found: "软" should be "軟"
CONFIDENCE: high"""

NEEDS_REVISION_ZH_TW = """VERDICT: NEEDS_REVISION
ISSUES:
- [ZH_TW] Mainland vocabulary: "软件" should be "軟體"
CONFIDENCE: high"""


class TestNewsReviewerAgent:
    def test_run_returns_pass_verdict(self):
        from agents.news_reviewer import NewsReviewerAgent
        agent = _make_agent(NewsReviewerAgent, "news_reviewer")
        with patch.object(agent, "call", return_value=PASS_OUTPUT):
            result = agent.run("# Article", "# 文章", "# 文章", source_url="https://example.com")
        assert result["verdict"] == "PASS"
        assert result["issues"] == []
        assert result["confidence"] == "high"

    def test_run_returns_needs_revision_with_issues(self):
        from agents.news_reviewer import NewsReviewerAgent
        agent = _make_agent(NewsReviewerAgent, "news_reviewer")
        with patch.object(agent, "call", return_value=NEEDS_REVISION_ENGLISH):
            result = agent.run("# Article", "# 文章", "# 文章", source_url="https://example.com")
        assert result["verdict"] == "NEEDS_REVISION"
        assert any("[FACT]" in i for i in result["issues"])
        assert any("[WORDING]" in i for i in result["issues"])

    def test_run_detects_zh_hk_issues(self):
        from agents.news_reviewer import NewsReviewerAgent
        agent = _make_agent(NewsReviewerAgent, "news_reviewer")
        with patch.object(agent, "call", return_value=NEEDS_REVISION_ZH_HK):
            result = agent.run("# Article", "# 文章", "# 文章", source_url="https://example.com")
        assert result["verdict"] == "NEEDS_REVISION"
        assert any("[ZH_HK]" in i for i in result["issues"])

    def test_run_detects_zh_tw_issues(self):
        from agents.news_reviewer import NewsReviewerAgent
        agent = _make_agent(NewsReviewerAgent, "news_reviewer")
        with patch.object(agent, "call", return_value=NEEDS_REVISION_ZH_TW):
            result = agent.run("# Article", "# 文章", "# 文章", source_url="https://example.com")
        assert result["verdict"] == "NEEDS_REVISION"
        assert any("[ZH_TW]" in i for i in result["issues"])

    def test_run_passes_through_on_unparseable_output(self):
        from agents.news_reviewer import NewsReviewerAgent
        agent = _make_agent(NewsReviewerAgent, "news_reviewer")
        with patch.object(agent, "call", return_value="Something went wrong, here is a summary..."):
            result = agent.run("# Article", "# 文章", "# 文章", source_url="https://example.com")
        assert result["verdict"] == "PASS"  # fail-safe: never block on bad reviewer output

    def test_run_works_without_source_url(self):
        from agents.news_reviewer import NewsReviewerAgent
        agent = _make_agent(NewsReviewerAgent, "news_reviewer")
        with patch.object(agent, "call", return_value=PASS_OUTPUT):
            result = agent.run("# Article", "# 文章", "# 文章", source_url="")
        assert result["verdict"] == "PASS"

    def test_run_injects_source_content_into_prompt(self):
        from agents.news_reviewer import NewsReviewerAgent
        agent = _make_agent(NewsReviewerAgent, "news_reviewer")
        captured = {}
        def capture(prompt):
            captured["prompt"] = prompt
            return PASS_OUTPUT
        with patch.object(agent, "call", side_effect=capture):
            with patch("agents.news_reviewer._fetch_source", return_value="Source text here"):
                agent.run("# Article", "# 文章", "# 文章", source_url="https://example.com")
        assert "Source text here" in captured["prompt"]

    def test_exports_from_agents_package(self):
        from agents import NewsReviewerAgent
        assert NewsReviewerAgent

    def test_unsafe_url_is_blocked(self):
        from agents.news_reviewer import _is_safe_url
        assert not _is_safe_url("file:///etc/passwd")
        assert not _is_safe_url("ftp://example.com/data")
        assert not _is_safe_url("http://localhost/admin")
        assert not _is_safe_url("http://127.0.0.1:8080/secret")
        assert not _is_safe_url("http://169.254.169.254/metadata")  # AWS metadata

    def test_safe_public_url_passes_validation(self):
        from agents.news_reviewer import _is_safe_url
        # Use patch to avoid real DNS lookup in tests
        with patch("agents.news_reviewer.socket.getaddrinfo", return_value=[(None, None, None, None, ("93.184.216.34", 0))]):
            assert _is_safe_url("https://example.com/article")
