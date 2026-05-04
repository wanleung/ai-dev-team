"""Tests for GitHubModelsBackend."""
from __future__ import annotations
import os
from unittest.mock import MagicMock, patch
import pytest


def _mock_response(content: str):
    return MagicMock(
        choices=[MagicMock(message=MagicMock(content=content, tool_calls=None))]
    )


def test_github_models_backend_requires_token():
    from agents.backends.github_models import GitHubModelsBackend
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(EnvironmentError, match="GITHUB_TOKEN"):
            GitHubModelsBackend(model="gpt-4.1", github_token=None)


def test_github_models_backend_uses_env_token():
    from agents.backends.github_models import GitHubModelsBackend
    with patch("agents.backends.github_models.OpenAI") as mock_cls:
        mock_cls.return_value = MagicMock()
        with patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"}):
            backend = GitHubModelsBackend(model="gpt-4.1")
    assert backend.model == "gpt-4.1"


def test_github_models_backend_call():
    from agents.backends.github_models import GitHubModelsBackend
    with patch("agents.backends.github_models.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_response("hello")
        mock_cls.return_value = mock_client
        with patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"}):
            backend = GitHubModelsBackend(model="gpt-4.1", stream=False)
    result = backend.call([{"role": "user", "content": "hi"}])
    assert result == "hello"


def test_github_models_backend_supports_tools():
    from agents.backends.github_models import GitHubModelsBackend
    with patch("agents.backends.github_models.OpenAI"):
        with patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"}):
            backend = GitHubModelsBackend(model="gpt-4.1")
    assert backend.supports_tools() is True


def test_github_models_backend_stream_default_true():
    """stream=True is the default to prevent Cloudflare 524 timeouts."""
    from agents.backends.github_models import GitHubModelsBackend
    with patch("agents.backends.github_models.OpenAI") as mock_cls:
        mock_cls.return_value = MagicMock()
        with patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"}):
            backend = GitHubModelsBackend(model="openai/gpt-4.1")
    assert backend._stream is True


def test_github_models_backend_stream_false_override():
    """stream=False can be set explicitly (e.g. for non-CF environments)."""
    from agents.backends.github_models import GitHubModelsBackend
    with patch("agents.backends.github_models.OpenAI") as mock_cls:
        mock_cls.return_value = MagicMock()
        with patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"}):
            backend = GitHubModelsBackend(model="openai/gpt-4.1", stream=False)
    assert backend._stream is False
