"""Thread-safety tests for checkpoint writes.

Task 3 of T4-A: concurrent _save_checkpoint() calls must not corrupt
the checkpoint file, and Orchestrator must have a _checkpoint_lock.
"""
import json
import threading
import pytest
from pathlib import Path


def _make_orchestrator_with_tmpdir(tmp_path):
    from orchestrator import Orchestrator
    return Orchestrator(model="gpt-4.1", workspace_dir=str(tmp_path))


def test_concurrent_checkpoint_writes_produce_valid_json(tmp_path):
    """10 threads calling _save_checkpoint concurrently must not corrupt the file."""
    from orchestrator import PipelineResult
    orch = _make_orchestrator_with_tmpdir(tmp_path)
    result = PipelineResult(requirement="test-req")
    # Need at least one completed stage so _save_checkpoint doesn't short-circuit
    result.add_completed_stage("init")

    barrier = threading.Barrier(10)

    def writer():
        barrier.wait()
        orch._save_checkpoint(result)

    threads = [threading.Thread(target=writer) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Find the checkpoint file and verify it's valid JSON
    files = list(tmp_path.glob("**/*.json"))
    assert len(files) >= 1, "No checkpoint file was written"
    data = json.loads(files[0].read_text())
    assert data["requirement"] == "test-req"


def test_checkpoint_lock_exists_on_orchestrator(tmp_path):
    """Orchestrator must have a _checkpoint_lock threading.Lock attribute."""
    orch = _make_orchestrator_with_tmpdir(tmp_path)
    assert hasattr(orch, "_checkpoint_lock")
    # threading.Lock() is a factory function, not a class; isinstance(x, threading.Lock)
    # raises TypeError.  Check for the lock protocol instead.
    assert hasattr(orch._checkpoint_lock, "acquire")
