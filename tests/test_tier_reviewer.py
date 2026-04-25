# tests/test_tier_reviewer.py
from unittest.mock import MagicMock
from agents.tier_reviewer import TierReviewerAgent


def _make_agent(response: str) -> TierReviewerAgent:
    agent = TierReviewerAgent.__new__(TierReviewerAgent)
    agent.call = MagicMock(return_value=response)
    return agent


def test_run_returns_revised_module_list():
    response = """
1. **`app/models/user`** [tier:junior]: User model
2. **`app/services/auth`** [tier:senior]: Auth service
"""
    agent = _make_agent(response)
    modules = [
        {"name": "`app/models/user`", "description": "User model", "tier": "senior"},
        {"name": "`app/services/auth`", "description": "Auth service", "tier": "junior"},
    ]
    result = agent.run(modules)
    assert result[0]["tier"] == "junior"
    assert result[1]["tier"] == "senior"


def test_run_preserves_modules_on_parse_failure():
    """If LLM returns unparseable output, original modules are returned unchanged."""
    agent = _make_agent("I cannot review these modules right now.")
    modules = [
        {"name": "app/core", "description": "Core", "tier": "senior"},
    ]
    result = agent.run(modules)
    assert result == modules


def test_run_prompt_contains_all_module_names():
    agent = _make_agent("1. **`app/models/user`** [tier:junior]: User model")
    captured = []
    agent.call = MagicMock(side_effect=lambda p: captured.append(p) or "1. **`app/models/user`** [tier:junior]: User model")
    modules = [{"name": "`app/models/user`", "description": "User model", "tier": "senior"}]
    agent.run(modules)
    assert "`app/models/user`" in captured[0]


def test_run_returns_same_length_as_input():
    response = """
1. **`app/a`** [tier:junior]: A
2. **`app/b`** [tier:senior]: B
3. **`app/c`** [tier:junior]: C
"""
    agent = _make_agent(response)
    modules = [
        {"name": "`app/a`", "description": "A", "tier": "senior"},
        {"name": "`app/b`", "description": "B", "tier": "junior"},
        {"name": "`app/c`", "description": "C", "tier": "senior"},
    ]
    result = agent.run(modules)
    assert len(result) == 3
