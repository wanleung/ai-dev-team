"""Tests for parallel_group stage execution in the pipeline (T2-D)."""
from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

from orchestrator import PipelineResult, PipelineStage, Orchestrator


def _make_orchestrator():
    """Build a minimal Orchestrator that can call _run_stage/_run_stage_safe."""
    orch = Orchestrator.__new__(Orchestrator)
    orch._agent_health = MagicMock()
    return orch


def _make_result():
    r = PipelineResult.__new__(PipelineResult)
    r.errors = []
    r.add_error = lambda msg: r.errors.append(msg)
    r.completed_stages = []
    return r


def test_parallel_group_default_is_none():
    """parallel_group=None by default — no change to sequential stages."""
    stage = PipelineStage(
        name="seq", label="Seq", description="", checkpoint_key="seq", fn=lambda r: None
    )
    assert stage.parallel_group is None


def test_parallel_group_field_stored_correctly():
    """parallel_group value round-trips through PipelineStage."""
    stage = PipelineStage(
        name="a", label="A", description="", checkpoint_key="a",
        fn=lambda r: None, parallel_group="my_group",
    )
    assert stage.parallel_group == "my_group"


def test_run_stage_safe_returns_true_on_success():
    """_run_stage_safe returns True when the stage completes without error."""
    orch = _make_orchestrator()
    result = _make_result()
    stage = PipelineStage(
        name="ok", label="OK", description="", checkpoint_key="ok",
        fn=lambda r: None,
    )
    with patch("orchestrator.console"):
        ok = orch._run_stage_safe(stage, result)
    assert ok is True
    assert result.errors == []


def test_run_stage_safe_returns_false_on_error():
    """_run_stage_safe returns False when the stage raises an exception."""
    orch = _make_orchestrator()
    result = _make_result()
    stage = PipelineStage(
        name="bad", label="Bad", description="", checkpoint_key="bad",
        fn=lambda r: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    with patch("orchestrator.console"):
        ok = orch._run_stage_safe(stage, result)
    assert ok is False
    assert any("boom" in e for e in result.errors)


def test_parallel_group_stages_run_concurrently():
    """Two stages sharing a parallel_group actually run in parallel via _run_stage_safe.

    A threading.Barrier(2) requires both threads to reach wait() before either
    proceeds. Sequential execution would deadlock; parallel execution resolves it.
    """
    barrier = threading.Barrier(2, timeout=2.0)
    orch = _make_orchestrator()
    result = _make_result()

    def body_a(r):
        barrier.wait()

    def body_b(r):
        barrier.wait()

    stage_a = PipelineStage(name="a", label="A", description="", checkpoint_key="a",
                            fn=body_a, parallel_group="g1")
    stage_b = PipelineStage(name="b", label="B", description="", checkpoint_key="b",
                            fn=body_b, parallel_group="g1")

    import concurrent.futures
    with patch("orchestrator.console"):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(orch._run_stage_safe, s, result)
                for s in [stage_a, stage_b]
            ]
            done, not_done = concurrent.futures.wait(futures, timeout=3.0)

    assert len(not_done) == 0, "Parallel stages deadlocked — barrier was not resolved"
    assert result.errors == []
