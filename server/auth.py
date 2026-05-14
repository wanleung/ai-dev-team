"""X-API-Key authentication for the AISW integration server."""
from __future__ import annotations

from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_configured_key: str = ""


def set_api_key(key: str) -> None:
    """Call once at startup with the configured API key."""
    global _configured_key
    _configured_key = key


def require_api_key():
    """FastAPI dependency that enforces X-API-Key auth."""
    def _check(api_key: str | None = Security(_api_key_header)):
        if not _configured_key:
            return  # no key configured → open access (dev mode)
        if api_key != _configured_key:
            raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")
    return Depends(_check)
