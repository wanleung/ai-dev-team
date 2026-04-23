"""Tests for Orchestrator._stage_deploy_fix_loop alias/restore pattern."""
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from orchestrator import Orchestrator, PipelineResult


def _make_orchestrator(tmp_path):
    orch = Orchestrator.__new__(Orchestrator)
    orch.workspace_dir = tmp_path
    orch.target_github = None
    orch.engineer = MagicMock()
    orch.max_deploy_retries = 3
    return orch


def _make_result():
    r = PipelineResult.__new__(PipelineResult)
    r.project_name = "testproject"
    r.tests_passed = True          # unit tests passed
    r.test_results = "5 passed"
    r.test_retry_count = 2
    r.test_fix_history = ["Attempt 1: 1 file(s) patched"]
    r.deploy_tests_passed = None   # not yet run
    r.deploy_test_results = ""
    r.deploy_retry_count = 0
    r.deploy_fix_history = []
    r.design = "design doc"
    r.branch = None
    r.pr_number = None
    return r


def test_deploy_loop_restores_unit_test_fields_after_success(tmp_path):
    """Unit-test fields must be unchanged after deploy loop completes."""
    orch = _make_orchestrator(tmp_path)
    result = _make_result()
    result.deploy_tests_passed = True  # deploy passes immediately

    with patch.object(orch, "_stage_deploy_test_runner", side_effect=lambda r: setattr(r, "deploy_tests_passed", True) or setattr(r, "deploy_test_results", "1 passed")):
        orch._stage_deploy_fix_loop(result)

    # Unit-test fields must be exactly as they were before
    assert result.tests_passed is True
    assert result.test_results == "5 passed"
    assert result.test_retry_count == 2
    assert result.test_fix_history == ["Attempt 1: 1 file(s) patched"]


def test_deploy_loop_skips_when_unit_tests_not_passed(tmp_path):
    """_stage_deploy_fix_loop must skip entirely if unit tests did not pass."""
    orch = _make_orchestrator(tmp_path)
    result = _make_result()
    result.tests_passed = False  # unit tests failed

    fix_loop_called = []
    with patch.object(orch, "run_test_fix_loop", side_effect=lambda **kw: fix_loop_called.append(True)):
        orch._stage_deploy_fix_loop(result)

    assert fix_loop_called == []


def test_deploy_loop_does_not_trigger_on_none_deploy_result(tmp_path):
    """None deploy_tests_passed (Docker unavailable) must not trigger fix loop."""
    orch = _make_orchestrator(tmp_path)
    result = _make_result()
    result.tests_passed = True

    fix_attempts = []

    def fake_deploy_test_runner(r):
        r.deploy_tests_passed = None  # Docker not available
        r.deploy_test_results = "Docker not available in this environment."

    with patch.object(orch, "_stage_deploy_test_runner", side_effect=fake_deploy_test_runner), \
         patch.object(orch.engineer, "fix_failures", side_effect=lambda **kw: fix_attempts.append(True) or {}):
        orch._stage_deploy_fix_loop(result)

    assert fix_attempts == [], "fix_failures must not be called when deploy tests are skipped (None)"
