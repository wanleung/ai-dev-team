"""Unit tests for OpenAI direct API backend."""
import os
from unittest.mock import MagicMock, patch

import pytest


# ── OpenAIApiBackend unit tests ───────────────────────────────────────────────

def test_strips_openai_prefix():
    """OpenAIApiBackend strips the 'openai/' prefix before passing model to client."""
    with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
        from agents.backends.openai_api import OpenAIApiBackend
        backend = OpenAIApiBackend(model="openai/gpt-4o")
        assert backend.model == "gpt-4o"


def test_requires_api_key(monkeypatch):
    """OpenAIApiBackend raises EnvironmentError when OPENAI_API_KEY is not set."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from agents.backends.openai_api import OpenAIApiBackend
    with pytest.raises(EnvironmentError, match="OPENAI_API_KEY"):
        OpenAIApiBackend(model="openai/gpt-4o")


def test_supports_tools():
    """OpenAIApiBackend.supports_tools() returns True."""
    with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
        from agents.backends.openai_api import OpenAIApiBackend
        backend = OpenAIApiBackend(model="openai/gpt-4o")
        assert backend.supports_tools() is True


def test_factory_routes_openai_prefix():
    """create_backend routes 'openai/...' models to OpenAIApiBackend."""
    with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
        from agents.backends.factory import create_backend
        from agents.backends.openai_api import OpenAIApiBackend
        backend = create_backend({"model": "openai/gpt-4o"})
        assert isinstance(backend, OpenAIApiBackend)
