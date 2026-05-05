"""Tests for PR watcher helpers and logic."""
from __future__ import annotations
import pytest
from unittest.mock import patch, MagicMock


# ── API helper tests ──────────────────────────────────────────────────────────

def _mock_response(json_data, status_code=200):
    m = MagicMock()
    m.ok = status_code < 400
    m.status_code = status_code
    m.json.return_value = json_data
    m.text = str(json_data)
    return m


def test_get_open_prs_returns_non_draft(monkeypatch):
    """get_open_prs filters out draft PRs when skip_drafts=True."""
    from watcher import get_open_prs
    prs = [
        {"number": 1, "draft": False, "title": "Real PR", "labels": []},
        {"number": 2, "draft": True, "title": "Draft PR", "labels": []},
    ]
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    with patch("watcher.requests.get", return_value=_mock_response(prs)):
        result = get_open_prs("owner/repo", skip_drafts=True)
    assert len(result) == 1
    assert result[0]["number"] == 1


def test_get_open_prs_includes_draft_when_disabled(monkeypatch):
    """get_open_prs includes drafts when skip_drafts=False."""
    from watcher import get_open_prs
    prs = [
        {"number": 1, "draft": False, "title": "Real PR", "labels": []},
        {"number": 2, "draft": True, "title": "Draft PR", "labels": []},
    ]
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    with patch("watcher.requests.get", return_value=_mock_response(prs)):
        result = get_open_prs("owner/repo", skip_drafts=False)
    assert len(result) == 2


def test_get_pr_comments_returns_list(monkeypatch):
    """get_pr_comments returns list of comment dicts."""
    from watcher import get_pr_comments
    comments = [{"id": 1, "body": "❌ Tests failed", "user": {"login": "bot"}}]
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    with patch("watcher.requests.get", return_value=_mock_response(comments)):
        result = get_pr_comments("owner/repo", 42)
    assert result == comments


# ── Error handling tests (API helpers) ───────────────────────────────────────

def test_get_open_prs_raises_on_api_error(monkeypatch):
    """get_open_prs raises RuntimeError on API error."""
    from watcher import get_open_prs
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    error_response = _mock_response({"message": "Not Found"}, status_code=404)
    with patch("watcher.requests.get", return_value=error_response):
        with pytest.raises(RuntimeError, match="GitHub API error 404"):
            get_open_prs("owner/repo")


def test_get_pr_comments_raises_on_api_error(monkeypatch):
    """get_pr_comments raises RuntimeError on API error."""
    from watcher import get_pr_comments
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    error_response = _mock_response({"message": "Not Found"}, status_code=404)
    with patch("watcher.requests.get", return_value=error_response):
        with pytest.raises(RuntimeError, match="GitHub API error 404"):
            get_pr_comments("owner/repo", 42)


def test_get_open_prs_handles_missing_draft_field(monkeypatch):
    """get_open_prs handles PRs without draft field (treats as non-draft)."""
    from watcher import get_open_prs
    prs = [{"number": 1, "title": "No draft field", "labels": []}]
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    with patch("watcher.requests.get", return_value=_mock_response(prs)):
        result = get_open_prs("owner/repo", skip_drafts=True)
    assert len(result) == 1


# ── Detection helper tests ────────────────────────────────────────────────────

def test_pr_attempt_count_zero_when_no_labels():
    from watcher import _pr_attempt_count
    assert _pr_attempt_count([]) == 0


def test_pr_attempt_count_reads_highest_n():
    from watcher import _pr_attempt_count
    labels = [
        {"name": "ai-pr-fix-1"},
        {"name": "ai-pr-fix-3"},
        {"name": "ai-pr-fix-2"},
        {"name": "unrelated"},
    ]
    assert _pr_attempt_count(labels) == 3


def test_should_fix_pr_label_trigger():
    """PR with pr_fix_label triggers a fix."""
    from watcher import _should_fix_pr
    pr = {"number": 5, "labels": [{"name": "ai-fix"}], "draft": False}
    assert _should_fix_pr(pr, [], "ai-fix", r"❌|FAILED", 3) is True


def test_should_fix_pr_comment_trigger():
    """PR with matching comment triggers a fix even without label."""
    from watcher import _should_fix_pr
    pr = {"number": 5, "labels": [], "draft": False}
    comments = [{"body": "❌ Tests failed: 3 errors", "user": {"login": "bot"}}]
    assert _should_fix_pr(pr, comments, "ai-fix", r"❌|FAILED", 3) is True


def test_should_fix_pr_skip_agent_running():
    """PR with agent-running label is skipped."""
    from watcher import _should_fix_pr
    pr = {"number": 5, "labels": [{"name": "ai-fix"}, {"name": "agent-running"}], "draft": False}
    assert _should_fix_pr(pr, [], "ai-fix", r"❌|FAILED", 3) is False


