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
        with pytest.raises(EnvironmentError, match="OPENCODE_GO_API_KEY"):
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


# ── Additional tests ──────────────────────────────────────────────────────────

def test_opencode_zen_claude_call_with_tools_raises():
    """call_with_tools() on a Claude model must raise NotImplementedError."""
    from agents.backends.opencode_zen import OpenCodeZenBackend
    mock_ant_client = MagicMock()
    with patch("agents.backends.opencode_zen.anthropic") as mock_ant:
        mock_ant.Anthropic.return_value = mock_ant_client
        with patch.dict(os.environ, {"OPENCODE_ZEN_API_KEY": "key_test"}):
            b = OpenCodeZenBackend(model="opencode-zen/claude-opus-4-5")
    with pytest.raises(NotImplementedError):
        b.call_with_tools([{"role": "user", "content": "hi"}], MagicMock())


def test_opencode_zen_claude_call_no_system_message():
    """call() with no system message must not set the 'system' key in Anthropic kwargs."""
    from agents.backends.opencode_zen import OpenCodeZenBackend
    mock_ant_client = MagicMock()
    mock_ant_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="OK")]
    )
    with patch("agents.backends.opencode_zen.anthropic") as mock_ant:
        mock_ant.Anthropic.return_value = mock_ant_client
        with patch.dict(os.environ, {"OPENCODE_ZEN_API_KEY": "key_test"}):
            b = OpenCodeZenBackend(model="opencode-zen/claude-3-5-sonnet-20241022")
    result = b.call([{"role": "user", "content": "hello"}])
    assert result == "OK"
    _, kwargs = mock_ant_client.messages.create.call_args
    # 'system' must be absent or empty when no system message was supplied
    assert kwargs.get("system", "") == ""


# ── OpenCodeGoBackend streaming tests ──────────────────────────────────────────

def test_opencode_go_default_stream_true():
    """Construct OpenCodeGoBackend with no stream argument and verify default is True."""
    from agents.backends.opencode_go import OpenCodeGoBackend
    with patch("agents.backends.opencode_go.OpenAI") as mock_oai:
        mock_oai.return_value = MagicMock()
        with patch.dict(os.environ, {"OPENCODE_ZEN_API_KEY": "key_test"}):
            backend = OpenCodeGoBackend(model="opencode-go/kimi-k2.5")
    # Verify the underlying OpenAICompatibleBackend has _stream=True
    assert backend._oai_backend._stream is True


def test_opencode_go_stream_false_disables_streaming():
    """Construct OpenCodeGoBackend with stream=False and verify streaming is disabled."""
    from agents.backends.opencode_go import OpenCodeGoBackend
    with patch("agents.backends.opencode_go.OpenAI") as mock_oai:
        mock_oai.return_value = MagicMock()
        with patch.dict(os.environ, {"OPENCODE_ZEN_API_KEY": "key_test"}):
            backend = OpenCodeGoBackend(model="opencode-go/kimi-k2.5", stream=False)
    # Verify the underlying OpenAICompatibleBackend has _stream=False
    assert backend._oai_backend._stream is False


def test_opencode_go_call_streams_when_enabled():
    """Call OpenCodeGoBackend with stream=True and verify it streams the response."""
    from agents.backends.opencode_go import OpenCodeGoBackend
    
    # Create mock chunks for streaming
    mock_chunk_1 = MagicMock()
    mock_chunk_1.choices[0].delta.content = "Hello "
    mock_chunk_2 = MagicMock()
    mock_chunk_2.choices[0].delta.content = "World"
    mock_chunk_3 = MagicMock()
    mock_chunk_3.choices[0].delta.content = None
    
    mock_oai_client = MagicMock()
    mock_oai_client.chat.completions.create.return_value = iter([mock_chunk_1, mock_chunk_2, mock_chunk_3])
    
    with patch("agents.backends.opencode_go.OpenAI") as mock_oai:
        mock_oai.return_value = mock_oai_client
        with patch.dict(os.environ, {"OPENCODE_ZEN_API_KEY": "key_test"}):
            backend = OpenCodeGoBackend(model="opencode-go/kimi-k2.5", stream=True)
    
    # Call with streaming enabled
    result = backend.call([{"role": "user", "content": "hello"}])
    
    # Verify the result is the assembled string
    assert result == "Hello World"
    
    # Verify create was called with stream=True
    _, kwargs = mock_oai_client.chat.completions.create.call_args
    assert kwargs["stream"] is True
