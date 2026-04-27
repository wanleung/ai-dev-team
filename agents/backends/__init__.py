"""LLM backend implementations for ai-software-house."""


def create_backend(cfg, github_token=None):
    """Lazy import wrapper — factory.py is created in Task 9."""
    from agents.backends.factory import create_backend as _create
    return _create(cfg, github_token=github_token)


__all__ = ["create_backend"]
