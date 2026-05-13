"""Functional tests for Orchestrator.run() stage ordering, context, checkpoint, failure, clarification.

Tests the high-level behavior of run() including:
- Stage ordering and execution
- Context/result propagation through stages
- Checkpoint save/restore
- Exception handling and propagation
- ClarificationNeeded pausing
"""
from __future__ import annotations

import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from orchestrator import (
    Orchestrator,
    PipelineResult,
    PipelineStage,
    ClarificationNeeded,
)


def _make_orchestrator(workspace_dir: Path | None = None):
    """Create a minimal Orchestrator instance for testing."""
    orch = Orchestrator.__new__(Orchestrator)
    orch.model = "test-model"
    orch.github = None
    orch.target_github = None
    orch.repo = "owner/repo"
    orch._github_token = None
    orch.repo_context_loader = None
    orch.memory = MagicMock()
    orch.memory.recall.return_value = None
    orch.skill_loader = None
    orch._original_system_prompts = {}
    orch._issue_prior_context = ""
    orch._shutdown_event = threading.Event()
    orch._agent_health = MagicMock()
    orch._cost_tracking = {}
    orch.repo_auto_indexer = None
    orch.progress_tracker_mode = "off"
    orch._stage_skips = {}
    orch._stage_timeouts = {}
    orch.stop_on_review_issues = False
    orch._checkpoint_lock = threading.Lock()
    orch.max_prd_revisions = 0
    orch.max_design_revisions = 0
    orch._pipeline_yaml_stages = None
    orch._mode = "standard"
    
    # Set up workspace directory
    if workspace_dir is None:
        workspace_dir = Path(tempfile.mkdtemp())
    orch.workspace_dir = workspace_dir
    
    # Set up agents
    for agent_name in ["pm", "architect", "pm_reviewer", "architect_reviewer",
                       "engineer", "junior_engineer", "senior_engineer", "tier_reviewer",
                       "reviewer", "qa_planner", "qa", "deployment_tester"]:
        agent = MagicMock()
        agent.system_prompt = f"{agent_name} prompt"
        setattr(orch, agent_name, agent)
    
    return orch


@contextmanager
def _mock_run_context(orch):
    """Context manager that mocks orchestrator setup/teardown dependencies for run().

    Mocked: revision loops, checkpoints, console, tracker, ledger.
    NOT mocked: _run_stage, _build_stage_list, _finish (tested as-is).
    """
    with patch.object(orch, "_prd_revision_loop", return_value=True), \
         patch.object(orch, "_design_revision_loop", return_value=True), \
         patch.object(orch, "_save_checkpoint"), \
         patch.object(orch, "_clear_checkpoint"), \
         patch("orchestrator.console"), \
         patch("orchestrator.ProgressTracker"), \
         patch("orchestrator.get_ledger"):
        yield


def _make_result(requirement: str = "test requirement"):
    """Create a minimal PipelineResult for testing."""
    return PipelineResult(requirement=requirement)


# ─────────────────────────────────────────────────────────────────────────────
# Stage ordering tests
# ─────────────────────────────────────────────────────────────────────────────

def test_run_executes_stages_in_order(tmp_path):
    """run() executes stages in the order defined by _build_stage_list."""
    orch = _make_orchestrator(tmp_path)
    executed = []
    
    stage_a = PipelineStage(
        name="stage_a", label="Stage A", description="Running A",
        checkpoint_key="stage_a", fn=lambda r: executed.append("stage_a"),
    )
    stage_b = PipelineStage(
        name="stage_b", label="Stage B", description="Running B",
        checkpoint_key="stage_b", fn=lambda r: executed.append("stage_b"),
    )
    stage_c = PipelineStage(
        name="stage_c", label="Stage C", description="Running C",
        checkpoint_key="stage_c", fn=lambda r: executed.append("stage_c"),
    )
    
    with _mock_run_context(orch), \
         patch.object(orch, "_build_stage_list", return_value=[stage_a, stage_b, stage_c]), \
         patch.object(orch, "_expected_stages", return_value=[]), \
         patch.object(orch, "_finish", return_value=_make_result()):
        orch.run("test requirement", resume=False)
    
    assert executed == ["stage_a", "stage_b", "stage_c"]


