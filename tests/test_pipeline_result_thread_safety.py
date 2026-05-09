"""Thread-safety tests for PipelineResult mutations.

Task 1 of T4-A: concurrent add_error() and add_completed_stage() must
produce exactly the expected number of entries with no data races.
"""
import threading
import pytest
from orchestrator import PipelineResult


def test_add_error_concurrent():
    """50 threads calling add_error simultaneously must produce exactly 50 errors."""
    result = PipelineResult(requirement="test")
    barrier = threading.Barrier(50)

    def worker(i):
        barrier.wait()
        result.add_error(f"error-{i}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(result.errors) == 50


def test_add_completed_stage_concurrent():
    """50 threads calling add_completed_stage simultaneously must produce exactly 50 entries."""
    result = PipelineResult(requirement="test")
    barrier = threading.Barrier(50)

    def worker(i):
        barrier.wait()
        result.add_completed_stage(f"stage-{i}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(result.completed_stages) == 50


def test_add_error_and_stage_concurrent_no_deadlock():
    """Mixed concurrent calls to add_error and add_completed_stage must not deadlock."""
    result = PipelineResult(requirement="test")
    barrier = threading.Barrier(20)

    def add_err(i):
        barrier.wait()
        result.add_error(f"e-{i}")

    def add_stage(i):
        barrier.wait()
        result.add_completed_stage(f"s-{i}")

    threads = (
        [threading.Thread(target=add_err, args=(i,)) for i in range(10)]
        + [threading.Thread(target=add_stage, args=(i,)) for i in range(10)]
    )
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(result.errors) == 10
    assert len(result.completed_stages) == 10