def test_should_fix_pr_skip_agent_failed():
    """PR with agent-failed label is skipped."""
    from watcher import _should_fix_pr
    pr = {"number": 5, "labels": [{"name": "ai-fix"}, {"name": "agent-failed"}], "draft": False}
    assert _should_fix_pr(pr, [], "ai-fix", r"❌|FAILED", 3) is False


def test_should_fix_pr_skip_max_retries():
    """PR at max retries is skipped."""
    from watcher import _should_fix_pr
    pr = {
        "number": 5,
        "labels": [{"name": "ai-fix"}, {"name": "ai-pr-fix-3"}],
        "draft": False,
    }
    assert _should_fix_pr(pr, [], "ai-fix", r"❌|FAILED", 3) is False


def test_should_fix_pr_no_trigger():
    """PR with no trigger label and no matching comments is not flagged."""
    from watcher import _should_fix_pr
    pr = {"number": 5, "labels": [{"name": "enhancement"}], "draft": False}
    comments = [{"body": "Looks good!", "user": {"login": "alice"}}]
    assert _should_fix_pr(pr, comments, "ai-fix", r"❌|FAILED", 3) is False


def test_should_fix_pr_skip_agent_complete():
    """PR with agent-complete label is skipped to avoid re-queueing after success."""
    from watcher import _should_fix_pr
    pr = {"number": 5, "labels": [{"name": "ai-fix"}, {"name": "agent-complete"}], "draft": False}
    assert _should_fix_pr(pr, [], "ai-fix", r"❌|FAILED", 3) is False


def test_pr_attempt_count_tolerates_missing_name_key():
    """_pr_attempt_count handles label dicts missing 'name' key without crashing."""
    from watcher import _pr_attempt_count
    assert _pr_attempt_count([{}, {"label": "ai-pr-fix-1"}]) == 0


# ── _run_pr_revision tests ────────────────────────────────────────────────────

def test_run_pr_revision_success(monkeypatch, tmp_path):
    """Successful revision: correct label transitions and stdout restored."""
    import sys
    import types
    import logging
    from watcher import _run_pr_revision

    pr = {"number": 7, "labels": [{"name": "ai-fix"}], "title": "Fix me"}
    calls = {"add": [], "remove": []}

    class FakeOrch:
        def __init__(self, **kwargs):
            pass
        def run_revision(self, pr_number):
            return {"status": "ok", "revision": 1}

    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    monkeypatch.setattr("watcher.add_label", lambda r, n, l: calls["add"].append(l))
    monkeypatch.setattr("watcher.remove_label", lambda r, n, l: calls["remove"].append(l))
    monkeypatch.setattr("watcher.post_comment", lambda *a: None)
    monkeypatch.setattr("watcher.ensure_label", lambda *a: None)
    fake_mod = types.ModuleType("orchestrator")
    fake_mod.Orchestrator = FakeOrch
    monkeypatch.setitem(sys.modules, "orchestrator", fake_mod)

    saved_stdout, saved_stderr = sys.stdout, sys.stderr
    _run_pr_revision(pr, "owner/tracker", "owner/target", "gpt-4.1", 2, tmp_path, logging.getLogger("test"), pr_fix_label="ai-fix")

    assert "agent-running" in calls["add"]
    assert "ai-pr-fix-1" in calls["add"]   # attempt label applied
    assert "agent-complete" in calls["add"]
    assert "agent-running" in calls["remove"]
    assert "ai-fix" in calls["remove"]     # configured trigger label removed after success
    assert sys.stdout is saved_stdout, "stdout was not restored"
    assert sys.stderr is saved_stderr, "stderr was not restored"


@pytest.mark.parametrize("status", ["max_revisions_reached", "error"])
def test_run_pr_revision_failure_statuses(monkeypatch, tmp_path, status):
    """Failure statuses add agent-failed and remove agent-running."""
    import sys
    import types
    import logging
    from watcher import _run_pr_revision

    pr = {"number": 8, "labels": [{"name": "ai-fix"}], "title": "Stuck"}
    calls = {"add": [], "remove": []}

    class FakeOrch:
        def __init__(self, **kwargs):
            pass
        def run_revision(self, pr_number):
            return {"status": status}

    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    monkeypatch.setattr("watcher.add_label", lambda r, n, l: calls["add"].append(l))
    monkeypatch.setattr("watcher.remove_label", lambda r, n, l: calls["remove"].append(l))
    monkeypatch.setattr("watcher.post_comment", lambda *a: None)
    monkeypatch.setattr("watcher.ensure_label", lambda *a: None)
    fake_mod = types.ModuleType("orchestrator")
    fake_mod.Orchestrator = FakeOrch
    monkeypatch.setitem(sys.modules, "orchestrator", fake_mod)

    _run_pr_revision(pr, "owner/tracker", "owner/target", "gpt-4.1", 2, tmp_path, logging.getLogger("test"))

    assert "agent-failed" in calls["add"]
    assert "agent-running" in calls["remove"]


