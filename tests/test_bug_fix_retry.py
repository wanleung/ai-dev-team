"""Tests for BugFixOrchestrator test runner and retry wiring."""
from dataclasses import dataclass, field
from typing import Optional
from unittest.mock import MagicMock, patch
import pytest
from bug_fix_orchestrator import BugFixOrchestrator, BugFixResult


def _make_orchestrator():
    orch = BugFixOrchestrator.__new__(BugFixOrchestrator)
    orch.workspace_dir = __import__("pathlib").Path("/tmp/test_bug_fix_workspace")
    orch.github = None
    orch._target_gh = None
    orch._github_token = None
    orch.engineer = MagicMock()
    orch.max_test_retries = 3
    return orch


def test_bug_fix_result_has_retry_fields():
    result = BugFixResult(issue_number=1, issue_title="Bug", issue_body="desc")
    assert hasattr(result, "test_retry_count")
    assert result.test_retry_count == 0
    assert result.test_results == ""
    assert hasattr(result, "test_fix_history")
    assert result.test_fix_history == []
    assert hasattr(result, "tests_passed")
    assert result.tests_passed is None


def test_bug_fix_orchestrator_inherits_mixin():
    from test_fix_loop import TestFixLoopMixin
    assert issubclass(BugFixOrchestrator, TestFixLoopMixin)


def test_stage_test_runner_sets_passed_on_success(tmp_path):
    orch = _make_orchestrator()
    orch.workspace_dir = tmp_path
    result = BugFixResult(issue_number=42, issue_title="T", issue_body="B")
    result.test_files = {"tests/test_foo.py": "def test_dummy(): assert True"}

    # Write test file to disk so pytest can run it
    project_dir = tmp_path / "fix-issue-42"
    project_dir.mkdir()
    tests_dir = project_dir / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_foo.py").write_text("def test_dummy(): assert True")

    orch._stage_test_runner(result)

    assert result.tests_passed is True
    assert "passed" in result.test_results.lower()


def test_stage_test_fix_loop_called_after_qa(tmp_path):
    orch = _make_orchestrator()
    orch.workspace_dir = tmp_path

    result = BugFixResult(issue_number=1, issue_title="Bug", issue_body="b")
    result.test_files = {}
    result.fixed_files = {}

    run_loop_calls = []

    with patch.object(orch, "_stage_test_runner"), \
         patch.object(orch, "run_test_fix_loop", side_effect=lambda **kw: run_loop_calls.append(kw)):
        orch._stage_test_fix_loop(result)

    assert len(run_loop_calls) == 1
