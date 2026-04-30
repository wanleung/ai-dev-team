"""Tests for watcher --once mode."""
import sys
from unittest.mock import patch, MagicMock


def test_once_mode_flags_parse():
    """`watcher.py --once --repo X --issue N --label L` parses correctly."""
    from watcher import _build_arg_parser

    parser = _build_arg_parser()
    args = parser.parse_args([
        "--once",
        "--repo", "owner/r",
        "--issue", "42",
        "--label", "ai-feature",
    ])
    assert args.once is True
    assert args.repo == "owner/r"
    assert args.issue == 42
    assert args.label == "ai-feature"


def test_once_dispatches_single_issue(monkeypatch):
    """`run_once(...)` calls _dispatch with the right args and exits."""
    from watcher import run_once

    called: dict = {}

    def fake_dispatch(**kwargs):
        called.update(kwargs)

    monkeypatch.setattr("watcher._dispatch", fake_dispatch)
    monkeypatch.setattr("watcher._load_pipeline_config", lambda: {})

    rc = run_once(repo="owner/r", issue=42, label="ai-feature", logger=MagicMock())
    assert rc == 0
    assert called["label"] == "ai-feature"
    assert called["tracker_repo"] == "owner/r"
    assert called["issue_number"] == 42
