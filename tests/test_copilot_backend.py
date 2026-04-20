"""Unit tests for GitHub Copilot backend in ai-software-house."""
import io
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

    try:
        assert token == "session_abc"
        assert _COPILOT_SESSION["token"] == "session_abc"
        assert _COPILOT_SESSION["expires_at"] > time.time()
    finally:
        _COPILOT_SESSION["token"] = ""
        _COPILOT_SESSION["expires_at"] = 0.0


def test_fetch_session_token_raises_on_http_error():
    from agents.base_agent import _fetch_copilot_session_token
    import urllib.error
    mock_body = b'{"message":"Bad credentials"}'
    with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError(
        url="", code=401, msg="Unauthorized", hdrs={}, fp=io.BytesIO(mock_body)
    )):
        try:
            _fetch_copilot_session_token("gho_bad")
            assert False, "Should have raised RuntimeError"
        except RuntimeError as exc:
            assert "401" in str(exc)
            assert "Bad credentials" in str(exc)


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


def test_fetch_session_token_raises_on_non_json_response():
    """Non-JSON response body raises RuntimeError."""
    from agents.base_agent import _fetch_copilot_session_token
    mock_resp = MagicMock()
    mock_resp.read.return_value = b"<html>Service Unavailable</html>"
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=mock_resp):
        import pytest
        with pytest.raises(RuntimeError, match="non-JSON response"):
            _fetch_copilot_session_token("gho_test")


def test_fetch_session_token_raises_on_missing_field():
    """Response missing 'token' field raises RuntimeError."""
    import json as _json
    from agents.base_agent import _fetch_copilot_session_token
    mock_resp = MagicMock()
    mock_resp.read.return_value = _json.dumps({"expires_at": "2099-01-01T00:00:00Z"}).encode()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=mock_resp):
        import pytest
        with pytest.raises(RuntimeError, match="unexpected response format"):
            _fetch_copilot_session_token("gho_test")


def test_discover_oauth_token_raises_when_config_is_corrupted():
    """Corrupted config.json (invalid JSON) falls through to EnvironmentError."""
    from agents.base_agent import _discover_copilot_oauth_token
    import pytest
    with patch.dict(os.environ, {}, clear=True):
        with patch("builtins.open", mock_open(read_data="not valid json")):
            with pytest.raises(EnvironmentError):
                _discover_copilot_oauth_token()


def test_fetch_session_token_raises_on_non_string_expires_at():
    """Response with null expires_at raises RuntimeError (AttributeError path)."""
    import json as _json
    import pytest
    from agents.base_agent import _fetch_copilot_session_token
    mock_resp = MagicMock()
    mock_resp.read.return_value = _json.dumps({"token": "abc", "expires_at": None}).encode()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=mock_resp):
        with pytest.raises(RuntimeError, match="unexpected response format"):
            _fetch_copilot_session_token("gho_test")


# ── BaseAgent copilot backend init ────────────────────────────────────────────

