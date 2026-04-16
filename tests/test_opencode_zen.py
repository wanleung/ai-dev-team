"""Unit tests for OpenCode Zen API backend in ai-software-house."""
from unittest.mock import MagicMock, patch

import pytest


# ── _is_opencode_zen_model ────────────────────────────────────────────────────

def test_is_opencode_zen_model_with_prefix():
    from agents.base_agent import _is_opencode_zen_model
    assert _is_opencode_zen_model("opencode-zen/claude-sonnet-4-6") is True
    assert _is_opencode_zen_model("opencode-zen/gpt-5.3-codex") is True
    assert _is_opencode_zen_model("opencode-zen/gemini-3-flash") is True


def test_is_opencode_zen_model_without_prefix():
    from agents.base_agent import _is_opencode_zen_model
    assert _is_opencode_zen_model("openai/gpt-4.1") is False
    assert _is_opencode_zen_model("opencode/anthropic/claude-sonnet-4-5") is False
    assert _is_opencode_zen_model("claude-sonnet-4-6") is False


# ── BaseAgent opencode_zen backend — Claude model (Anthropic path) ─────────────

def test_opencode_zen_claude_backend_detected():
    """Auto-detects opencode_zen backend from prefix."""
    with patch.dict("os.environ", {"OPENCODE_ZEN_API_KEY": "zen-test-key"}):
        with patch("anthropic.Anthropic"):
            from agents.base_agent import BaseAgent
            agent = BaseAgent(model="opencode-zen/claude-sonnet-4-6")
    assert agent._backend == "opencode_zen"


def test_opencode_zen_claude_strips_prefix():
    """Strips opencode-zen/ prefix for the API model name."""
    with patch.dict("os.environ", {"OPENCODE_ZEN_API_KEY": "zen-test-key"}):
        with patch("anthropic.Anthropic"):
            from agents.base_agent import BaseAgent
            agent = BaseAgent(model="opencode-zen/claude-sonnet-4-6")
    assert agent._api_model == "claude-sonnet-4-6"


def test_opencode_zen_claude_uses_anthropic_client():
    """Claude models get an Anthropic client, not an OpenAI client."""
    with patch.dict("os.environ", {"OPENCODE_ZEN_API_KEY": "zen-test-key"}):
        with patch("anthropic.Anthropic") as mock_anthropic:
            from agents.base_agent import BaseAgent
            agent = BaseAgent(model="opencode-zen/claude-haiku-4-5")
    assert agent.client is None
    assert agent._anthropic_client is not None


def test_opencode_zen_claude_anthropic_client_uses_zen_base_url():
    """Anthropic client is configured with the zen base URL."""
    with patch.dict("os.environ", {"OPENCODE_ZEN_API_KEY": "zen-test-key"}):
        with patch("anthropic.Anthropic") as mock_cls:
            from agents.base_agent import BaseAgent
            BaseAgent(model="opencode-zen/claude-sonnet-4-6")
    mock_cls.assert_called_once_with(
        api_key="zen-test-key",
        base_url="https://opencode.ai/zen/v1",
    )


def test_opencode_zen_custom_base_url():
    """OPENCODE_ZEN_BASE_URL overrides the default endpoint."""
    env = {
        "OPENCODE_ZEN_API_KEY": "zen-test-key",
        "OPENCODE_ZEN_BASE_URL": "https://custom.example.com/v1",
    }
    with patch.dict("os.environ", env):
        with patch("anthropic.Anthropic") as mock_cls:
            from agents.base_agent import BaseAgent
            BaseAgent(model="opencode-zen/claude-sonnet-4-6")
    mock_cls.assert_called_once_with(
        api_key="zen-test-key",
        base_url="https://custom.example.com/v1",
    )


# ── BaseAgent opencode_zen backend — non-Claude model (OpenAI path) ────────────

def test_opencode_zen_gpt_uses_openai_client():
    """Non-Claude models get an OpenAI client pointed at the zen base URL."""
    with patch.dict("os.environ", {"OPENCODE_ZEN_API_KEY": "zen-test-key"}):
        with patch("agents.base_agent.OpenAI") as mock_cls:
            from agents.base_agent import BaseAgent
            agent = BaseAgent(model="opencode-zen/gpt-5.3-codex")
    mock_cls.assert_called_once_with(
        base_url="https://opencode.ai/zen/v1",
        api_key="zen-test-key",
    )
    assert agent._anthropic_client is None


