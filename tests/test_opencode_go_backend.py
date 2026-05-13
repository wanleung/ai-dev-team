"""Tests for OpenCodeGoBackend."""
import os
from unittest.mock import MagicMock, patch
import pytest


def test_opencode_go_requires_api_key():
    """OpenCodeGoBackend raises if no API key is set."""
    from agents.backends.opencode_go import OpenCodeGoBackend
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(EnvironmentError, match="OPENCODE_GO_API_KEY"):
            OpenCodeGoBackend(model="opencode-go/gpt-4o")


def test_opencode_go_strips_prefix():
    """OpenCodeGoBackend strips the 'opencode-go/' prefix."""
    from agents.backends.opencode_go import OpenCodeGoBackend
    with patch("agents.backends.opencode_go.OpenAI"):
        with patch.dict(os.environ, {"OPENCODE_GO_API_KEY": "test_key"}):
            b = OpenCodeGoBackend(model="opencode-go/gpt-4o")
    assert b.model == "gpt-4o"


def test_opencode_go_minimax_uses_anthropic():
    """MiniMax models route to Anthropic client."""
    from agents.backends.opencode_go import OpenCodeGoBackend
    with patch("agents.backends.opencode_go.anthropic") as mock_anthropic:
        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client
        with patch.dict(os.environ, {"OPENCODE_GO_API_KEY": "test_key"}):
            b = OpenCodeGoBackend(model="opencode-go/minimax-m2.7")
    assert b._anthropic_client is mock_client
    assert b._oai_backend is None
    assert not b.supports_tools()


def test_opencode_go_non_minimax_uses_openai():
    """Non-MiniMax models route to OpenAI-compatible backend."""
    from agents.backends.opencode_go import OpenCodeGoBackend
    with patch("agents.backends.opencode_go.OpenAI"):
        with patch.dict(os.environ, {"OPENCODE_GO_API_KEY": "test_key"}):
            b = OpenCodeGoBackend(model="opencode-go/gpt-4o")
    assert b._oai_backend is not None
    assert b._anthropic_client is None
    assert b.supports_tools()


def test_opencode_go_call_minimax_anthropic_path():
    """MiniMax call() uses Anthropic Messages API and returns text content."""
    from agents.backends.opencode_go import OpenCodeGoBackend
    with patch("agents.backends.opencode_go.anthropic") as mock_anthropic:
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_content = MagicMock()
        mock_content.text = "Hello from MiniMax"
        mock_response.content = [mock_content]
        mock_response.stop_reason = "end_turn"
        mock_client.messages.create.return_value = mock_response
        mock_anthropic.Anthropic.return_value = mock_client
        
        with patch.dict(os.environ, {"OPENCODE_GO_API_KEY": "test_key"}):
            b = OpenCodeGoBackend(model="opencode-go/minimax-m2.7")
        
        result = b.call([{"role": "user", "content": "hi"}])
    
    assert result == "Hello from MiniMax"
    mock_client.messages.create.assert_called_once()


def test_opencode_go_call_minimax_empty_content_raises():
    """MiniMax call() raises RuntimeError if Anthropic returns empty content."""
    from agents.backends.opencode_go import OpenCodeGoBackend
    with patch("agents.backends.opencode_go.anthropic") as mock_anthropic:
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = []
        mock_response.stop_reason = "max_tokens"
        mock_client.messages.create.return_value = mock_response
        mock_anthropic.Anthropic.return_value = mock_client
        
        with patch.dict(os.environ, {"OPENCODE_GO_API_KEY": "test_key"}):
            b = OpenCodeGoBackend(model="opencode-go/minimax-m2.5")
        
        with pytest.raises(RuntimeError, match="Anthropic returned empty content"):
            b.call([{"role": "user", "content": "hi"}])


def test_opencode_go_call_non_minimax_delegates():
    """Non-MiniMax call() delegates to OpenAICompatibleBackend."""
    from agents.backends.opencode_go import OpenCodeGoBackend
    with patch("agents.backends.opencode_go.OpenAI"):
        with patch.dict(os.environ, {"OPENCODE_GO_API_KEY": "test_key"}):
            b = OpenCodeGoBackend(model="opencode-go/gpt-4o")
        
        # Mock the internal OpenAICompatibleBackend
        b._oai_backend.call = MagicMock(return_value="OpenAI response")
        result = b.call([{"role": "user", "content": "hi"}])
    
    assert result == "OpenAI response"
    b._oai_backend.call.assert_called_once()


