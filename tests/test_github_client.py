# tests/test_github_client.py
import pytest
from unittest.mock import MagicMock, patch
from github_client import GitHubClient


@pytest.fixture
def gc():
    return GitHubClient("owner/repo", github_token="tok")


def test_merge_base_into_branch_clean(gc):
    """Returns 201 when GitHub creates a merge commit."""
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    with patch.object(gc._session, "post", return_value=mock_resp) as mock_post:
        result = gc.merge_base_into_branch("master", "feature/agent/1-my-pr")
    assert result == 201
    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert kwargs["json"]["base"] == "feature/agent/1-my-pr"
    assert kwargs["json"]["head"] == "master"


def test_merge_base_into_branch_up_to_date(gc):
    """Returns 204 when GitHub says already up to date."""
    mock_resp = MagicMock()
    mock_resp.status_code = 204
    with patch.object(gc._session, "post", return_value=mock_resp):
        result = gc.merge_base_into_branch("master", "feature/agent/1-my-pr")
    assert result == 204


def test_merge_base_into_branch_conflict(gc):
    """Returns 409 when GitHub reports a merge conflict."""
    mock_resp = MagicMock()
    mock_resp.status_code = 409
    with patch.object(gc._session, "post", return_value=mock_resp):
        result = gc.merge_base_into_branch("master", "feature/agent/1-my-pr")
    assert result == 409


def test_merge_base_into_branch_unexpected_error(gc):
    """Raises RuntimeError when GitHub returns unexpected status."""
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "Internal Server Error from GitHub"
    with patch.object(gc._session, "post", return_value=mock_resp):
        with pytest.raises(RuntimeError) as exc_info:
            gc.merge_base_into_branch("master", "feature/agent/1-my-pr")
        assert "GitHub merges API failed [500]" in str(exc_info.value)


def test_token_attribute_stored():
    gc = GitHubClient("owner/repo", github_token="fake-token-abc")
    assert gc.token == "fake-token-abc"


def test_token_attribute_stored_from_env(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "env-token-xyz")
    gc = GitHubClient("owner/repo")          # no github_token arg
    assert gc.token == "env-token-xyz"


# ── Session tests (QW-1) ──────────────────────────────────────────────────────

def test_session_created_on_init():
    """GitHubClient creates a requests.Session in __init__."""
    with patch("github_client.requests.Session") as mock_session_cls:
        mock_session_cls.return_value = MagicMock()
        gc = GitHubClient("owner/repo", github_token="tok")
    mock_session_cls.assert_called_once()


def test_session_headers_set_on_init():
    """Session headers include Authorization and Accept."""
    with patch("github_client.requests.Session") as mock_session_cls:
        mock_sess = MagicMock()
        mock_session_cls.return_value = mock_sess
        gc = GitHubClient("owner/repo", github_token="mytoken")
    mock_sess.headers.update.assert_called_once()
    call_kwargs = mock_sess.headers.update.call_args[0][0]
    assert call_kwargs["Authorization"] == "Bearer mytoken"
    assert call_kwargs["Accept"] == "application/vnd.github+json"
    assert "X-GitHub-Api-Version" in call_kwargs


def test_request_uses_session():
    """_request() uses self._session.request, not requests.request."""
    gc = GitHubClient("owner/repo", github_token="tok")
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.text = '{"id": 1}'
    mock_resp.json.return_value = {"id": 1}
    gc._session = MagicMock()
    gc._session.request.return_value = mock_resp
    result = gc._request("GET", "/repos/owner/repo")
    gc._session.request.assert_called_once()
    args, kwargs = gc._session.request.call_args
    assert args[0] == "GET"
    assert args[1] == "https://api.github.com/repos/owner/repo"
    assert result == {"id": 1}


def test_session_closed_on_del():
    """__del__ calls session.close()."""
    gc = GitHubClient("owner/repo", github_token="tok")
    mock_session = MagicMock()
    gc._session = mock_session
    gc.__del__()
    mock_session.close.assert_called_once()
