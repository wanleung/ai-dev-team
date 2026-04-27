"""Tests for AnthropicBackend."""
from __future__ import annotations
import os
from unittest.mock import MagicMock, patch
import pytest


def test_anthropic_backend_requires_key():
    from agents.backends.anthropic import AnthropicBackend
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(EnvironmentError, match="ANTHROPIC_API_KEY"):
            AnthropicBackend(model="claude-sonnet-4-5")


def test_anthropic_backend_supports_tools_false():
    from agents.backends.anthropic import AnthropicBackend
    with patch("agents.backends.anthropic.anthropic") as mock_ant:
        mock_ant.Anthropic.return_value = MagicMock()
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test"}):
            b = AnthropicBackend(model="claude-sonnet-4-5")
    assert b.supports_tools() is False


def test_anthropic_backend_call_raises_for_tools():
    from agents.backends.anthropic import AnthropicBackend
    with patch("agents.backends.anthropic.anthropic") as mock_ant:
        mock_ant.Anthropic.return_value = MagicMock()
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test"}):
            b = AnthropicBackend(model="claude-sonnet-4-5")
    with pytest.raises(NotImplementedError, match="anthropic"):
        b.call_with_tools([], MagicMock())


def test_anthropic_backend_call_extracts_system_from_messages():
    from agents.backends.anthropic import AnthropicBackend
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="Hello")]
    )
    with patch("agents.backends.anthropic.anthropic") as mock_ant:
        mock_ant.Anthropic.return_value = mock_client
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test"}):
            b = AnthropicBackend(model="claude-sonnet-4-5")

    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Hi"},
    ]
    result = b.call(messages)
    assert result == "Hello"

    _, kwargs = mock_client.messages.create.call_args
    assert kwargs["system"] == "You are helpful."
    assert kwargs["messages"] == [{"role": "user", "content": "Hi"}]


def test_anthropic_backend_call_no_system():
    from agents.backends.anthropic import AnthropicBackend
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="Reply")]
    )
    with patch("agents.backends.anthropic.anthropic") as mock_ant:
        mock_ant.Anthropic.return_value = mock_client
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test"}):
            b = AnthropicBackend(model="claude-sonnet-4-5")

    b.call([{"role": "user", "content": "Hi"}])
    _, kwargs = mock_client.messages.create.call_args
    assert "system" not in kwargs or kwargs.get("system") == ""
