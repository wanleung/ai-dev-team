"""Tests for GrokOAuthBackend — all network/browser calls mocked."""
from __future__ import annotations

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
from unittest.mock import MagicMock, patch

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
            import http.client as _http_client
            import time as _time
            # Wait for auth_url to be set (up to 2s)
            deadline = _time.time() + 2.0
            while not auth_url_holder.get("url") and _time.time() < deadline:
                _time.sleep(0.01)
            url = auth_url_holder.get("url", "")
            params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
            state = params.get("state", "")
            try:
                conn = _http_client.HTTPConnection("127.0.0.1", 56121, timeout=5)
                conn.request("GET", f"/callback?code=authcode123&state={state}")
                conn.getresponse()
            except Exception:
                pass  # server may have shut down before we read response

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
            with patch.dict(os.environ, {"SSH_TTY": ""}):
                with patch("sys.stdout.isatty", return_value=True):
                    with patch("agents.backends.grok_oauth.urllib.request.urlopen",
                               return_value=fake_token_resp):
                        result = _do_pkce_login()

        t.join(timeout=5)
        self.assertEqual(result["access_token"], "access_xyz")
        self.assertEqual(result["refresh_token"], "refresh_xyz")
        self.assertAlmostEqual(result["expires_at"], time.time() + 3600, delta=5)

    def test_pkce_login_timeout(self):
        """_do_pkce_login raises TimeoutError when loopback server times out."""
        original_timer = threading.Timer

        def fast_timer(interval, func, *args, **kwargs):
            return original_timer(0.05, func, *args, **kwargs)

        with patch("agents.backends.grok_oauth.threading.Timer", side_effect=fast_timer):
            with patch("webbrowser.open"):
                with patch.dict(os.environ, {"SSH_TTY": ""}):
                    with patch("sys.stdout.isatty", return_value=True):
                        with self.assertRaises(TimeoutError) as ctx:
                            _do_pkce_login()

        self.assertIn("timed out", str(ctx.exception).lower())

    def test_pkce_login_state_mismatch(self):
        """_do_pkce_login raises RuntimeError when callback state doesn't match."""

        def send_bad_state_callback() -> None:
            import http.client as _http_client
            import time as _time
            _time.sleep(0.2)
            try:
                conn = _http_client.HTTPConnection("127.0.0.1", 56121, timeout=5)
                conn.request("GET", "/callback?code=authcode&state=WRONG_STATE")
                conn.getresponse()
            except Exception:
                pass

        t = threading.Thread(target=send_bad_state_callback, daemon=True)
        t.start()

        with patch("webbrowser.open"):
            with patch.dict(os.environ, {"SSH_TTY": ""}):
                with patch("sys.stdout.isatty", return_value=True):
                    with self.assertRaises(RuntimeError) as ctx:
                        _do_pkce_login()

        t.join(timeout=5)
        self.assertIn("state mismatch", str(ctx.exception).lower())

    def test_pkce_login_headless_prints_url(self):
        """On headless session, URL is printed and webbrowser.open is NOT called."""
        original_timer = threading.Timer

        def fast_timer(interval, func, *args, **kwargs):
            return original_timer(0.05, func, *args, **kwargs)

        with patch("agents.backends.grok_oauth.threading.Timer", side_effect=fast_timer):
            with patch("webbrowser.open") as mock_browser:
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
        from agents.backends.grok_oauth import _RefreshAuthError
        self.assertIsInstance(ctx.exception, _RefreshAuthError)
        self.assertEqual(ctx.exception.code, 401)

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
            "expires_at": time.time() + 30,
        }

        with patch("agents.backends.grok_oauth._ensure_valid_token", return_value="old_access"):
            with patch("openai.OpenAI"):
                backend = GrokOAuthBackend(model="grok-oauth/grok-3")

        with patch("agents.backends.grok_oauth._load_tokens", return_value=stale):
            with patch("agents.backends.grok_oauth._ensure_valid_token", return_value="new_access") as mock_ensure:
                with patch("openai.OpenAI") as mock_openai:
                    backend._pre_call()

        mock_ensure.assert_called_once()
        from agents.backends.grok_oauth import XAI_API_BASE
        mock_openai.assert_called_once_with(base_url=XAI_API_BASE, api_key="new_access")
        self.assertIs(backend._client, mock_openai.return_value)

    def test_pre_call_skips_refresh_when_token_fresh(self):
        """_pre_call() is a no-op when the access token is not near expiry."""
        fresh_tokens = {
            "access_token": "good_access",
            "refresh_token": "some_refresh",
            "expires_at": time.time() + 3600,
        }
        with patch("agents.backends.grok_oauth._ensure_valid_token", return_value="good_access"), \
             patch("openai.OpenAI"):
            backend = GrokOAuthBackend(model="grok-oauth/grok-3")

        original_client = backend._client
        with patch("agents.backends.grok_oauth._load_tokens", return_value=fresh_tokens), \
             patch("agents.backends.grok_oauth._ensure_valid_token") as mock_ensure:
            backend._pre_call()

        mock_ensure.assert_not_called()
        self.assertIs(backend._client, original_client)


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
