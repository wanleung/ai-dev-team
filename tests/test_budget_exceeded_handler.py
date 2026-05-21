"""Tests for BudgetExceededError handling in the sequential run() path (I4 fix).

BudgetExceededError raised in _run_stage() must be caught by run(), causing:
  1. A warning to be logged
  2. An error added to the result
  3. A checkpoint saved
  4. A clean return via _finish() — not an unhandled exception
"""
from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

from agents.token_ledger import BudgetExceededError
from orchestrator import Orchestrator, PipelineResult, PipelineStage


def _make_orchestrator() -> Orchestrator:
    """Create a minimal Orchestrator without calling __init__.

    Sets only the attributes actually accessed by run()'s early-setup section
    and the stage-running loop, mirroring the pattern in test_graceful_shutdown.py.
    """
    orch = Orchestrator.__new__(Orchestrator)
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
    return orch


def _make_budget_stage() -> PipelineStage:
    """Return a PipelineStage whose fn raises BudgetExceededError."""
    return PipelineStage(
        name="budget_stage",
        label="Budget Stage",
        description="A stage that exhausts the token budget",
        checkpoint_key="budget_stage",
        fn=lambda r: None,
    )


def test_budget_exceeded_saves_checkpoint_and_returns(tmp_path):
    """When BudgetExceededError is raised in a stage, run() must save a
    checkpoint and return a PipelineResult (not propagate the exception)."""
    orch = _make_orchestrator()
    fake_stage = _make_budget_stage()

    def _run_stage_raises(*args, **kwargs):
        raise BudgetExceededError("token quota exhausted")

    with patch.object(orch, "_load_checkpoint", return_value=None), \
         patch.object(orch, "_save_checkpoint") as mock_save, \
         patch.object(orch, "_finish", side_effect=lambda r, t: r), \
         patch.object(orch, "_expected_stages", return_value=[]), \
         patch.object(orch, "_build_stage_list", return_value=[fake_stage]), \
         patch.object(orch, "_run_stage", side_effect=_run_stage_raises), \
         patch("orchestrator.console"):
        result = orch.run("test requirement for budget exceeded")

    # Must return a PipelineResult, not raise
    assert isinstance(result, PipelineResult), (
        f"run() must return a PipelineResult, got {type(result)!r}"
    )

    # Checkpoint must be saved so partial progress is not lost
    mock_save.assert_called_once_with(result), "run() must call _save_checkpoint(result)"

    # Result must contain an error message about the budget
    assert result.errors, "run() must add an error to the result when budget is exceeded"
    budget_error = next(
        (e for e in result.errors if "budget" in str(e).lower()),
        None,
    )
    assert budget_error is not None, (
        f"Expected an error mentioning 'budget', got: {result.errors!r}"
    )


def test_budget_exceeded_error_is_not_reraised(tmp_path):
    """BudgetExceededError must not propagate out of run().

    Before the I4 fix, BudgetExceededError was re-raised by _run_stage() and
    was not caught by the outer try/except in run(), crashing the pipeline thread.
    After the fix, run() catches it and returns cleanly.
    """
    orch = _make_orchestrator()
    fake_stage = _make_budget_stage()

    def _run_stage_raises(*args, **kwargs):
        raise BudgetExceededError("over quota")

    with patch.object(orch, "_load_checkpoint", return_value=None), \
         patch.object(orch, "_save_checkpoint"), \
         patch.object(orch, "_finish", side_effect=lambda r, t: r), \
         patch.object(orch, "_expected_stages", return_value=[]), \
         patch.object(orch, "_build_stage_list", return_value=[fake_stage]), \
         patch.object(orch, "_run_stage", side_effect=_run_stage_raises), \
         patch("orchestrator.console"):
        # Must not raise — if BudgetExceededError escapes, this call propagates it
        try:
            orch.run("test requirement for no-reraise check")
        except BudgetExceededError:
            pytest.fail(
                "BudgetExceededError propagated out of run() — "
                "the except BudgetExceededError clause is missing or misplaced"
            )
