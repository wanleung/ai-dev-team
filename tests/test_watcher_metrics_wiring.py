"""Tests that watch() wires the metrics callback when metrics_url is configured."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml


def _write_minimal_config(tmp_path: Path, settings: dict | None = None) -> Path:
    """Write a minimal watchers.yml with an empty watchers list."""
    config = {
        "settings": settings or {},
        "watchers": [],
    }
    path = tmp_path / "watchers.yml"
    path.write_text(yaml.dump(config))
    return path


def _apply_common_patches(monkeypatch) -> None:
    """Apply patches that prevent real I/O or GitHub calls in all wiring tests."""
    # Prevent pipeline config from reading real config.yaml (which may not validate)
    monkeypatch.setattr(
        "watcher._load_pipeline_config",
        MagicMock(return_value={"pipeline": {}, "github": {}}),
    )
    # Prevent log directory creation
    monkeypatch.setattr("watcher._setup_logging", MagicMock(return_value=MagicMock()))
    # Prevent context-var side effects
    monkeypatch.setattr("watcher.bind_run_id", MagicMock())
    # Prevent real GitHub calls
    monkeypatch.setattr("watcher.check_waiting_issues", MagicMock())
    monkeypatch.setattr("watcher._watch_prs", MagicMock())
    monkeypatch.setattr("watcher._process_resume_queue", MagicMock(return_value=[]))


def test_watch_wires_metrics_callback_when_url_set(tmp_path, monkeypatch):
    """watch() must call set_emit_callback(fn) exactly once when metrics_url is set."""
    config_path = _write_minimal_config(
        tmp_path, settings={"metrics_url": "http://localhost:9091"}
    )

    _apply_common_patches(monkeypatch)

    wired = []
    monkeypatch.setattr("core.events.set_emit_callback", lambda fn: wired.append(fn))

    from watcher import watch

    watch(config_path)  # returns naturally: watchers=[] → tasks=[] → "Nothing to do"

    assert len(wired) == 1, "set_emit_callback should be called exactly once"
    assert callable(wired[0]), "the argument passed to set_emit_callback must be callable"


def test_watch_skips_metrics_wiring_when_url_absent(tmp_path, monkeypatch):
    """watch() must NOT call set_emit_callback when metrics_url is absent."""
    config_path = _write_minimal_config(tmp_path, settings={})  # no metrics_url

    _apply_common_patches(monkeypatch)

    wired = []
    monkeypatch.setattr("core.events.set_emit_callback", lambda fn: wired.append(fn))

    from watcher import watch

    watch(config_path)

    assert len(wired) == 0, "set_emit_callback should NOT be called without metrics_url"