def test_run_pr_revision_exception_path(monkeypatch, tmp_path):
    """Unhandled exception adds agent-failed, posts comment, restores stdout."""
    import sys
    import types
    import logging
    from watcher import _run_pr_revision

    pr = {"number": 10, "labels": [], "title": "Crash"}
    calls = {"add": [], "remove": [], "comments": []}

    class FakeOrch:
        def __init__(self, **kwargs):
            pass
        def run_revision(self, pr_number):
            raise RuntimeError("kaboom")

    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    monkeypatch.setattr("watcher.add_label", lambda r, n, l: calls["add"].append(l))
    monkeypatch.setattr("watcher.remove_label", lambda r, n, l: calls["remove"].append(l))
    monkeypatch.setattr("watcher.post_comment", lambda r, n, b: calls["comments"].append(b))
    monkeypatch.setattr("watcher.ensure_label", lambda *a: None)
    fake_mod = types.ModuleType("orchestrator")
    fake_mod.Orchestrator = FakeOrch
    monkeypatch.setitem(sys.modules, "orchestrator", fake_mod)

    saved_stdout, saved_stderr = sys.stdout, sys.stderr
    _run_pr_revision(pr, "owner/tracker", "owner/target", "gpt-4.1", 2, tmp_path, logging.getLogger("test"))

    assert "agent-failed" in calls["add"]
    assert "agent-running" in calls["remove"]
    assert any("kaboom" in c for c in calls["comments"])
    assert sys.stdout is saved_stdout, "stdout was not restored"
    assert sys.stderr is saved_stderr, "stderr was not restored"


# ── _watch_prs integration tests ─────────────────────────────────────────────

def test_watch_prs_dispatches_when_label_trigger(monkeypatch, tmp_path):
    """_watch_prs calls _run_pr_revision when PR has the fix label."""
    from watcher import _watch_prs
    import logging

    pr = {
        "number": 10,
        "title": "Bad PR",
        "labels": [{"name": "ai-fix"}],
        "draft": False,
        "head": {"repo": {"full_name": "owner/target"}},
    }
    watchers = [{
        "tracker_repo": "owner/tracker",
        "default_target": "owner/target",
        "enabled": True,
        "_settings": {"watch_prs": True, "pr_fix_label": "ai-fix",
                      "pr_failure_pattern": r"❌|FAILED", "max_pr_retries": 3,
                      "watch_draft_prs": False},
    }]

    dispatched = []

    monkeypatch.setattr("watcher.get_open_prs", lambda repo, skip_drafts=True: [pr])
    monkeypatch.setattr("watcher.get_pr_comments", lambda repo, num: [])
    monkeypatch.setattr(
        "watcher._run_pr_revision",
        lambda pr, tracker, target, model, num_eng, log_dir, logger, pr_fix_label="ai-fix":
            dispatched.append((pr["number"], tracker, target, model, num_eng, pr_fix_label)),
    )

    _watch_prs(watchers, {"model": "gpt-4.1", "num_engineers": 2}, tmp_path, False, logging.getLogger("test"))

    assert dispatched == [(10, "owner/tracker", "owner/target", "gpt-4.1", 2, "ai-fix")]


def test_watch_prs_skips_when_disabled(monkeypatch, tmp_path):
    """_watch_prs does not scan PRs when watch_prs is False."""
    from watcher import _watch_prs
    import logging

    watchers = [{
        "tracker_repo": "owner/tracker",
        "default_target": "owner/target",
        "enabled": True,
        "_settings": {"watch_prs": False},
    }]

    get_open_prs_called = []
    monkeypatch.setattr("watcher.get_open_prs", lambda *a, **k: get_open_prs_called.append(True) or [])

    _watch_prs(watchers, {"model": "gpt-4.1", "num_engineers": 2}, tmp_path, False, logging.getLogger("test"))

    assert get_open_prs_called == []


def test_watch_prs_dry_run_does_not_dispatch(monkeypatch, tmp_path):
    """_watch_prs does not dispatch in dry-run mode."""
    from watcher import _watch_prs
    import logging

    pr = {
        "number": 11,
        "title": "PR",
        "labels": [{"name": "ai-fix"}],
        "draft": False,
        "head": {"repo": {"full_name": "owner/target"}},
    }
    watchers = [{
        "tracker_repo": "owner/tracker",
        "default_target": "owner/target",
        "enabled": True,
        "_settings": {"watch_prs": True, "pr_fix_label": "ai-fix",
                      "pr_failure_pattern": r"❌|FAILED", "max_pr_retries": 3,
                      "watch_draft_prs": False},
    }]

    dispatched = []
    monkeypatch.setattr("watcher.get_open_prs", lambda *a, **k: [pr])
    monkeypatch.setattr("watcher.get_pr_comments", lambda *a: [])
    monkeypatch.setattr("watcher._run_pr_revision", lambda *a, **k: dispatched.append(True))

    _watch_prs(watchers, {"model": "gpt-4.1", "num_engineers": 2}, tmp_path, dry_run=True, logger=logging.getLogger("test"))

    assert dispatched == []