def test_base_agent_copilot_backend_detected_from_prefix():
    """'copilot/' prefix auto-selects the copilot backend."""
    from datetime import datetime, timezone, timedelta
    import json as _json
    expires = (datetime.now(timezone.utc) + timedelta(minutes=30)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    response_body = _json.dumps({"token": "sess_init", "expires_at": expires}).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = response_body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch.dict(os.environ, {"COPILOT_OAUTH_TOKEN": "gho_fake"}):
        with patch("urllib.request.urlopen", return_value=mock_resp):
            with patch("agents.base_agent.OpenAI") as mock_openai:
                mock_openai.return_value = MagicMock()
                from agents.base_agent import BaseAgent
                agent = BaseAgent(model="copilot/gpt-4o")
                assert agent._backend == "copilot"
                assert agent._api_model == "gpt-4o"


def test_base_agent_copilot_strips_prefix():
    """_api_model is the model ID with 'copilot/' stripped."""
    from datetime import datetime, timezone, timedelta
    import json as _json
    expires = (datetime.now(timezone.utc) + timedelta(minutes=30)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    response_body = _json.dumps({"token": "sess_init", "expires_at": expires}).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = response_body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch.dict(os.environ, {"COPILOT_OAUTH_TOKEN": "gho_fake"}):
        with patch("urllib.request.urlopen", return_value=mock_resp):
            with patch("agents.base_agent.OpenAI") as mock_openai:
                mock_openai.return_value = MagicMock()
                from agents.base_agent import BaseAgent
                agent = BaseAgent(model="copilot/claude-sonnet-4.6")
                assert agent._api_model == "claude-sonnet-4.6"


def test_base_agent_copilot_openai_client_base_url():
    """OpenAI client is initialised with the Copilot API base URL."""
    from datetime import datetime, timezone, timedelta
    import json as _json
    expires = (datetime.now(timezone.utc) + timedelta(minutes=30)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    response_body = _json.dumps({"token": "sess_tok", "expires_at": expires}).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = response_body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch.dict(os.environ, {"COPILOT_OAUTH_TOKEN": "gho_fake"}):
        with patch("urllib.request.urlopen", return_value=mock_resp):
            with patch("agents.base_agent.OpenAI") as mock_openai:
                mock_openai.return_value = MagicMock()
                from agents.base_agent import BaseAgent
                BaseAgent(model="copilot/gpt-4o")
                call_kwargs = mock_openai.call_args[1]
                assert call_kwargs["base_url"] == "https://api.githubcopilot.com"
                assert call_kwargs["api_key"] == "sess_tok"
                assert call_kwargs["default_headers"]["Copilot-Integration-Id"] == "vscode-chat"


def test_base_agent_copilot_raises_without_token():
    """EnvironmentError is raised when no OAuth token is available."""
    with patch.dict(os.environ, {}, clear=True):
        with patch("builtins.open", side_effect=FileNotFoundError):
            from agents.base_agent import BaseAgent
            try:
                BaseAgent(model="copilot/gpt-4o")
                assert False, "Expected EnvironmentError"
            except EnvironmentError as exc:
                assert "COPILOT_OAUTH_TOKEN" in str(exc)


# ── _ensure_copilot_session ───────────────────────────────────────────────────

def test_ensure_copilot_session_skips_refresh_when_fresh():
    """No token exchange when the cached token is still valid."""
    from datetime import datetime, timezone, timedelta
    import json as _json
    expires = (datetime.now(timezone.utc) + timedelta(minutes=30)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    response_body = _json.dumps({"token": "initial_tok", "expires_at": expires}).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = response_body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch.dict(os.environ, {"COPILOT_OAUTH_TOKEN": "gho_fake"}):
        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
            with patch("agents.base_agent.OpenAI") as mock_openai:
                mock_openai.return_value = MagicMock()
                from agents.base_agent import BaseAgent
                agent = BaseAgent(model="copilot/gpt-4o")
                call_count_after_init = mock_urlopen.call_count
                agent._ensure_copilot_session()
                # No additional urlopen call — token is still fresh
                assert mock_urlopen.call_count == call_count_after_init


def test_ensure_copilot_session_refreshes_when_stale():
    """Token exchange is triggered when cached token has expired."""
    import agents.base_agent as ba_module
    from datetime import datetime, timezone, timedelta
    import json as _json

    expires = (datetime.now(timezone.utc) + timedelta(minutes=30)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    response_body = _json.dumps({"token": "new_tok", "expires_at": expires}).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = response_body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch.dict(os.environ, {"COPILOT_OAUTH_TOKEN": "gho_fake"}):
        with patch("urllib.request.urlopen", return_value=mock_resp):
            with patch("agents.base_agent.OpenAI") as mock_openai:
                mock_openai.return_value = MagicMock()
                # Init with a fresh token so __init__ succeeds
                fresh_expiry = time.time() + 1800
                ba_module._COPILOT_SESSION["expires_at"] = fresh_expiry
                ba_module._COPILOT_SESSION["token"] = "old_tok"
                from agents.base_agent import BaseAgent
                agent = BaseAgent(model="copilot/gpt-4o")

                # Now force expiry
                ba_module._COPILOT_SESSION["expires_at"] = time.time() - 10
                agent._ensure_copilot_session()

                assert ba_module._COPILOT_SESSION["token"] == "new_tok"
