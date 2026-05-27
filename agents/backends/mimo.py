"""Xiaomi MiMo API backend — OpenAI-compatible.

MiMo uses the standard OpenAI chat completions protocol with a Xiaomi-specific
base URL (https://api.xiaomimimo.com/v1).

Config keys (in llm: section of config.yaml / config.local.yaml):
  mimo_api_key  — API key (falls back to MIMO_API_KEY env var)
  mimo_url      — optional base URL override (default: https://api.xiaomimimo.com/v1)
  mimo_think    — True/False to force thinking on/off; omit to use model default
                  (mimo-v2.5-pro/mimo-v2.5/mimo-v2-pro/mimo-v2-omni: default ON)
                  (mimo-v2-flash: default OFF)

Model prefix: ``mimo/``

Example config.local.yaml snippet::

    llm:
      model: "mimo/mimo-v2.5-pro"
      mimo_api_key: "your-key-here"
      mimo_think: false   # disable chain-of-thought

Docs: https://platform.xiaomimimo.com/docs/en-US/quick-start/first-api-call
"""
from __future__ import annotations

import os

from openai import OpenAI
from openai import Timeout as OpenAITimeout

from agents.backends.base import (
    OpenAICompatibleBackend,
    _DEFAULT_BASE_DELAY,
    _DEFAULT_MAX_RETRIES,
)

_MIMO_BASE_URL = "https://token-plan-sgp.xiaomimimo.com/v1"


class MiMoBackend(OpenAICompatibleBackend):
    """Xiaomi MiMo API backend (OpenAI-compatible).

    Model prefix ``mimo/`` is stripped before sending to the API.
    Auth: MIMO_API_KEY env var or mimo_api_key constructor arg.

    Think mode (chain-of-thought) is controlled via the ``think`` parameter:
    - ``None`` (default) — let the model decide (pro/omni models default ON,
      flash model defaults OFF)
    - ``True``  — force ``thinking: {type: enabled}``
    - ``False`` — force ``thinking: {type: disabled}``
    """

    def __init__(
        self,
        model: str,
        mimo_api_key: str | None = None,
        mimo_url: str | None = None,
        think: bool | None = None,
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
        # MiMo thinking models can take a while; 5 min connect + 10 min read.
        client = OpenAI(
            base_url=base_url,
            api_key=key,
            timeout=OpenAITimeout(connect=30.0, read=600.0, write=30.0, pool=10.0),
        )
        self._think = think
        super().__init__(
            model=model.removeprefix("mimo/"),
            client=client,
            inter_call_delay=inter_call_delay,
            max_retries=max_retries,
            retry_delay=retry_delay,
            stream=stream,
        )

    def _extra_body(self) -> dict:
        """Inject MiMo thinking mode into the request body.

        Returns ``{"extra_body": {"thinking": {"type": "enabled"|"disabled"}}}``
        when ``think`` was explicitly set; empty dict otherwise (model default).
        """
        if self._think is None:
            return {}
        return {"extra_body": {"thinking": {"type": "enabled" if self._think else "disabled"}}}
