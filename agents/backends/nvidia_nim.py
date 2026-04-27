"""NVIDIA NIM API backend — OpenAI-compatible."""
from __future__ import annotations
import os
from openai import OpenAI
from agents.backends.base import OpenAICompatibleBackend, _DEFAULT_MAX_RETRIES, _DEFAULT_BASE_DELAY


class NvidiaNimBackend(OpenAICompatibleBackend):
    """NVIDIA NIM API (OpenAI-compatible).

    Model prefix "nvidia-nim/" is stripped.
    Auth: NVIDIA_API_KEY env var or nvidia_nim_api_key constructor arg.
    """

    def __init__(
        self,
        model: str,
        nvidia_nim_api_key: str | None = None,
        nvidia_nim_base_url: str | None = None,
        inter_call_delay: int = 0,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        retry_delay: float = _DEFAULT_BASE_DELAY,
    ) -> None:
        key = nvidia_nim_api_key or os.environ.get("NVIDIA_API_KEY")
        if not key:
            raise EnvironmentError(
                "NVIDIA_API_KEY environment variable is required for NVIDIA NIM. "
                "Get your key at https://build.nvidia.com/"
            )
        base_url = (
            nvidia_nim_base_url
            or os.environ.get("NVIDIA_NIM_BASE_URL")
            or "https://integrate.api.nvidia.com/v1"
        ).rstrip("/")
        client = OpenAI(base_url=base_url, api_key=key)
        super().__init__(
            model=model.removeprefix("nvidia-nim/"),
            client=client,
            inter_call_delay=inter_call_delay,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )
