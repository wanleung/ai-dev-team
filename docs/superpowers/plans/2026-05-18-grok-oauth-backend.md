# GrokOAuthBackend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `GrokOAuthBackend` — a backend that authenticates to xAI's API via OAuth 2.0 PKCE (SuperGrok subscription) with automatic token refresh, 120s login timeout, and headless/SSH support.

**Architecture:** `GrokOAuthBackend` extends `OpenAICompatibleBackend` (same as `CopilotBackend`). All OAuth logic lives in `agents/backends/grok_oauth.py`: PKCE browser flow via stdlib `http.server` + `threading.Timer`, token persistence in `~/.ai-software-house/auth.json`, proactive refresh in `_pre_call()` with `RLock` double-check. Factory registered under `grok-oauth/` prefix.

**Tech Stack:** Python stdlib only (`urllib.request`, `http.server`, `threading`, `webbrowser`, `secrets`, `hashlib`, `base64`). `openai` SDK (already a project dependency).

**Spec:** `docs/superpowers/specs/2026-05-18-grok-oauth-backend-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `agents/backends/grok_oauth.py` | **Create** | All OAuth logic + `GrokOAuthBackend` class |
| `agents/backends/factory.py` | **Modify** | Add `grok-oauth/` dispatch block + update ValueError |
| `tests/test_grok_oauth_backend.py` | **Create** | 10 tests (all mocked, no real HTTP) |

---

## Task 1: Write All Failing Tests

**Files:**
- Create: `tests/test_grok_oauth_backend.py`

- [ ] **Step 1: Create the test file with all 10 tests**

Create `tests/test_grok_oauth_backend.py`:

```python
"""Tests for GrokOAuthBackend — all network/browser calls mocked."""
from __future__ import annotations

import base64
import json
import os
import stat
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest.mock import MagicMock, call, patch

# All imports will fail until Task 2–5 are implemented — that's expected.
from agents.backends.grok_oauth import (
    LOGIN_TIMEOUT_SECS,
    TOKEN_EXPIRY_BUFFER_SECS,
    GrokOAuthBackend,
    _do_pkce_login,
    _ensure_valid_token,
    _load_tokens,
    _refresh_access_token,
    _save_tokens,
)


class TestTokenStorage(unittest.TestCase):
    """Tests for _load_tokens / _save_tokens."""

    def test_load_save_tokens_roundtrip(self):
        """save then load returns same values; file has mode 0o600."""
        with tempfile.TemporaryDirectory() as tmpdir:
            auth_path = os.path.join(tmpdir, "auth.json")
            with patch("agents.backends.grok_oauth.XAI_AUTH_PATH", auth_path):
                _save_tokens(
                    access_token="acc_123",
                    refresh_token="ref_456",
                    expires_at=9999999999.0,
                )
                result = _load_tokens()

            self.assertEqual(result["access_token"], "acc_123")
            self.assertEqual(result["refresh_token"], "ref_456")
            self.assertEqual(result["expires_at"], 9999999999.0)
            mode = stat.S_IMODE(os.stat(auth_path).st_mode)
            self.assertEqual(mode, 0o600)

    def test_load_tokens_returns_none_when_missing(self):
        """_load_tokens returns None when auth file does not exist."""
        with patch("agents.backends.grok_oauth.XAI_AUTH_PATH", "/nonexistent/path/auth.json"):
            result = _load_tokens()
        self.assertIsNone(result)


class TestPkceLogin(unittest.TestCase):
    """Tests for _do_pkce_login."""

    def test_pkce_login_success(self):
        """Full PKCE flow: real loopback server receives callback, tokens returned."""
        auth_url_holder: dict = {}

        def fake_browser_open(url: str) -> None:
            auth_url_holder["url"] = url

        def send_callback() -> None:
            # Wait briefly for serve_forever() to start, then send the callback.
            time.sleep(0.2)
            url = auth_url_holder.get("url", "")
            params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
            state = params.get("state", "")
            callback = f"http://127.0.0.1:56121/callback?code=authcode123&state={state}"
            try:
                urllib.request.urlopen(callback, timeout=5)
            except Exception:
                pass  # 200 HTML response is fine; connection close also OK

        fake_token_resp = MagicMock()
        fake_token_resp.read.return_value = json.dumps({
            "access_token": "access_xyz",
            "refresh_token": "refresh_xyz",
            "expires_in": 3600,
        }).encode()
        fake_token_resp.__enter__ = lambda s: s
        fake_token_resp.__exit__ = MagicMock(return_value=False)

        t = threading.Thread(target=send_callback, daemon=True)
        t.start()

        with patch("webbrowser.open", side_effect=fake_browser_open):
            with patch("sys.stdout.isatty", return_value=True):
                # Patch urlopen only for the token exchange POST (not the callback GET)
                with patch("agents.backends.grok_oauth.urllib.request.urlopen",
                           return_value=fake_token_resp):
                    result = _do_pkce_login()

        t.join(timeout=5)
        self.assertEqual(result["access_token"], "access_xyz")
        self.assertEqual(result["refresh_token"], "refresh_xyz")
        self.assertAlmostEqual(result["expires_at"], time.time() + 3600, delta=5)

    def test_pkce_login_timeout(self):
        """_do_pkce_login raises TimeoutError when loopback server times out."""
        # Patch Timer to fire after 0.05s instead of LOGIN_TIMEOUT_SECS
        original_timer = threading.Timer

        def fast_timer(interval, func, *args, **kwargs):
            return original_timer(0.05, func, *args, **kwargs)

        with patch("agents.backends.grok_oauth.threading.Timer", side_effect=fast_timer):
            with patch("webbrowser.open"):
                with patch("sys.stdout.isatty", return_value=True):
                    with self.assertRaises(TimeoutError) as ctx:
                        _do_pkce_login()

        self.assertIn("timed out", str(ctx.exception).lower())

    def test_pkce_login_state_mismatch(self):
        """_do_pkce_login raises RuntimeError when callback state doesn't match."""

        def send_bad_state_callback() -> None:
            time.sleep(0.2)
            callback = "http://127.0.0.1:56121/callback?code=authcode&state=WRONG_STATE"
            try:
                urllib.request.urlopen(callback, timeout=5)
            except Exception:
                pass

        t = threading.Thread(target=send_bad_state_callback, daemon=True)
        t.start()

        with patch("webbrowser.open"):
            with patch("sys.stdout.isatty", return_value=True):
                with self.assertRaises(RuntimeError) as ctx:
                    _do_pkce_login()

        t.join(timeout=5)
        self.assertIn("state mismatch", str(ctx.exception).lower())

    def test_pkce_login_headless_prints_url(self):
        """On headless session, URL is printed and webbrowser.open is NOT called."""
        # Simulate timeout so we don't hang — headless path is the interesting bit
        original_timer = threading.Timer

        def fast_timer(interval, func, *args, **kwargs):
            return original_timer(0.05, func, *args, **kwargs)

        with patch("agents.backends.grok_oauth.threading.Timer", side_effect=fast_timer):
            with patch("webbrowser.open") as mock_browser:
                # SSH_TTY set → headless
                with patch.dict(os.environ, {"SSH_TTY": "/dev/pts/0"}):
                    with patch("sys.stdout.isatty", return_value=False):
                        with self.assertRaises(TimeoutError):
                            _do_pkce_login()

        mock_browser.assert_not_called()


class TestRefreshToken(unittest.TestCase):
    """Tests for _refresh_access_token."""

    def _make_response(self, body: dict) -> MagicMock:
        resp = MagicMock()
        resp.read.return_value = json.dumps(body).encode()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    def test_refresh_token_success(self):
        """_refresh_access_token returns new tokens on HTTP 200."""
        resp = self._make_response({
            "access_token": "new_access",
            "refresh_token": "new_refresh",
            "expires_in": 7200,
        })
        with patch("agents.backends.grok_oauth.urllib.request.urlopen", return_value=resp):
            result = _refresh_access_token("old_refresh")

        self.assertEqual(result["access_token"], "new_access")
        self.assertEqual(result["refresh_token"], "new_refresh")
        self.assertAlmostEqual(result["expires_at"], time.time() + 7200, delta=5)

    def test_refresh_token_expired_raises(self):
        """_refresh_access_token raises RuntimeError containing 'HTTP 401' on expired token."""
        err = urllib.error.HTTPError(url=None, code=401, msg="Unauthorized", hdrs={}, fp=None)
        with patch("agents.backends.grok_oauth.urllib.request.urlopen", side_effect=err):
            with self.assertRaises(RuntimeError) as ctx:
                _refresh_access_token("expired_refresh")

        self.assertIn("HTTP 401", str(ctx.exception))

    def test_refresh_network_error_raises(self):
        """_refresh_access_token raises RuntimeError on network failure."""
        err = urllib.error.URLError("connection refused")
        with patch("agents.backends.grok_oauth.urllib.request.urlopen", side_effect=err):
            with self.assertRaises(RuntimeError) as ctx:
                _refresh_access_token("any_refresh")

        self.assertIn("network error", str(ctx.exception).lower())


class TestGrokOAuthBackend(unittest.TestCase):
    """Tests for GrokOAuthBackend._pre_call() token refresh."""

    def test_pre_call_refreshes_token_near_expiry(self):
        """_pre_call() triggers token refresh when access token is within 60s of expiry."""
        stale = {
            "access_token": "old_access",
            "refresh_token": "old_refresh",
            "expires_at": time.time() + 30,  # 30s left — within 60s buffer
        }
        fresh = {
            "access_token": "new_access",
            "refresh_token": "new_refresh",
            "expires_at": time.time() + 3600,
        }

        with patch("agents.backends.grok_oauth._ensure_valid_token", return_value="old_access"):
            with patch("openai.OpenAI"):
                backend = GrokOAuthBackend(model="grok-oauth/grok-3")

        with patch("agents.backends.grok_oauth._load_tokens", return_value=stale):
            with patch("agents.backends.grok_oauth._ensure_valid_token", return_value="new_access") as mock_ensure:
                with patch("openai.OpenAI") as mock_openai:
                    backend._pre_call()

        mock_ensure.assert_called_once()
        mock_openai.assert_called_once()  # client was rebuilt


class TestGrokOAuthFactory(unittest.TestCase):
    """Tests for factory.py grok-oauth/ dispatch."""

    def test_factory_returns_grok_oauth_backend(self):
        """create_backend({'model': 'grok-oauth/grok-3'}) returns GrokOAuthBackend."""
        from agents.backends.factory import create_backend

        with patch("agents.backends.grok_oauth._ensure_valid_token", return_value="tok"):
            with patch("openai.OpenAI"):
                backend = create_backend({"model": "grok-oauth/grok-3"})

        self.assertIsInstance(backend, GrokOAuthBackend)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify all tests fail with ImportError**

```bash
cd /home/wanleung/Projects/ai-software-house
python3 -m pytest tests/test_grok_oauth_backend.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'agents.backends.grok_oauth'` or `ImportError`.

- [ ] **Step 3: Commit the failing tests**

```bash
git add tests/test_grok_oauth_backend.py
git commit -m "test(grok-oauth): add 10 failing tests for GrokOAuthBackend"
```

---

## Task 2: Implement Token Storage

**Files:**
- Create: `agents/backends/grok_oauth.py` (skeleton + token storage only)

- [ ] **Step 1: Create `agents/backends/grok_oauth.py` with constants and token storage**

```python
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
from typing import Callable

from openai import OpenAI

from agents.backends.base import OpenAICompatibleBackend, _DEFAULT_MAX_RETRIES, _DEFAULT_BASE_DELAY

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Override XAI_OAUTH_CLIENT_ID env var if xAI publishes a different client_id.
# Confirm the correct value from https://accounts.x.ai or grok-cli source.
XAI_CLIENT_ID: str = os.environ.get("XAI_OAUTH_CLIENT_ID", "xai-supergrok")
XAI_AUTH_URL = "https://accounts.x.ai/oauth/authorize"
XAI_TOKEN_URL = "https://accounts.x.ai/oauth/token"
XAI_API_BASE = "https://api.x.ai/v1"
XAI_REDIRECT_URI = "http://127.0.0.1:56121/callback"
XAI_SCOPES = "openid offline_access"
XAI_AUTH_PATH: str = os.path.expanduser("~/.ai-software-house/auth.json")

LOGIN_TIMEOUT_SECS = 120
TOKEN_EXPIRY_BUFFER_SECS = 60

# Module-level lock — RLock so __init__ and _pre_call can both hold it.
_XAI_SESSION_LOCK = threading.RLock()

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

    # Read existing file so other provider keys aren't clobbered.
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
```

- [ ] **Step 2: Add placeholder stubs for the remaining public symbols (so the test file can import)**

Append to `agents/backends/grok_oauth.py`:

```python
# ---------------------------------------------------------------------------
# Stubs (implemented in Tasks 3–5)
# ---------------------------------------------------------------------------


def _do_pkce_login() -> dict:
    raise NotImplementedError


def _refresh_access_token(refresh_token: str) -> dict:
    raise NotImplementedError


def _ensure_valid_token() -> str:
    raise NotImplementedError


class GrokOAuthBackend(OpenAICompatibleBackend):
    def __init__(self, model: str, max_retries: int = _DEFAULT_MAX_RETRIES,
                 retry_delay: float = _DEFAULT_BASE_DELAY) -> None:
        raise NotImplementedError
```

- [ ] **Step 3: Run token storage tests only — must pass; others fail with NotImplementedError**

```bash
python3 -m pytest tests/test_grok_oauth_backend.py::TestTokenStorage -v
```

Expected: `2 passed`.

- [ ] **Step 4: Commit**

```bash
git add agents/backends/grok_oauth.py
git commit -m "feat(grok-oauth): token storage skeleton (_load_tokens, _save_tokens)"
```

---

## Task 3: Implement PKCE Login Flow

**Files:**
- Modify: `agents/backends/grok_oauth.py` — replace `_do_pkce_login` stub

- [ ] **Step 1: Replace the `_do_pkce_login` stub with the full implementation**

Replace the `def _do_pkce_login() -> dict: raise NotImplementedError` stub with:

```python
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

    # --- Loopback server ---
    result: dict = {}
    error_holder: list[str] = []
    timed_out = [False]

    class _CallbackHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            qs = dict(urllib.parse.parse_qsl(parsed.query))

            if qs.get("state") != state:
                error_holder.append("xAI login aborted: state mismatch (possible CSRF)")
                self._respond(400, "Login failed: state mismatch.")
            else:
                result["code"] = qs.get("code", "")
                self._respond(200, "Login successful — return to your terminal.")

            # Signal serve_forever() to stop.
            threading.Thread(target=server.shutdown, daemon=True).start()

        def _respond(self, code: int, body: str) -> None:
            encoded = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, *_: object) -> None:  # suppress access log noise
            pass

    server = http.server.HTTPServer(("127.0.0.1", 56121), _CallbackHandler)

    def _on_timeout() -> None:
        timed_out[0] = True
        server.shutdown()

    timer = threading.Timer(LOGIN_TIMEOUT_SECS, _on_timeout)

    # --- Open browser (or print URL for headless) ---
    is_headless = (not sys.stdout.isatty()) or bool(os.environ.get("SSH_TTY"))
    if is_headless:
        print(f"\nOpen this URL in your browser to log in to xAI:\n\n  {auth_url}\n"
              f"\nWaiting {LOGIN_TIMEOUT_SECS}s for callback…")
    else:
        print(f"Opening browser for xAI login… (timeout: {LOGIN_TIMEOUT_SECS}s)")
        webbrowser.open(auth_url)

    timer.start()
    server.serve_forever()  # blocks until shutdown()
    timer.cancel()

    if timed_out[0]:
        raise TimeoutError(
            f"xAI login timed out after {LOGIN_TIMEOUT_SECS}s. Run again to retry."
        )
    if error_holder:
        raise RuntimeError(error_holder[0])
    if "code" not in result:
        raise RuntimeError("xAI login failed: no authorization code received.")

    # --- Token exchange ---
    body = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": result["code"],
        "redirect_uri": XAI_REDIRECT_URI,
        "client_id": XAI_CLIENT_ID,
        "code_verifier": code_verifier,
    }).encode()
    req = urllib.request.Request(
        XAI_TOKEN_URL,
        data=body,
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
```