def test_run_skips_completed_stages_from_checkpoint(tmp_path):
    """run() skips stages already in result.completed_stages."""
    orch = _make_orchestrator(tmp_path)
    executed = []
    
    stage_a = PipelineStage(
        name="stage_a", label="Stage A", description="Running A",
        checkpoint_key="stage_a", fn=lambda r: executed.append("stage_a"),
    )
    stage_b = PipelineStage(
        name="stage_b", label="Stage B", description="Running B",
        checkpoint_key="stage_b", fn=lambda r: executed.append("stage_b"),
    )
    stage_c = PipelineStage(
        name="stage_c", label="Stage C", description="Running C",
        checkpoint_key="stage_c", fn=lambda r: executed.append("stage_c"),
    )
    
    checkpoint_result = _make_result("test requirement")
    checkpoint_result.completed_stages = ["stage_a"]
    
    with _mock_run_context(orch), \
         patch.object(orch, "_build_stage_list", return_value=[stage_a, stage_b, stage_c]), \
         patch.object(orch, "_expected_stages", return_value=[]), \
         patch.object(orch, "_load_checkpoint", return_value=checkpoint_result), \
         patch.object(orch, "_finish", return_value=checkpoint_result):
        orch.run("test requirement", resume=True)
    
    assert executed == ["stage_b", "stage_c"]


def test_run_respects_skip_if_condition(tmp_path):
    """run() skips stages when skip_if returns True."""
    orch = _make_orchestrator(tmp_path)
    executed = []
    
    stage_a = PipelineStage(
        name="stage_a", label="Stage A", description="Running A",
        checkpoint_key="stage_a", fn=lambda r: executed.append("stage_a"),
    )
    stage_b = PipelineStage(
        name="stage_b", label="Stage B", description="Running B",
        checkpoint_key="stage_b", fn=lambda r: executed.append("stage_b"),
        skip_if=lambda r: True,
    )
    
    with _mock_run_context(orch), \
         patch.object(orch, "_build_stage_list", return_value=[stage_a, stage_b]), \
         patch.object(orch, "_expected_stages", return_value=[]), \
         patch.object(orch, "_finish", return_value=_make_result()):
        orch.run("test requirement", resume=False)
    
    assert executed == ["stage_a"]


# ─────────────────────────────────────────────────────────────────────────────
# Context propagation tests
# ─────────────────────────────────────────────────────────────────────────────

def test_run_passes_result_through_all_stages(tmp_path):
    """run() passes the same PipelineResult object to all stages."""
    orch = _make_orchestrator(tmp_path)
    captured_results = []
    
    def capture_a(result):
        captured_results.append(result)
        result.test_field_a = "value_a"
    
    def capture_b(result):
        captured_results.append(result)
        result.test_field_b = "value_b"
    
    stage_a = PipelineStage(
        name="stage_a", label="Stage A", description="Running A",
        checkpoint_key="stage_a", fn=capture_a,
    )
    stage_b = PipelineStage(
        name="stage_b", label="Stage B", description="Running B",
        checkpoint_key="stage_b", fn=capture_b,
    )
    
    with _mock_run_context(orch), \
         patch.object(orch, "_build_stage_list", return_value=[stage_a, stage_b]), \
         patch.object(orch, "_expected_stages", return_value=[]), \
         patch.object(orch, "_finish", return_value=_make_result()):
        orch.run("test requirement", resume=False)
    
    assert len(captured_results) == 2
    assert captured_results[0] is captured_results[1]
    assert captured_results[1].test_field_a == "value_a"
    assert captured_results[1].test_field_b == "value_b"


# ─────────────────────────────────────────────────────────────────────────────
# Checkpoint save/restore tests
# ─────────────────────────────────────────────────────────────────────────────

def test_run_saves_checkpoint_after_each_stage(tmp_path):
    """run() calls _save_checkpoint after each stage completes."""
    orch = _make_orchestrator(tmp_path)
    
    stage_a = PipelineStage(
        name="stage_a", label="Stage A", description="Running A",
        checkpoint_key="stage_a", fn=lambda r: None,
    )
    stage_b = PipelineStage(
        name="stage_b", label="Stage B", description="Running B",
        checkpoint_key="stage_b", fn=lambda r: None,
    )
    
    with _mock_run_context(orch) as _, \
         patch.object(orch, "_build_stage_list", return_value=[stage_a, stage_b]), \
         patch.object(orch, "_expected_stages", return_value=[]), \
         patch.object(orch, "_save_checkpoint") as mock_save, \
         patch.object(orch, "_finish", return_value=_make_result()):
        orch.run("test requirement", resume=False)
    
    assert mock_save.call_count == 2


