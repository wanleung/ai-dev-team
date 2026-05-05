"""tests/test_watcher_config.py — Tests for load_watcher_config() and repo sub-commands."""
from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest
import yaml

import watcher
from watcher import load_watcher_config


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


def test_broken_symlink_skipped(tmp_path):
    """Broken symlinks in repos-enabled/ are skipped with a warning."""
    cfg = tmp_path / "repos.yaml"
    _write(cfg, "settings:\n  max_parallel: 1\n")

    enabled = tmp_path / "repos-enabled"
    enabled.mkdir()
    # Symlink pointing to a non-existent file
    os.symlink(tmp_path / "repos-available" / "ghost.yaml", enabled / "ghost.yaml")

    result = load_watcher_config(cfg)
    assert result["watchers"] == []


def test_duplicate_tracker_repo_enabled_wins(tmp_path):
    """If same tracker_repo appears in both legacy and repos-enabled/, enabled wins."""
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

    result = load_watcher_config(cfg)
    repos = [w["tracker_repo"] for w in result["watchers"]]
    assert repos.count("owner/shared") == 1
    w = next(w for w in result["watchers"] if w["tracker_repo"] == "owner/shared")
    assert w["feature_label"] == "new-label"
