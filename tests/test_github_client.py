# tests/test_github_client.py
import pytest
from unittest.mock import patch, MagicMock
from github_client import GitHubClient


@pytest.fixture
def gc():
    return GitHubClient("owner/repo", github_token="tok")


def test_merge_base_into_branch_clean(gc):
    """Returns 201 when GitHub creates a merge commit."""
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    with patch("requests.post", return_value=mock_resp) as mock_post:
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
    with patch("requests.post", return_value=mock_resp):
        result = gc.merge_base_into_branch("master", "feature/agent/1-my-pr")
    assert result == 204


def test_merge_base_into_branch_conflict(gc):
    """Returns 409 when GitHub reports a merge conflict."""
    mock_resp = MagicMock()
    mock_resp.status_code = 409
    with patch("requests.post", return_value=mock_resp):
        result = gc.merge_base_into_branch("master", "feature/agent/1-my-pr")
    assert result == 409


def test_merge_base_into_branch_unexpected_error(gc):
    """Raises RuntimeError when GitHub returns unexpected status."""
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "Internal Server Error from GitHub"
    with patch("requests.post", return_value=mock_resp):
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