- [ ] **Step 2: Run PKCE login tests**

```bash
python3 -m pytest tests/test_grok_oauth_backend.py::TestPkceLogin -v
```

Expected: `4 passed`.

- [ ] **Step 3: Commit**

```bash
git add agents/backends/grok_oauth.py
git commit -m "feat(grok-oauth): PKCE browser login flow with 120s timeout and headless support"
```

---

## Task 4: Implement Token Refresh and `_ensure_valid_token`

**Files:**
- Modify: `agents/backends/grok_oauth.py` — replace `_refresh_access_token` and `_ensure_valid_token` stubs

- [ ] **Step 1: Replace `_refresh_access_token` stub**

Replace `def _refresh_access_token(refresh_token: str) -> dict: raise NotImplementedError` with:

```python
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
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode(errors="replace")[:200]
        raise RuntimeError(
            f"xAI token refresh failed: HTTP {exc.code} — {exc.reason}\n{body_text}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"xAI token refresh failed: network error — {exc.reason}"
        ) from exc

    try:
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
```

- [ ] **Step 2: Replace `_ensure_valid_token` stub**

Replace `def _ensure_valid_token() -> str: raise NotImplementedError` with:

```python
def _ensure_valid_token() -> str:
    """Return a valid xAI access token, refreshing or re-logging in as needed.

    Called under _XAI_SESSION_LOCK from __init__ and _pre_call.
    """
    tokens = _load_tokens()

    if tokens is None or not tokens.get("access_token"):
        _log.info("No xAI tokens found — starting browser login.")
        new = _do_pkce_login()
        _save_tokens(**new)
        return new["access_token"]

    if time.time() >= tokens["expires_at"] - TOKEN_EXPIRY_BUFFER_SECS:
        _log.info("xAI access token near/past expiry — refreshing.")
        try:
            new = _refresh_access_token(tokens["refresh_token"])
            _save_tokens(**new)
            return new["access_token"]
        except RuntimeError as exc:
            # Refresh token expired (HTTP 400/401) → re-login
            if "HTTP 400" in str(exc) or "HTTP 401" in str(exc):
                _log.info("xAI refresh token expired — starting browser re-login.")
                new = _do_pkce_login()
                _save_tokens(**new)
                return new["access_token"]
            raise  # propagate network errors

    return tokens["access_token"]
```

- [ ] **Step 3: Run refresh tests**

```bash
python3 -m pytest tests/test_grok_oauth_backend.py::TestRefreshToken -v
```

Expected: `3 passed`.

- [ ] **Step 4: Commit**

```bash
git add agents/backends/grok_oauth.py
git commit -m "feat(grok-oauth): token refresh and _ensure_valid_token with auto re-login"
```

---

## Task 5: Implement `GrokOAuthBackend` + Factory Registration

**Files:**
- Modify: `agents/backends/grok_oauth.py` — replace `GrokOAuthBackend` stub
- Modify: `agents/backends/factory.py` — add `grok-oauth/` block

- [ ] **Step 1: Replace `GrokOAuthBackend` stub**

Replace the stub class at the bottom of `agents/backends/grok_oauth.py` with:

