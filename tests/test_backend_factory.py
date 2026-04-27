"""Tests for create_backend factory."""
import os
from unittest.mock import MagicMock, patch
import pytest


def _patch_all_clients():
    """Context manager to stub all network clients."""
    from contextlib import ExitStack
    stack = ExitStack()
    stack.enter_context(patch("agents.backends.github_models.OpenAI", return_value=MagicMock()))
    stack.enter_context(patch("agents.backends.ollama.OpenAI", return_value=MagicMock()))
    stack.enter_context(patch("agents.backends.nvidia_nim.OpenAI", return_value=MagicMock()))
    stack.enter_context(patch("agents.backends.opencode_zen.OpenAI", return_value=MagicMock()))
    stack.enter_context(patch("agents.backends.opencode_go.OpenAI", return_value=MagicMock()))
    stack.enter_context(patch("agents.backends.anthropic.anthropic"))
    return stack


def test_factory_github_models():
    from agents.backends.factory import create_backend
    from agents.backends.github_models import GitHubModelsBackend
    with patch("agents.backends.github_models.OpenAI", return_value=MagicMock()):
        with patch.dict(os.environ, {"GITHUB_TOKEN": "gh_test"}):
            b = create_backend({"model": "gpt-4.1"})
    assert isinstance(b, GitHubModelsBackend)
    assert b.model == "gpt-4.1"


def test_factory_ollama():
    from agents.backends.factory import create_backend
    from agents.backends.ollama import OllamaBackend
    with patch("agents.backends.ollama.OpenAI", return_value=MagicMock()):
        b = create_backend({"model": "ollama/llama3.2"})
    assert isinstance(b, OllamaBackend)
    assert b.model == "llama3.2"


def test_factory_copilot():
    from agents.backends.factory import create_backend
    from agents.backends.copilot import CopilotBackend
    mock_token_data = b'{"token": "copilot_test", "expires_at": "2099-01-01T00:00:00Z"}'
    with patch("agents.backends.copilot.urllib.request.urlopen") as mock_url:
        mock_url.return_value.__enter__ = lambda s: s
        mock_url.return_value.__exit__ = MagicMock(return_value=False)
        mock_url.return_value.read.return_value = mock_token_data
        with patch.dict(os.environ, {"COPILOT_OAUTH_TOKEN": "oauth_test"}):
            with patch("agents.backends.copilot.OpenAI", return_value=MagicMock()):
                b = create_backend({"model": "copilot/gpt-4.1"})
    assert isinstance(b, CopilotBackend)


def test_factory_nvidia_nim():
    from agents.backends.factory import create_backend
    from agents.backends.nvidia_nim import NvidiaNimBackend
    with patch("agents.backends.nvidia_nim.OpenAI", return_value=MagicMock()):
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "nvd_test"}):
            b = create_backend({"model": "nvidia-nim/meta/llama-3.1-8b-instruct"})
    assert isinstance(b, NvidiaNimBackend)
    assert b.model == "meta/llama-3.1-8b-instruct"


def test_factory_opencode_zen():
    from agents.backends.factory import create_backend
    from agents.backends.opencode_zen import OpenCodeZenBackend
    with patch("agents.backends.opencode_zen.OpenAI", return_value=MagicMock()):
        with patch.dict(os.environ, {"OPENCODE_ZEN_API_KEY": "zen_test"}):
            b = create_backend({"model": "opencode-zen/gpt-4.1"})
    assert isinstance(b, OpenCodeZenBackend)


def test_factory_opencode_go():
    from agents.backends.factory import create_backend
    from agents.backends.opencode_go import OpenCodeGoBackend
    with patch("agents.backends.opencode_go.OpenAI", return_value=MagicMock()):
        with patch.dict(os.environ, {"OPENCODE_ZEN_API_KEY": "zen_test"}):
            b = create_backend({"model": "opencode-go/kimi-k2.5"})
    assert isinstance(b, OpenCodeGoBackend)


def test_factory_anthropic():
    from agents.backends.factory import create_backend
    from agents.backends.anthropic import AnthropicBackend
    with patch("agents.backends.anthropic.anthropic") as mock_ant:
        mock_ant.Anthropic.return_value = MagicMock()
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "ant_test"}):
            b = create_backend({"model": "claude-sonnet-4-5"})
    assert isinstance(b, AnthropicBackend)


def test_factory_opencode_subprocess():
    from agents.backends.factory import create_backend
    from agents.backends.opencode import OpenCodeBackend
    b = create_backend({"model": "opencode/my-model"})
    assert isinstance(b, OpenCodeBackend)
    assert b.model == "my-model"


def test_factory_fallback_wraps():
    from agents.backends.factory import create_backend
    from agents.backends.fallback import FallbackLLMBackend
    cfg = {
        "model": "ollama/llama3.2",
        "fallbacks": [{"model": "ollama/mistral"}],
    }
    with patch("agents.backends.ollama.OpenAI", return_value=MagicMock()):
        b = create_backend(cfg)
    assert isinstance(b, FallbackLLMBackend)
    assert b.model == "llama3.2"


def test_factory_unknown_model_raises():
    from agents.backends.factory import create_backend
    with pytest.raises(ValueError, match="Cannot determine backend"):
        create_backend({"model": "unknown-prefix/some-model"})
