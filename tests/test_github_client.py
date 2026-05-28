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


def test_request_error_redacts_token():
    """RuntimeError from _request() must not contain the raw token."""
    gc = GitHubClient("owner/repo", github_token="supersecret")
    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 401  # not in _RETRYABLE, raises immediately
    mock_resp.text = "https://x-access-token:supersecret@github.com/owner/repo: error"

    gc._session = MagicMock()
    gc._session.request.return_value = mock_resp
    with pytest.raises(RuntimeError) as exc_info:
        gc._request("GET", "/repos/owner/repo")
    assert "supersecret" not in str(exc_info.value)
    assert "***" in str(exc_info.value)


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


class TestCommitFileShaRetry:
    """commit_file retries once with a fresh SHA on 409 conflict."""

    def test_commit_file_success_no_retry(self, gc):
        """Happy path: first PUT succeeds."""
        get_resp = MagicMock()
        get_resp.ok = True
        get_resp.status_code = 200
        get_resp.text = '{"sha": "abc123"}'
        get_resp.json.return_value = {"sha": "abc123"}

        put_resp = MagicMock()
        put_resp.ok = True
        put_resp.status_code = 200
        put_resp.text = '{"commit": {}}'
        put_resp.json.return_value = {"commit": {}}

        with patch.object(gc._session, "request", side_effect=[get_resp, put_resp]) as mock_req:
            result = gc.commit_file("src/foo.py", "content", "feat: add foo", "main")

        assert result == {"commit": {}}
        assert mock_req.call_count == 2  # GET (check existing) + PUT

    def test_commit_file_409_retries_with_fresh_sha(self, gc):
        """On 409, fetches fresh SHA and retries the PUT once."""
        # GET for existing file on first commit attempt
        get_existing = MagicMock()
        get_existing.ok = True
        get_existing.status_code = 200
        get_existing.text = '{"sha": "stale-sha"}'
        get_existing.json.return_value = {"sha": "stale-sha"}

        # PUT fails with 409
        put_fail = MagicMock()
        put_fail.ok = False
        put_fail.status_code = 409
        put_fail.text = '{"message":"is at fresh-sha but expected stale-sha"}'

        # GET for fresh SHA (retry step)
        get_fresh = MagicMock()
        get_fresh.ok = True
        get_fresh.status_code = 200
        get_fresh.text = '{"sha": "fresh-sha"}'
        get_fresh.json.return_value = {"sha": "fresh-sha"}

        # Second PUT succeeds
        put_ok = MagicMock()
        put_ok.ok = True
        put_ok.status_code = 200
        put_ok.text = '{"commit": {"sha": "new-commit"}}'
        put_ok.json.return_value = {"commit": {"sha": "new-commit"}}

        with patch.object(gc._session, "request",
                          side_effect=[get_existing, put_fail, get_fresh, put_ok]) as mock_req:
            result = gc.commit_file("src/foo.py", "content", "feat: add foo", "main")

        assert result == {"commit": {"sha": "new-commit"}}
        assert mock_req.call_count == 4  # GET existing, PUT fail, GET fresh, PUT success
        # Verify the retry PUT used the fresh SHA
        retry_put_call = mock_req.call_args_list[3]
        assert retry_put_call[1]["json"]["sha"] == "fresh-sha"

    def test_commit_file_409_no_second_retry(self, gc):
        """Does NOT retry a second time if the retry also returns 409."""
        get_existing = MagicMock()
        get_existing.ok = True
        get_existing.status_code = 200
        get_existing.text = '{"sha": "sha1"}'
        get_existing.json.return_value = {"sha": "sha1"}

        put_fail = MagicMock()
        put_fail.ok = False
        put_fail.status_code = 409
        put_fail.text = '{"message":"is at sha2 but expected sha1"}'

        get_fresh = MagicMock()
        get_fresh.ok = True
        get_fresh.status_code = 200
        get_fresh.text = '{"sha": "sha2"}'
        get_fresh.json.return_value = {"sha": "sha2"}

        put_fail2 = MagicMock()
        put_fail2.ok = False
        put_fail2.status_code = 409
        put_fail2.text = '{"message":"is at sha3 but expected sha2"}'

        with patch.object(gc._session, "request",
                          side_effect=[get_existing, put_fail, get_fresh,
                                       put_fail2, put_fail2, put_fail2]):
            with pytest.raises(RuntimeError, match="409"):
                gc.commit_file("src/foo.py", "content", "feat: add foo", "main")