```python
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
    ) -> None:
        with _XAI_SESSION_LOCK:
            token = _ensure_valid_token()
            client = OpenAI(base_url=XAI_API_BASE, api_key=token)
        super().__init__(
            model=model.removeprefix("grok-oauth/"),
            client=client,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )

    def _pre_call(self) -> None:
        """Proactively refresh access token if within TOKEN_EXPIRY_BUFFER_SECS of expiry."""
        with _XAI_SESSION_LOCK:
            tokens = _load_tokens()
            if tokens and time.time() < tokens["expires_at"] - TOKEN_EXPIRY_BUFFER_SECS:
                return  # still valid — double-check under lock
            new_token = _ensure_valid_token()
            self._client = OpenAI(base_url=XAI_API_BASE, api_key=new_token)
```

- [ ] **Step 2: Add `grok-oauth/` to factory.py**

In `agents/backends/factory.py`, find the `if model.startswith("grok/"):` block and add the `grok-oauth/` block immediately after it:

```python
    if model.startswith("grok-oauth/"):
        from agents.backends.grok_oauth import GrokOAuthBackend
        return GrokOAuthBackend(model=model, **kwargs)
```

Also update the `ValueError` at the bottom to include `'grok-oauth/'`:

```python
    raise ValueError(
        f"Cannot determine backend for model {model!r}. "
        "Prefix with 'ollama/', 'copilot/', 'nvidia-nim/', 'opencode/', "
        "'opencode-zen/', 'opencode-go/', 'grok/', 'grok-oauth/', "
        "or use 'claude-*' for Anthropic."
    )
```

- [ ] **Step 3: Run all grok-oauth tests**

```bash
python3 -m pytest tests/test_grok_oauth_backend.py -v
```

Expected: `10 passed`.

- [ ] **Step 4: Run the full test suite to check for regressions**

```bash
python3 -m pytest tests/ -x -q --timeout=30 2>&1 | tail -20
```

Expected: all existing tests pass (1 pre-existing deployment test failure is OK).

- [ ] **Step 5: Commit**

```bash
git add agents/backends/grok_oauth.py agents/backends/factory.py
git commit -m "feat(grok-oauth): GrokOAuthBackend class and factory registration"
```

---

## Task 6: Open PR

**Files:** none — push + PR only.

- [ ] **Step 1: Push branch**

```bash
git push -u origin feature/grok-oauth-backend
```

- [ ] **Step 2: Open PR**

```bash
gh pr create \
  --title "feat(backends): GrokOAuthBackend — xAI SuperGrok subscription via OAuth 2.0 PKCE" \
  --body "## Summary

Adds \`GrokOAuthBackend\` for users with a SuperGrok subscription. No \`XAI_API_KEY\` required — authenticates via browser OAuth 2.0 PKCE against \`accounts.x.ai\`.

## Changes

- \`agents/backends/grok_oauth.py\` — new backend: PKCE flow, token storage, auto-refresh
- \`agents/backends/factory.py\` — \`grok-oauth/\` prefix dispatch
- \`tests/test_grok_oauth_backend.py\` — 10 tests

## Key behaviours

- **Token expiry**: proactive refresh 60s before expiry in \`_pre_call()\` (RLock + double-check); if refresh token itself expires → auto re-launch browser login
- **Auth timeout**: loopback HTTP server killed after 120s via \`threading.Timer\`; raises \`TimeoutError\`
- **Headless/SSH**: detects missing TTY or \`SSH_TTY\` env → prints URL instead of opening browser
- **Thread-safe**: \`RLock\` guards both \`__init__\` and \`_pre_call\` token check/refresh/rebuild

## Pre-implementation dependency

\`XAI_CLIENT_ID\` defaults to \`xai-supergrok\` but is overridable via \`XAI_OAUTH_CLIENT_ID\` env var. Confirm actual value from xAI developer docs before merging to production.

Spec: \`docs/superpowers/specs/2026-05-18-grok-oauth-backend-design.md\`
Plan: \`docs/superpowers/plans/2026-05-18-grok-oauth-backend.md\`" \
  --base master \
  --head feature/grok-oauth-backend
```
