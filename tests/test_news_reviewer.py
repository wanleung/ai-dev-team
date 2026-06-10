"""Tests for NewsReviewerAgent."""
from __future__ import annotations
from unittest.mock import MagicMock, patch


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

NEEDS_REVISION_ZH_TW = """VERDICT: NEEDS_REVISION
ISSUES:
- [ZH_TW] Simplified character found: "软" should be "軟"
CONFIDENCE: high"""


class TestNewsReviewerAgent:
    def test_run_returns_pass_verdict(self):
        from agents.news_reviewer import NewsReviewerAgent
        agent = _make_agent(NewsReviewerAgent, "news_reviewer")
        with patch.object(agent, "call", return_value=PASS_OUTPUT):
            result = agent.run("# Article", "# 文章", source_url="https://example.com")
        assert result["verdict"] == "PASS"
        assert result["issues"] == []
        assert result["confidence"] == "high"

    def test_run_returns_needs_revision_with_issues(self):
        from agents.news_reviewer import NewsReviewerAgent
        agent = _make_agent(NewsReviewerAgent, "news_reviewer")
        with patch.object(agent, "call", return_value=NEEDS_REVISION_ENGLISH):
            result = agent.run("# Article", "# 文章", source_url="https://example.com")
        assert result["verdict"] == "NEEDS_REVISION"
        assert any("[FACT]" in i for i in result["issues"])
        assert any("[WORDING]" in i for i in result["issues"])

    def test_run_detects_zh_tw_issues(self):
        from agents.news_reviewer import NewsReviewerAgent
        agent = _make_agent(NewsReviewerAgent, "news_reviewer")
        with patch.object(agent, "call", return_value=NEEDS_REVISION_ZH_TW):
            result = agent.run("# Article", "# 文章", source_url="https://example.com")
        assert result["verdict"] == "NEEDS_REVISION"
        assert any("[ZH_TW]" in i for i in result["issues"])

    def test_run_passes_through_on_unparseable_output(self):
        from agents.news_reviewer import NewsReviewerAgent
        agent = _make_agent(NewsReviewerAgent, "news_reviewer")
        with patch.object(agent, "call", return_value="Something went wrong, here is a summary..."):
            result = agent.run("# Article", "# 文章", source_url="https://example.com")
        assert result["verdict"] == "PASS"  # fail-safe: never block on bad reviewer output

    def test_run_works_without_source_url(self):
        from agents.news_reviewer import NewsReviewerAgent
        agent = _make_agent(NewsReviewerAgent, "news_reviewer")
        with patch.object(agent, "call", return_value=PASS_OUTPUT):
            result = agent.run("# Article", "# 文章", source_url="")
        assert result["verdict"] == "PASS"

    def test_run_injects_source_content_into_prompt(self):
        from agents.news_reviewer import NewsReviewerAgent
        agent = _make_agent(NewsReviewerAgent, "news_reviewer")
        captured = {}
        def capture(prompt):
            captured["prompt"] = prompt
            return PASS_OUTPUT
        with patch.object(agent, "call", side_effect=capture):
            source_text = (
                "Source text here with enough article body content to be useful for fact checking. "
                "The article explains a software release, names the project, describes the change, "
                "and includes several factual details that the reviewer can compare against the draft. "
                "It also mentions the upstream repository, supported platforms, implementation timeline, "
                "maintainer comments, and release context so the fetched page is clearly not boilerplate."
            )
            with patch("agents.news_reviewer._fetch_source", return_value=source_text):
                agent.run("# Article", "# 文章", source_url="https://example.com")
        assert "Source text here" in captured["prompt"]
        assert "Source text here" in captured["prompt"]

    def test_cookie_boilerplate_source_uses_tool_fallback(self):
        from agents.news_reviewer import NewsReviewerAgent
        agent = _make_agent(NewsReviewerAgent, "news_reviewer")
        agent._tool_registry = MagicMock()
        captured = {}

        def capture(prompt, tools):
            captured["prompt"] = prompt
            captured["tools"] = tools
            return PASS_OUTPUT

        boilerplate = """
        <html><head><style>.banner{display:block}</style><script>window.cookieConsent=true</script></head>
        <body>Cookie consent We use cookies Accept Reject Manage preferences Privacy Policy</body></html>
        """
        with patch.object(agent, "call_with_tools", side_effect=capture):
            with patch("agents.news_reviewer._fetch_source", return_value=boilerplate):
                result = agent.run("# Article", "# 文章", source_url="https://example.com/story")

        assert result["verdict"] == "PASS"
        assert "Direct fetch of 'https://example.com/story' returned boilerplate" in captured["prompt"]
        assert captured["tools"] is agent._tool_registry

    def test_large_cookie_modal_html_uses_tool_fallback(self):
        from agents.news_reviewer import NewsReviewerAgent
        agent = _make_agent(NewsReviewerAgent, "news_reviewer")
        agent._tool_registry = MagicMock()
        captured = {}

        def capture(prompt, tools):
            captured["prompt"] = prompt
            captured["tools"] = tools
            return PASS_OUTPUT

        repeated_js = " ".join(
            ["function CookieConsentModal(){return window.localStorage.getItem('cookie-consent');}"] * 80
        )
        modal_html = f"""
        <html>
          <head>
            <style>.cookie-consent-modal {{ display: block; position: fixed; }}</style>
            <script>{repeated_js}</script>
          </head>
          <body>
            <div id="cookie-consent-modal">
              Cookie settings. We use cookies to personalise content and analyse traffic.
              Accept all cookies. Reject optional cookies. Manage preferences.
              Privacy Policy. Consent Management Platform.
            </div>
          </body>
        </html>
        """
        with patch.object(agent, "call_with_tools", side_effect=capture):
            with patch("agents.news_reviewer._fetch_source", return_value=modal_html):
                result = agent.run("# Article", "# 文章", source_url="https://example.com/story")

        assert result["verdict"] == "PASS"
        assert "returned boilerplate" in captured["prompt"]
        assert captured["tools"] is agent._tool_registry

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
