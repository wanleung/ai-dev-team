"""Tests for PR/Marketing Campaign Pipeline agents."""
import json
import pytest
from unittest.mock import MagicMock, patch


class TestPRAnalystAgent:
    def _make_agent(self):
        from agents.pr_analyst import PRAnalystAgent
        with patch.object(PRAnalystAgent, "__init__", lambda self, **kwargs: None):
            agent = PRAnalystAgent.__new__(PRAnalystAgent)
            agent.logger = __import__("logging").getLogger("test")
            return agent

    def test_parse_brief_extracts_required_fields(self):
        from agents.pr_analyst import PRAnalystAgent
        agent = self._make_agent()
        issue_body = (
            "### Client/Product *\n<!-- hint -->\nAcme Widget\n"
            "### Goal *\n<!-- hint -->\nIncrease awareness\n"
            "### Target Audience *\n<!-- hint -->\nDevelopers\n"
            "### Key Message *\n<!-- hint -->\nBuild faster\n"
        )
        parsed = agent._parse_brief(issue_body)
        assert parsed["client_product"] == "Acme Widget"
        assert parsed["goal"] == "Increase awareness"
        assert parsed["target_audience"] == "Developers"
        assert parsed["key_message"] == "Build faster"

    def test_validate_brief_raises_on_missing_field(self):
        from agents.pr_analyst import PRAnalystAgent
        agent = self._make_agent()
        with pytest.raises(ValueError, match="Missing required"):
            agent._validate_brief({"client_product": "X"}, issue_number=1)

    def test_parse_and_validate_json_valid(self):
        from agents.pr_analyst import PRAnalystAgent
        agent = self._make_agent()
        data = {
            "Opportunity": "Big market",
            "Audience": "Devs",
            "Angle": "Speed",
            "Channels": ["LinkedIn"],
            "Risks": ["Low budget"],
        }
        result = agent._parse_and_validate_json(json.dumps(data))
        assert result["Opportunity"] == "Big market"

    def test_parse_and_validate_json_missing_key_raises(self):
        from agents.pr_analyst import PRAnalystAgent, ParseError
        agent = self._make_agent()
        with pytest.raises((ValueError, ParseError)):
            agent._parse_and_validate_json(json.dumps({"Opportunity": "x"}))

    def test_parse_and_validate_json_invalid_json_raises(self):
        from agents.pr_analyst import PRAnalystAgent, ParseError
        agent = self._make_agent()
        with pytest.raises((ValueError, ParseError)):
            agent._parse_and_validate_json("not json")


class TestPRCreativeAgent:
    def _make_agent(self):
        from agents.pr_creative import PRCreativeAgent
        with patch.object(PRCreativeAgent, "__init__", lambda self, **kwargs: None):
            agent = PRCreativeAgent.__new__(PRCreativeAgent)
            agent.logger = __import__("logging").getLogger("test")
            return agent

    def _make_concept(self, **overrides):
        base = {
            "big_idea": "Test idea",
            "how_it_works": "How",
            "why_it_works": "Why",
            "headline_hook": "Hook",
            "platform_tactics": {"LinkedIn": "post", "Instagram": "reel", "TikTok": "video", "X/Twitter": "thread"},
            "press_release_angle": "Angle",
            "social_copy_example": "Copy",
        }
        base.update(overrides)
        return base

    def test_parse_valid_json_array(self):
        from agents.pr_creative import PRCreativeAgent
        agent = self._make_agent()
        concepts = [self._make_concept() for _ in range(3)]
        result = agent._parse_and_validate_concepts(json.dumps(concepts))
        assert len(result) == 3

    def test_parse_raises_on_too_few_concepts(self):
        from agents.pr_creative import PRCreativeAgent
        agent = self._make_agent()
        concepts = [self._make_concept() for _ in range(2)]
        with pytest.raises(ValueError, match="need at least 3"):
            agent._parse_and_validate_concepts(json.dumps(concepts))

    def test_parse_truncates_to_5(self):
        from agents.pr_creative import PRCreativeAgent
        agent = self._make_agent()
        concepts = [self._make_concept() for _ in range(7)]
        result = agent._parse_and_validate_concepts(json.dumps(concepts))
        assert len(result) == 5

    def test_parse_strips_markdown_fences(self):
        from agents.pr_creative import PRCreativeAgent
        agent = self._make_agent()
        concepts = [self._make_concept() for _ in range(3)]
        fenced = f"```json\n{json.dumps(concepts)}\n```"
        result = agent._parse_and_validate_concepts(fenced)
        assert len(result) == 3

    def test_required_platforms_added_when_missing(self):
        from agents.pr_creative import PRCreativeAgent
        agent = self._make_agent()
        concept = self._make_concept(platform_tactics={})
        result = agent._parse_and_validate_concepts(json.dumps([concept, concept, concept]))
        for platform in ["LinkedIn", "Instagram", "TikTok", "X/Twitter"]:
            assert platform in result[0]["platform_tactics"]

    def test_invalid_json_raises(self):
        from agents.pr_creative import PRCreativeAgent
        agent = self._make_agent()
        with pytest.raises(ValueError, match="Invalid JSON"):
            agent._parse_and_validate_concepts("not json")


