"""Tests for zombie thread tracking — Task 2 of T5-A concurrency plan."""
import pytest


def test_leaked_thread_count_increments_on_timeout(tmp_path):
    """get_leaked_thread_count() increments when a stage times out."""
    import orchestrator as orch_mod
    initial = orch_mod.get_leaked_thread_count()

    # Simulate the timeout path by calling the tracking function directly
    orch_mod._record_leaked_thread("test-stage")

    assert orch_mod.get_leaked_thread_count() == initial + 1


def test_leaked_thread_warning_logged(tmp_path, caplog):
    """A warning is logged when a thread is leaked."""
    import orchestrator as orch_mod
    import logging

    with caplog.at_level(logging.WARNING):
        orch_mod._record_leaked_thread("my-slow-stage")

    assert any("my-slow-stage" in r.message for r in caplog.records)
    assert any("leaked" in r.message.lower() for r in caplog.records)


def test_get_leaked_thread_count_returns_int():
    """get_leaked_thread_count() always returns an int >= 0."""
    import orchestrator as orch_mod
    count = orch_mod.get_leaked_thread_count()
    assert isinstance(count, int)
    assert count >= 0
