"""tests/test_watcher_config.py — Tests for load_watcher_config() and repo sub-commands."""
from __future__ import annotations

import logging
import os
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import watcher
from watcher import load_watcher_config, cmd_repo_enable, cmd_repo_disable, cmd_repo_list


# ── load_watcher_config ───────────────────────────────────────────────────────

def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return path


def test_legacy_only(tmp_path):
    """repos.yaml with watchers: list, no repos-enabled/ — unchanged behaviour."""
    cfg = tmp_path / "repos.yaml"
    _write(cfg, """
        watchers:
          - tracker_repo: owner/alpha
            enabled: true
        settings:
          max_parallel: 2
    """)
    result = load_watcher_config(cfg)
    assert len(result["watchers"]) == 1
    assert result["watchers"][0]["tracker_repo"] == "owner/alpha"
    assert result["settings"]["max_parallel"] == 2


def test_repos_enabled_only(tmp_path):
    """repos-enabled/ symlinks with no legacy watchers: list."""
    cfg = tmp_path / "repos.yaml"
    _write(cfg, "settings:\n  max_parallel: 1\n")

    avail = tmp_path / "repos-available"
    avail.mkdir()
    _write(avail / "my-repo.yaml", """
        tracker_repo: owner/my-repo
        feature_label: feature-request
        enabled: true
    """)

    enabled = tmp_path / "repos-enabled"
    enabled.mkdir()
    os.symlink(avail / "my-repo.yaml", enabled / "my-repo.yaml")

    result = load_watcher_config(cfg)
    assert len(result["watchers"]) == 1
    assert result["watchers"][0]["tracker_repo"] == "owner/my-repo"


def test_mixed_legacy_and_enabled(tmp_path):
    """Legacy watchers: entries merged with repos-enabled/ entries."""
    cfg = tmp_path / "repos.yaml"
    _write(cfg, """
        watchers:
          - tracker_repo: owner/legacy
            enabled: true
        settings:
          max_parallel: 3
    """)

    avail = tmp_path / "repos-available"
    avail.mkdir()
    _write(avail / "new-repo.yaml", """
        tracker_repo: owner/new-repo
        feature_label: feature-request
    """)
    enabled = tmp_path / "repos-enabled"
    enabled.mkdir()
    os.symlink(avail / "new-repo.yaml", enabled / "new-repo.yaml")

    result = load_watcher_config(cfg)
    repos = [w["tracker_repo"] for w in result["watchers"]]
    assert "owner/legacy" in repos
    assert "owner/new-repo" in repos
    assert len(repos) == 2


def test_per_watcher_settings_stored(tmp_path):
    """Per-watcher settings: block is stored on the watcher dict as _settings."""
    cfg = tmp_path / "repos.yaml"
    _write(cfg, "settings:\n  model: gpt-4.1\n")

    avail = tmp_path / "repos-available"
    avail.mkdir()
    _write(avail / "fast-repo.yaml", """
        tracker_repo: owner/fast-repo
        feature_label: feature-request
        settings:
          model: gpt-4.1-mini
          num_engineers: 1
    """)
    enabled = tmp_path / "repos-enabled"
    enabled.mkdir()
    os.symlink(avail / "fast-repo.yaml", enabled / "fast-repo.yaml")

    result = load_watcher_config(cfg)
    w = result["watchers"][0]
    assert w["_settings"]["model"] == "gpt-4.1-mini"
    assert w["_settings"]["num_engineers"] == 1
    # settings: key must be removed from the watcher dict itself
    assert "settings" not in w


def test_broken_symlink_skipped(tmp_path, caplog):
    """Broken symlinks in repos-enabled/ are skipped with a warning."""
    import logging
    cfg = tmp_path / "repos.yaml"
    _write(cfg, "settings:\n  max_parallel: 1\n")

    enabled = tmp_path / "repos-enabled"
    enabled.mkdir()
    os.symlink(tmp_path / "repos-available" / "ghost.yaml", enabled / "ghost.yaml")

    with caplog.at_level(logging.WARNING, logger="watcher"):
        result = load_watcher_config(cfg)
    assert "Broken symlink" in caplog.text
    assert result["watchers"] == []


def test_duplicate_tracker_repo_enabled_wins(tmp_path, caplog):
    """If same tracker_repo appears in both legacy and repos-enabled/, enabled wins."""
    import logging
    cfg = tmp_path / "repos.yaml"
    _write(cfg, """
        watchers:
          - tracker_repo: owner/shared
            feature_label: old-label
            enabled: true
        settings:
          max_parallel: 1
    """)

    avail = tmp_path / "repos-available"
    avail.mkdir()
    _write(avail / "shared.yaml", """
        tracker_repo: owner/shared
        feature_label: new-label
        enabled: true
    """)
    enabled = tmp_path / "repos-enabled"
    enabled.mkdir()
    os.symlink(avail / "shared.yaml", enabled / "shared.yaml")

    with caplog.at_level(logging.WARNING, logger="watcher"):
        result = load_watcher_config(cfg)
    assert "Duplicate tracker_repo" in caplog.text
    repos = [w["tracker_repo"] for w in result["watchers"]]
    assert repos.count("owner/shared") == 1
    w = next(w for w in result["watchers"] if w["tracker_repo"] == "owner/shared")
    assert w["feature_label"] == "new-label"


