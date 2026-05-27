"""Xiaomi MiMo API backend — OpenAI-compatible.

MiMo uses the standard OpenAI chat completions protocol with a Xiaomi-specific
base URL (https://api.xiaomimimo.com/v1).

Config keys (in llm: section of config.yaml / config.local.yaml):
  mimo_api_key  — API key (falls back to MIMO_API_KEY env var)
  mimo_url      — optional base URL override (default: https://api.xiaomimimo.com/v1)

Model prefix: ``mimo/``

Example config.local.yaml snippet::

    llm:
      model: "mimo/mimo-v2.5-pro"
      mimo_api_key: "your-key-here"

Docs: https://platform.xiaomimimo.com/docs/en-US/quick-start/first-api-call
"""
from __future__ import annotations

import os

from openai import OpenAI

from agents.backends.base import (
    OpenAICompatibleBackend,
    _DEFAULT_BASE_DELAY,
    _DEFAULT_MAX_RETRIES,
)

_MIMO_BASE_URL = "https://api.xiaomimimo.com/v1"


class MiMoBackend(OpenAICompatibleBackend):
    """Xiaomi MiMo API backend (OpenAI-compatible).

    Model prefix ``mimo/`` is stripped before sending to the API.
    Auth: MIMO_API_KEY env var or mimo_api_key constructor arg.
    """

    def __init__(
        self,
        model: str,
        mimo_api_key: str | None = None,
        mimo_url: str | None = None,
        inter_call_delay: int = 0,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        retry_delay: float = _DEFAULT_BASE_DELAY,
        stream: bool = True,
    ) -> None:
        key = mimo_api_key or os.environ.get("MIMO_API_KEY")
        if not key:
            raise EnvironmentError(
                "MIMO_API_KEY environment variable is required for Xiaomi MiMo. "
                "Get your key at https://platform.xiaomimimo.com/#/console/api-keys"
            )
        base_url = (mimo_url or _MIMO_BASE_URL).rstrip("/")
        client = OpenAI(base_url=base_url, api_key=key)
        super().__init__(
            model=model.removeprefix("mimo/"),
            client=client,
            inter_call_delay=inter_call_delay,
            max_retries=max_retries,
            retry_delay=retry_delay,
            stream=stream,
        )
