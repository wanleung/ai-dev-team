"""Tests for CopilotBackend — token discovery and session refresh."""
from __future__ import annotations
import io
import json
import os
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, mock_open
import pytest


def _expires_str(minutes_from_now: int = 30) -> str:
    dt = datetime.now(timezone.utc) + timedelta(minutes=minutes_from_now)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_discover_oauth_token_from_env():
    from agents.backends.copilot import _discover_copilot_oauth_token
    with patch.dict(os.environ, {"COPILOT_OAUTH_TOKEN": "gho_test"}):
        assert _discover_copilot_oauth_token() == "gho_test"


def test_discover_oauth_token_from_config_file():
    from agents.backends.copilot import _discover_copilot_oauth_token
    cfg = {"copilot_tokens": {"https://github.com:user": "gho_fromfile"}}
    with patch.dict(os.environ, {}, clear=True):
        with patch("builtins.open", mock_open(read_data=json.dumps(cfg))):
            assert _discover_copilot_oauth_token() == "gho_fromfile"


def test_discover_oauth_token_raises_when_missing():
    from agents.backends.copilot import _discover_copilot_oauth_token
    with patch.dict(os.environ, {}, clear=True):
        with patch("builtins.open", side_effect=FileNotFoundError):
            with pytest.raises(EnvironmentError, match="COPILOT_OAUTH_TOKEN"):
                _discover_copilot_oauth_token()


def test_fetch_session_token_success():
    from agents.backends.copilot import _fetch_copilot_session_token, _COPILOT_SESSION
    body = json.dumps({"token": "session_abc", "expires_at": _expires_str(30)}).encode()
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = body
    with patch("urllib.request.urlopen", return_value=mock_resp):
        token = _fetch_copilot_session_token("gho_test")
    assert token == "session_abc"
    assert _COPILOT_SESSION["token"] == "session_abc"


def test_copilot_backend_refreshes_expired_session():
    from agents.backends.copilot import CopilotBackend, _COPILOT_SESSION
    _COPILOT_SESSION["token"] = "old_token"
    _COPILOT_SESSION["expires_at"] = time.time() - 10  # expired

    new_body = json.dumps({"token": "new_token", "expires_at": _expires_str(30)}).encode()
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = new_body

    with patch.dict(os.environ, {"COPILOT_OAUTH_TOKEN": "gho_test"}):
        with patch("agents.backends.copilot.OpenAI") as mock_oai:
            mock_oai.return_value = MagicMock()
            with patch("urllib.request.urlopen", return_value=mock_resp):
                backend = CopilotBackend(model="copilot/gpt-4.1")

    assert backend.model == "gpt-4.1"
    assert _COPILOT_SESSION["token"] == "new_token"


def test_copilot_backend_call_refreshes_before_call():
    from agents.backends.copilot import CopilotBackend, _COPILOT_SESSION
    _COPILOT_SESSION["token"] = "valid_token"
    _COPILOT_SESSION["expires_at"] = time.time() + 3600  # valid — well outside 60s window

    with patch.dict(os.environ, {"COPILOT_OAUTH_TOKEN": "gho_test"}):
        with patch("agents.backends.copilot.OpenAI") as mock_oai:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = MagicMock(
                choices=[MagicMock(message=MagicMock(content="reply", tool_calls=None))]
            )
            mock_oai.return_value = mock_client
            with patch("urllib.request.urlopen") as mock_urlopen:
                backend = CopilotBackend(model="copilot/gpt-4.1")
                call_count_after_init = mock_urlopen.call_count

                result = backend.call([{"role": "user", "content": "hi"}])

                assert result == "reply"
                # Token is still fresh — _pre_call() must NOT have called urlopen
                assert mock_urlopen.call_count == call_count_after_init


def test_fetch_session_token_raises_on_null_token():
    """_fetch_copilot_session_token() raises RuntimeError when the API returns a null token."""
    from agents.backends.copilot import _fetch_copilot_session_token, _COPILOT_SESSION
    # Force expiry so the double-checked locking does not short-circuit.
    _COPILOT_SESSION["token"] = ""
    _COPILOT_SESSION["expires_at"] = 0.0

    null_response_data = json.dumps({"token": None, "expires_at": "2099-01-01T00:00:00Z"}).encode()
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = null_response_data

    with patch("urllib.request.urlopen", return_value=mock_resp):
        with pytest.raises(RuntimeError, match="empty or non-string token"):
            _fetch_copilot_session_token("gho_test")


def test_discover_oauth_token_raises_on_permission_error():
    """_discover_copilot_oauth_token() wraps a PermissionError into EnvironmentError."""
    from agents.backends.copilot import _discover_copilot_oauth_token
    import builtins

    with patch.dict(os.environ, {}, clear=True):
        with patch("builtins.open", side_effect=PermissionError("permission denied")):
            with pytest.raises(EnvironmentError, match="COPILOT_OAUTH_TOKEN"):
                _discover_copilot_oauth_token()


def test_copilot_backend_pre_call_refreshes_when_near_expiry():
    """_pre_call() triggers a token refresh when the session expires within 60 s."""
    from agents.backends.copilot import CopilotBackend, _COPILOT_SESSION

    # Prime the session so __init__ skips the initial fetch
    _COPILOT_SESSION["token"] = "valid_token"
    _COPILOT_SESSION["expires_at"] = time.time() + 3600

    refresh_body = json.dumps(
        {"token": "refreshed_token", "expires_at": _expires_str(30)}
    ).encode()
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = refresh_body

    with patch.dict(os.environ, {"COPILOT_OAUTH_TOKEN": "gho_test"}):
        with patch("agents.backends.copilot.OpenAI") as mock_oai:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = MagicMock(
                choices=[MagicMock(message=MagicMock(content="reply", tool_calls=None))]
            )
            mock_oai.return_value = mock_client
            with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
                backend = CopilotBackend(model="copilot/gpt-4.1")
                call_count_after_init = mock_urlopen.call_count

                # Push expiry into the 60-second danger window — triggers _pre_call() refresh
                _COPILOT_SESSION["expires_at"] = time.time() + 30

                result = backend.call([{"role": "user", "content": "hi"}])

                assert result == "reply"
                # _pre_call() must have fetched a new token exactly once
                assert mock_urlopen.call_count == call_count_after_init + 1
