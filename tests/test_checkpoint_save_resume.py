"""Integration tests for checkpoint save/resume functionality.

T6-B Task 5: verifies that _save_checkpoint / _load_checkpoint round-trip
correctly, honours the "skip empty stages" guard, handles missing workspace
directories gracefully, and always picks the most-completed checkpoint when
multiple candidates exist for the same requirement.
"""
import threading
from pathlib import Path

from orchestrator import Orchestrator, PipelineResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_orchestrator(workspace: Path) -> Orchestrator:
    """Create a minimal Orchestrator wired to *workspace* without spinning up
    any background threads, GitHub clients, or LLM backends.
    """
    orch = Orchestrator.__new__(Orchestrator)
    orch.workspace_dir = workspace
    orch._checkpoint_lock = threading.Lock()
    return orch


def _result(requirement: str, project_name: str = "", stages: list[str] | None = None) -> PipelineResult:
    """Build a PipelineResult with the given fields pre-populated."""
    r = PipelineResult(requirement=requirement, project_name=project_name, prd="some prd text")
    for s in (stages or []):
        r.completed_stages.append(s)
    return r


# ---------------------------------------------------------------------------
# Test 1 — round-trip: save then load preserves all fields
# ---------------------------------------------------------------------------

def test_checkpoint_save_and_load(tmp_path: Path) -> None:
    """Saving a result and loading it back must preserve requirement, project_name,
    prd, and completed_stages exactly."""
    orch = _make_orchestrator(tmp_path)
    result = _result(
        requirement="build a todo app",
        project_name="todo-app",
        stages=["pm"],
    )

    orch._save_checkpoint(result)

    loaded = orch._load_checkpoint("build a todo app")
    assert loaded is not None, "_load_checkpoint returned None — checkpoint was not persisted"
    assert loaded.requirement == "build a todo app"
    assert loaded.project_name == "todo-app"
    assert loaded.prd == "some prd text"
    assert loaded.completed_stages == ["pm"]


# ---------------------------------------------------------------------------
# Test 2 — empty completed_stages → no file written
# ---------------------------------------------------------------------------

def test_checkpoint_skips_nothing_saved_for_empty_stages(tmp_path: Path) -> None:
    """When completed_stages is empty _save_checkpoint must NOT write any file."""
    orch = _make_orchestrator(tmp_path)
    result = _result(requirement="build a dashboard", project_name="dashboard", stages=[])

    orch._save_checkpoint(result)

    checkpoint_files = list(tmp_path.glob("*/checkpoint.json"))
    assert checkpoint_files == [], (
        f"Expected no checkpoint files but found: {checkpoint_files}"
    )


# ---------------------------------------------------------------------------
# Test 3 — load from missing workspace directory → None
# ---------------------------------------------------------------------------

def test_checkpoint_load_returns_none_when_no_file(tmp_path: Path) -> None:
    """_load_checkpoint must return None when the workspace directory does not exist."""
    missing_dir = tmp_path / "does_not_exist"
    orch = _make_orchestrator(missing_dir)

    result = orch._load_checkpoint("build anything")

    assert result is None, f"Expected None but got {result!r}"


# ---------------------------------------------------------------------------
# Test 4 — stage resume: completed stages are recorded; fresh load shows them
# ---------------------------------------------------------------------------

def test_checkpoint_stage_resume_records_completed_stage(tmp_path: Path) -> None:
    """Simulate a 'first run' completing stage_a, saving a checkpoint, then a
    'restart' loading the checkpoint.  The loaded result must show stage_a as
    completed and stage_b as NOT yet completed, so a real orchestrator would
    skip stage_a and run stage_b.
    """
    requirement = "build a REST API"
    project_name = "rest-api"

    # ── First run: stage_a finishes, checkpoint saved ──────────────────────
    orch_run1 = _make_orchestrator(tmp_path)
    result_run1 = _result(requirement=requirement, project_name=project_name, stages=[])

    # Simulate stage_a completing
    result_run1.add_completed_stage("stage_a")
    orch_run1._save_checkpoint(result_run1)

    # ── Simulated restart: fresh orchestrator, load checkpoint ─────────────
    orch_run2 = _make_orchestrator(tmp_path)
    resumed = orch_run2._load_checkpoint(requirement)

    assert resumed is not None, "Checkpoint was not found after restart"
    assert "stage_a" in resumed.completed_stages, (
        "stage_a should be in completed_stages so it can be skipped on resume"
    )
    assert "stage_b" not in resumed.completed_stages, (
        "stage_b was never run, so it must NOT appear in completed_stages"
    )


# ---------------------------------------------------------------------------
# Test 5 — load picks the checkpoint with the most completed stages
# ---------------------------------------------------------------------------

def test_checkpoint_load_picks_most_completed(tmp_path: Path) -> None:
    """When multiple checkpoint files exist for the same requirement, _load_checkpoint
    must return the one with the greatest number of completed stages."""
    requirement = "build a search engine"
    orch = _make_orchestrator(tmp_path)

    # Write a shallow checkpoint (1 stage) under project name "search-v1"
    shallow = _result(requirement=requirement, project_name="search-v1", stages=["pm"])
    orch._save_checkpoint(shallow)

    # Write a deeper checkpoint (2 stages) under a different project name "search-v2"
    deep = _result(
        requirement=requirement,
        project_name="search-v2",
        stages=["pm", "architect"],
    )
    orch._save_checkpoint(deep)

    # Both checkpoint files must exist on disk
    files = list(tmp_path.glob("*/checkpoint.json"))
    assert len(files) == 2, f"Expected 2 checkpoint files, found {len(files)}: {files}"

    # load must favour the deeper checkpoint
    loaded = orch._load_checkpoint(requirement)
    assert loaded is not None
    assert loaded.project_name == "search-v2", (
        "Expected the deeper checkpoint ('search-v2'), not the shallower one"
    )
    assert len(loaded.completed_stages) == 2, (
        f"Expected 2 completed stages (the most-complete checkpoint), "
        f"got {loaded.completed_stages!r}"
    )
    assert "pm" in loaded.completed_stages
    assert "architect" in loaded.completed_stages
