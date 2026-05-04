"""GitHub Models API backend (OpenAI-compatible, uses GITHUB_TOKEN)."""
from __future__ import annotations

import os
from typing import Optional

from openai import OpenAI

from agents.backends.base import OpenAICompatibleBackend, _DEFAULT_MAX_RETRIES, _DEFAULT_BASE_DELAY


class GitHubModelsBackend(OpenAICompatibleBackend):
    """GitHub Models API via OpenAI SDK.

    Model names are passed as-is (no prefix to strip).
    Auth: GITHUB_TOKEN env var or github_token constructor arg.
    """

    def __init__(
        self,
        model: str,
        github_token: Optional[str] = None,
        inter_call_delay: int = 0,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        retry_delay: float = _DEFAULT_BASE_DELAY,
        stream: bool = True,
    ) -> None:
        token = github_token or os.environ.get("GITHUB_TOKEN")
        if not token:
            raise EnvironmentError(
                "GITHUB_TOKEN environment variable is required for GitHub Models. "
                "Create a token at https://github.com/settings/personal-access-tokens/new "
                "with 'Copilot Requests', 'Contents', 'Issues', and 'Pull requests' permissions."
            )
        client = OpenAI(base_url="https://models.github.ai/inference", api_key=token)
        super().__init__(
            model=model,
            client=client,
            inter_call_delay=inter_call_delay,
            max_retries=max_retries,
            retry_delay=retry_delay,
            stream=stream,
        )
