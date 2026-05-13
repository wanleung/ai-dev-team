"""Extended CLI tests for check.py commands.

Tests CLI commands using both subprocess calls and direct function calls
with mocked dependencies to cover edge cases and error scenarios.
"""
import subprocess
import sys
import pathlib
from unittest.mock import patch, MagicMock
import pytest
import yaml
import requests

import check

_CWD = pathlib.Path(__file__).parent.parent.resolve()


def _run_check(*args):
    """Run check.py as subprocess and return (returncode, stdout, stderr)."""
    result = subprocess.run(
        [sys.executable, "check.py"] + list(args),
        capture_output=True,
        text=True,
        cwd=str(_CWD)
    )
    return result.returncode, result.stdout, result.stderr


# ── validate-config tests ────────────────────────────────────────────────────

def test_validate_config_missing_file(tmp_path):
    """validate-config exits 1 when config file doesn't exist."""
    missing = tmp_path / "nonexistent.yaml"
    code, out, err = _run_check("validate-config", "--config", str(missing))
    assert code == 1
    combined = out + err
    assert "not found" in combined.lower() or "❌" in combined


def test_validate_config_empty_file(tmp_path):
    """validate-config handles empty config file (uses defaults)."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("")
    code, out, err = _run_check("validate-config", "--config", str(cfg_file))
    # Empty file is valid because schema provides defaults
    assert code == 0
    combined = out + err
    assert "✅" in combined or "valid" in combined.lower()


def test_validate_config_malformed_yaml(tmp_path):
    """validate-config exits 1 on malformed YAML."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("invalid: yaml: structure:\n  bad indent")
    code, out, err = _run_check("validate-config", "--config", str(cfg_file))
    assert code == 1


def test_validate_config_repos_optional(tmp_path):
    """validate-config succeeds when repos.yaml is missing (optional)."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump({"llm": {"model": "gpt-4.1"}}))
    missing_repos = tmp_path / "nonexistent_repos.yaml"
    code, out, err = _run_check(
        "validate-config",
        "--config", str(cfg_file),
        "--repos", str(missing_repos)
    )
    # Should warn but not fail since repos.yaml is optional
    assert code == 0
    combined = out + err
    assert "optional" in combined.lower() or "⚠️" in combined


def test_validate_config_with_repos(tmp_path):
    """validate-config validates both config and repos successfully."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump({
        "llm": {"model": "gpt-4.1"},
        "github": {"repo": "owner/repo"}
    }))
    
    repos_file = tmp_path / "repos.yaml"
    repos_file.write_text(yaml.dump({
        "watchers": [
            {
                "tracker_repo": "owner/repo1",
                "enabled": True,
                "parallel_issues": 2
            }
        ]
    }))
    
    code, out, err = _run_check(
        "validate-config",
        "--config", str(cfg_file),
        "--repos", str(repos_file)
    )
    assert code == 0
    combined = out + err
    assert "✅" in combined or "valid" in combined.lower()


