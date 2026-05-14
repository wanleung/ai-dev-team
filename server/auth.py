"""X-API-Key authentication for the AISW integration server."""
from __future__ import annotations

import hmac
import warnings

from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_configured_key: str = ""


def set_api_key(key: str) -> None:
    """Call once at startup with the configured API key.

    Passing an empty string enables open-access dev mode — all requests
    are accepted regardless of headers. A warning is emitted.
    """
    global _configured_key
    if not key:
        warnings.warn(
            "set_api_key called with empty string — server running in open-access dev mode",
            UserWarning,
            stacklevel=2,
        )
    _configured_key = key


def require_api_key() -> Depends:
    """Return a FastAPI dependency that enforces X-API-Key auth.

    Factory pattern is intentional — reserved for future scope-based parameterisation.
    """
    def _check(api_key: str | None = Security(_api_key_header)) -> None:
        """Validate the X-API-Key header value."""
        if not _configured_key:
            return  # no key configured → open access (dev mode)
        if api_key is None or not hmac.compare_digest(api_key, _configured_key):
            raise HTTPException(
                status_code=401,
                detail="Invalid or missing X-API-Key",
                headers={"WWW-Authenticate": "ApiKey"},
            )
    return Depends(_check)
