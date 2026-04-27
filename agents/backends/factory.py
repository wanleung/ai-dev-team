"""Factory function: create_backend(cfg) → LLMBackend | FallbackLLMBackend."""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.backends.base import LLMBackend


def _make_single_backend(cfg: dict, github_token: str | None = None) -> "LLMBackend":
    """Instantiate one backend from a config dict."""
    model: str = cfg["model"]
    kwargs = {k: v for k, v in cfg.items() if k not in ("model", "fallbacks")}

    if model.startswith("ollama/"):
        from agents.backends.ollama import OllamaBackend
        return OllamaBackend(model=model, **kwargs)

    if model.startswith("copilot/"):
        from agents.backends.copilot import CopilotBackend
        return CopilotBackend(model=model, **kwargs)

    if model.startswith("nvidia-nim/"):
        from agents.backends.nvidia_nim import NvidiaNimBackend
        return NvidiaNimBackend(model=model, **kwargs)

    if model.startswith("opencode/"):
        from agents.backends.opencode import OpenCodeBackend
        return OpenCodeBackend(model=model, **kwargs)

    if model.startswith("opencode-zen/"):
        from agents.backends.opencode_zen import OpenCodeZenBackend
        return OpenCodeZenBackend(model=model, **kwargs)

    if model.startswith("opencode-go/"):
        from agents.backends.opencode_go import OpenCodeGoBackend
        return OpenCodeGoBackend(model=model, **kwargs)

    if model.startswith("claude-"):
        from agents.backends.anthropic import AnthropicBackend
        return AnthropicBackend(model=model, **kwargs)

    # Default: GitHub Models (OpenAI-compatible)
    if "/" not in model or model.startswith("gpt-") or model.startswith("o"):
        from agents.backends.github_models import GitHubModelsBackend
        return GitHubModelsBackend(model=model, github_token=github_token, **kwargs)

    raise ValueError(
        f"Cannot determine backend for model {model!r}. "
        "Prefix with 'ollama/', 'copilot/', 'nvidia-nim/', 'opencode/', "
        "'opencode-zen/', 'opencode-go/', or use 'claude-*' for Anthropic."
    )


def create_backend(
    cfg: dict,
    github_token: str | None = None,
) -> "LLMBackend":
    """Create an LLMBackend (or FallbackLLMBackend) from a config dict.

    cfg keys:
      model     (required) — model identifier with optional prefix
      fallbacks (optional) — list of fallback cfg dicts
      any other key is forwarded to the backend constructor
    """
    primary = _make_single_backend(cfg, github_token=github_token)

    fallback_cfgs: list[dict] = cfg.get("fallbacks") or []
    if not fallback_cfgs:
        return primary

    from agents.backends.fallback import FallbackLLMBackend
    backends = [primary] + [
        _make_single_backend(fb_cfg, github_token=github_token)
        for fb_cfg in fallback_cfgs
    ]
    return FallbackLLMBackend(backends)