def test_opencode_go_call_with_tools_minimax_not_supported():
    """MiniMax models raise NotImplementedError for call_with_tools."""
    from agents.backends.opencode_go import OpenCodeGoBackend
    with patch("agents.backends.opencode_go.anthropic") as mock_anthropic:
        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client
        
        with patch.dict(os.environ, {"OPENCODE_GO_API_KEY": "test_key"}):
            b = OpenCodeGoBackend(model="opencode-go/minimax-m2.7")
        
        with pytest.raises(NotImplementedError, match="not supported for opencode_go with MiniMax"):
            b.call_with_tools([{"role": "user", "content": "hi"}], tools=MagicMock())


def test_opencode_go_call_with_tools_non_minimax_delegates():
    """Non-MiniMax call_with_tools() delegates to OpenAICompatibleBackend."""
    from agents.backends.opencode_go import OpenCodeGoBackend
    with patch("agents.backends.opencode_go.OpenAI"):
        with patch.dict(os.environ, {"OPENCODE_GO_API_KEY": "test_key"}):
            b = OpenCodeGoBackend(model="opencode-go/gpt-4o")
        
        # Mock the internal OpenAICompatibleBackend
        mock_tools = MagicMock()
        b._oai_backend.call_with_tools = MagicMock(return_value="Tool response")
        result = b.call_with_tools([{"role": "user", "content": "hi"}], tools=mock_tools)
    
    assert result == "Tool response"
    b._oai_backend.call_with_tools.assert_called_once()


def test_opencode_go_minimax_system_message_handling():
    """MiniMax call() extracts system message correctly."""
    from agents.backends.opencode_go import OpenCodeGoBackend
    with patch("agents.backends.opencode_go.anthropic") as mock_anthropic:
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_content = MagicMock()
        mock_content.text = "Response"
        mock_response.content = [mock_content]
        mock_response.stop_reason = "end_turn"
        mock_client.messages.create.return_value = mock_response
        mock_anthropic.Anthropic.return_value = mock_client
        
        with patch.dict(os.environ, {"OPENCODE_GO_API_KEY": "test_key"}):
            b = OpenCodeGoBackend(model="opencode-go/minimax-m2.7")
        
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "hi"}
        ]
        b.call(messages)
        
        # Verify system message was passed separately
        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["system"] == "You are helpful"
        assert len(call_kwargs["messages"]) == 1
        assert call_kwargs["messages"][0]["role"] == "user"


def test_opencode_go_api_key_fallback_order():
    """OpenCodeGoBackend tries multiple env vars in order."""
    from agents.backends.opencode_go import OpenCodeGoBackend
    
    # Test OPENCODE_ZEN_API_KEY fallback
    with patch("agents.backends.opencode_go.OpenAI"):
        with patch.dict(os.environ, {"OPENCODE_ZEN_API_KEY": "zen_key"}, clear=True):
            b = OpenCodeGoBackend(model="opencode-go/gpt-4o")
    assert b.model == "gpt-4o"
    
    # Test OPENCODE_API_KEY fallback
    with patch("agents.backends.opencode_go.OpenAI"):
        with patch.dict(os.environ, {"OPENCODE_API_KEY": "opencode_key"}, clear=True):
            b = OpenCodeGoBackend(model="opencode-go/gpt-4o")
    assert b.model == "gpt-4o"


def test_opencode_go_base_url_configuration():
    """OpenCodeGoBackend respects base_url parameter and environment variable."""
    from agents.backends.opencode_go import OpenCodeGoBackend
    
    with patch("agents.backends.opencode_go.OpenAI") as mock_openai:
        with patch.dict(os.environ, {"OPENCODE_GO_API_KEY": "test_key"}):
            b = OpenCodeGoBackend(model="opencode-go/gpt-4o", base_url="https://custom.url/v1")
    
    # Verify OpenAI client was created with custom base_url
    mock_openai.assert_called_once()
    call_kwargs = mock_openai.call_args[1]
    assert call_kwargs["base_url"] == "https://custom.url/v1"
