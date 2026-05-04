"""Unit tests for OpenCode Go plan API backend in ai-software-house."""
from unittest.mock import MagicMock, patch

import pytest


# ── _is_opencode_go_model ─────────────────────────────────────────────────────

def test_is_opencode_go_model_with_prefix():
    from agents.base_agent import _is_opencode_go_model
    assert _is_opencode_go_model("opencode-go/kimi-k2.5") is True
    assert _is_opencode_go_model("opencode-go/qwen3.6-plus") is True
    assert _is_opencode_go_model("opencode-go/minimax-m2.7") is True


def test_is_opencode_go_model_without_prefix():
    from agents.base_agent import _is_opencode_go_model
    assert _is_opencode_go_model("opencode-zen/gpt-5.3-codex") is False
    assert _is_opencode_go_model("opencode/anthropic/claude-sonnet-4-5") is False
    assert _is_opencode_go_model("kimi-k2.5") is False


# ── BaseAgent opencode_go backend — OpenAI-compatible models ──────────────────

def test_opencode_go_backend_detected():
    with patch.dict("os.environ", {"OPENCODE_ZEN_API_KEY": "zen-key"}):
        with patch("agents.base_agent.OpenAI"):
            from agents.base_agent import BaseAgent
            agent = BaseAgent(model="opencode-go/kimi-k2.5")
    assert agent._backend == "opencode_go"


def test_opencode_go_strips_prefix():
    with patch.dict("os.environ", {"OPENCODE_ZEN_API_KEY": "zen-key"}):
        with patch("agents.base_agent.OpenAI"):
            from agents.base_agent import BaseAgent
            agent = BaseAgent(model="opencode-go/kimi-k2.5")
    assert agent._api_model == "kimi-k2.5"


def test_opencode_go_uses_openai_client_for_chat_models():
    with patch.dict("os.environ", {"OPENCODE_ZEN_API_KEY": "zen-key"}):
        with patch("agents.backends.opencode_go.OpenAI") as mock_cls:
            from agents.base_agent import BaseAgent
            agent = BaseAgent(model="opencode-go/kimi-k2.5")
    mock_cls.assert_called_once_with(
        base_url="https://opencode.ai/zen/go/v1",
        api_key="zen-key",
    )
    assert agent._anthropic_client is None


def test_opencode_go_qwen_uses_chat_completions():
    """Qwen models (alibaba SDK) still use chat/completions via OpenAI client."""
    with patch.dict("os.environ", {"OPENCODE_ZEN_API_KEY": "zen-key"}):
        with patch("agents.backends.opencode_go.OpenAI") as mock_cls:
            from agents.base_agent import BaseAgent
            BaseAgent(model="opencode-go/qwen3.6-plus")
    mock_cls.assert_called_once_with(
        base_url="https://opencode.ai/zen/go/v1",
        api_key="zen-key",
    )


def test_opencode_go_glm_uses_chat_completions():
    with patch.dict("os.environ", {"OPENCODE_ZEN_API_KEY": "zen-key"}):
        with patch("agents.backends.opencode_go.OpenAI") as mock_cls:
            from agents.base_agent import BaseAgent
            BaseAgent(model="opencode-go/glm-5.1")
    mock_cls.assert_called_once_with(
        base_url="https://opencode.ai/zen/go/v1",
        api_key="zen-key",
    )


# ── BaseAgent opencode_go backend — MiniMax (Anthropic endpoint) ──────────────

def test_opencode_go_minimax_uses_anthropic_client():
    with patch.dict("os.environ", {"OPENCODE_ZEN_API_KEY": "zen-key"}):
        with patch("anthropic.Anthropic") as mock_cls:
            from agents.base_agent import BaseAgent
            agent = BaseAgent(model="opencode-go/minimax-m2.7")
    mock_cls.assert_called_once_with(
        api_key="zen-key",
        base_url="https://opencode.ai/zen/go/v1",
    )
    assert agent.client is None


def test_opencode_go_minimax_m25_uses_anthropic_client():
    with patch.dict("os.environ", {"OPENCODE_ZEN_API_KEY": "zen-key"}):
        with patch("anthropic.Anthropic") as mock_cls:
            from agents.base_agent import BaseAgent
            BaseAgent(model="opencode-go/minimax-m2.5")
    mock_cls.assert_called_once()


# ── Custom base URL ───────────────────────────────────────────────────────────

