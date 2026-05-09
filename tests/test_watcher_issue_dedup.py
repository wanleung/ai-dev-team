"""Verify that the same issue number is never processed twice concurrently."""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import watcher


def _fresh_active_issues():
    """Return a context manager that replaces _ACTIVE_ISSUES with a clean set."""
    return patch("watcher._ACTIVE_ISSUES", new_callable=set)


def test_duplicate_issue_skipped_while_active():
    """If issue #42 in the same repo is already being processed, a second submission is skipped."""
    call_log: list[int] = []
    barrier = threading.Barrier(2, timeout=2.0)

    def slow_pipeline(issue, *args, **kwargs):
        call_log.append(issue["number"])
        try:
            barrier.wait()  # wait for second thread to arrive (or time out)
        except threading.BrokenBarrierError:
            pass
        time.sleep(0.05)

    issue = {"number": 42, "title": "Test Issue", "body": ""}
    tracker_repo = "owner/tracker"

    # Simulate two concurrent calls for the same (repo, issue_number) pair
    with patch("watcher._ACTIVE_ISSUES", new=set()):
        with patch("watcher._ACTIVE_ISSUES_LOCK", threading.Lock()):
            threads = []
            for _ in range(2):
                t = threading.Thread(
                    target=watcher._run_with_issue_lock,
                    args=(slow_pipeline, issue, tracker_repo, "owner/target",
                          "ai-task", "gpt-4.1", 2, "/tmp", False, MagicMock()),
                )
                threads.append(t)
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=3.0)

    # One thread hit the barrier timeout, meaning it was skipped — only 1 call expected
    assert len(call_log) == 1, f"Expected 1 call, got {len(call_log)}: {call_log}"


def test_issue_lock_released_after_completion():
    """After processing completes, the (repo, issue_number) key is removed from _ACTIVE_ISSUES."""
    call_log: list[int] = []
    tracker_repo = "owner/tracker"

    def fast_pipeline(issue, *args, **kwargs):
        call_log.append(issue["number"])

    issue = {"number": 99, "title": "Another", "body": ""}

    active: set = set()
    with patch("watcher._ACTIVE_ISSUES", new=active):
        with patch("watcher._ACTIVE_ISSUES_LOCK", threading.Lock()):
            watcher._run_with_issue_lock(
                fast_pipeline, issue, tracker_repo, "owner/target",
                "ai-task", "gpt-4.1", 2, "/tmp", False, MagicMock(),
            )
            assert (tracker_repo, 99) not in active, "Key should be cleaned up after run"

    assert call_log == [99]


def test_different_repos_same_issue_number_run_independently():
    """Issue #42 in repo-A and issue #42 in repo-B must BOTH run, not suppress each other."""
    call_log: list[tuple[str, int]] = []
    # Use an event to make the first thread hold the active-issues slot while the second starts
    first_started = threading.Event()
    first_may_finish = threading.Event()

    def pipeline_a(issue, repo, *args, **kwargs):
        call_log.append((repo, issue["number"]))
        first_started.set()
        first_may_finish.wait(timeout=2.0)

    def pipeline_b(issue, repo, *args, **kwargs):
        call_log.append((repo, issue["number"]))

    issue = {"number": 42, "title": "Same number, different repo", "body": ""}

    active: set = set()
    lock = threading.Lock()

    with patch("watcher._ACTIVE_ISSUES", new=active):
        with patch("watcher._ACTIVE_ISSUES_LOCK", lock):
            t_a = threading.Thread(
                target=watcher._run_with_issue_lock,
                args=(pipeline_a, issue, "owner/repo-a", "owner/target",
                      "ai-task", "gpt-4.1", 2, "/tmp", False, MagicMock()),
            )
            t_a.start()
            # Wait until repo-a has registered its key before launching repo-b
            first_started.wait(timeout=2.0)

            t_b = threading.Thread(
                target=watcher._run_with_issue_lock,
                args=(pipeline_b, issue, "owner/repo-b", "owner/target",
                      "ai-task", "gpt-4.1", 2, "/tmp", False, MagicMock()),
            )
            t_b.start()
            t_b.join(timeout=2.0)

            first_may_finish.set()
            t_a.join(timeout=2.0)

    assert ("owner/repo-a", 42) in call_log, "repo-a issue #42 should have run"
    assert ("owner/repo-b", 42) in call_log, "repo-b issue #42 should have run (different repo)"
    assert len(call_log) == 2, f"Both issues should run independently, got: {call_log}"

