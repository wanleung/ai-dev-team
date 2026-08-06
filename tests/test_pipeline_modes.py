"""Tests for TDD pipeline mode: stage registry, mode config, QA write-only, engineer test injection."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock


# ── Task 1: QAEngineerAgent write_only ───────────────────────────────────────

def test_qa_engineer_write_only_returns_test_files_without_running():
    """write_only=True returns test_files and skips test execution."""
    from agents.qa_engineer import QAEngineerAgent

    agent = QAEngineerAgent.__new__(QAEngineerAgent)
    agent._tool_registry = None
    agent.call = MagicMock(return_value=(
        "### FILE: tests/test_auth.py\n```python\ndef test_login(): pass\n```"
    ))

    result = agent.run({}, "PRD text", project_name="myapp", write_only=True)

    assert "tests/test_auth.py" in result["test_files"]
    assert result.get("tests_ran") is False


def test_qa_engineer_write_only_prompt_does_not_mention_implemented_code():
    """write_only prompt should say 'define the expected behavior', not 'verify implemented code'."""
    from agents.qa_engineer import QAEngineerAgent

    agent = QAEngineerAgent.__new__(QAEngineerAgent)
    agent._tool_registry = None
    captured = {}
    def capture_call(prompt):
        captured["prompt"] = prompt
        return "### FILE: tests/test_foo.py\n```python\npass\n```"
    agent.call = capture_call

    agent.run({}, "PRD text", project_name="myapp", write_only=True)

    assert "define the expected behavior" in captured["prompt"]
    assert "Implemented code" not in captured["prompt"]


def test_qa_engineer_normal_mode_unchanged():
    """Normal run() (write_only=False default) works as before."""
    from agents.qa_engineer import QAEngineerAgent

    agent = QAEngineerAgent.__new__(QAEngineerAgent)
    agent._tool_registry = None
    agent.call = MagicMock(return_value=(
        "### FILE: tests/test_foo.py\n```python\ndef test_x(): pass\n```\n"
        "## Test Plan\nsome plan"
    ))

    result = agent.run({"main.py": "print('hi')"}, "PRD", project_name="p")

    assert "tests/test_foo.py" in result["test_files"]
    # Normal mode: tests_ran is True
    assert result.get("tests_ran") is True


# ── Task 2: EngineerAgent test_files injection ───────────────────────────────

def test_engineer_run_module_injects_test_files_into_prompt():
    """When test_files is provided, the prompt includes their content."""
    from agents.engineer import EngineerAgent

    agent = EngineerAgent.__new__(EngineerAgent)
    agent._tool_registry = None
    captured = {}
    def capture_call(prompt):
        captured["prompt"] = prompt
        return "### FILE: auth.py\n```python\npass\n```"
    agent.call = capture_call
    agent._parse_files = MagicMock(return_value={"auth.py": "pass"})

    agent.run_module(
        design="design",
        module={"name": "auth", "description": "auth module"},
        project_name="myapp",
        test_files={"tests/test_auth.py": "def test_login(): pass"},
    )

    assert "Pre-written tests" in captured["prompt"]
    assert "tests/test_auth.py" in captured["prompt"]
    assert "def test_login(): pass" in captured["prompt"]


def test_engineer_run_module_no_test_files_unchanged():
    """When test_files is absent, the prompt is unchanged (no test section)."""
    from agents.engineer import EngineerAgent

    agent = EngineerAgent.__new__(EngineerAgent)
    agent._tool_registry = None
    captured = {}
    def capture_call(prompt):
        captured["prompt"] = prompt
        return "### FILE: auth.py\n```python\npass\n```"
    agent.call = capture_call
    agent._parse_files = MagicMock(return_value={"auth.py": "pass"})

    agent.run_module(
        design="design",
        module={"name": "auth", "description": "auth module"},
        project_name="myapp",
    )

    assert "Pre-written tests" not in captured["prompt"]


# ── Task 3: PipelineStage + MODES ────────────────────────────────────────────

def test_modes_dict_standard_contains_expected_stages():
    from orchestrator import MODES
    standard = MODES["standard"]
    assert "tier_review" in standard
    assert "junior_engineer" in standard
    assert "senior_engineer" in standard
    assert "reviewer" in standard
    assert "qa_planner" in standard
    assert "qa_engineer" in standard
    assert "test_fix" in standard
    assert "deploy_tester" in standard
    assert "deploy_fix" in standard
    # qa_write must NOT be in standard mode
    assert "qa_write" not in standard


def test_modes_dict_tdd_contains_qa_write_before_engineers():
    from orchestrator import MODES
    tdd = MODES["tdd"]
    assert "qa_write" in tdd
    assert "qa_planner" in tdd
    qa_write_idx = tdd.index("qa_write")
    jr_idx = tdd.index("junior_engineer")
    sr_idx = tdd.index("senior_engineer")
    assert qa_write_idx < jr_idx
    assert qa_write_idx < sr_idx


def test_modes_dict_tdd_has_reviewer_after_test_fix():
    from orchestrator import MODES
    tdd = MODES["tdd"]
    reviewer_idx = tdd.index("reviewer")
    test_fix_idx = tdd.index("test_fix")
    assert reviewer_idx > test_fix_idx


def test_modes_dict_tdd_has_no_qa_engineer():
    """TDD mode uses qa_write instead of qa_engineer."""
    from orchestrator import MODES
    assert "qa_engineer" not in MODES["tdd"]


def test_modes_dict_planned_has_superpowers_tdd_review_before_engineers():
    """Planned mode ingests Superpowers artifacts and gates TDD tests before implementation."""
    from orchestrator import MODES
    planned = MODES["planned"]
    assert planned[:2] == ["superpowers_ingest", "qa_planner"]
    assert "qa_write" in planned
    assert "tdd_review" in planned
    assert "qa_fix" in planned
    assert planned.index("tdd_review") < planned.index("junior_engineer")
    assert planned.index("qa_fix") < planned.index("junior_engineer")


def test_pipeline_stage_defaults_skip_stop_to_false():
    from orchestrator import PipelineStage, PipelineResult
    stage = PipelineStage(
        name="example",
        label="Example",
        description="Running example",
        checkpoint_key="example_done",
        fn=lambda r: None,
    )
    r = PipelineResult(requirement="test req")
    assert stage.skip_if(r) is False
    assert stage.stop_if(r) is False


def test_pipeline_stage_required_fields():
    import dataclasses
    from orchestrator import PipelineStage
    fields = {f.name for f in dataclasses.fields(PipelineStage)}
    assert {"name", "label", "description", "checkpoint_key", "fn"} <= fields


# ── Task 4: Orchestrator config + _build_stage_list ──────────────────────────

def _make_minimal_orch(mode: str = "standard", stage_skips: dict | None = None):
    """Build a minimal Orchestrator with mode set, all agents mocked."""
    from orchestrator import Orchestrator
    o = Orchestrator.__new__(Orchestrator)
    # Set all attrs that _make_stage_registry references
    o._mode = mode
    o._stage_skips = stage_skips or {}
    o.stop_on_review_issues = False
    # Minimal agents — stage methods are called in some tests (T5+), so real implementations run.
    o._stage_tier_review = lambda r: None
    o._stage_senior_engineer = lambda r: None
    o._stage_reviewer = lambda r: None
    o._stage_qa_planner = lambda r: None
    o._stage_qa = lambda r: None
    o._stage_test_fix_loop = lambda r: None
    o._stage_deployment_tester = lambda r: None
    o._stage_deploy_fix_loop = lambda r: None
    # Supporting attributes needed when real stage methods are called
    o.workspace_dir = MagicMock()
    o.framework_docs_loader = MagicMock(load=MagicMock(return_value=""))
    o.num_junior_engineers = 1
    o.junior_quality_gate = False
    o._save_files_locally = MagicMock()
    o.tdd_commit_tests = False  # token-counter feature
    return o


def test_build_stage_list_standard_order():
    o = _make_minimal_orch(mode="standard")
    stages = o._build_stage_list()
    names = [s.name for s in stages]
    assert names.index("tier_review") < names.index("junior_engineer")
    assert names.index("junior_engineer") < names.index("reviewer")
    assert names.index("reviewer") < names.index("qa_planner")
    assert names.index("qa_planner") < names.index("qa_engineer")
    assert "qa_write" not in names


def test_build_stage_list_tdd_order():
    o = _make_minimal_orch(mode="tdd")
    stages = o._build_stage_list()
    names = [s.name for s in stages]
    assert names.index("qa_write") < names.index("junior_engineer")
    assert names.index("test_fix") < names.index("reviewer")
    assert "qa_engineer" not in names


def test_build_stage_list_planned_order():
    o = _make_minimal_orch(mode="planned")
    stages = o._build_stage_list()
    names = [s.name for s in stages]
    assert names[0] == "superpowers_ingest"
    assert names.index("tdd_review") < names.index("junior_engineer")
    assert names.index("qa_fix") < names.index("junior_engineer")
    assert "qa_engineer" not in names


def test_build_stage_list_respects_skip_config():
    o = _make_minimal_orch(mode="standard", stage_skips={"reviewer": True})
    stages = o._build_stage_list()
    names = [s.name for s in stages]
    assert "reviewer" not in names


def test_orchestrator_from_config_reads_mode(tmp_path, monkeypatch):
    import yaml
    from orchestrator import Orchestrator

    cfg = {
        "llm": {"model": "openai/gpt-4.1-mini"},
        "pipeline": {
            "mode": "tdd",
            "stages": {"reviewer": {"skip": True}},
        },
    }
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump(cfg))
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")

    o = Orchestrator.from_config(str(cfg_file))
    assert o._mode == "tdd"
    assert o._stage_skips.get("reviewer") is True


def test_orchestrator_from_config_defaults_to_standard(tmp_path, monkeypatch):
    import yaml
    from orchestrator import Orchestrator

    cfg = {"llm": {"model": "openai/gpt-4.1-mini"}, "pipeline": {}}
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump(cfg))
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")

    o = Orchestrator.from_config(str(cfg_file))
    assert o._mode == "standard"
    assert o._stage_skips == {}


def test_build_stage_list_raises_on_unknown_mode():
    o = _make_minimal_orch(mode="nonexistent")
    with pytest.raises(ValueError, match="nonexistent"):
        o._build_stage_list()


def test_from_config_raises_on_non_dict_stage_value(tmp_path, monkeypatch):
    import yaml
    from orchestrator import Orchestrator
    cfg = {
        "llm": {"model": "openai/gpt-4.1-mini"},
        "pipeline": {"stages": {"reviewer": True}},
    }
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump(cfg))
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    with pytest.raises(ValueError, match="pipeline.stages.reviewer"):
        Orchestrator.from_config(str(cfg_file))


def test_build_stage_list_standard_complete():
    o = _make_minimal_orch(mode="standard")
    names = [s.name for s in o._build_stage_list()]
    expected = [
        "tier_review", "junior_engineer", "senior_engineer", "reviewer",
        "qa_planner", "qa_engineer", "test_fix", "deploy_tester", "deploy_fix",
    ]
    assert names == expected

# ── Task 5 ──────────────────────────────────────────────────────────────────
from orchestrator import PipelineResult  # noqa: E402 — imported here for T5 tests

def test_stage_qa_write_stores_test_files(monkeypatch, tmp_path):
    """_stage_qa_write() stores test_files on result and writes locally."""
    orch = _make_minimal_orch()
    orch.output_dir = str(tmp_path)
    orch._mode = "standard"

    fake_qa = MagicMock()
    fake_qa.run.return_value = {
        "test_files": {"test_app.py": "def test_hello(): pass"},
        "test_plan": "Plan here",
    }
    orch.qa = fake_qa
    orch._save_files_locally = MagicMock()

    result = PipelineResult(project_name="testproj", prd="PRD text", qa_plan="Plan here")
    orch._stage_qa_write(result)

    assert result.test_files == {"test_app.py": "def test_hello(): pass"}
    assert result.test_plan == "Plan here"
    orch._save_files_locally.assert_called_once_with(
        {"test_app.py": "def test_hello(): pass"}, "testproj"
    )


def test_stage_qa_write_indexes_tests_without_logger_name_error(tmp_path):
    """_stage_qa_write() indexes generated tests when RAG indexing is enabled."""
    orch = _make_minimal_orch()
    orch.workspace_dir = tmp_path
    orch.repo_auto_indexer = MagicMock()

    fake_qa = MagicMock()
    fake_qa.run.return_value = {
        "test_files": {"tests/test_app.py": "def test_hello(): pass"},
        "test_plan": "Plan here",
    }
    orch.qa = fake_qa
    orch._save_files_locally = MagicMock()

    result = PipelineResult(project_name="Test Project", prd="PRD text", qa_plan="Plan here")
    orch._stage_qa_write(result)

    orch.repo_auto_indexer.index_local_dir.assert_called_once()


def test_stage_superpowers_ingest_maps_artifacts_to_pipeline_result():
    """Superpowers spec/plan becomes the PRD/design contract used by downstream agents."""
    orch = _make_minimal_orch()
    orch._superpowers_artifacts = {
        "spec": "# Spec\n\nAcceptance Criteria:\n- Login works\n- Logout works",
        "plan": "# Plan\n\n### Task 1: Auth API\nBuild login/logout endpoints.",
        "sources": {"spec": "issue", "plan": "issue"},
    }

    result = PipelineResult(requirement="Build auth")
    orch._stage_superpowers_ingest(result)

    assert result.prd.startswith("# Spec")
    assert result.design.startswith("# Plan")
    assert result.project_name == "Spec"
    assert result.qa_acceptance_criteria == ["Login works", "Logout works"]
    assert result.modules == [{"name": "Auth API", "description": "Build login/logout endpoints."}]


def test_stage_qa_fix_aliases_tdd_review():
    """qa_fix is a named pipeline stage for reviewing/fixing generated TDD tests."""
    orch = _make_minimal_orch()
    orch._stage_tdd_review = MagicMock()
    result = PipelineResult(test_files={"tests/test_app.py": "def test_x(): pass"})

    orch._stage_qa_fix(result)

    orch._stage_tdd_review.assert_called_once_with(result)


def test_stage_test_runner_stops_on_pytest_collection_failure(monkeypatch, tmp_path):
    """_stage_test_runner() records collection failures before running full pytest."""
    from types import SimpleNamespace

    from orchestrator import Orchestrator

    orch = Orchestrator.__new__(Orchestrator)
    orch.workspace_dir = tmp_path
    orch.target_github = MagicMock()

    project_dir = tmp_path / "project"
    tests_dir = project_dir / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_bad.py").write_text("from tests.conftest import _Obj\n")

    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if "pip" in args:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if "--collect-only" in args:
            return SimpleNamespace(returncode=2, stdout="", stderr="collection failed")
        raise AssertionError("full pytest should not run after collection failure")

    monkeypatch.setattr("orchestrator.subprocess.run", fake_run)

    result = PipelineResult(project_name="project", pr_number=2)
    orch._stage_test_runner(result)

    assert result.tests_passed is False
    assert "collection failed" in result.test_results
    assert any("--collect-only" in call for call in calls)
    orch.target_github.add_pr_comment.assert_called_once()


def test_stage_junior_engineer_omits_test_files_in_standard_mode(monkeypatch):
    """_stage_junior_engineer() passes test_files=None when mode is not tdd."""
    orch = _make_minimal_orch()
    orch._mode = "standard"
    orch.target_github = None

    fake_eng = MagicMock()
    fake_eng.run_all_modules.return_value = {"modules": []}
    orch.junior_engineer = fake_eng

    result = PipelineResult(
        project_name="proj",
        prd="PRD",
        design_output={"modules": [{"name": "mod", "description": "desc"}]},
        test_files={"test_mod.py": "def test_x(): pass"},
    )
    orch._stage_junior_engineer(result)

    call_kwargs = fake_eng.run_all_modules.call_args
    assert call_kwargs.kwargs.get("test_files") is None



def test_stage_junior_engineer_passes_test_files_in_tdd_mode(monkeypatch):
    """_stage_junior_engineer() passes test_files when mode is tdd."""
    orch = _make_minimal_orch()
    orch._mode = "tdd"
    orch.target_github = None  # force local path

    fake_eng = MagicMock()
    fake_eng.run_all_modules.return_value = {"modules": []}
    orch.junior_engineer = fake_eng

    result = PipelineResult(
        project_name="proj",
        prd="PRD",
        design_output={"modules": [{"name": "mod", "description": "desc"}]},
        test_files={"test_mod.py": "def test_x(): pass"},
    )
    orch._stage_junior_engineer(result)

    call_kwargs = fake_eng.run_all_modules.call_args
    assert call_kwargs.kwargs.get("test_files") == {"test_mod.py": "def test_x(): pass"}


# ── Task 6: run() stage loop ──────────────────────────────────────────────────

def _make_full_orch(mode: str = "standard"):
    """Build a minimal but runnable Orchestrator with all stages mocked."""
    from orchestrator import Orchestrator

    o = Orchestrator.__new__(Orchestrator)
    o._mode = mode
    o._stage_skips = {}
    o.stop_on_review_issues = False
    o.stop_on_design_issues = False
    o.stop_on_prd_issues = False
    o.max_prd_revisions = 0
    o.max_design_revisions = 0
    o.workspace_dir = MagicMock()
    o.github = None
    o.target_github = None
    o.memory = MagicMock(recall=MagicMock(return_value=None))
    o.skill_loader = None
    o.repo_context_loader = None
    o.repo_auto_indexer = None
    o._github_token = None
    o.progress_tracker_mode = "off"
    o._cost_tracking = {}  # token-counter feature; disabled in tests
    o.tdd_commit_tests = False  # token-counter feature helper attr

    # Minimal result fixture
    def fake_load_checkpoint(req):
        return None
    def fake_save_checkpoint(r): pass
    def fake_clear_checkpoint(r): pass
    def fake_finish(r, t):
        return r
    o._load_checkpoint = fake_load_checkpoint
    o._save_checkpoint = fake_save_checkpoint
    o._clear_checkpoint = fake_clear_checkpoint
    o._finish = fake_finish

    # All stage methods stubbed — record calls
    called = []
    def make_stub(name):
        def stub(r):
            called.append(name)
        return stub

    stage_names = [
        "_stage_tier_review", "_stage_junior_engineer", "_stage_senior_engineer",
        "_stage_reviewer", "_stage_qa_planner", "_stage_qa", "_stage_qa_write",
        "_stage_test_fix_loop", "_stage_deployment_tester", "_stage_deploy_fix_loop",
    ]
    for name in stage_names:
        setattr(o, name, make_stub(name))

    # Minimal PRD/design loop stubs
    def fake_prd_loop(r, req):
        r.prd = "PRD"
        r.project_name = "myapp"
        r.completed_stages.append("pm_review_loop")
        return True
    def fake_design_loop(r):
        r.design = "design"
        r.modules = [{"name": "auth", "description": "auth", "tier": "junior"}]
        r.completed_stages.append("architect_review_loop")
        return True

    o._prd_revision_loop = fake_prd_loop
    o._design_revision_loop = fake_design_loop
    o._run_stage = MagicMock(side_effect=lambda label, desc, r, fn, timeout_s=None, required_output_fields=None, cb_key=None, is_critical=False: fn())

    return o, called


def test_run_standard_mode_calls_qa_engineer_not_qa_write():
    o, called = _make_full_orch(mode="standard")
    # need test_files to avoid test_fix skip
    # (skip_if checks r.test_files — leave empty to skip test_fix)
    o.run("build x")
    assert "_stage_qa" in called
    assert "_stage_qa_write" not in called
    assert "_stage_senior_engineer" in called
    assert "_stage_tier_review" in called


def test_run_tdd_mode_calls_qa_write_not_qa_engineer():
    o, called = _make_full_orch(mode="tdd")
    o.run("build x")
    assert "_stage_qa_write" in called
    assert "_stage_qa" not in called


def test_run_tdd_mode_qa_write_before_junior_engineer():
    o, called = _make_full_orch(mode="tdd")
    o.run("build x")
    assert called.index("_stage_qa_write") < called.index("_stage_junior_engineer")


def test_run_tdd_mode_test_fix_before_reviewer():
    o, called = _make_full_orch(mode="tdd")
    # give test_files so test_fix isn't skipped
    def fake_qa_write(r):
        r.test_files = {"tests/test_foo.py": "pass"}
        called.append("_stage_qa_write")
    o._stage_qa_write = fake_qa_write
    o.run("build x")
    assert called.index("_stage_test_fix_loop") < called.index("_stage_reviewer")


def test_run_reviewer_stop_marks_reviewer_as_completed():
    """When reviewer triggers stop_if, reviewer checkpoint_key is already saved."""
    from orchestrator import Orchestrator
    o, called = _make_full_orch(mode="standard")

    # Make reviewer's stop_if return True
    # Patch stop_if on reviewer stage via _build_stage_list override
    saved_build = Orchestrator._build_stage_list
    def patched_build(self):
        stage_list = saved_build(self)
        for i, s in enumerate(stage_list):
            if s.name == "reviewer":
                import dataclasses
                stage_list[i] = dataclasses.replace(s, stop_if=lambda r: True)
        return stage_list
    o._build_stage_list = lambda: patched_build(o)

    result = o.run("build x")
    # reviewer checkpoint_key should be in completed_stages
    assert "reviewer" in result.completed_stages
