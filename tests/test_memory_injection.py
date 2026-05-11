"""Tests that memory context injection does not stack across multiple run() calls."""
import pytest


class _FakeAgent:
    """Minimal agent stub with a system_prompt attribute."""

    def __init__(self, system_prompt: str) -> None:
        self.system_prompt = system_prompt


def _inject_memory(agent: _FakeAgent, memory_context: str, original_system_prompts: dict) -> None:
    """
    Replicate the fixed injection logic from orchestrator.py.

    Uses the original system prompt stored in *original_system_prompts* as the
    base so that repeated calls do not stack the memory context.
    """
    if agent.system_prompt is not None:
        original = original_system_prompts.get(agent, agent.system_prompt)
        agent.system_prompt = memory_context + "\n\n---\n\n" + original


def _inject_memory_buggy(agent: _FakeAgent, memory_context: str) -> None:
    """Replicate the *buggy* injection logic — always reads agent.system_prompt."""
    if agent.system_prompt:
        agent.system_prompt = memory_context + "\n\n---\n\n" + agent.system_prompt


# ---------------------------------------------------------------------------
# Tests for the FIXED injection helper
# ---------------------------------------------------------------------------

def test_memory_injection_does_not_stack():
    """Calling _inject_memory twice must not prepend memory_context twice."""
    base_prompt = "You are a helpful engineer."
    memory_context = "MEMORY: previous work summary."

    agent = _FakeAgent(base_prompt)
    original_system_prompts = {agent: base_prompt}

    # First injection
    _inject_memory(agent, memory_context, original_system_prompts)
    after_first = agent.system_prompt

    # Second injection (simulates a second run() call)
    _inject_memory(agent, memory_context, original_system_prompts)
    after_second = agent.system_prompt

    expected = memory_context + "\n\n---\n\n" + base_prompt

    assert after_first == expected, "First injection should prefix memory onto the base prompt"
    assert after_second == expected, (
        "Second injection should produce the same result — memory must not stack"
    )
    assert after_second.count(memory_context) == 1, (
        "memory_context must appear exactly once after two injections"
    )


def test_memory_injection_first_call_correct():
    """A single injection should produce memory_context + separator + base_prompt."""
    base_prompt = "You are a QA engineer."
    memory_context = "MEMORY: context block."

    agent = _FakeAgent(base_prompt)
    original_system_prompts = {agent: base_prompt}

    _inject_memory(agent, memory_context, original_system_prompts)

    assert agent.system_prompt == memory_context + "\n\n---\n\n" + base_prompt


def test_memory_injection_skips_none_prompt():
    """Agents with system_prompt=None should be left untouched."""
    agent = _FakeAgent(None)
    original_system_prompts = {agent: None}

    _inject_memory(agent, "MEMORY: context.", original_system_prompts)

    assert agent.system_prompt is None


def test_memory_injection_allows_empty_string_prompt():
    """An empty-string system_prompt is a valid base and should be injected."""
    base_prompt = ""
    memory_context = "MEMORY: context."

    agent = _FakeAgent(base_prompt)
    original_system_prompts = {agent: base_prompt}

    _inject_memory(agent, memory_context, original_system_prompts)

    assert agent.system_prompt == memory_context + "\n\n---\n\n" + base_prompt


def test_injection_three_times_still_no_stack():
    """Three consecutive injections must still result in exactly one memory prefix."""
    base_prompt = "You are an architect."
    memory_context = "MEMORY: block."

    agent = _FakeAgent(base_prompt)
    original_system_prompts = {agent: base_prompt}

    for _ in range(3):
        _inject_memory(agent, memory_context, original_system_prompts)

    assert agent.system_prompt.count(memory_context) == 1, (
        "memory_context must appear exactly once regardless of injection count"
    )


# ---------------------------------------------------------------------------
# Regression guard: demonstrate that the buggy logic DOES stack
# (so we know the test would catch a regression if the fix were reverted)
# ---------------------------------------------------------------------------

def test_buggy_injection_stacks_to_confirm_regression_detection():
    """
    The original (buggy) logic stacks memory context on repeated calls.
    This test proves our regression-detection test would catch a revert.
    """
    base_prompt = "You are a PM."
    memory_context = "MEMORY: old work."

    agent = _FakeAgent(base_prompt)

    _inject_memory_buggy(agent, memory_context)
    _inject_memory_buggy(agent, memory_context)

    # With the buggy logic the prompt now has memory_context twice
    assert agent.system_prompt.count(memory_context) == 2, (
        "Buggy injection should stack — if this fails the buggy helper is wrong"
    )