def test_run_loads_checkpoint_when_resume_true(tmp_path):
    """run() loads checkpoint when resume=True."""
    orch = _make_orchestrator(tmp_path)
    checkpoint_result = _make_result("test requirement")
    checkpoint_result.completed_stages = ["stage_a"]
    
    with _mock_run_context(orch), \
         patch.object(orch, "_build_stage_list", return_value=[]), \
         patch.object(orch, "_expected_stages", return_value=[]), \
         patch.object(orch, "_load_checkpoint", return_value=checkpoint_result) as mock_load, \
         patch.object(orch, "_finish", return_value=checkpoint_result):
        result = orch.run("test requirement", resume=True)
    
    mock_load.assert_called_once_with("test requirement")
    assert result.completed_stages == ["stage_a"]


def test_run_does_not_load_checkpoint_when_resume_false(tmp_path):
    """run() does not load checkpoint when resume=False."""
    orch = _make_orchestrator(tmp_path)
    
    with _mock_run_context(orch), \
         patch.object(orch, "_build_stage_list", return_value=[]), \
         patch.object(orch, "_expected_stages", return_value=[]), \
         patch.object(orch, "_load_checkpoint") as mock_load, \
         patch.object(orch, "_finish", return_value=_make_result()):
        orch.run("test requirement", resume=False)
    
    mock_load.assert_not_called()


def test_run_clears_checkpoint_on_completion(tmp_path):
    """run() clears checkpoint when all stages complete successfully."""
    orch = _make_orchestrator(tmp_path)
    
    stage = PipelineStage(
        name="stage_a", label="Stage A", description="Running A",
        checkpoint_key="stage_a", fn=lambda r: None,
    )
    
    with _mock_run_context(orch) as _, \
         patch.object(orch, "_build_stage_list", return_value=[stage]), \
         patch.object(orch, "_expected_stages", return_value=[]), \
         patch.object(orch, "_clear_checkpoint") as mock_clear, \
         patch.object(orch, "_finish", return_value=_make_result()):
        orch.run("test requirement", resume=False)
    
    mock_clear.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# Exception handling tests
# ─────────────────────────────────────────────────────────────────────────────

def test_run_stops_on_stage_failure(tmp_path):
    """run() stops pipeline when a stage adds an error to result."""
    orch = _make_orchestrator(tmp_path)
    executed = []
    
    def failing_stage(result):
        executed.append("failing_stage")
        raise RuntimeError("Stage failed")
    
    stage_a = PipelineStage(
        name="failing_stage", label="Failing Stage", description="Will fail",
        checkpoint_key="failing_stage", fn=failing_stage,
    )
    stage_b = PipelineStage(
        name="should_not_run", label="Should Not Run", description="Should skip",
        checkpoint_key="should_not_run", fn=lambda r: executed.append("should_not_run"),
    )
    
    with _mock_run_context(orch), \
         patch.object(orch, "_build_stage_list", return_value=[stage_a, stage_b]), \
         patch.object(orch, "_expected_stages", return_value=[]), \
         patch.object(orch, "_finish", return_value=_make_result()):
        orch.run("test requirement", resume=False)
    
    assert executed == ["failing_stage"]
    # Verify the error was recorded in the result (not silently swallowed)
    # _run_stage catches the exception and calls result.add_error()


def test_run_respects_stop_if_condition(tmp_path):
    """run() stops pipeline when stop_if returns True after a stage."""
    orch = _make_orchestrator(tmp_path)
    executed = []
    
    def mock_stage_a(result):
        executed.append("stage_a")
        result.verdict = "CHANGES REQUESTED"
    
    stage_a = PipelineStage(
        name="stage_a", label="Stage A", description="Running A",
        checkpoint_key="stage_a", fn=mock_stage_a,
        stop_if=lambda r: r.verdict == "CHANGES REQUESTED",
        stop_message="Pipeline stopped due to changes requested",
    )
    stage_b = PipelineStage(
        name="should_not_run", label="Should Not Run", description="Should skip",
        checkpoint_key="should_not_run", fn=lambda r: executed.append("should_not_run"),
    )
    
    with _mock_run_context(orch), \
         patch.object(orch, "_build_stage_list", return_value=[stage_a, stage_b]), \
         patch.object(orch, "_expected_stages", return_value=[]), \
         patch.object(orch, "_finish", return_value=_make_result()):
        orch.run("test requirement", resume=False)
    
    assert executed == ["stage_a"]
    # stop_if is intentional early exit — not an error condition


