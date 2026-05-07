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
