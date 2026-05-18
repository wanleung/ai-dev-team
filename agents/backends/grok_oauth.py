"""GrokOAuthBackend — xAI Grok via SuperGrok subscription (OAuth 2.0 PKCE)."""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import logging
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import sys

import openai as _openai_module

from agents.backends.base import OpenAICompatibleBackend, _DEFAULT_MAX_RETRIES, _DEFAULT_BASE_DELAY

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

XAI_CLIENT_ID: str = os.environ.get("XAI_OAUTH_CLIENT_ID", "xai-supergrok")
XAI_AUTH_URL = "https://accounts.x.ai/oauth/authorize"
XAI_TOKEN_URL = "https://accounts.x.ai/oauth/token"
XAI_API_BASE = "https://api.x.ai/v1"
XAI_REDIRECT_URI = "http://127.0.0.1:56121/callback"
XAI_SCOPES = "openid offline_access"
XAI_AUTH_PATH: str = os.path.expanduser("~/.ai-software-house/auth.json")

LOGIN_TIMEOUT_SECS = 120
TOKEN_EXPIRY_BUFFER_SECS = 60

_XAI_SESSION_LOCK = threading.RLock()
_client_id_warned: bool = False

# ---------------------------------------------------------------------------
# Token storage
# ---------------------------------------------------------------------------


def _load_tokens() -> dict | None:
    """Read xAI tokens from ~/.ai-software-house/auth.json. Returns None if absent/corrupt."""
    try:
        with open(XAI_AUTH_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        return data.get("xai") or None
    except (OSError, json.JSONDecodeError):
        return None


def _save_tokens(access_token: str, refresh_token: str, expires_at: float) -> None:
    """Persist xAI tokens to ~/.ai-software-house/auth.json (mode 0o600, atomic write)."""
    os.makedirs(os.path.dirname(XAI_AUTH_PATH), exist_ok=True)

    try:
        with open(XAI_AUTH_PATH, encoding="utf-8") as fh:
            existing: dict = json.load(fh)
    except (OSError, json.JSONDecodeError):
        existing = {}

    existing["xai"] = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at,
    }

    tmp_path = XAI_AUTH_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(existing, fh, indent=2)
    os.chmod(tmp_path, 0o600)
    os.replace(tmp_path, XAI_AUTH_PATH)


# ---------------------------------------------------------------------------
# PKCE login flow
# ---------------------------------------------------------------------------


