"""Unit tests for GitHub Copilot backend in ai-software-house."""
import json
import os
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, mock_open


# ── _is_copilot_model ────────────────────────────────────────────────────────

def test_is_copilot_model_with_prefix():
    from agents.base_agent import _is_copilot_model
    assert _is_copilot_model("copilot/claude-sonnet-4.6") is True
    assert _is_copilot_model("copilot/gpt-4o") is True


def test_is_copilot_model_without_prefix():
    from agents.base_agent import _is_copilot_model
    assert _is_copilot_model("ollama/llama3.2") is False
    assert _is_copilot_model("gpt-4o") is False
    assert _is_copilot_model("claude-sonnet-4.6") is False


# ── _discover_copilot_oauth_token ─────────────────────────────────────────────

def test_discover_oauth_token_from_env():
    from agents.base_agent import _discover_copilot_oauth_token
    with patch.dict(os.environ, {"COPILOT_OAUTH_TOKEN": "gho_test123"}):
        assert _discover_copilot_oauth_token() == "gho_test123"


def test_discover_oauth_token_from_config_file():
    from agents.base_agent import _discover_copilot_oauth_token
    config = {"copilot_tokens": {"https://github.com:testuser": "gho_fromfile"}}
    config_json = json.dumps(config)
    with patch.dict(os.environ, {}, clear=True):
        with patch("builtins.open", mock_open(read_data=config_json)):
            assert _discover_copilot_oauth_token() == "gho_fromfile"


def test_discover_oauth_token_raises_when_missing():
    from agents.base_agent import _discover_copilot_oauth_token
    with patch.dict(os.environ, {}, clear=True):
        with patch("builtins.open", side_effect=FileNotFoundError):
            try:
                _discover_copilot_oauth_token()
                assert False, "Should have raised EnvironmentError"
            except EnvironmentError as exc:
                assert "COPILOT_OAUTH_TOKEN" in str(exc)


# ── _fetch_copilot_session_token ──────────────────────────────────────────────

def test_fetch_session_token_success():
    from agents.base_agent import _fetch_copilot_session_token, _COPILOT_SESSION
    expires = (datetime.now(timezone.utc) + timedelta(minutes=30)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    response_body = json.dumps({"token": "session_abc", "expires_at": expires}).encode()

    mock_resp = MagicMock()
    mock_resp.read.return_value = response_body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        token = _fetch_copilot_session_token("gho_fake")

    assert token == "session_abc"
    assert _COPILOT_SESSION["token"] == "session_abc"
    assert _COPILOT_SESSION["expires_at"] > time.time()
    _COPILOT_SESSION["token"] = ""
    _COPILOT_SESSION["expires_at"] = 0.0


def test_fetch_session_token_raises_on_http_error():
    from agents.base_agent import _fetch_copilot_session_token
    import urllib.error
    with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError(
        url="", code=401, msg="Unauthorized", hdrs={}, fp=None
    )):
        try:
            _fetch_copilot_session_token("gho_bad")
            assert False, "Should have raised RuntimeError"
        except RuntimeError as exc:
            assert "401" in str(exc)


def test_fetch_session_token_raises_on_url_error():
    from agents.base_agent import _fetch_copilot_session_token
    import urllib.error
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
        try:
            _fetch_copilot_session_token("gho_fake")
            assert False, "Should have raised RuntimeError"
        except RuntimeError as exc:
            assert "network error" in str(exc)


def test_discover_oauth_token_raises_when_config_has_empty_tokens():
    from agents.base_agent import _discover_copilot_oauth_token
    config_json = json.dumps({"copilot_tokens": {}})
    with patch.dict(os.environ, {}, clear=True):
        with patch("builtins.open", mock_open(read_data=config_json)):
            try:
                _discover_copilot_oauth_token()
                assert False, "Should have raised EnvironmentError"
            except EnvironmentError as exc:
                assert "COPILOT_OAUTH_TOKEN" in str(exc)
