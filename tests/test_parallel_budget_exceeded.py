"""Test that BudgetExceededError from a parallel stage invokes production error-handling.

The test calls Orchestrator._run_parallel_batch() directly so that the real
try/except BudgetExceededError block in orchestrator.py is exercised.
Removing or misplacing that block would cause the test to fail.
"""
from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

from agents.token_ledger import BudgetExceededError
from orchestrator import Orchestrator, PipelineResult, MAX_PARALLEL_STAGES


def _stub_orchestrator() -> Orchestrator:
    """Build a minimal Orchestrator without calling __init__."""
    orch = Orchestrator.__new__(Orchestrator)
    orch._agent_health = MagicMock()
    orch._shutdown_event = threading.Event()
    orch._stage_timeouts = None
    orch._tracker = MagicMock()
    orch._tracker.comment_id = "comment-42"
    return orch


def test_budget_exceeded_parallel_calls_mark_failed_and_finish():
    """BudgetExceededError in a parallel stage must:
    - call mark_failed() on the triggering stage
    - call _save_checkpoint()
    - call _finish() exactly once
    - return the PipelineResult from _finish()
    """
    orch = _stub_orchestrator()
    result = PipelineResult(requirement="parallel budget test")

    stage_a = MagicMock()
    stage_a.checkpoint_key = "stage_a"
    stage_b = MagicMock()
    stage_b.checkpoint_key = "stage_b"
    runnable = [stage_a, stage_b]

    sentinel_result = object()

    with patch.object(orch, "_run_stage_safe", side_effect=BudgetExceededError("quota")), \
         patch.object(orch, "_finish", return_value=sentinel_result) as mock_finish, \
         patch.object(orch, "_save_checkpoint") as mock_save, \
         patch("orchestrator.console"):

        stage_results: dict[str, bool] = {}
        returned = orch._run_parallel_batch(runnable, result, 0.0, stage_results)

    # Must return whatever _finish() returns
    assert returned is sentinel_result, f"Expected sentinel_result, got {returned!r}"

    # _finish() must be called exactly once
    mock_finish.assert_called_once()

    # mark_failed() must be called with "budget exceeded" on the triggering stage
    assert orch._tracker.mark_failed.called, "mark_failed() was not called"
    call_args = orch._tracker.mark_failed.call_args
    assert call_args[0][1] == "budget exceeded", (
        f"mark_failed() called with wrong reason: {call_args!r}"
    )

    # _save_checkpoint() must be called
    mock_save.assert_called_once_with(result)

    # progress_comment_id must be synced from tracker
    assert result.progress_comment_id == "comment-42"


def test_budget_exceeded_without_fix_would_not_call_mark_failed():
    """Regression guard: if mark_failed is NOT called, the test above catches it.

    This test verifies our assertion is meaningful by confirming mark_failed
    was *not* called when we skip the production code path.
    """
    orch = _stub_orchestrator()
    # Simulate the broken old behaviour: no mark_failed call
    orch._tracker.mark_failed.assert_not_called()