def test_opencode_zen_gpt_strips_prefix():
    """Non-Claude model strips prefix correctly."""
    with patch.dict("os.environ", {"OPENCODE_ZEN_API_KEY": "zen-test-key"}):
        with patch("openai.OpenAI"):
            from agents.base_agent import BaseAgent
            agent = BaseAgent(model="opencode-zen/gpt-5.3-codex")
    assert agent._api_model == "gpt-5.3-codex"


# ── Missing API key ────────────────────────────────────────────────────────────

def test_opencode_zen_raises_on_missing_key():
    """Raises EnvironmentError when OPENCODE_ZEN_API_KEY is not set."""
    env = {k: "" for k in ("OPENCODE_ZEN_API_KEY", "OPENCODE_API_KEY")}
    with patch.dict("os.environ", env, clear=False):
        # Remove the keys from env
        import os
        os.environ.pop("OPENCODE_ZEN_API_KEY", None)
        os.environ.pop("OPENCODE_API_KEY", None)
        from agents.base_agent import BaseAgent
        with pytest.raises(EnvironmentError, match="OPENCODE_ZEN_API_KEY"):
            BaseAgent(model="opencode-zen/gpt-5.3-codex")


def test_opencode_zen_falls_back_to_opencode_api_key():
    """Falls back to OPENCODE_API_KEY when ZEN-specific key is absent."""
    import os
    os.environ.pop("OPENCODE_ZEN_API_KEY", None)
    with patch.dict("os.environ", {"OPENCODE_API_KEY": "fallback-key"}, clear=False):
        with patch("agents.base_agent.OpenAI") as mock_cls:
            from agents.base_agent import BaseAgent
            BaseAgent(model="opencode-zen/gpt-5.3-codex")
    mock_cls.assert_called_once_with(
        base_url="https://opencode.ai/zen/v1",
        api_key="fallback-key",
    )


# ── call() routing ─────────────────────────────────────────────────────────────

def test_call_routes_zen_claude_to_anthropic():
    """call() routes opencode_zen Claude models through _call_anthropic."""
    with patch.dict("os.environ", {"OPENCODE_ZEN_API_KEY": "zen-test-key"}):
        with patch("anthropic.Anthropic"):
            from agents.base_agent import BaseAgent
            agent = BaseAgent(model="opencode-zen/claude-sonnet-4-6")
    with patch.object(agent, "_call_anthropic", return_value="zen claude reply") as mock_call:
        result = agent.call("test prompt")
    mock_call.assert_called_once_with("test prompt")
    assert result == "zen claude reply"


def test_call_routes_zen_gpt_to_openai():
    """call() routes opencode_zen non-Claude models through OpenAI-compatible path."""
    with patch.dict("os.environ", {"OPENCODE_ZEN_API_KEY": "zen-test-key"}):
        with patch("agents.base_agent.OpenAI") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            from agents.base_agent import BaseAgent
            agent = BaseAgent(model="opencode-zen/gpt-5.3-codex")

    mock_response = MagicMock()
    mock_response.choices[0].message.content = "zen gpt reply"
    agent.client.chat.completions.create.return_value = mock_response

    result = agent.call("test prompt")
    assert result == "zen gpt reply"


# ── call_with_tools() guard ────────────────────────────────────────────────────

def test_call_with_tools_raises_for_zen_claude():
    """call_with_tools raises NotImplementedError for opencode_zen + Claude."""
    with patch.dict("os.environ", {"OPENCODE_ZEN_API_KEY": "zen-test-key"}):
        with patch("anthropic.Anthropic"):
            from agents.base_agent import BaseAgent
            agent = BaseAgent(model="opencode-zen/claude-sonnet-4-6")
    tools = MagicMock()
    with pytest.raises(NotImplementedError):
        agent.call_with_tools("task", tools)


def test_call_with_tools_allowed_for_zen_gpt():
    """call_with_tools is allowed for opencode_zen + non-Claude (OpenAI-compatible)."""
    with patch.dict("os.environ", {"OPENCODE_ZEN_API_KEY": "zen-test-key"}):
        with patch("agents.base_agent.OpenAI") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            from agents.base_agent import BaseAgent
            agent = BaseAgent(model="opencode-zen/gpt-5.3-codex")

    mock_response = MagicMock()
    mock_response.choices[0].message.tool_calls = None
    mock_response.choices[0].message.content = "final answer"
    agent.client.chat.completions.create.return_value = mock_response

    tools = MagicMock()
    tools.schemas = []
    result = agent.call_with_tools("task", tools)
    assert result == "final answer"
