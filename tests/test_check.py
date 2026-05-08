import subprocess, sys
import pathlib
from unittest.mock import patch, MagicMock
import check

_CWD = pathlib.Path(__file__).parent.parent.resolve()

def _run_check(*args):
    """Run check.py as subprocess and return (returncode, stdout)."""
    result = subprocess.run(
        [sys.executable, "check.py"] + list(args),
        capture_output=True, text=True,
        cwd=str(_CWD)
    )
    return result.returncode, result.stdout + result.stderr

def test_validate_config_valid(tmp_path):
    """Valid config.yaml exits 0."""
    import yaml
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump({"llm": {"model": "gpt-4.1"}}))
    code, out = _run_check("validate-config", "--config", str(cfg_file))
    assert code == 0
    assert "✅" in out or "valid" in out.lower()

def test_validate_config_invalid(tmp_path):
    """Invalid config.yaml exits 1 with error details."""
    import yaml
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump({"unknown_top_level": "bad"}))
    code, out = _run_check("validate-config", "--config", str(cfg_file))
    assert code == 1
    assert "❌" in out or "error" in out.lower()

def test_test_github_success(monkeypatch):
    """test-github subcommand exits 0 when token and repo are valid."""
    monkeypatch.setenv("GITHUB_TOKEN", "faketoken")

    user_resp = MagicMock()
    user_resp.ok = True
    user_resp.status_code = 200
    user_resp.json.return_value = {"login": "testuser"}
    user_resp.headers = {"X-OAuth-Scopes": "repo", "X-RateLimit-Remaining": "4999", "X-RateLimit-Reset": "9999999999"}

    repo_resp = MagicMock()
    repo_resp.ok = True
    repo_resp.status_code = 200
    repo_resp.json.return_value = {"full_name": "owner/repo", "permissions": {"push": True}}

    with patch("requests.get", side_effect=[user_resp, repo_resp]):
        code = check.cmd_test_github(repo="owner/repo", token="faketoken")
    assert code == 0

def test_test_github_bad_token(monkeypatch):
    """test-github exits 1 when token is invalid (401)."""
    monkeypatch.setenv("GITHUB_TOKEN", "badtoken")
    resp = MagicMock()
    resp.ok = False
    resp.status_code = 401
    resp.json.return_value = {"message": "Bad credentials"}

    with patch("requests.get", return_value=resp):
        code = check.cmd_test_github(repo="owner/repo", token="badtoken")
    assert code == 1
