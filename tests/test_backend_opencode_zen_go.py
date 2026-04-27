"""Tests for OpenCodeZenBackend and OpenCodeGoBackend."""
import os
from unittest.mock import MagicMock, patch
import pytest


# ── OpenCodeZenBackend ────────────────────────────────────────────────────────

def test_opencode_zen_requires_key():
    from agents.backends.opencode_zen import OpenCodeZenBackend
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(EnvironmentError, match="OPENCODE_ZEN_API_KEY"):
            OpenCodeZenBackend(model="opencode-zen/gpt-4.1")


def test_opencode_zen_non_claude_uses_openai_client():
    from agents.backends.opencode_zen import OpenCodeZenBackend
    with patch("agents.backends.opencode_zen.OpenAI") as mock_oai:
        mock_oai.return_value = MagicMock()
        with patch.dict(os.environ, {"OPENCODE_ZEN_API_KEY": "key_test"}):
            b = OpenCodeZenBackend(model="opencode-zen/gpt-4.1")
    assert b.model == "gpt-4.1"
    assert b.supports_tools() is True


def test_opencode_zen_claude_uses_anthropic_client():
    from agents.backends.opencode_zen import OpenCodeZenBackend
    with patch("agents.backends.opencode_zen.anthropic") as mock_ant:
        mock_ant.Anthropic.return_value = MagicMock()
        with patch.dict(os.environ, {"OPENCODE_ZEN_API_KEY": "key_test"}):
            b = OpenCodeZenBackend(model="opencode-zen/claude-sonnet-4-5")
    assert b.supports_tools() is False


def test_opencode_zen_claude_call_extracts_system():
    from agents.backends.opencode_zen import OpenCodeZenBackend
    mock_ant_client = MagicMock()
    mock_ant_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="Reply")]
    )
    with patch("agents.backends.opencode_zen.anthropic") as mock_ant:
        mock_ant.Anthropic.return_value = mock_ant_client
        with patch.dict(os.environ, {"OPENCODE_ZEN_API_KEY": "key_test"}):
            b = OpenCodeZenBackend(model="opencode-zen/claude-sonnet-4-5")
    result = b.call([{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}])
    assert result == "Reply"
    _, kwargs = mock_ant_client.messages.create.call_args
    assert kwargs["system"] == "sys"


# ── OpenCodeGoBackend ─────────────────────────────────────────────────────────

def test_opencode_go_requires_key():
    from agents.backends.opencode_go import OpenCodeGoBackend
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(EnvironmentError, match="OPENCODE_ZEN_API_KEY"):
            OpenCodeGoBackend(model="opencode-go/kimi-k2.5")


def test_opencode_go_non_minimax_uses_openai_client():
    from agents.backends.opencode_go import OpenCodeGoBackend
    with patch("agents.backends.opencode_go.OpenAI") as mock_oai:
        mock_oai.return_value = MagicMock()
        with patch.dict(os.environ, {"OPENCODE_ZEN_API_KEY": "key_test"}):
            b = OpenCodeGoBackend(model="opencode-go/kimi-k2.5")
    assert b.model == "kimi-k2.5"
    assert b.supports_tools() is True


def test_opencode_go_minimax_uses_anthropic_client():
    from agents.backends.opencode_go import OpenCodeGoBackend
    with patch("agents.backends.opencode_go.anthropic") as mock_ant:
        mock_ant.Anthropic.return_value = MagicMock()
        with patch.dict(os.environ, {"OPENCODE_ZEN_API_KEY": "key_test"}):
            b = OpenCodeGoBackend(model="opencode-go/minimax-m2.7")
    assert b.supports_tools() is False
