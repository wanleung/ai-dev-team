"""Shared utility functions for ai-software-house."""
from __future__ import annotations


def sanitise(text: str, *secrets: str | None) -> str:
    """Replace every occurrence of each secret in text with '***'.

    Safe to call with empty or None secrets — they are silently skipped.

    Example:
        sanitise("clone https://tok@host/repo failed", "tok")
        # → "clone https://***@host/repo failed"
    """
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text


def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into *base*; override wins on scalar conflicts.

    Neither *base* nor *override* is mutated — a new dict is always returned.
    However, non-overlapping nested dicts from *base* are shallow-copied by
    reference into the result, not deep-copied. Callers that mutate nested dicts
    in the result may also mutate *base* at those keys.

    Example:
        deep_merge({"a": {"x": 1, "y": 2}}, {"a": {"x": 9}, "b": 3})
        # → {"a": {"x": 9, "y": 2}, "b": 3}
    """
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = deep_merge(result[key], val)
        else:
            result[key] = val
    return result