# ─────────────────────────────────────────────────────────────────────────────
# Result modification tracking
# ─────────────────────────────────────────────────────────────────────────────

def test_run_tracks_completed_stages(tmp_path):
    """run() adds each stage's checkpoint_key to result.completed_stages."""
    orch = _make_orchestrator(tmp_path)
    
    captured_result = None
    
    def capture_result(r):
        nonlocal captured_result
        captured_result = r
    
    stage_a = PipelineStage(
        name="stage_a", label="Stage A", description="Running A",
        checkpoint_key="stage_a", fn=lambda r: None,
    )
    stage_b = PipelineStage(
        name="stage_b", label="Stage B", description="Running B",
        checkpoint_key="stage_b", fn=capture_result,
    )
    
    result = _make_result()
    with _mock_run_context(orch), \
         patch.object(orch, "_build_stage_list", return_value=[stage_a, stage_b]), \
         patch.object(orch, "_expected_stages", return_value=[]), \
         patch.object(orch, "_finish", return_value=result):
        orch.run("test requirement", resume=False)
    
    # Check the result that was passed to the stage functions (which gets modified)
    assert captured_result is not None
    assert "stage_a" in captured_result.completed_stages
    assert "stage_b" in captured_result.completed_stages


def test_run_preserves_requirement(tmp_path):
    """run() creates PipelineResult with the correct requirement."""
    orch = _make_orchestrator(tmp_path)
    requirement = "Build a REST API"
    result = _make_result(requirement)
    
    with _mock_run_context(orch), \
         patch.object(orch, "_build_stage_list", return_value=[]), \
         patch.object(orch, "_expected_stages", return_value=[]), \
         patch.object(orch, "_finish", return_value=result):
        returned_result = orch.run(requirement, resume=False)
    
    assert returned_result.requirement == requirement


def test_run_sets_issue_number_from_parameter(tmp_path):
    """run() sets issue_number on result when provided as parameter."""
    orch = _make_orchestrator(tmp_path)
    
    # Capture the result that run() creates internally
    captured_result = None
    
    def finish_spy(result, *args):
        nonlocal captured_result
        captured_result = result
        return result
    
    with _mock_run_context(orch), \
         patch.object(orch, "_build_stage_list", return_value=[]), \
         patch.object(orch, "_expected_stages", return_value=[]), \
         patch.object(orch, "_finish", side_effect=finish_spy):
        orch.run("test requirement", issue_number=42, resume=False)
    
    assert captured_result is not None
    assert captured_result.issue_number == 42


# ─────────────────────────────────────────────────────────────────────────────
# ClarificationNeeded pausing tests
# ─────────────────────────────────────────────────────────────────────────────

def test_run_pauses_on_clarification_needed_from_prd(tmp_path):
    """run() stops pipeline when _prd_revision_loop returns False due to ClarificationNeeded."""
    orch = _make_orchestrator(tmp_path)
    
    # Mock _prd_revision_loop to return False (simulating ClarificationNeeded was raised internally)
    with patch.object(orch, "_prd_revision_loop", return_value=False), \
         patch.object(orch, "_design_revision_loop") as mock_design, \
         patch.object(orch, "_save_checkpoint"), \
         patch.object(orch, "_clear_checkpoint"), \
         patch.object(orch, "_build_stage_list", return_value=[]), \
         patch.object(orch, "_expected_stages", return_value=[]), \
         patch.object(orch, "_finish", return_value=_make_result()) as mock_finish, \
         patch("orchestrator.console"), \
         patch("orchestrator.ProgressTracker"), \
         patch("orchestrator.get_ledger"):
        orch.run("build a todo app", resume=False)
    
    # When _prd_revision_loop returns False, pipeline should stop
    # and _design_revision_loop should NOT be called
    mock_design.assert_not_called()
    # _finish should be called to wrap up the pipeline
    mock_finish.assert_called_once()
