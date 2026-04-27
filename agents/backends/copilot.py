"""GitHub Copilot Chat API backend — OpenAI-compatible with session token refresh."""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Optional

from openai import OpenAI

from agents.backends.base import OpenAICompatibleBackend, _DEFAULT_MAX_RETRIES, _DEFAULT_BASE_DELAY

_COPILOT_API_BASE = "https://api.githubcopilot.com"
_COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
_COPILOT_CONFIG_PATH = os.path.expanduser("~/.copilot/config.json")

# Module-level session cache — shared across all CopilotBackend instances.
_COPILOT_SESSION: dict = {"token": "", "expires_at": 0.0}

# Fix 1: RLock (reentrant) allows __init__ / _pre_call to hold the lock while
# calling _fetch_copilot_session_token, which also acquires it for double-check.
_COPILOT_SESSION_LOCK = threading.RLock()


def _discover_copilot_oauth_token() -> str:
    """Return the Copilot OAuth token from COPILOT_OAUTH_TOKEN env or ~/.copilot/config.json."""
    token = os.environ.get("COPILOT_OAUTH_TOKEN")
    if token:
        return token
    try:
        with open(_COPILOT_CONFIG_PATH, encoding="utf-8") as fh:
            cfg = json.load(fh)
        tokens: dict = cfg.get("copilot_tokens", {})
        if tokens:
            return next(iter(tokens.values()))
    except (OSError, json.JSONDecodeError):
        # Fix 4: OSError widens FileNotFoundError to also catch PermissionError etc.
        pass
    raise EnvironmentError(
        "No GitHub Copilot OAuth token found. Either:\n"
        "  1. Set COPILOT_OAUTH_TOKEN=<gho_...> environment variable, or\n"
        "  2. Log in to Copilot CLI (token auto-discovered from ~/.copilot/config.json)."
    )


def _fetch_copilot_session_token(oauth_token: str) -> str:
    """Exchange OAuth token for a short-lived session token. Updates _COPILOT_SESSION.

    Fix 1: Acquires _COPILOT_SESSION_LOCK and performs a double-checked test so
    that concurrent callers (e.g. from multiple threads) only do the HTTP round-
    trip once per expiry window.
    """
    with _COPILOT_SESSION_LOCK:
        # Double-checked locking: re-test inside the lock so a second thread that
        # was waiting finds the already-refreshed token and returns immediately.
        if time.time() < _COPILOT_SESSION["expires_at"] - 60:
            return _COPILOT_SESSION["token"]

        req = urllib.request.Request(
            _COPILOT_TOKEN_URL,
            headers={"Authorization": f"token {oauth_token}"},
        )
        try:
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")[:500]
            raise RuntimeError(
                f"Copilot token exchange failed: HTTP {exc.code} — {exc.reason}\n{body}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Copilot token exchange failed: network error — {exc.reason}"
            ) from exc

        try:
            session_token: str = data["token"]
            expires_str: str = data["expires_at"]
            dt = datetime.fromisoformat(expires_str.replace("Z", "+00:00"))
        except (KeyError, ValueError) as exc:
            raise RuntimeError(
                f"Copilot token exchange failed: unexpected response format — {exc}"
            ) from exc

        # Fix 3: Guard against a null or non-string token in the response.
        if not session_token or not isinstance(session_token, str):
            raise RuntimeError(
                f"Copilot token exchange returned an empty or non-string token: {session_token!r}"
            )

        _COPILOT_SESSION["token"] = session_token
        _COPILOT_SESSION["expires_at"] = dt.timestamp()
        return session_token


def _build_copilot_client(token: str) -> OpenAI:
    """Build an OpenAI client configured for the GitHub Copilot API."""
    return OpenAI(
        base_url=_COPILOT_API_BASE,
        api_key=token,
        default_headers={
            "Editor-Version": "vscode/1.90.0",
            "Copilot-Integration-Id": "vscode-chat",
        },
    )


class CopilotBackend(OpenAICompatibleBackend):
    """GitHub Copilot Chat API backend.

    Auto-refreshes the short-lived session token before each API call.
    Model prefix "copilot/" is stripped.
    Auth: COPILOT_OAUTH_TOKEN env var or ~/.copilot/config.json.
    """

    def __init__(
        self,
        model: str,
        inter_call_delay: int = 0,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        retry_delay: float = _DEFAULT_BASE_DELAY,
    ) -> None:
        self._oauth_token = _discover_copilot_oauth_token()
        # Fix 1: Hold the lock for the entire check→fetch→read sequence so no
        # other thread can mutate _COPILOT_SESSION between the expiry test and
        # the subsequent token read.  _fetch_copilot_session_token re-acquires
        # the same RLock (reentrant), performing its own double-check inside.
        with _COPILOT_SESSION_LOCK:
            if time.time() >= _COPILOT_SESSION["expires_at"] - 60:
                _fetch_copilot_session_token(self._oauth_token)
            client = _build_copilot_client(_COPILOT_SESSION["token"])
        super().__init__(
            model=model.removeprefix("copilot/"),
            client=client,
            inter_call_delay=inter_call_delay,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )

    def _pre_call(self) -> None:
        """Refresh session token if within 60s of expiry; rebuild client if refreshed.

        Fix 1: Hold the lock for the full check→fetch→rebuild sequence so a
        concurrent call cannot race between the expiry read and the client swap.
        """
        with _COPILOT_SESSION_LOCK:
            if time.time() < _COPILOT_SESSION["expires_at"] - 60:
                return
            new_token = _fetch_copilot_session_token(self._oauth_token)
            self._client = _build_copilot_client(new_token)
