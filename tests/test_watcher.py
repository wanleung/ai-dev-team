"""
tests/test_watcher.py — Unit tests for watcher.py pipeline dispatch and issue queuing.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch, call
import tempfile
import logging

import pytest
import yaml

import watcher
from watcher import _dispatch, watch


# ── Shared fixture — prevent _dispatch from reading real config.yaml ──────────

@pytest.fixture(autouse=True)
def _no_pipeline_config(monkeypatch):
    """Prevent _dispatch from loading config.yaml so tests control model/settings."""
    monkeypatch.setattr("watcher._load_pipeline_config", lambda: {})


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_logger() -> logging.Logger:
    logger = logging.getLogger("test_watcher")
    logger.addHandler(logging.NullHandler())
    return logger


def _make_issue(number: int = 1, title: str = "Test issue", labels: list[str] | None = None) -> dict:
    """Build a minimal GitHub issue dict."""
    return {
        "number": number,
        "title": title,
        "body": "",
        "labels": [{"name": lbl} for lbl in (labels or [])],
    }


def _stub_dispatch_args(pipeline_type: str, tmp_path: Path) -> dict:
    """Return a minimal set of kwargs for _dispatch."""
    return dict(
        pipeline_type=pipeline_type,
        tracker_repo="owner/tracker",
        target_repo="owner/target",
        issue_number=42,
        model="gpt-4.1",
        num_engineers=1,
        log_file=tmp_path / "issue-42.log",
        logger=_make_logger(),
    )


# ── _dispatch: feature pipeline ───────────────────────────────────────────────

class TestDispatchFeature:
    def test_dispatch_feature_imports_orchestrator(self, tmp_path: Path) -> None:
        """_dispatch with pipeline_type='feature' calls Orchestrator.run()."""
        mock_orch_instance = MagicMock()
        mock_orch_class = MagicMock(return_value=mock_orch_instance)
        mock_gh_client = MagicMock()
        mock_gh_client.return_value.get_issue.return_value = {
            "title": "Add feature",
            "body": "Some description",
        }

        with patch.dict("sys.modules", {
            "orchestrator": MagicMock(Orchestrator=mock_orch_class),
            "github_client": MagicMock(GitHubClient=mock_gh_client, parse_target_repo=lambda b: None),
        }):
            _dispatch(**_stub_dispatch_args("feature", tmp_path))

        mock_orch_class.assert_called_once()
        mock_orch_instance.run.assert_called_once()

    def test_dispatch_feature_log_file_created(self, tmp_path: Path) -> None:
        """_dispatch creates its log file for a feature pipeline."""
        mock_orch_instance = MagicMock()
        mock_orch_class = MagicMock(return_value=mock_orch_instance)
        mock_gh_client = MagicMock()
        mock_gh_client.return_value.get_issue.return_value = {
            "title": "Add feature",
            "body": "",
        }

        log_file = tmp_path / "issue-42-feature.log"
        kwargs = _stub_dispatch_args("feature", tmp_path)
        kwargs["log_file"] = log_file

        with patch.dict("sys.modules", {
            "orchestrator": MagicMock(Orchestrator=mock_orch_class),
            "github_client": MagicMock(GitHubClient=mock_gh_client, parse_target_repo=lambda b: None),
        }):
            _dispatch(**kwargs)

        assert log_file.exists()


# ── _dispatch: bug pipeline ───────────────────────────────────────────────────

class TestDispatchBug:
    def test_dispatch_bug_imports_bugfixorchestrator(self, tmp_path: Path) -> None:
        """_dispatch with pipeline_type='bug' calls BugFixOrchestrator.run()."""
        mock_orch_instance = MagicMock()
        mock_orch_class = MagicMock(return_value=mock_orch_instance)

        with patch.dict("sys.modules", {
            "bug_fix_orchestrator": MagicMock(BugFixOrchestrator=mock_orch_class),
        }):
            _dispatch(**_stub_dispatch_args("bug", tmp_path))

        mock_orch_class.assert_called_once()
        mock_orch_instance.run.assert_called_once_with(issue_number=42)

    def test_dispatch_bug_passes_issue_number(self, tmp_path: Path) -> None:
        """_dispatch passes the correct issue_number to BugFixOrchestrator.run()."""
        mock_orch_instance = MagicMock()
        mock_orch_class = MagicMock(return_value=mock_orch_instance)

        kwargs = _stub_dispatch_args("bug", tmp_path)
        kwargs["issue_number"] = 99

        with patch.dict("sys.modules", {
            "bug_fix_orchestrator": MagicMock(BugFixOrchestrator=mock_orch_class),
        }):
            _dispatch(**kwargs)

        mock_orch_instance.run.assert_called_once_with(issue_number=99)


# ── _dispatch: documentation pipeline ────────────────────────────────────────

class TestDispatchDocumentation:
    def test_dispatch_documentation_imports_docorchestrator(self, tmp_path: Path) -> None:
        """_dispatch with pipeline_type='documentation' calls DocOrchestrator.run()."""
        mock_orch_instance = MagicMock()
        mock_orch_class = MagicMock(return_value=mock_orch_instance)

        with patch.dict("sys.modules", {
            "doc_orchestrator": MagicMock(DocOrchestrator=mock_orch_class),
        }):
            _dispatch(**_stub_dispatch_args("documentation", tmp_path))

        mock_orch_class.assert_called_once()
        mock_orch_instance.run.assert_called_once_with(issue_number=42)

    def test_dispatch_documentation_passes_issue_number(self, tmp_path: Path) -> None:
        """_dispatch passes the correct issue_number to DocOrchestrator.run()."""
        mock_orch_instance = MagicMock()
        mock_orch_class = MagicMock(return_value=mock_orch_instance)

        kwargs = _stub_dispatch_args("documentation", tmp_path)
        kwargs["issue_number"] = 7

        with patch.dict("sys.modules", {
            "doc_orchestrator": MagicMock(DocOrchestrator=mock_orch_class),
        }):
            _dispatch(**kwargs)

        mock_orch_instance.run.assert_called_once_with(issue_number=7)

    def test_dispatch_documentation_passes_model_and_repo(self, tmp_path: Path) -> None:
        """_dispatch passes model, github_token, and github_repo to DocOrchestrator."""
        mock_orch_instance = MagicMock()
        mock_orch_class = MagicMock(return_value=mock_orch_instance)

        kwargs = _stub_dispatch_args("documentation", tmp_path)
        kwargs["model"] = "gpt-4o"
        kwargs["tracker_repo"] = "myorg/myrepo"

        with patch.dict("sys.modules", {
            "doc_orchestrator": MagicMock(DocOrchestrator=mock_orch_class),
        }):
            _dispatch(**kwargs)

        # DocOrchestrator is constructed with model, github_token, github_repo
        call_kwargs = mock_orch_class.call_args.kwargs
        assert call_kwargs.get("model") == "gpt-4o"
        assert call_kwargs.get("github_repo") == "myorg/myrepo"
        assert "github_token" in call_kwargs


# ── watch(): queuing logic ────────────────────────────────────────────────────

def _write_config(tmp_path: Path, extra_watcher_keys: dict | None = None) -> Path:
    """Write a minimal repos.yaml to tmp_path and return its path."""
    watcher_entry: dict = {
        "tracker_repo": "owner/repo",
        "default_target": None,
        "feature_label": "feature-request",
        "bug_label": "bug",
        "doc_label": "documentation",
        "enabled": True,
    }
    if extra_watcher_keys:
        watcher_entry.update(extra_watcher_keys)

    config = {
        "settings": {
            "max_parallel": 1,
            "log_dir": str(tmp_path / "logs"),
            "model": "gpt-4.1",
            "num_engineers": 1,
        },
        "watchers": [watcher_entry],
    }
    cfg_path = tmp_path / "repos.yaml"
    cfg_path.write_text(yaml.dump(config))
    return cfg_path


class TestWatchQueuing:
    """Tests that watch() queues issues with the correct pipeline_type."""

    @patch("watcher.run_pipeline")
    @patch("watcher.add_label")
    @patch("watcher.ensure_label")
    @patch("watcher.get_open_issues")
    def test_watch_queues_feature_issues(
        self,
        mock_get_issues: MagicMock,
        mock_ensure: MagicMock,
        mock_add_label: MagicMock,
        mock_run_pipeline: MagicMock,
        tmp_path: Path,
    ) -> None:
        """watch() queues open feature issues with pipeline_type='feature'."""
        feature_issue = _make_issue(number=10, title="New feature")

        def side_effect(repo: str, label) -> list:
            if label == "feature-request" or label == ["feature-request"]:
                return [feature_issue]
            return []

        mock_get_issues.side_effect = side_effect
        mock_run_pipeline.return_value = True

        cfg = _write_config(tmp_path)
        watch(cfg, dry_run=True, logger=_make_logger())

        # At least one call with feature pipeline_type
        calls = mock_run_pipeline.call_args_list
        types = [c.args[3] if c.args else c.kwargs.get("pipeline_type") for c in calls]
        assert "feature" in types

    @patch("watcher.run_pipeline")
    @patch("watcher.add_label")
    @patch("watcher.ensure_label")
    @patch("watcher.get_open_issues")
    def test_watch_queues_bug_issues(
        self,
        mock_get_issues: MagicMock,
        mock_ensure: MagicMock,
        mock_add_label: MagicMock,
        mock_run_pipeline: MagicMock,
        tmp_path: Path,
    ) -> None:
        """watch() queues open bug issues with pipeline_type='bug'."""
        bug_issue = _make_issue(number=20, title="Crash on startup")

        def side_effect(repo: str, label) -> list:
            if label == "bug" or label == ["bug"]:
                return [bug_issue]
            return []

        mock_get_issues.side_effect = side_effect
        mock_run_pipeline.return_value = True

        cfg = _write_config(tmp_path)
        watch(cfg, dry_run=True, logger=_make_logger())

        calls = mock_run_pipeline.call_args_list
        types = [c.args[3] if c.args else c.kwargs.get("pipeline_type") for c in calls]
        assert "bug" in types

    @patch("watcher.run_pipeline")
    @patch("watcher.add_label")
    @patch("watcher.ensure_label")
    @patch("watcher.get_open_issues")
    def test_watch_queues_doc_issues(
        self,
        mock_get_issues: MagicMock,
        mock_ensure: MagicMock,
        mock_add_label: MagicMock,
        mock_run_pipeline: MagicMock,
        tmp_path: Path,
    ) -> None:
        """watch() queues issues labelled 'documentation' with pipeline_type='documentation'."""
        doc_issue = _make_issue(number=30, title="Write API docs")

        def side_effect(repo: str, label) -> list:
            if label == "documentation" or label == ["documentation"]:
                return [doc_issue]
            return []

        mock_get_issues.side_effect = side_effect
        mock_run_pipeline.return_value = True

        cfg = _write_config(tmp_path)
        watch(cfg, dry_run=True, logger=_make_logger())

        calls = mock_run_pipeline.call_args_list
        types = [c.args[3] if c.args else c.kwargs.get("pipeline_type") for c in calls]
        assert "documentation" in types

    @patch("watcher.run_pipeline")
    @patch("watcher.add_label")
    @patch("watcher.ensure_label")
    @patch("watcher.get_open_issues")
    def test_watch_skips_disabled_watchers(
        self,
        mock_get_issues: MagicMock,
        mock_ensure: MagicMock,
        mock_add_label: MagicMock,
        mock_run_pipeline: MagicMock,
        tmp_path: Path,
    ) -> None:
        """watch() does not process issues from disabled watcher entries."""
        doc_issue = _make_issue(number=31, title="Docs for disabled watcher")
        mock_get_issues.return_value = [doc_issue]
        mock_run_pipeline.return_value = True

        cfg = _write_config(tmp_path, extra_watcher_keys={"enabled": False})
        watch(cfg, dry_run=True, logger=_make_logger())

        mock_get_issues.assert_not_called()
        mock_run_pipeline.assert_not_called()

    @patch("watcher.run_pipeline")
    @patch("watcher.add_label")
    @patch("watcher.ensure_label")
    @patch("watcher.get_open_issues")
    def test_watch_uses_default_doc_label_when_missing(
        self,
        mock_get_issues: MagicMock,
        mock_ensure: MagicMock,
        mock_add_label: MagicMock,
        mock_run_pipeline: MagicMock,
        tmp_path: Path,
    ) -> None:
        """watch() defaults doc_label to 'documentation' when not specified in config."""
        mock_get_issues.return_value = []
        mock_run_pipeline.return_value = True

        # Config with no doc_label key at all
        cfg = _write_config(tmp_path, extra_watcher_keys={"doc_label": None})
        # Remove doc_label from yaml so it's truly absent
        raw = yaml.safe_load(cfg.read_text())
        del raw["watchers"][0]["doc_label"]
        cfg.write_text(yaml.dump(raw))

        watch(cfg, dry_run=True, logger=_make_logger())

        # get_open_issues must be called with "documentation" at some point
        all_label_args = [c.args[1] for c in mock_get_issues.call_args_list]
        assert "documentation" in all_label_args

    @patch("watcher.run_pipeline")
    @patch("watcher.add_label")
    @patch("watcher.ensure_label")
    @patch("watcher.get_open_issues")
    def test_watch_queues_doc_issues_with_list_label(
        self,
        mock_get_issues: MagicMock,
        mock_ensure: MagicMock,
        mock_add_label: MagicMock,
        mock_run_pipeline: MagicMock,
        tmp_path: Path,
    ) -> None:
        """watch() supports doc_label as a list of strings."""
        doc_issue = _make_issue(number=32, title="Write README")

        def side_effect(repo: str, label) -> list:
            if label in (["documentation", "docs"], "documentation", "docs"):
                return [doc_issue]
            return []

        mock_get_issues.side_effect = side_effect
        mock_run_pipeline.return_value = True

        cfg = _write_config(tmp_path, extra_watcher_keys={"doc_label": ["documentation", "docs"]})
        watch(cfg, dry_run=True, logger=_make_logger())

        calls = mock_run_pipeline.call_args_list
        types = [c.args[3] if c.args else c.kwargs.get("pipeline_type") for c in calls]
        assert "documentation" in types