def test_non_yaml_files_in_enabled_are_ignored(tmp_path):
    """README and .conf files in repos-enabled/ are silently skipped."""
    cfg = tmp_path / "repos.yaml"
    _write(cfg, "settings:\n  max_parallel: 1\n")
    enabled = tmp_path / "repos-enabled"
    enabled.mkdir()
    (enabled / "README").write_text("don't parse me")
    (enabled / "repo.conf").write_text("tracker_repo: owner/should-not-appear")

    result = load_watcher_config(cfg)
    assert result["watchers"] == []


def test_missing_tracker_repo_in_enabled_is_skipped(tmp_path, caplog):
    """repos-enabled/ file without tracker_repo is skipped with a warning."""
    import logging
    cfg = tmp_path / "repos.yaml"
    _write(cfg, "settings:\n  max_parallel: 1\n")

    avail = tmp_path / "repos-available"
    avail.mkdir()
    _write(avail / "broken-config.yaml", "feature_label: feature-request\n")

    enabled = tmp_path / "repos-enabled"
    enabled.mkdir()
    os.symlink(avail / "broken-config.yaml", enabled / "broken-config.yaml")

    with caplog.at_level(logging.WARNING, logger="watcher"):
        result = load_watcher_config(cfg)
    assert "no tracker_repo" in caplog.text
    assert result["watchers"] == []


def test_watch_uses_per_watcher_model(tmp_path, monkeypatch):
    """watch() dispatches with per-watcher model override from _settings."""
    cfg = tmp_path / "repos.yaml"
    _write(cfg, """
        settings:
          model: gpt-4.1
          num_engineers: 2
          max_parallel: 1
          log_dir: logs/watcher
    """)

    avail = tmp_path / "repos-available"
    avail.mkdir()
    _write(avail / "cheap-repo.yaml", """
        tracker_repo: owner/cheap-repo
        feature_label: feature-request
        enabled: true
        settings:
          model: gpt-4.1-mini
          num_engineers: 1
    """)
    enabled = tmp_path / "repos-enabled"
    enabled.mkdir()
    os.symlink(avail / "cheap-repo.yaml", enabled / "cheap-repo.yaml")

    dispatched = []

    def fake_get_open_issues(repo, label):
        if label == "feature-request":
            return [{"number": 1, "title": "T", "body": "", "labels": [{"name": "feature-request"}]}]
        return []

    def fake_dispatch(**kwargs):
        dispatched.append(kwargs)
        return SimpleNamespace(
            next_label=None,
            verdict="success",
            tests_passed=True,
            deploy_tests_passed=True,
        )

    monkeypatch.setattr("watcher.get_open_issues", fake_get_open_issues)
    monkeypatch.setattr("watcher._dispatch", fake_dispatch)
    monkeypatch.setattr("watcher.ensure_label", lambda *a, **kw: None)
    monkeypatch.setattr("watcher.add_label", lambda *a, **kw: None)
    monkeypatch.setattr("watcher.remove_label", lambda *a, **kw: None)
    monkeypatch.setattr("watcher.post_comment",  lambda *a, **kw: None)
    monkeypatch.setattr("watcher.check_waiting_issues", lambda *a, **kw: None)
    monkeypatch.setattr("watcher._process_resume_queue", lambda *a, **kw: [])
    monkeypatch.setattr("watcher._load_pipeline_config", lambda: {})
    (tmp_path / "logs" / "watcher").mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("test")
    logger.addHandler(logging.NullHandler())

    watcher.watch(cfg, dry_run=False, logger=logger)

    assert len(dispatched) == 1
    assert dispatched[0]["model"] == "gpt-4.1-mini"
    assert dispatched[0]["num_engineers"] == 1


