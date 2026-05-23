"""OpenAI direct API backend (api.openai.com)."""
from __future__ import annotations

import os

from openai import OpenAI

from agents.backends.base import OpenAICompatibleBackend, _DEFAULT_MAX_RETRIES, _DEFAULT_BASE_DELAY


class OpenAIApiBackend(OpenAICompatibleBackend):
    """OpenAI API backend via openai SDK.

    Auth: OPENAI_API_KEY env var.
    Model prefix 'openai/' is stripped; remainder is the model name
    passed directly to the OpenAI API (e.g. 'gpt-4o', 'gpt-4.1', 'o3').
    Supports tool calling.
    """

    def __init__(
        self,
        model: str,
        openai_api_key: str | None = None,
        inter_call_delay: int = 0,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        retry_delay: float = _DEFAULT_BASE_DELAY,
        stream: bool = True,
    ) -> None:
        key = openai_api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise EnvironmentError(
                "OPENAI_API_KEY environment variable is required for OpenAI API. "
                "Get your key at https://platform.openai.com/api-keys"
            )
        client = OpenAI(api_key=key)
        super().__init__(
            model=model.removeprefix("openai/"),
            client=client,
            inter_call_delay=inter_call_delay,
            max_retries=max_retries,
            retry_delay=retry_delay,
            stream=stream,
        )
