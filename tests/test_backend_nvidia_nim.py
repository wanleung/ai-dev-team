"""Tests for NvidiaNimBackend."""
import os
from unittest.mock import MagicMock, patch
import pytest


def test_nvidia_nim_requires_api_key():
    from agents.backends.nvidia_nim import NvidiaNimBackend
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(EnvironmentError, match="NVIDIA_API_KEY"):
            NvidiaNimBackend(model="nvidia-nim/nvidia/llama-3.1-8b")


def test_nvidia_nim_strips_prefix():
    from agents.backends.nvidia_nim import NvidiaNimBackend
    with patch("agents.backends.nvidia_nim.OpenAI"):
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "nvapi_test"}):
            b = NvidiaNimBackend(model="nvidia-nim/nvidia/glm-4.1-9b-ea")
    assert b.model == "nvidia/glm-4.1-9b-ea"


def test_nvidia_nim_call():
    from agents.backends.nvidia_nim import NvidiaNimBackend
    with patch("agents.backends.nvidia_nim.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="ok", tool_calls=None))]
        )
        mock_cls.return_value = mock_client
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "nvapi_test"}):
            b = NvidiaNimBackend(model="nvidia-nim/nvidia/llama-3.1-8b")
    assert b.call([{"role": "user", "content": "hi"}]) == "ok"