def test_watch_uses_global_model_when_no_per_watcher_settings(tmp_path, monkeypatch):
    """watch() uses global model when watcher has no _settings."""
    cfg = tmp_path / "repos.yaml"
    _write(cfg, """
        settings:
          model: gpt-4.1
          num_engineers: 2
          max_parallel: 1
          log_dir: logs/watcher
        watchers:
          - tracker_repo: owner/plain-repo
            feature_label: feature-request
            enabled: true
    """)
    (tmp_path / "logs" / "watcher").mkdir(parents=True, exist_ok=True)

    dispatched = []

    def fake_get_open_issues(repo, label):
        if label == "feature-request":
            return [{"number": 1, "title": "T", "body": "", "labels": [{"name": "feature-request"}]}]
        return []

    def fake_dispatch(**kwargs):
        dispatched.append(kwargs)
        return SimpleNamespace(next_label=None, verdict="success", tests_passed=True, deploy_tests_passed=True)

    monkeypatch.setattr("watcher.get_open_issues", fake_get_open_issues)
    monkeypatch.setattr("watcher._dispatch", fake_dispatch)
    monkeypatch.setattr("watcher.ensure_label", lambda *a, **kw: None)
    monkeypatch.setattr("watcher.add_label", lambda *a, **kw: None)
    monkeypatch.setattr("watcher.remove_label", lambda *a, **kw: None)
    monkeypatch.setattr("watcher.post_comment", lambda *a, **kw: None)
    monkeypatch.setattr("watcher.check_waiting_issues", lambda *a, **kw: None)
    monkeypatch.setattr("watcher._process_resume_queue", lambda *a, **kw: [])
    monkeypatch.setattr("watcher._load_pipeline_config", lambda: {})

    logger = logging.getLogger("test")
    logger.addHandler(logging.NullHandler())

    watcher.watch(cfg, dry_run=False, logger=logger)

    assert len(dispatched) == 1
    assert dispatched[0]["model"] == "gpt-4.1"
    assert dispatched[0]["num_engineers"] == 2


# ── repo sub-commands ─────────────────────────────────────────────────────────

def test_repo_enable_creates_symlink(tmp_path):
    """repo enable <name> creates a symlink repos-enabled/<name>.yaml."""
    avail = tmp_path / "repos-available"
    avail.mkdir()
    _write(avail / "mcp-tfl.yaml", "tracker_repo: owner/mcp-tfl\n")

    cmd_repo_enable(tmp_path, "mcp-tfl")

    link = tmp_path / "repos-enabled" / "mcp-tfl.yaml"
    assert link.is_symlink()
    assert link.resolve() == (avail / "mcp-tfl.yaml").resolve()


def test_repo_enable_creates_repos_enabled_dir(tmp_path):
    """repo enable creates repos-enabled/ if it doesn't exist."""
    avail = tmp_path / "repos-available"
    avail.mkdir()
    _write(avail / "my-app.yaml", "tracker_repo: owner/my-app\n")

    assert not (tmp_path / "repos-enabled").exists()
    cmd_repo_enable(tmp_path, "my-app")
    assert (tmp_path / "repos-enabled").is_dir()


def test_repo_enable_error_not_found(tmp_path):
    """repo enable <name> raises SystemExit if the file doesn't exist."""
    (tmp_path / "repos-available").mkdir()
    with pytest.raises(SystemExit):
        cmd_repo_enable(tmp_path, "nonexistent")


def test_repo_enable_error_already_enabled(tmp_path):
    """repo enable raises SystemExit if already enabled."""
    avail = tmp_path / "repos-available"
    avail.mkdir()
    _write(avail / "alpha.yaml", "tracker_repo: owner/alpha\n")
    cmd_repo_enable(tmp_path, "alpha")
    with pytest.raises(SystemExit):
        cmd_repo_enable(tmp_path, "alpha")


def test_repo_disable_removes_symlink(tmp_path):
    """repo disable removes the symlink."""
    avail = tmp_path / "repos-available"
    avail.mkdir()
    _write(avail / "beta.yaml", "tracker_repo: owner/beta\n")
    cmd_repo_enable(tmp_path, "beta")
    assert (tmp_path / "repos-enabled" / "beta.yaml").exists()

    cmd_repo_disable(tmp_path, "beta")
    assert not (tmp_path / "repos-enabled" / "beta.yaml").exists()
    # source file must still be there
    assert (avail / "beta.yaml").exists()


def test_repo_disable_error_not_enabled(tmp_path):
    """repo disable raises SystemExit if not currently enabled."""
    (tmp_path / "repos-available").mkdir()
    (tmp_path / "repos-enabled").mkdir()
    with pytest.raises(SystemExit):
        cmd_repo_disable(tmp_path, "unknown")


def test_repo_list_output(tmp_path, capsys):
    """repo list prints [enabled] / [disabled] status."""
    avail = tmp_path / "repos-available"
    avail.mkdir()
    _write(avail / "repo-a.yaml", "tracker_repo: owner/a\n")
    _write(avail / "repo-b.yaml", "tracker_repo: owner/b\n")
    cmd_repo_enable(tmp_path, "repo-a")

    cmd_repo_list(tmp_path)
    out = capsys.readouterr().out
    assert "repo-a" in out and "enabled" in out
    assert "repo-b" in out and "disabled" in out


def test_repo_list_empty(tmp_path, capsys):
    """repo list on empty repos-available/ prints a helpful message."""
    (tmp_path / "repos-available").mkdir()
    cmd_repo_list(tmp_path)
    out = capsys.readouterr().out
    assert "No repos found" in out
