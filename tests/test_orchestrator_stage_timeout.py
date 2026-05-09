"""Tests for per-stage timeout in Orchestrator._run_stage() (T2-C Task 1)."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from orchestrator import Orchestrator, PipelineResult


def _make_orchestrator():
    orch = Orchestrator.__new__(Orchestrator)
    orch._agent_health = MagicMock()
    return orch


def _make_result():
    r = PipelineResult.__new__(PipelineResult)
    r.errors = []
    r.add_error = lambda msg: r.errors.append(msg)
    return r


def test_stage_timeout_records_error():
    """When a stage exceeds timeout_s, _run_stage records a timeout error."""
    orch = _make_orchestrator()
    result = _make_result()

    def slow_fn():
        time.sleep(0.2)  # longer than the timeout but short enough for fast test runs

    with patch("orchestrator.console"):
        orch._run_stage("TestStage", "testing...", result, slow_fn, timeout_s=0.05)

    assert len(result.errors) == 1
    assert "timed out" in result.errors[0]
    assert "TestStage" in result.errors[0]


def test_stage_no_timeout_runs_normally():
    """When timeout_s is None, the stage runs normally with no error."""
    orch = _make_orchestrator()
    result = _make_result()
    called = []

    def fast_fn():
        called.append(True)

    with patch("orchestrator.console"):
        orch._run_stage("FastStage", "testing...", result, fast_fn, timeout_s=None)

    assert called == [True]
    assert result.errors == []