class TestPRProposalAgent:
    def _make_agent(self):
        from agents.pr_proposal import PRProposalAgent
        with patch.object(PRProposalAgent, "__init__", lambda self, **kwargs: None):
            agent = PRProposalAgent.__new__(PRProposalAgent)
            agent.logger = __import__("logging").getLogger("test")
            return agent

    def test_parse_llm_response_extracts_last_json_block(self):
        from agents.pr_proposal import PRProposalAgent
        agent = self._make_agent()
        response = (
            "Some text with ```json\n{\"fake\": true}\n``` in the middle.\n\n"
            "Proposal body here.\n\n"
            "```json\n{\"pr_title\": \"Real Title\", \"pr_body\": \"Body\"}\n```"
        )
        body, metadata = agent._parse_llm_response(response)
        assert metadata["pr_title"] == "Real Title"
        assert "fake" not in metadata

    def test_parse_llm_response_fallback_on_no_json(self):
        from agents.pr_proposal import PRProposalAgent
        agent = self._make_agent()
        body, metadata = agent._parse_llm_response("Just plain text")
        assert body == "Just plain text"
        assert "pr_title" in metadata

    def test_create_pr_maps_response_keys_correctly(self):
        from agents.pr_proposal import PRProposalAgent
        agent = self._make_agent()
        mock_client = MagicMock()
        mock_client.create_branch.return_value = "campaign/1-test"
        mock_client.commit_file.return_value = {}
        mock_client.create_pull_request.return_value = {
            "html_url": "https://github.com/owner/repo/pull/42",
            "number": 42,
        }
        result = agent._create_pr_with_retry(
            client=mock_client,
            branch_name="campaign/1-test",
            title="Test",
            body="Body",
            issue_number=1,
            markdown_body="# Proposal",
        )
        assert result["pr_url"] == "https://github.com/owner/repo/pull/42"
        assert result["pr_number"] == 42

    def test_create_pr_calls_add_issue_comment_on_failure(self):
        from agents.pr_proposal import PRProposalAgent
        agent = self._make_agent()
        mock_client = MagicMock()
        mock_client.create_branch.return_value = "campaign/1-test"
        mock_client.commit_file.return_value = {}
        mock_client.create_pull_request.side_effect = RuntimeError("Server error")
        with pytest.raises(RuntimeError):
            agent._create_pr_with_retry(
                client=mock_client,
                branch_name="campaign/1-test",
                title="Test",
                body="Body",
                issue_number=1,
                markdown_body="# Proposal",
            )
        mock_client.add_issue_comment.assert_called_once()
