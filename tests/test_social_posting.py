"""Tests for PRSocialPostAgent and watcher /post-social command detection."""
from __future__ import annotations
import json
from unittest.mock import MagicMock, patch

import pytest


# ── PRSocialPostAgent unit tests ─────────────────────────────────────────────

class TestPRSocialPostAgentParse:
    """Test that the agent parses social data correctly from prior context."""

    def _make_agent(self):
        from agents.pr_social_post import PRSocialPostAgent
        agent = PRSocialPostAgent.__new__(PRSocialPostAgent)
        agent._tool_registry = None
        return agent

    def test_extract_social_data_found(self):
        from agents.pr_social_post import extract_social_copy_data
        creative = {"social_copy_example": "Big news!", "angle": "test"}
        payload = json.dumps(creative)
        prior_ctx = f"Some text\n<!-- social-copy-data\n{payload}\n-->\nMore text"
        result = extract_social_copy_data(prior_ctx)
        assert result is not None
        assert result["social_copy_example"] == "Big news!"

    def test_extract_social_data_missing(self):
        from agents.pr_social_post import extract_social_copy_data
        assert extract_social_copy_data("no data here") is None

    def test_build_prompt_includes_platforms(self):
        from agents.pr_social_post import PRSocialPostAgent
        agent = PRSocialPostAgent.__new__(PRSocialPostAgent)
        creative = {"social_copy_example": "Example copy", "angle": "test angle"}
        prompt = agent._build_prompt(creative, ["x_twitter", "instagram"])
        assert "x_twitter" in prompt.lower() or "x/twitter" in prompt.lower()
        assert "instagram" in prompt.lower()
        assert "Example copy" in prompt

    def test_parse_llm_output_valid_json(self):
        from agents.pr_social_post import PRSocialPostAgent
        agent = PRSocialPostAgent.__new__(PRSocialPostAgent)
        raw = json.dumps({
            "x_twitter": {"text": "Hello world! #test", "posted": False, "url": None, "error": None},
            "instagram": {"caption": "Hello world! #test #social", "posted": False, "url": None, "error": None},
        })
        result = agent._parse_llm_output(raw)
        assert result["x_twitter"]["text"] == "Hello world! #test"
        assert "instagram" in result

    def test_parse_llm_output_strips_fences(self):
        from agents.pr_social_post import PRSocialPostAgent
        agent = PRSocialPostAgent.__new__(PRSocialPostAgent)
        raw = '```json\n{"x_twitter": {"text": "Hi!", "posted": false, "url": null, "error": null}}\n```'
        result = agent._parse_llm_output(raw)
        assert result["x_twitter"]["text"] == "Hi!"

    def test_parse_llm_output_invalid_returns_empty(self):
        from agents.pr_social_post import PRSocialPostAgent
        agent = PRSocialPostAgent.__new__(PRSocialPostAgent)
        result = agent._parse_llm_output("not json at all")
        assert result == {}


class TestPRSocialPostAgentRun:
    """Test agent.run() end-to-end with a mocked LLM call."""

    def test_run_posts_to_enabled_platforms(self):
        from agents.pr_social_post import PRSocialPostAgent, extract_social_copy_data
        creative = {
            "social_copy_example": "Big announcement today!",
            "angle": "innovation",
            "Opportunity": "New product launch",
        }
        prior_ctx_payload = json.dumps(creative)
        prior_ctx = f"<!-- social-copy-data\n{prior_ctx_payload}\n-->"

        llm_output = json.dumps({
            "x_twitter": {"text": "Big announcement! #launch", "posted": False, "url": None, "error": None},
        })

        with patch.object(PRSocialPostAgent, "call", return_value=llm_output) as mock_call:
            agent = PRSocialPostAgent.__new__(PRSocialPostAgent)
            agent._tool_registry = None
            # Simulate _post_platform returning a (url, error) tuple
            with patch.object(PRSocialPostAgent, "_post_platform", return_value=("https://x.com/status/1", None)) as mock_post:
                context = {
                    "prior_context": prior_ctx,
                    "enabled_platforms": ["x_twitter"],
                    "issue_number": 42,
                    "github_client": None,
                }
                result = agent.run(context)

        assert "pr_social_post" in result
        output = result["pr_social_post"]
        assert "x_twitter" in output

    def test_run_fails_gracefully_when_no_social_data(self):
        from agents.pr_social_post import PRSocialPostAgent
        agent = PRSocialPostAgent.__new__(PRSocialPostAgent)
        agent._tool_registry = None
        context = {
            "prior_context": "no social data here",
            "enabled_platforms": ["x_twitter"],
            "issue_number": 42,
            "github_client": None,
        }
        result = agent.run(context)
        assert "pr_social_post" in result
        assert "error" in result["pr_social_post"]