class _RefreshAuthError(RuntimeError):
    """Raised by _refresh_access_token when the server returns a 4xx HTTP status."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


def _do_pkce_login() -> dict:
    """Run OAuth 2.0 PKCE browser login. Returns {'access_token', 'refresh_token', 'expires_at'}.

    Raises:
        TimeoutError:  Browser login not completed within LOGIN_TIMEOUT_SECS.
        RuntimeError:  State mismatch, token exchange failure, or network error.
    """
    # --- PKCE parameters ---
    code_verifier = (
        base64.urlsafe_b64encode(secrets.token_bytes(96)).rstrip(b"=").decode()
    )
    code_challenge = (
        base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode()).digest()
        )
        .rstrip(b"=")
        .decode()
    )
    state = secrets.token_urlsafe(16)

    params = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": XAI_CLIENT_ID,
        "redirect_uri": XAI_REDIRECT_URI,
        "scope": XAI_SCOPES,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    })
    auth_url = f"{XAI_AUTH_URL}?{params}"

    # --- Shared state for all callback-delivery paths ---
    result: dict = {}
    error_holder: list[str] = []
    timed_out = False
    done = threading.Event()

    def _process_callback_qs(qs: dict) -> None:
        """Extract code/state from query string; populate result/error_holder; signal done."""
        if qs.get("state") != state:
            error_holder.append("xAI login aborted: state mismatch (possible CSRF)")
            done.set()
            return
        code = qs.get("code", "")
        if not code:
            error_holder.append("xAI login failed: no authorization code in callback.")
            done.set()
            return
        result["code"] = code
        done.set()

    server: http.server.HTTPServer | None = None
    timer: threading.Timer | None = None
    server_thread: threading.Thread | None = None

    try:
        # --- Loopback HTTP server (handles real browser redirects) ---
        class _CallbackHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                parsed = urllib.parse.urlparse(self.path)
                qs = dict(urllib.parse.parse_qsl(parsed.query))
                if qs.get("state") != state:
                    body = "Login failed: state mismatch.".encode()
                    self.send_response(400)
                else:
                    body = "Login successful — return to your terminal.".encode()
                    self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                # Signal after response is fully written.
                _process_callback_qs(qs)

            def log_message(self, *_: object) -> None:  # noqa: D102
                pass

        try:
            server = http.server.HTTPServer(("127.0.0.1", 56121), _CallbackHandler)
        except OSError as exc:
            raise RuntimeError(
                f"xAI login failed: could not bind port 56121 — {exc}. "
                "Check that no other process (e.g. a previous login) is using this port."
            ) from exc

        def _on_timeout() -> None:
            nonlocal timed_out
            timed_out = True
            server.shutdown()
            done.set()

        timer = threading.Timer(LOGIN_TIMEOUT_SECS, _on_timeout)

        # --- Open browser (or print URL for headless) ---
        is_headless = (not sys.stdout.isatty()) or bool(os.environ.get("SSH_TTY"))
        if is_headless:
            print(
                f"\nOpen this URL in your browser to log in to xAI:\n\n  {auth_url}\n"
                f"\nWaiting {LOGIN_TIMEOUT_SECS}s for callback…"
            )
        else:
            print(f"Opening browser for xAI login… (timeout: {LOGIN_TIMEOUT_SECS}s)")
            webbrowser.open(auth_url)

        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        timer.start()
        server_thread.start()

        done.wait(timeout=LOGIN_TIMEOUT_SECS + 5)  # defensive: timer should fire first

        if timer is not None:
            timer.cancel()
        if not timed_out:
            server.shutdown()
        server_thread.join(timeout=2)

        if timed_out:
            raise TimeoutError(
                f"xAI login timed out after {LOGIN_TIMEOUT_SECS}s. Run again to retry."
            )
        if error_holder:
            raise RuntimeError(error_holder[0])
        if "code" not in result:
            raise RuntimeError("xAI login failed: no authorization code received.")

        # --- Token exchange ---
        body_bytes = urllib.parse.urlencode({
            "grant_type": "authorization_code",
            "code": result["code"],
            "redirect_uri": XAI_REDIRECT_URI,
            "client_id": XAI_CLIENT_ID,
            "code_verifier": code_verifier,
        }).encode()
        req = urllib.request.Request(
            XAI_TOKEN_URL,
            data=body_bytes,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode(errors="replace")[:200]
            raise RuntimeError(
                f"xAI token exchange failed: HTTP {exc.code} — {exc.reason}\n{body_text}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"xAI token exchange failed: network error — {exc.reason}"
            ) from exc

        try:
            access_token: str = data["access_token"]
            refresh_token: str = data["refresh_token"]
            expires_in: int = int(data["expires_in"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(
                f"xAI token exchange failed: unexpected response format — {exc}"
            ) from exc

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": time.time() + expires_in,
        }

    finally:
        if server is not None:
            server.server_close()


def _refresh_access_token(refresh_token: str) -> dict:
    """Exchange a refresh token for a new access token.

    Returns {'access_token', 'refresh_token', 'expires_at'}.

    Raises:
        RuntimeError: HTTP error (including 401 expired) or network error.
    """
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": XAI_CLIENT_ID,
    }).encode()
    req = urllib.request.Request(
        XAI_TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode(errors="replace")[:200]
        msg = f"xAI token refresh failed: HTTP {exc.code} — {exc.reason}\n{body_text}"
        if 400 <= exc.code < 500:
            raise _RefreshAuthError(exc.code, msg) from exc
        raise RuntimeError(msg) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"xAI token refresh failed: network error — {exc.reason}"
        ) from exc

    try:
        data = json.loads(raw)
        new_access: str = data["access_token"]
        new_refresh: str = data.get("refresh_token", refresh_token)  # some providers reuse
        expires_in: int = int(data["expires_in"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(
            f"xAI token refresh failed: unexpected response format — {exc}"
        ) from exc

    return {
        "access_token": new_access,
        "refresh_token": new_refresh,
        "expires_at": time.time() + expires_in,
    }


def _ensure_valid_token() -> str:
    """Return a valid xAI access token, refreshing or re-logging in as needed.

    Called under _XAI_SESSION_LOCK from __init__ and _pre_call.
    """
    global _client_id_warned
    if not os.environ.get("XAI_OAUTH_CLIENT_ID") and not _client_id_warned:
        _client_id_warned = True
        _log.warning(
            "XAI_OAUTH_CLIENT_ID is not set; using default '%s' which may be incorrect. "
            "Set XAI_OAUTH_CLIENT_ID to the verified xAI OAuth client ID.",
            XAI_CLIENT_ID,
        )
    tokens = _load_tokens()

    REQUIRED = {"access_token", "refresh_token", "expires_at"}
    if (
        tokens is None
        or not REQUIRED.issubset(tokens)
        or not tokens["access_token"]
        or not isinstance(tokens["expires_at"], (int, float))
        or not isinstance(tokens["refresh_token"], str)
        or not tokens["refresh_token"]
    ):
        _log.info("No valid xAI tokens found — starting browser login.")
        new = _do_pkce_login()
        _save_tokens(**new)
        return new["access_token"]

    if time.time() >= tokens["expires_at"] - TOKEN_EXPIRY_BUFFER_SECS:
        _log.info("xAI access token near/past expiry — refreshing.")
        try:
            new = _refresh_access_token(tokens["refresh_token"])
            _save_tokens(**new)
            return new["access_token"]
        except _RefreshAuthError as exc:
            if exc.code in (400, 401):
                _log.info("xAI refresh token expired — starting browser re-login.")
                new = _do_pkce_login()
                _save_tokens(**new)
                return new["access_token"]
            raise RuntimeError(str(exc)) from exc  # other 4xx: propagate

    return tokens["access_token"]


class GrokOAuthBackend(OpenAICompatibleBackend):
    """xAI Grok backend using SuperGrok subscription OAuth 2.0 PKCE.

    Auth: browser login to accounts.x.ai (one-time); tokens auto-refresh.
    Token store: ~/.ai-software-house/auth.json
    Model prefix 'grok-oauth/' is stripped (e.g. 'grok-oauth/grok-3' → 'grok-3').
    """

    def __init__(
        self,
        model: str,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        retry_delay: float = _DEFAULT_BASE_DELAY,
        inter_call_delay: int = 0,
        stream: bool = False,
    ) -> None:
        with _XAI_SESSION_LOCK:  # held for up to LOGIN_TIMEOUT_SECS if browser login is needed
            token = _ensure_valid_token()
            client = _openai_module.OpenAI(base_url=XAI_API_BASE, api_key=token)
        super().__init__(
            model=model.removeprefix("grok-oauth/"),
            client=client,
            max_retries=max_retries,
            retry_delay=retry_delay,
            inter_call_delay=inter_call_delay,
            stream=stream,
        )

    def _pre_call(self) -> None:
        """Proactively refresh access token if within TOKEN_EXPIRY_BUFFER_SECS of expiry."""
        with _XAI_SESSION_LOCK:  # held for up to LOGIN_TIMEOUT_SECS if browser login is needed
            tokens = _load_tokens()
            expires_at = tokens.get("expires_at") if tokens else None
            if expires_at and time.time() < expires_at - TOKEN_EXPIRY_BUFFER_SECS:
                return  # still valid — double-check under lock
            new_token = _ensure_valid_token()
            self._client = _openai_module.OpenAI(base_url=XAI_API_BASE, api_key=new_token)
