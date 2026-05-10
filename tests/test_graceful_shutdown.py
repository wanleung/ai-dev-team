"""Verify graceful shutdown via _shutdown_event.

When _shutdown_event is set, _run_stage must raise _ShutdownRequested immediately
without calling the stage function or recording any errors.  The caller (run())
catches _ShutdownRequested and returns a partial PipelineResult without marking
the interrupted stage as completed in completed_stages.
"""
from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

from orchestrator import Orchestrator, PipelineResult, PipelineStage, _ShutdownRequested


def _make_orchestrator() -> Orchestrator:
    orch = Orchestrator.__new__(Orchestrator)
    orch._agent_health = MagicMock()
    orch._shutdown_event = threading.Event()
    return orch


def _make_result() -> PipelineResult:
    return PipelineResult(requirement="test")


def test_run_stage_raises_shutdown_when_event_set():
    """_run_stage must raise _ShutdownRequested when shutdown event is set."""
    orch = _make_orchestrator()
    orch._shutdown_event.set()
    result = _make_result()
    called = []

    def stage_fn():
        called.append(True)

    with pytest.raises(_ShutdownRequested):
        with patch("orchestrator.console"):
            orch._run_stage("Test", "testing...", result, stage_fn)

    assert called == [], "Stage function must not be called when shutting down"
    assert len(result.errors) == 0, "No errors should be recorded for clean shutdown"


def test_run_stage_proceeds_when_shutdown_not_set():
    """_run_stage must call fn normally when shutdown event is not set."""
    orch = _make_orchestrator()
    result = _make_result()
    called = []

    def stage_fn():
        called.append(True)

    with patch("orchestrator.console"), \
         patch.object(orch, "_critical_cb_open", return_value=None):
        orch._run_stage("Test", "testing...", result, stage_fn)

    assert called == [True], "Stage function must be called when not shutting down"


def test_shutdown_event_is_threading_event():
    """_shutdown_event must be a threading.Event (set/is_set API)."""
    orch = Orchestrator.__new__(Orchestrator)
    orch._shutdown_event = threading.Event()
    assert not orch._shutdown_event.is_set()
    orch._shutdown_event.set()
    assert orch._shutdown_event.is_set()


def test_run_does_not_mark_interrupted_stage_done():
    """run() must NOT add the interrupted stage to completed_stages.

    When _run_stage raises _ShutdownRequested the outer except block in run()
    saves the checkpoint and returns — without calling add_completed_stage for
    the stage that was cut short.
    """
    orch = Orchestrator.__new__(Orchestrator)

    # Minimal attributes required by run()'s early-setup section.
    orch._shutdown_event = threading.Event()
    orch._agent_health = MagicMock()
    orch._cost_tracking = {"enabled": False}
    orch.github = None
    orch.target_github = None
    orch._github_token = "test-token"
    orch.repo_context_loader = None
    orch.memory = MagicMock()
    orch.memory.recall.return_value = ""
    orch.skill_loader = None
    orch.repo_auto_indexer = None
    orch.progress_tracker_mode = "off"
    # Non-None so run() skips the hardcoded PM/Arch revision loops and goes
    # straight to the mode-driven stage loop.
    orch._pipeline_yaml_stages = []

    interrupted_key = "interrupted_stage"

    fake_stage = PipelineStage(
        name="interrupted_stage",
        label="Interrupted Stage",
        description="A stage that gets interrupted",
        checkpoint_key=interrupted_key,
        fn=lambda r: None,
    )

    def _run_stage_raises(*args, **kwargs):
        orch._shutdown_event.set()
        raise _ShutdownRequested()

    with patch.object(orch, "_load_checkpoint", return_value=None), \
         patch.object(orch, "_save_checkpoint") as mock_save, \
         patch.object(orch, "_finish", side_effect=lambda r, t: r), \
         patch.object(orch, "_expected_stages", return_value=[]), \
         patch.object(orch, "_build_stage_list", return_value=[fake_stage]), \
         patch.object(orch, "_run_stage", side_effect=_run_stage_raises), \
         patch("orchestrator.console"):
        result = orch.run("test requirement for shutdown")

    assert interrupted_key not in result.completed_stages, (
        "run() must not mark the interrupted stage as completed in completed_stages"
    )
    mock_save.assert_called_once_with(result)


def test_shutdown_requested_is_base_exception():
    """_ShutdownRequested must be a BaseException, not just Exception.

    This ensures it propagates through broad ``except Exception`` handlers
    in stage loops without being accidentally swallowed.
    """
    assert issubclass(_ShutdownRequested, BaseException)
    assert not issubclass(_ShutdownRequested, Exception), (
        "_ShutdownRequested must NOT subclass Exception — it must bypass "
        "broad except Exception handlers in stage loops"
    )