def test_validate_config_repos_invalid_entry(tmp_path):
    """validate-config catches invalid repo entries."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump({"llm": {"model": "gpt-4.1"}}))
    
    repos_file = tmp_path / "repos.yaml"
    repos_file.write_text(yaml.dump({
        "watchers": [
            {
                "tracker_repo": "owner/repo1",
                "parallel_issues": "not_a_number"  # Invalid
            }
        ]
    }))
    
    code, out, err = _run_check(
        "validate-config",
        "--config", str(cfg_file),
        "--repos", str(repos_file)
    )
    assert code == 1
    combined = out + err
    assert "❌" in combined or "error" in combined.lower()


def test_validate_config_default_paths():
    """validate-config runs without crashing when using default paths."""
    # This will fail in tmp test dir but tests that defaults work
    code, out, err = _run_check("validate-config")
    # Exit code depends on whether default files exist in test env
    # Just verify it doesn't crash with an unhandled exception
    assert code in (0, 1)  # Either succeeds or fails, but doesn't crash
    assert "Traceback" not in out + err  # Must not crash with a Python traceback


# ── test-github tests ─────────────────────────────────────────────────────────

def test_test_github_no_token():
    """test-github exits 1 when no token provided and env not set."""
    with patch.dict("os.environ", {}, clear=True):
        code = check.cmd_test_github(repo="", token=None)
    assert code == 1


def test_test_github_token_from_env():
    """test-github reads token from GITHUB_TOKEN environment variable."""
    user_resp = MagicMock()
    user_resp.ok = True
    user_resp.status_code = 200
    user_resp.json.return_value = {"login": "envuser"}
    user_resp.headers = {
        "X-OAuth-Scopes": "repo",
        "X-RateLimit-Remaining": "5000",
        "X-RateLimit-Reset": "9999999999"
    }
    
    with patch.dict("os.environ", {"GITHUB_TOKEN": "env_token"}):
        with patch("requests.get", return_value=user_resp):
            code = check.cmd_test_github(repo="", token=None)
    assert code == 0


def test_test_github_network_error():
    """test-github handles network errors gracefully."""
    with patch("requests.get", side_effect=requests.exceptions.ConnectionError("Network down")):
        code = check.cmd_test_github(repo="", token="faketoken")
    assert code == 1


def test_test_github_timeout():
    """test-github handles request timeouts."""
    with patch("requests.get", side_effect=requests.exceptions.Timeout("Request timed out")):
        code = check.cmd_test_github(repo="", token="faketoken")
    assert code == 1


def test_test_github_invalid_json_response():
    """test-github handles invalid JSON in error response."""
    resp = MagicMock()
    resp.ok = False
    resp.status_code = 403
    resp.json.side_effect = ValueError("Invalid JSON")
    resp.text = "Raw error text"
    
    with patch("requests.get", return_value=resp):
        code = check.cmd_test_github(repo="", token="badtoken")
    assert code == 1


def test_test_github_repo_no_push_access():
    """test-github exits 1 when repo has no push access (pipeline cannot commit code)."""
    user_resp = MagicMock()
    user_resp.ok = True
    user_resp.json.return_value = {"login": "testuser"}
    user_resp.headers = {
        "X-OAuth-Scopes": "repo",
        "X-RateLimit-Remaining": "5000",
        "X-RateLimit-Reset": "9999999999"
    }
    
    repo_resp = MagicMock()
    repo_resp.ok = True
    repo_resp.status_code = 200
    repo_resp.json.return_value = {
        "full_name": "owner/repo",
        "permissions": {"push": False},  # No push access
        "default_branch": "main"
    }
    
    with patch("requests.get", side_effect=[user_resp, repo_resp]):
        code = check.cmd_test_github(repo="owner/repo", token="faketoken")
    # Should warn but set error
    assert code == 1


def test_test_github_repo_not_found():
    """test-github handles 404 for non-existent repo."""
    user_resp = MagicMock()
    user_resp.ok = True
    user_resp.json.return_value = {"login": "testuser"}
    user_resp.headers = {
        "X-OAuth-Scopes": "repo",
        "X-RateLimit-Remaining": "5000",
        "X-RateLimit-Reset": "9999999999"
    }
    
    repo_resp = MagicMock()
    repo_resp.ok = False
    repo_resp.status_code = 404
    repo_resp.json.return_value = {"message": "Not Found"}
    
    with patch("requests.get", side_effect=[user_resp, repo_resp]):
        code = check.cmd_test_github(repo="owner/nonexistent", token="faketoken")
    assert code == 1


def test_test_github_rate_limit_info():
    """test-github displays rate limit information correctly."""
    from datetime import datetime, timezone, timedelta
    
    future_time = datetime.now(tz=timezone.utc) + timedelta(minutes=30)
    reset_ts = str(int(future_time.timestamp()))
    
    user_resp = MagicMock()
    user_resp.ok = True
    user_resp.json.return_value = {"login": "testuser"}
    user_resp.headers = {
        "X-OAuth-Scopes": "repo,workflow",
        "X-RateLimit-Remaining": "4500",
        "X-RateLimit-Reset": reset_ts
    }
    
    with patch("requests.get", return_value=user_resp):
        code = check.cmd_test_github(repo="", token="faketoken")
    assert code == 0


def test_test_github_repo_success():
    """test-github exits 0 when token is valid and repo has push access."""
    user_resp = MagicMock()
    user_resp.ok = True
    user_resp.json.return_value = {"login": "testuser"}
    user_resp.headers = {
        "X-OAuth-Scopes": "repo",
        "X-RateLimit-Remaining": "5000",
        "X-RateLimit-Reset": "9999999999",
    }

    repo_resp = MagicMock()
    repo_resp.ok = True
    repo_resp.json.return_value = {
        "full_name": "owner/repo",
        "permissions": {"push": True},
        "default_branch": "main",
    }

    with patch("requests.get", side_effect=[user_resp, repo_resp]):
        code = check.cmd_test_github(repo="owner/repo", token="faketoken")
    assert code == 0


def test_test_github_repo_network_error_on_second_call():
    """test-github handles network error when checking repo after successful auth."""
    user_resp = MagicMock()
    user_resp.ok = True
    user_resp.json.return_value = {"login": "testuser"}
    user_resp.headers = {
        "X-OAuth-Scopes": "repo",
        "X-RateLimit-Remaining": "5000",
        "X-RateLimit-Reset": "9999999999"
    }
    
    with patch("requests.get", side_effect=[user_resp, requests.exceptions.RequestException("Network error")]):
        code = check.cmd_test_github(repo="owner/repo", token="faketoken")
    assert code == 1


# ── main/CLI integration tests ────────────────────────────────────────────────

def test_cli_no_command():
    """CLI exits with error when no command provided."""
    code, out, err = _run_check()
    assert code != 0
    combined = out + err
    assert "required" in combined.lower() or "usage" in combined.lower()


def test_cli_invalid_command():
    """CLI exits with error for invalid command."""
    code, out, err = _run_check("invalid-command")
    assert code != 0
    combined = out + err
    assert "invalid" in combined.lower() or "unrecognized" in combined.lower()


def test_cli_help():
    """CLI shows help message."""
    code, out, err = _run_check("--help")
    combined = out + err
    assert "validate-config" in combined
    assert "test-github" in combined


def test_validate_config_help():
    """validate-config subcommand shows help."""
    code, out, err = _run_check("validate-config", "--help")
    combined = out + err
    assert "--config" in combined
    assert "--repos" in combined


def test_test_github_help():
    """test-github subcommand shows help."""
    code, out, err = _run_check("test-github", "--help")
    combined = out + err
    assert "--repo" in combined
    assert "--token" in combined