def test_opencode_go_custom_base_url():
    env = {
        "OPENCODE_ZEN_API_KEY": "zen-key",
        "OPENCODE_GO_BASE_URL": "https://custom-go.example.com/v1",
    }
    with patch.dict("os.environ", env):
        with patch("agents.backends.opencode_go.OpenAI") as mock_cls:
            from agents.base_agent import BaseAgent
            BaseAgent(model="opencode-go/kimi-k2.5")
    mock_cls.assert_called_once_with(
        base_url="https://custom-go.example.com/v1",
        api_key="zen-key",
    )


# ── Missing API key ───────────────────────────────────────────────────────────

def test_opencode_go_raises_on_missing_key():
    import os
    os.environ.pop("OPENCODE_ZEN_API_KEY", None)
    os.environ.pop("OPENCODE_API_KEY", None)
    from agents.base_agent import BaseAgent
    with pytest.raises(EnvironmentError, match="OPENCODE_ZEN_API_KEY"):
        BaseAgent(model="opencode-go/kimi-k2.5")


# ── call() routing ────────────────────────────────────────────────────────────

def test_call_routes_go_chat_model_to_openai():
    with patch.dict("os.environ", {"OPENCODE_ZEN_API_KEY": "zen-key"}):
        with patch("agents.backends.opencode_go.OpenAI") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            from agents.base_agent import BaseAgent
            agent = BaseAgent(model="opencode-go/kimi-k2.5", opencode_stream=False)

    mock_response = MagicMock()
    mock_response.choices[0].message.content = "kimi reply"
    agent.client.chat.completions.create.return_value = mock_response

    result = agent.call("test prompt")
    assert result == "kimi reply"


def test_call_routes_go_minimax_to_anthropic():
    with patch.dict("os.environ", {"OPENCODE_ZEN_API_KEY": "zen-key"}):
        with patch("anthropic.Anthropic"):
            from agents.base_agent import BaseAgent
            agent = BaseAgent(model="opencode-go/minimax-m2.7")
    with patch.object(agent, "_call_anthropic", return_value="minimax reply") as mock_call:
        result = agent.call("test prompt")
    mock_call.assert_called_once_with("test prompt")
    assert result == "minimax reply"


# ── call_with_tools() ─────────────────────────────────────────────────────────

def test_call_with_tools_works_for_go_chat_models():
    """Tool-calling works for Go plan chat/completions models (fixes Code Reviewer)."""
    with patch.dict("os.environ", {"OPENCODE_ZEN_API_KEY": "zen-key"}):
        with patch("agents.backends.opencode_go.OpenAI") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            from agents.base_agent import BaseAgent
            agent = BaseAgent(model="opencode-go/kimi-k2.5", opencode_stream=False)

    mock_response = MagicMock()
    mock_response.choices[0].message.tool_calls = None
    mock_response.choices[0].message.content = "review result"
    agent.client.chat.completions.create.return_value = mock_response

    tools = MagicMock()
    tools.schemas = []
    result = agent.call_with_tools("review this code", tools)
    assert result == "review result"


def test_call_with_tools_raises_for_go_minimax():
    """Tool-calling is blocked for MiniMax (Anthropic endpoint)."""
    with patch.dict("os.environ", {"OPENCODE_ZEN_API_KEY": "zen-key"}):
        with patch("anthropic.Anthropic"):
            from agents.base_agent import BaseAgent
            agent = BaseAgent(model="opencode-go/minimax-m2.7")
    tools = MagicMock()
    with pytest.raises(NotImplementedError):
        agent.call_with_tools("task", tools)


# ── opencode_stream parameter ────────────────────────────────────────────────

def test_base_agent_opencode_stream_default_true():
    """BaseAgent with opencode-go model defaults opencode_stream to True."""
    with patch.dict("os.environ", {"OPENCODE_ZEN_API_KEY": "zen-key"}):
        with patch("agents.backends.opencode_go.OpenAI"):
            from agents.base_agent import BaseAgent
            agent = BaseAgent(model="opencode-go/kimi-k2.5")
    assert agent._opencode_stream is True


def test_base_agent_opencode_stream_false():
    """BaseAgent with opencode_stream=False stores it correctly."""
    with patch.dict("os.environ", {"OPENCODE_ZEN_API_KEY": "zen-key"}):
        with patch("agents.backends.opencode_go.OpenAI"):
            from agents.base_agent import BaseAgent
            agent = BaseAgent(model="opencode-go/kimi-k2.5", opencode_stream=False)
    assert agent._opencode_stream is False
