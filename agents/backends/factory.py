"""Factory function: create_backend(cfg) → LLMBackend | FallbackLLMBackend."""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.backends.base import LLMBackend


def _make_single_backend(cfg: dict, github_token: str | None = None) -> "LLMBackend":
    """Instantiate one backend from a config dict."""
    model: str = cfg["model"]
    kwargs = {k: v for k, v in cfg.items() if k not in ("model", "fallbacks")}

    # Keys that are specific to a single backend type and must not leak to others
    _OLLAMA_ONLY = {"ollama_url"}
    _DASHSCOPE_ONLY = {
        "dashscope_api_key", "dashscope_url",
        "think", "preserve_thinking",
    }
    _ALL_PROVIDER_SPECIFIC = _OLLAMA_ONLY | _DASHSCOPE_ONLY

    if model.startswith("ollama/"):
        from agents.backends.ollama import OllamaBackend
        return OllamaBackend(model=model, **kwargs)

    if model.startswith("copilot/"):
        from agents.backends.copilot import CopilotBackend
        ck = {k: v for k, v in kwargs.items() if k not in _ALL_PROVIDER_SPECIFIC}
        return CopilotBackend(model=model, **ck)

    if model.startswith("nvidia-nim/"):
        from agents.backends.nvidia_nim import NvidiaNimBackend
        ck = {k: v for k, v in kwargs.items() if k not in _ALL_PROVIDER_SPECIFIC}
        return NvidiaNimBackend(model=model, **ck)

    if model.startswith("dashscope/"):
        from agents.backends.dashscope import DashScopeBackend
        ck = {k: v for k, v in kwargs.items() if k not in _OLLAMA_ONLY}
        return DashScopeBackend(model=model, **ck)

    if model.startswith("opencode/"):
        from agents.backends.opencode import OpenCodeBackend
        ck = {k: v for k, v in kwargs.items() if k not in _ALL_PROVIDER_SPECIFIC}
        return OpenCodeBackend(model=model, **ck)

    if model.startswith("opencode-zen/"):
        from agents.backends.opencode_zen import OpenCodeZenBackend
        ck = {k: v for k, v in kwargs.items() if k not in _ALL_PROVIDER_SPECIFIC}
        return OpenCodeZenBackend(model=model, **ck)

    if model.startswith("opencode-go/"):
        from agents.backends.opencode_go import OpenCodeGoBackend
        ck = {k: v for k, v in kwargs.items() if k not in _ALL_PROVIDER_SPECIFIC}
        return OpenCodeGoBackend(model=model, **ck)

    if model.startswith("claude-"):
        from agents.backends.anthropic import AnthropicBackend
        ck = {k: v for k, v in kwargs.items() if k not in _ALL_PROVIDER_SPECIFIC}
        return AnthropicBackend(model=model, **ck)

    if model.startswith("grok/"):
        from agents.backends.grok import GrokBackend
        ck = {k: v for k, v in kwargs.items() if k not in _ALL_PROVIDER_SPECIFIC}
        return GrokBackend(model=model, **ck)

    if model.startswith("grok-oauth/"):
        from agents.backends.grok_oauth import GrokOAuthBackend
        ck = {k: v for k, v in kwargs.items() if k not in _ALL_PROVIDER_SPECIFIC}
        return GrokOAuthBackend(model=model, **ck)

    if model.startswith("openai/"):
        from agents.backends.openai_api import OpenAIApiBackend
        ck = {k: v for k, v in kwargs.items() if k not in _ALL_PROVIDER_SPECIFIC}
        return OpenAIApiBackend(model=model, **ck)

    # Default: bare model names (no prefix slash) go to GitHub Models
    if "/" not in model:
        from agents.backends.github_models import GitHubModelsBackend
        ck = {k: v for k, v in kwargs.items() if k not in _ALL_PROVIDER_SPECIFIC}
        return GitHubModelsBackend(model=model, github_token=github_token, **ck)

    raise ValueError(
        f"Cannot determine backend for model {model!r}. "
        "Prefix with 'ollama/', 'copilot/', 'nvidia-nim/', 'dashscope/', 'opencode/', "
        "'opencode-zen/', 'opencode-go/', 'grok/', 'grok-oauth/', 'openai/', 'codex/', "
        "or use 'claude-*' for Anthropic."
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