# ── Watcher command detection tests ──────────────────────────────────────────

class TestCheckSocialPostCommands:
    """Test _check_social_post_commands watcher function."""

    def test_detects_post_social_comment(self):
        """Returns a task when an agent-complete issue has /post-social comment."""
        from watcher import _check_social_post_commands

        mock_issues = [
            {
                "number": 10,
                "title": "Campaign X",
                "body": "Launch brief",
                "labels": [
                    {"name": "agent-complete"},
                    {"name": "pr-campaign"},
                ],
            }
        ]
        mock_comments = [
            {"body": "/post-social", "user": {"login": "wanleung"}},
        ]

        watchers = [
            {
                "tracker_repo": "owner/tracker",
                "enabled": True,
                "labels": {"pr-campaign": {"pipeline": "pr-campaign"}},
                "mcp_servers": [
                    {"name": "x-twitter", "enabled": True, "command": "npx", "args": ["-y", "@modelcontextprotocol/server-twitter"]},
                ],
            }
        ]

        with patch("watcher.requests.get") as mock_get, \
             patch("watcher._get_issue_comments", return_value=mock_comments), \
             patch("watcher.add_label") as mock_add_label, \
             patch("watcher.remove_label") as mock_remove_label:
            mock_resp = mock_get.return_value
            mock_resp.raise_for_status.return_value = None
            mock_resp.json.return_value = mock_issues
            tasks = _check_social_post_commands(watchers, "fake-token")

        assert len(tasks) == 1
        assert tasks[0]["issue"]["number"] == 10
        assert tasks[0]["tracker_repo"] == "owner/tracker"
        mock_remove_label.assert_any_call("owner/tracker", 10, "agent-complete")
        mock_add_label.assert_called_once_with("owner/tracker", 10, "ai-social-post")

    def test_skips_already_posted_issues(self):
        """Does not return a task when ai-social-post label already applied."""
        from watcher import _check_social_post_commands

        mock_issues = [
            {
                "number": 11,
                "title": "Campaign Y",
                "body": "Brief",
                "labels": [
                    {"name": "agent-complete"},
                    {"name": "ai-social-post"},  # already labelled
                ],
            }
        ]
        mock_comments = [{"body": "/post-social", "user": {"login": "wanleung"}}]
        watchers = [
            {
                "tracker_repo": "owner/tracker",
                "enabled": True,
                "labels": {"pr-campaign": {"pipeline": "pr-campaign"}},
                "mcp_servers": [
                    {"name": "x-twitter", "enabled": True, "command": "npx", "args": ["-y", "@modelcontextprotocol/server-twitter"]},
                ],
            }
        ]

        with patch("watcher.requests.get") as mock_get, \
             patch("watcher._get_issue_comments", return_value=mock_comments), \
             patch("watcher.add_label") as mock_add_label:
            mock_resp = mock_get.return_value
            mock_resp.raise_for_status.return_value = None
            mock_resp.json.return_value = mock_issues
            tasks = _check_social_post_commands(watchers, "fake-token")

        assert tasks == []
        mock_add_label.assert_not_called()

    def test_skips_watchers_without_social_mcp(self):
        """Does not scan issues when watcher has no enabled social MCP servers."""
        from watcher import _check_social_post_commands

        watchers = [
            {
                "tracker_repo": "owner/tracker",
                "enabled": True,
                "labels": {"pr-campaign": {}},
                "mcp_servers": [],  # no social servers
            }
        ]

        with patch("watcher.requests.get") as mock_get:
            tasks = _check_social_post_commands(watchers, "fake-token")

        mock_get.assert_not_called()
        assert tasks == []
