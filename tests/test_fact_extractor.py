"""Unit tests for FactExtractorAgent."""
import json
from unittest.mock import patch

import pytest

from agents.fact_extractor import FactExtractorAgent


def _make_agent():
    """Create a FactExtractorAgent with mocked internals (no real API calls)."""
    return FactExtractorAgent(model="gpt-4.1")


# ── extract() — end to end via a mocked call() ─────────────────────────────

def test_extract_returns_parsed_facts():
    """extract() calls the LLM and returns the parsed fact list."""
    raw = json.dumps([
        {"type": "issue", "entity": "RSS watcher", "fact": "403 errors from dedup", "resolved": False},
    ])
    with patch.object(FactExtractorAgent, "call", return_value=raw):
        agent = _make_agent()
        facts = agent.extract(
            repo="owner/repo", requirement="req", prd="prd", design="design",
            review="review", summary="summary",
        )
    assert facts == [
        {"type": "issue", "entity": "RSS watcher", "fact": "403 errors from dedup", "resolved": False},
    ]


def test_extract_returns_empty_list_when_nothing_fact_worthy():
    """extract() handles the documented '[]' case — not an error."""
    with patch.object(FactExtractorAgent, "call", return_value="[]"):
        agent = _make_agent()
        facts = agent.extract(
            repo="owner/repo", requirement="", prd="", design="", review="", summary="",
        )
    assert facts == []


# ── _parse_facts() — validation and normalisation ───────────────────────────

class TestParseFacts:
    def test_parses_clean_json(self):
        agent = _make_agent()
        raw = json.dumps([
            {"type": "decision", "entity": "database", "fact": "Switched to raw SQL", "resolved": True},
        ])
        assert agent._parse_facts(raw) == [
            {"type": "decision", "entity": "database", "fact": "Switched to raw SQL", "resolved": True},
        ]

    def test_strips_markdown_json_fences(self):
        agent = _make_agent()
        raw = '```json\n[{"type": "status", "entity": "image gen", "fact": "ComfyUI shipped", "resolved": true}]\n```'
        result = agent._parse_facts(raw)
        assert len(result) == 1
        assert result[0]["fact"] == "ComfyUI shipped"

    def test_extracts_json_array_from_surrounding_prose(self):
        """Falls back to regex extraction when the LLM adds prose around the array."""
        agent = _make_agent()
        raw = (
            "Here are the facts I found:\n"
            '[{"type": "learning", "entity": "tests", "fact": "dont import conftest", "resolved": true}]\n'
            "Hope this helps!"
        )
        result = agent._parse_facts(raw)
        assert len(result) == 1
        assert result[0]["type"] == "learning"

    def test_unparseable_input_returns_empty_list_not_raise(self):
        agent = _make_agent()
        assert agent._parse_facts("not json at all, sorry!") == []

    def test_non_list_json_returns_empty_list(self):
        """A JSON object instead of an array is invalid output — never raises."""
        agent = _make_agent()
        assert agent._parse_facts('{"type": "issue", "fact": "oops"}') == []

    def test_invalid_fact_type_normalised_to_default(self):
        agent = _make_agent()
        raw = json.dumps([{"type": "bogus", "entity": "x", "fact": "something happened", "resolved": True}])
        result = agent._parse_facts(raw)
        assert result[0]["type"] == "status"

    def test_items_missing_fact_text_are_dropped(self):
        agent = _make_agent()
        raw = json.dumps([
            {"type": "issue", "entity": "x", "resolved": False},
            {"type": "issue", "entity": "y", "fact": "real one", "resolved": False},
        ])
        result = agent._parse_facts(raw)
        assert len(result) == 1
        assert result[0]["fact"] == "real one"

    def test_non_dict_items_in_array_are_skipped(self):
        agent = _make_agent()
        raw = json.dumps(["just a string", {"type": "status", "entity": "x", "fact": "ok", "resolved": True}])
        result = agent._parse_facts(raw)
        assert len(result) == 1

    def test_missing_resolved_defaults_to_false(self):
        agent = _make_agent()
        raw = json.dumps([{"type": "issue", "entity": "x", "fact": "something broke"}])
        result = agent._parse_facts(raw)
        assert result[0]["resolved"] is False

    def test_fact_type_is_lowercased(self):
        agent = _make_agent()
        raw = json.dumps([{"type": "DECISION", "entity": "x", "fact": "chose Postgres", "resolved": True}])
        result = agent._parse_facts(raw)
        assert result[0]["type"] == "decision"

    def test_entity_whitespace_is_stripped(self):
        agent = _make_agent()
        raw = json.dumps([{"type": "status", "entity": "  RSS watcher  ", "fact": "shipped", "resolved": True}])
        result = agent._parse_facts(raw)
        assert result[0]["entity"] == "RSS watcher"
