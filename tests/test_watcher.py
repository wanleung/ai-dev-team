"""
tests/test_watcher.py — Unit tests for watcher.py pipeline dispatch and issue queuing.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import tempfile
import logging
import concurrent.futures

import pytest
import yaml
import requests

import watcher
from watcher import _dispatch, watch, _run_pr_revision, _is_retryable_http_error, ensure_label
from watcher_types import GitHubIssue, GitHubLabel, GitHubPR, GitHubComment, WatcherTask


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


def _stub_dispatch_args(label: str, tmp_path: Path) -> dict:
    """Return a minimal set of kwargs for _dispatch."""
    return dict(
        label=label,
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
        """_dispatch with label='ai-feature' calls Orchestrator.run()."""
        mock_orch_instance = MagicMock()
        mock_orch_instance.load_pipeline_for_label.return_value = None
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
            _dispatch(**_stub_dispatch_args("ai-feature", tmp_path))

        mock_orch_class.assert_called_once()
        mock_orch_instance.run.assert_called_once()

    def test_dispatch_feature_log_file_created(self, tmp_path: Path) -> None:
        """_dispatch creates its log file for a feature pipeline."""
        mock_orch_instance = MagicMock()
        mock_orch_instance.load_pipeline_for_label.return_value = None
        mock_orch_class = MagicMock(return_value=mock_orch_instance)
        mock_gh_client = MagicMock()
        mock_gh_client.return_value.get_issue.return_value = {
            "title": "Add feature",
            "body": "",
        }

        log_file = tmp_path / "issue-42-feature.log"
        kwargs = _stub_dispatch_args("ai-feature", tmp_path)
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
        """_dispatch with label='ai-fix' calls Orchestrator.run() with bug pipeline stages."""
        mock_orch_instance = MagicMock()
        mock_orch_instance.load_pipeline_for_label.return_value = ["triager", "engineer"]
        mock_orch_class = MagicMock(return_value=mock_orch_instance)
        mock_gh_client = MagicMock()
        mock_gh_client.return_value.get_issue.return_value = {
            "title": "Bug",
            "body": "",
        }

        with patch.dict("sys.modules", {
            "orchestrator": MagicMock(Orchestrator=mock_orch_class),
            "github_client": MagicMock(GitHubClient=mock_gh_client, parse_target_repo=lambda b: None),
        }):
            _dispatch(**_stub_dispatch_args("ai-fix", tmp_path))

        mock_orch_class.assert_called_once()
        mock_orch_instance.run.assert_called_once()
        mock_orch_instance.load_pipeline_for_label.assert_called_once_with("ai-fix")

    def test_dispatch_bug_passes_issue_number(self, tmp_path: Path) -> None:
        """_dispatch passes the correct issue_number to Orchestrator.run()."""
        mock_orch_instance = MagicMock()
        mock_orch_instance.load_pipeline_for_label.return_value = None
        mock_orch_class = MagicMock(return_value=mock_orch_instance)
        mock_gh_client = MagicMock()
        mock_gh_client.return_value.get_issue.return_value = {"title": "Bug", "body": "B"}

        kwargs = _stub_dispatch_args("ai-fix", tmp_path)
        kwargs["issue_number"] = 99

        with patch.dict("sys.modules", {
            "orchestrator": MagicMock(Orchestrator=mock_orch_class),
            "github_client": MagicMock(GitHubClient=mock_gh_client, parse_target_repo=lambda b: None),
        }):
            _dispatch(**kwargs)

        run_kwargs = mock_orch_instance.run.call_args.kwargs
        assert run_kwargs.get("issue_number") == 99


# ── _dispatch: documentation pipeline ────────────────────────────────────────

class TestDispatchDocumentation:
    def test_dispatch_documentation_imports_docorchestrator(self, tmp_path: Path) -> None:
        """_dispatch with label='ai-docs' calls Orchestrator.run() with docs pipeline."""
        mock_orch_instance = MagicMock()
        mock_orch_instance.load_pipeline_for_label.return_value = ["doc_engineer"]
        mock_orch_class = MagicMock(return_value=mock_orch_instance)
        mock_gh_client = MagicMock()
        mock_gh_client.return_value.get_issue.return_value = {"title": "Docs", "body": ""}

        with patch.dict("sys.modules", {
            "orchestrator": MagicMock(Orchestrator=mock_orch_class),
            "github_client": MagicMock(GitHubClient=mock_gh_client, parse_target_repo=lambda b: None),
        }):
            _dispatch(**_stub_dispatch_args("ai-docs", tmp_path))

        mock_orch_class.assert_called_once()
        mock_orch_instance.run.assert_called_once()
        mock_orch_instance.load_pipeline_for_label.assert_called_once_with("ai-docs")

    def test_dispatch_documentation_passes_issue_number(self, tmp_path: Path) -> None:
        """_dispatch passes the correct issue_number to Orchestrator.run()."""
        mock_orch_instance = MagicMock()
        mock_orch_instance.load_pipeline_for_label.return_value = None
        mock_orch_class = MagicMock(return_value=mock_orch_instance)
        mock_gh_client = MagicMock()
        mock_gh_client.return_value.get_issue.return_value = {"title": "Docs", "body": ""}

        kwargs = _stub_dispatch_args("ai-docs", tmp_path)
        kwargs["issue_number"] = 7

        with patch.dict("sys.modules", {
            "orchestrator": MagicMock(Orchestrator=mock_orch_class),
            "github_client": MagicMock(GitHubClient=mock_gh_client, parse_target_repo=lambda b: None),
        }):
            _dispatch(**kwargs)

        run_kwargs = mock_orch_instance.run.call_args.kwargs
        assert run_kwargs.get("issue_number") == 7

    def test_dispatch_documentation_passes_model_and_repo(self, tmp_path: Path) -> None:
        """_dispatch passes model, github_token, and github_repo to Orchestrator."""
        mock_orch_instance = MagicMock()
        mock_orch_instance.load_pipeline_for_label.return_value = None
        mock_orch_class = MagicMock(return_value=mock_orch_instance)
        mock_gh_client = MagicMock()
        mock_gh_client.return_value.get_issue.return_value = {"title": "Docs", "body": ""}

        kwargs = _stub_dispatch_args("ai-docs", tmp_path)
        kwargs["model"] = "gpt-4o"
        kwargs["tracker_repo"] = "myorg/myrepo"

        with patch.dict("sys.modules", {
            "orchestrator": MagicMock(Orchestrator=mock_orch_class),
            "github_client": MagicMock(GitHubClient=mock_gh_client, parse_target_repo=lambda b: None),
        }):
            _dispatch(**kwargs)

        # Orchestrator is constructed with model, github_token, github_repo
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

        def side_effect(repo: str, label, **kw) -> list:
            if label == "feature-request" or label == ["feature-request"]:
                return [feature_issue]
            return []

        mock_get_issues.side_effect = side_effect
        mock_run_pipeline.return_value = True

        cfg = _write_config(tmp_path)
        watch(cfg, dry_run=True)

        # At least one call with feature pipeline
        calls = mock_run_pipeline.call_args_list
        types = [c.args[3] if c.args else c.kwargs.get("label") for c in calls]
        assert "ai-feature" in types

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

        def side_effect(repo: str, label, **kw) -> list:
            if label == "bug" or label == ["bug"]:
                return [bug_issue]
            return []

        mock_get_issues.side_effect = side_effect
        mock_run_pipeline.return_value = True

        cfg = _write_config(tmp_path)
        watch(cfg, dry_run=True)

        calls = mock_run_pipeline.call_args_list
        types = [c.args[3] if c.args else c.kwargs.get("label") for c in calls]
        assert "ai-fix" in types

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

        def side_effect(repo: str, label, **kw) -> list:
            if label == "documentation" or label == ["documentation"]:
                return [doc_issue]
            return []

        mock_get_issues.side_effect = side_effect
        mock_run_pipeline.return_value = True

        cfg = _write_config(tmp_path)
        watch(cfg, dry_run=True)

        calls = mock_run_pipeline.call_args_list
        types = [c.args[3] if c.args else c.kwargs.get("label") for c in calls]
        assert "ai-docs" in types

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
        watch(cfg, dry_run=True)

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

        watch(cfg, dry_run=True)

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

        def side_effect(repo: str, label, **kw) -> list:
            if label in (["documentation", "docs"], "documentation", "docs"):
                return [doc_issue]
            return []

        mock_get_issues.side_effect = side_effect
        mock_run_pipeline.return_value = True

        cfg = _write_config(tmp_path, extra_watcher_keys={"doc_label": ["documentation", "docs"]})
        watch(cfg, dry_run=True)

        calls = mock_run_pipeline.call_args_list
        types = [c.args[3] if c.args else c.kwargs.get("label") for c in calls]
        assert "ai-docs" in types


# ── _run_pr_revision: conflict_resolver_model wiring ─────────────────────────

class TestRunPrRevisionConflictResolverModel:
    """Tests that _run_pr_revision passes conflict_resolver_model to Orchestrator."""

    def _make_pr(self, number: int = 1) -> dict:
        return {"number": number, "title": "Test PR", "labels": []}

    @patch("watcher.post_comment")
    @patch("watcher.remove_label")
    @patch("watcher.add_label")
    @patch("watcher.ensure_label")
    def test_conflict_resolver_model_passed_to_orchestrator(
        self,
        mock_ensure: MagicMock,
        mock_add_label: MagicMock,
        mock_remove_label: MagicMock,
        mock_post_comment: MagicMock,
        tmp_path: Path,
    ) -> None:
        """_run_pr_revision passes conflict_resolver_model='gpt-4o' to Orchestrator."""
        mock_orch_instance = MagicMock()
        mock_orch_instance.run_revision.return_value = {"status": "ok"}
        mock_orch_class = MagicMock(return_value=mock_orch_instance)

        with patch.dict("sys.modules", {
            "orchestrator": MagicMock(Orchestrator=mock_orch_class),
        }):
            _run_pr_revision(
                pr=self._make_pr(42),
                tracker_repo="owner/tracker",
                target_repo="owner/target",
                model="gpt-4.1",
                num_engineers=1,
                log_dir=tmp_path / "logs",
                logger=_make_logger(),
                conflict_resolver_model="gpt-4o",
            )

        call_kwargs = mock_orch_class.call_args.kwargs
        assert call_kwargs.get("conflict_resolver_model") == "gpt-4o"

    @patch("watcher.post_comment")
    @patch("watcher.remove_label")
    @patch("watcher.add_label")
    @patch("watcher.ensure_label")
    def test_conflict_resolver_model_none_by_default(
        self,
        mock_ensure: MagicMock,
        mock_add_label: MagicMock,
        mock_remove_label: MagicMock,
        mock_post_comment: MagicMock,
        tmp_path: Path,
    ) -> None:
        """_run_pr_revision passes conflict_resolver_model=None when not set."""
        mock_orch_instance = MagicMock()
        mock_orch_instance.run_revision.return_value = {"status": "ok"}
        mock_orch_class = MagicMock(return_value=mock_orch_instance)

        with patch.dict("sys.modules", {
            "orchestrator": MagicMock(Orchestrator=mock_orch_class),
        }):
            _run_pr_revision(
                pr=self._make_pr(43),
                tracker_repo="owner/tracker",
                target_repo="owner/target",
                model="gpt-4.1",
                num_engineers=1,
                log_dir=tmp_path / "logs",
                logger=_make_logger(),
            )

        call_kwargs = mock_orch_class.call_args.kwargs
        assert call_kwargs.get("conflict_resolver_model") is None

# ── Tenacity retry tests ──────────────────────────────────────────────────────

def test_ensure_label_retries_on_429(monkeypatch):
    """ensure_label retries when GitHub returns 429."""
    call_count = {"n": 0}

    def fake_get(url, **kwargs):
        call_count["n"] += 1
        resp = MagicMock()
        if call_count["n"] < 3:
            resp.ok = False
            resp.status_code = 429
            resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
        else:
            resp.ok = True
            resp.status_code = 200
            resp.json.return_value = []
            resp.raise_for_status.return_value = None
        return resp

    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    with patch("watcher.requests.get", side_effect=fake_get), \
         patch("watcher.requests.post", return_value=MagicMock(ok=True, raise_for_status=lambda: None)), \
         patch("tenacity.nap.time.sleep"):
        watcher.ensure_label("owner/repo", "ai-feature", "0075ca")

    assert call_count["n"] == 3   # failed twice, succeeded on 3rd


def test_post_comment_raises_on_503(monkeypatch):
    """post_comment raises HTTPError on 503 (no retry — non-idempotent POST)."""
    resp = MagicMock()
    resp.status_code = 503
    resp.raise_for_status.side_effect = requests.HTTPError(response=resp)

    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    with patch("watcher.requests.post", return_value=resp):
        with pytest.raises(requests.HTTPError):
            watcher.post_comment("owner/repo", 42, "hello")


# ── HP-1: retry predicate and ensure_label 422 race ──────────────────────────

def test_retryable_on_timeout():
    exc = requests.Timeout("timed out")
    assert _is_retryable_http_error(exc) is True


def test_retryable_on_connection_error():
    exc = requests.ConnectionError("connection refused")
    assert _is_retryable_http_error(exc) is True


def test_retryable_on_429():
    resp = MagicMock()
    resp.status_code = 429
    exc = requests.HTTPError(response=resp)
    assert _is_retryable_http_error(exc) is True


def test_not_retryable_on_404():
    resp = MagicMock()
    resp.status_code = 404
    exc = requests.HTTPError(response=resp)
    assert _is_retryable_http_error(exc) is False


def test_ensure_label_idempotent_on_422():
    """ensure_label must not raise when POST returns 422 with already_exists code."""
    get_resp = MagicMock()
    get_resp.raise_for_status = MagicMock()
    get_resp.json.return_value = []  # label absent in GET

    post_resp = MagicMock()
    post_resp.status_code = 422
    post_resp.content = b'{"errors": [{"code": "already_exists"}]}'
    post_resp.json.return_value = {"errors": [{"code": "already_exists"}]}
    post_resp.raise_for_status.side_effect = requests.HTTPError(response=post_resp)

    with patch("watcher.requests.get", return_value=get_resp), \
         patch("watcher.requests.post", return_value=post_resp):
        ensure_label("owner/repo", "ai-feature", "0075ca")  # must not raise


def test_ensure_label_raises_on_422_validation_error():
    """ensure_label must propagate 422 that is NOT an already_exists race."""
    get_resp = MagicMock()
    get_resp.raise_for_status = MagicMock()
    get_resp.json.return_value = []

    post_resp = MagicMock()
    post_resp.status_code = 422
    post_resp.content = b'{"errors": [{"code": "invalid"}]}'
    post_resp.json.return_value = {"errors": [{"code": "invalid"}]}
    post_resp.raise_for_status.side_effect = requests.HTTPError(response=post_resp)

    with patch("watcher.requests.get", return_value=get_resp), \
         patch("watcher.requests.post", return_value=post_resp):
        with pytest.raises(requests.HTTPError):
            ensure_label("owner/repo", "ai-feature", "bad-colour")


def test_ensure_label_skips_post_when_label_exists():
    """ensure_label must not POST if the label already exists in the GET response."""
    get_resp = MagicMock()
    get_resp.raise_for_status = MagicMock()
    get_resp.json.return_value = [{"name": "ai-feature"}]  # already present

    with patch("watcher.requests.get", return_value=get_resp) as mock_get, \
         patch("watcher.requests.post") as mock_post:
        ensure_label("owner/repo", "ai-feature", "0075ca")
        mock_post.assert_not_called()


# ── TypedDict field-access tests ──────────────────────────────────────────────

def test_github_issue_typeddict_fields():
    issue: GitHubIssue = {
        "number": 1,
        "title": "Test issue",
        "body": "body text",
        "html_url": "https://github.com/owner/repo/issues/1",
        "labels": [],
        "state": "open",
        "pull_request": None,
    }
    assert issue["number"] == 1
    assert issue["state"] == "open"


def test_github_label_typeddict_fields():
    label: GitHubLabel = {"name": "ai-feature", "color": "0075ca"}
    assert label["name"] == "ai-feature"


def test_github_pr_typeddict_fields():
    pr: GitHubPR = {
        "number": 7,
        "title": "My PR",
        "body": None,
        "html_url": "https://github.com/owner/repo/pull/7",
        "labels": [],
        "state": "open",
        "draft": False,
        "head": {"ref": "feature-branch", "sha": "abc123"},
        "base": {"ref": "master"},
    }
    assert pr["number"] == 7
    assert pr["draft"] is False


def test_github_comment_typeddict_fields():
    comment: GitHubComment = {
        "id": 101,
        "body": "looks good",
        "user": {"login": "alice"},
        "created_at": "2025-01-01T00:00:00Z",
    }
    assert comment["id"] == 101
    assert comment["user"]["login"] == "alice"


def test_watcher_task_typeddict_fields():
    issue: GitHubIssue = {
        "number": 42,
        "title": "Fix thing",
        "body": None,
        "html_url": "https://github.com/owner/repo/issues/42",
        "labels": [],
        "state": "open",
        "pull_request": None,
    }
    task: WatcherTask = {
        "issue": issue,
        "tracker_repo": "owner/repo",
        "default_target": None,
        "label": "ai-feature",
        "model": "gpt-4.1",
        "num_engineers": 2,
    }
    assert task["tracker_repo"] == "owner/repo"


def test_run_pipeline_handler_logs_exc_info(caplog, monkeypatch, tmp_path):
    """run_pipeline() outer handler captures traceback via exc_info=True."""
    import logging

    monkeypatch.setattr(watcher, "add_label", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")))

    issue = {"number": 99, "title": "test issue", "body": ""}
    with caplog.at_level(logging.ERROR, logger="watcher"):
        result = watcher.run_pipeline(
            issue=issue,
            tracker_repo="owner/repo",
            default_target=None,
            label="ai-feature",
            model="gpt-4.1",
            num_engineers=2,
            log_dir=tmp_path,
            dry_run=False,
            logger=logging.getLogger("watcher"),
        )

    assert result is False, "run_pipeline should return False on failure"
    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert error_records, "Expected at least one ERROR log"
    assert error_records[0].exc_info is not None, "exc_info must be set so traceback is captured"


# ── HP-4: Atomic resume queue tests ──────────────────────────────────────────

def test_trigger_resume_is_atomic(tmp_path):
    """No .tmp file should remain after a successful trigger write."""
    workspace = str(tmp_path)
    watcher._trigger_resume(42, "Fix auth bug", "Add JWT support", workspace)
    trigger = tmp_path / "resume_queue" / "resume_42.json"
    assert trigger.exists()
    data = json.loads(trigger.read_text())
    assert data["issue_number"] == 42
    assert data["issue_title"] == "Fix auth bug"
    assert not (tmp_path / "resume_queue" / "resume_42.json.tmp").exists()


def test_trigger_resume_overwrites_safely(tmp_path):
    """A second write to the same issue replaces the first atomically."""
    workspace = str(tmp_path)
    watcher._trigger_resume(7, "First title", "First req", workspace)
    watcher._trigger_resume(7, "Updated title", "Updated req", workspace)
    trigger = tmp_path / "resume_queue" / "resume_7.json"
    data = json.loads(trigger.read_text())
    assert data["issue_title"] == "Updated title"


def test_process_resume_queue_skips_locked_file(tmp_path, caplog):
    """_process_resume_queue skips a file that is already locked by another process."""
    import fcntl as _fcntl

    workspace = str(tmp_path)
    watcher._trigger_resume(99, "Locked issue", "Requirement", workspace)

    def fake_flock(fd, op):
        if op == _fcntl.LOCK_EX | _fcntl.LOCK_NB:
            raise BlockingIOError("locked")

    with patch("fcntl.flock", side_effect=fake_flock):
        with caplog.at_level(logging.DEBUG, logger="watcher"):
            tasks = watcher._process_resume_queue(
                workspace, ["owner/repo"], {}, "gpt-4.1", 2,
                tmp_path / "logs", dry_run=False, logger=logging.getLogger("watcher"),
            )

    assert tasks == []
    assert any(
        "locked" in r.message.lower() or "skip" in r.message.lower()
        for r in caplog.records
    )


def test_watch_timeout_cancels_hung_futures(monkeypatch, tmp_path, caplog):
    """watch() cancels hung futures and shuts down non-blocking on pipeline_timeout_s exceeded."""
    # --- Setup: fake config file ---
    cfg = {
        "watchers": [{
            "tracker_repo": "owner/repo",
            "labels": {"ai-feature": "ai-feature"},
        }],
        "settings": {"pipeline_timeout_s": 1},
    }
    cfg_file = tmp_path / "repos.yaml"
    cfg_file.write_text(yaml.dump(cfg))

    # --- Fake future tracking ---
    cancelled = []

    class FakeFuture:
        def done(self): return False
        def cancel(self): cancelled.append(self)
        def cancelled(self): return self in cancelled
        def result(self): pass  # Never called — TimeoutError fires first

    fake_fut = FakeFuture()

    # --- Fake executor tracking ---
    shutdown_calls = []

    class FakeExecutor:
        def submit(self, *a, **kw): return fake_fut
        def shutdown(self, wait=True, cancel_futures=False):
            shutdown_calls.append({"wait": wait, "cancel_futures": cancel_futures})

    # --- Patch watcher internals ---
    monkeypatch.setattr("watcher._load_pipeline_config", lambda: {})
    monkeypatch.setattr("watcher._watch_prs", lambda *a, **kw: None)
    monkeypatch.setattr("watcher._process_resume_queue", lambda *a, **kw: [])
    monkeypatch.setattr("watcher.ensure_label", lambda *a, **kw: None)
    monkeypatch.setattr("watcher.get_open_issues",
                        lambda repo, label, **kw: [{"number": 42, "title": "Hang", "body": "",
                                              "labels": [], "state": "open",
                                              "pull_request": None, "html_url": ""}])
    monkeypatch.setattr("watcher.add_label", lambda *a, **kw: None)
    monkeypatch.setattr("watcher.remove_label", lambda *a, **kw: None)
    monkeypatch.setattr("watcher.ThreadPoolExecutor",
                        lambda **kw: FakeExecutor())
    monkeypatch.setattr("watcher.as_completed",
                        lambda fs, timeout=None: (_ for _ in ()).throw(
                            concurrent.futures.TimeoutError()))

    # --- Run watch() ---
    with caplog.at_level(logging.WARNING, logger="watcher"):
        watcher.watch(cfg_file, dry_run=False)

    # --- Assert cancellation and non-blocking shutdown ---
    assert len(cancelled) >= 1, "Expected at least one future to be cancelled"
    assert shutdown_calls, "Expected executor.shutdown() to be called"
    assert shutdown_calls[-1]["wait"] is False, "shutdown must be non-blocking"
    assert shutdown_calls[-1]["cancel_futures"] is True, "shutdown must cancel futures"
    assert any("Pipeline timeout" in r.message for r in caplog.records), \
        "Expected a pipeline timeout warning in the logs"


def test_watch_timeout_cleans_up_labels_for_cancelled_futures(monkeypatch, tmp_path, caplog):
    """watch(): futures that are cancelled (never started) get agent-queued removed and agent-failed added."""
    cfg = {
        "watchers": [{
            "tracker_repo": "owner/repo",
            "labels": {"ai-feature": "ai-feature"},
        }],
        "settings": {"pipeline_timeout_s": 1},
    }
    cfg_file = tmp_path / "repos.yaml"
    cfg_file.write_text(yaml.dump(cfg))

    class FakeFuture:
        def __init__(self, cancelled_after_cancel):
            self._cancelled = cancelled_after_cancel
        def done(self): return False
        def cancel(self): return self._cancelled
        def cancelled(self): return self._cancelled

    # Two futures: one that was cancelled (never started), one that was running (can't cancel)
    cancelled_fut = FakeFuture(cancelled_after_cancel=True)
    running_fut = FakeFuture(cancelled_after_cancel=False)

    class FakeExecutor:
        def submit(self, *a, **kw):
            # First call returns cancelled_fut, second returns running_fut
            if not hasattr(self, '_count'):
                self._count = 0
            self._count += 1
            return cancelled_fut if self._count == 1 else running_fut
        def shutdown(self, wait=True, cancel_futures=False): pass

    label_calls = []

    monkeypatch.setattr("watcher._load_pipeline_config", lambda: {})
    monkeypatch.setattr("watcher._watch_prs", lambda *a, **kw: None)
    monkeypatch.setattr("watcher._process_resume_queue", lambda *a, **kw: [])
    monkeypatch.setattr("watcher.ensure_label", lambda *a, **kw: None)
    monkeypatch.setattr("watcher.get_open_issues",
                        lambda repo, label, **kw: [
                            {"number": 1, "title": "T1", "body": "", "labels": [], "state": "open", "pull_request": None, "html_url": ""},
                            {"number": 2, "title": "T2", "body": "", "labels": [], "state": "open", "pull_request": None, "html_url": ""},
                        ])
    monkeypatch.setattr("watcher.add_label",
                        lambda repo, num, lbl: label_calls.append(("add", num, lbl)))
    monkeypatch.setattr("watcher.remove_label",
                        lambda repo, num, lbl: label_calls.append(("remove", num, lbl)))
    monkeypatch.setattr("watcher.ThreadPoolExecutor", lambda **kw: FakeExecutor())
    monkeypatch.setattr("watcher.as_completed",
                        lambda fs, timeout=None: (_ for _ in ()).throw(
                            concurrent.futures.TimeoutError()))

    with caplog.at_level(logging.WARNING, logger="watcher"):
        watcher.watch(cfg_file, dry_run=False)

    # Only the cancelled future (issue #1) should get label cleanup
    assert ("remove", 1, "agent-queued") in label_calls, \
        "Expected agent-queued removed for cancelled future"
    assert ("add", 1, "agent-failed") in label_calls, \
        "Expected agent-failed added for cancelled future"
    # Running future (issue #2) should NOT get label cleanup here (run_pipeline handles it)
    assert ("remove", 2, "agent-queued") not in label_calls, \
        "Should not clean up labels for still-running future"
    assert ("add", 2, "agent-failed") not in label_calls, \
        "Should not add agent-failed for still-running future"
    assert any("timed out before starting" in r.message for r in caplog.records), \
        "Expected per-issue timeout warning in logs"


# ── T1: DLQ integration ───────────────────────────────────────────────────────

def test_run_pipeline_enqueues_to_dlq_on_failure(tmp_path, monkeypatch):
    """When run_pipeline raises, the DLQ receives an entry."""
    from pathlib import Path
    from core.dead_letter import FileDeadLetterQueue, DLQEntry

    dlq_path = tmp_path / "dlq"
    dlq = FileDeadLetterQueue(dlq_path)

    def fake_dispatch(**kwargs):
        raise RuntimeError("pipeline failed")

    monkeypatch.setattr("watcher._dispatch", fake_dispatch)
    monkeypatch.setattr("watcher.add_label", lambda *a, **kw: None)
    monkeypatch.setattr("watcher.remove_label", lambda *a, **kw: None)
    monkeypatch.setattr("watcher.post_comment", lambda *a, **kw: None)
    monkeypatch.setattr("watcher.ensure_label", lambda *a, **kw: None)

    import watcher as w
    try:
        w.run_pipeline(
            label="feature-request",
            tracker_repo="owner/repo",
            target_repo="owner/repo",
            issue_number=42,
            model="gpt-4.1",
            num_engineers=2,
            log_file=Path(tmp_path / "log.txt"),
            logger=logging.getLogger("test"),
            dlq=dlq,
        )
    except Exception:
        pass  # run_pipeline may re-raise; we just check DLQ

    entries = list(dlq.drain())
    assert len(entries) == 1
    assert entries[0].issue_number == 42
    assert entries[0].tracker_repo == "owner/repo"


def test_run_pipeline_no_dlq_enqueue_on_success(tmp_path, monkeypatch):
    """Successful pipeline does not write to DLQ."""
    from pathlib import Path
    from core.dead_letter import FileDeadLetterQueue
    from types import SimpleNamespace

    dlq_path = tmp_path / "dlq"
    dlq = FileDeadLetterQueue(dlq_path)

    monkeypatch.setattr("watcher._dispatch", lambda **kw: SimpleNamespace(
        next_label=None, verdict="success", tests_passed=True, deploy_tests_passed=True
    ))
    monkeypatch.setattr("watcher.ensure_label", lambda *a, **kw: None)
    monkeypatch.setattr("watcher.add_label", lambda *a, **kw: None)
    monkeypatch.setattr("watcher.remove_label", lambda *a, **kw: None)
    monkeypatch.setattr("watcher.post_comment", lambda *a, **kw: None)

    import watcher as w
    w.run_pipeline(
        label="feature-request",
        tracker_repo="owner/repo",
        target_repo="owner/repo",
        issue_number=1,
        model="gpt-4.1",
        num_engineers=2,
        log_file=Path(tmp_path / "log.txt"),
        logger=logging.getLogger("test"),
        dlq=dlq,
    )

    assert list(dlq.drain()) == []


# ── _collect_issue_prior_context: error handling ──────────────────────────────

def test_collect_issue_prior_context_swallows_exception_gracefully():
    """_collect_issue_prior_context must return '' (not raise NameError) when fetching comments fails."""
    mock_gh = MagicMock()
    mock_gh.get_issue_comments.side_effect = RuntimeError("network failure")

    from watcher import _collect_issue_prior_context
    result = _collect_issue_prior_context(mock_gh, issue_number=42)
    assert result == ""


# ── trigger label lifecycle ───────────────────────────────────────────────────

def test_run_pipeline_removes_trigger_label_and_agent_complete_on_start(tmp_path, monkeypatch):
    """When a pipeline run starts, the trigger label and agent-complete are removed
    so that a new trigger label (e.g. image-article) added after completion can be
    picked up by the watcher without the old labels re-firing."""
    from pathlib import Path
    from types import SimpleNamespace

    removed_labels = []

    monkeypatch.setattr("watcher._dispatch", lambda **kw: SimpleNamespace(
        next_label=None, verdict="success", tests_passed=True, deploy_tests_passed=True,
        errors=[],
    ))
    monkeypatch.setattr("watcher.ensure_label", lambda *a, **kw: None)
    monkeypatch.setattr("watcher.add_label", lambda *a, **kw: None)
    monkeypatch.setattr("watcher.remove_label", lambda repo, issue, lbl: removed_labels.append(lbl))
    monkeypatch.setattr("watcher.post_comment", lambda *a, **kw: None)

    import watcher as w
    w.run_pipeline(
        label="news-article",
        trigger_label="press",
        tracker_repo="owner/repo",
        target_repo="owner/repo",
        issue_number=99,
        model="gpt-4.1",
        num_engineers=2,
        log_file=Path(tmp_path / "log.txt"),
        logger=logging.getLogger("test"),
    )

    assert "press" in removed_labels, "trigger label must be removed at pipeline start"
    assert "agent-complete" in removed_labels, "agent-complete must be removed at pipeline start"


def test_get_open_issues_returns_issue_with_agent_complete_when_multi_run_allowed(monkeypatch):
    """get_open_issues(allow_completed=True) must return issues that have agent-complete,
    so multi-run labels (e.g. image-article) can trigger on previously completed issues.
    By default (allow_completed=False), agent-complete still blocks — other repos are safe."""
    import watcher as w

    issue_with_both = {
        "number": 5,
        "title": "Test article",
        "labels": [
            {"name": "image-article"},
            {"name": "agent-complete"},
        ],
        "body": "",
    }

    def fake_get(url, headers, params, timeout):
        class R:
            def raise_for_status(self): pass
            def json(self): return [issue_with_both]
        return R()

    monkeypatch.setattr("watcher.requests.get", fake_get)

    # Default: agent-complete blocks (preserves existing behaviour for all other repos)
    issues = w.get_open_issues("owner/repo", "image-article", allow_completed=False)
    assert len(issues) == 0, "agent-complete should block pickup by default"

    # allow_completed=True: image-article can run on a completed issue
    issues = w.get_open_issues("owner/repo", "image-article", allow_completed=True)
    assert len(issues) == 1, "should return issue when allow_completed=True"
    assert issues[0]["number"] == 5

