"""Verify that _run_stage() enforces required_output_fields via OutputVerifier.

These inline call sites were missing required_output_fields before T6-A; this
test confirms OutputVerifier is now active on those paths.
"""
from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

from orchestrator import Orchestrator, PipelineResult

def _make_orchestrator() -> Orchestrator:
    """Bypass __init__ — we only need _run_stage() wired up."""
    orch = Orchestrator.__new__(Orchestrator)
    orch._agent_health = MagicMock()
    orch._shutdown_event = threading.Event()
    return orch


def _make_result() -> PipelineResult:
    return PipelineResult(requirement="test requirement")


def test_run_stage_raises_when_required_field_missing():
    """_run_stage records OutputVerificationError when stage omits a required field."""
    orch = _make_orchestrator()
    result = _make_result()

    def stage_fn():
        # Deliberately sets nothing — result.prd stays ""
        pass

    with patch("orchestrator.console"), \
         patch.object(orch, "_critical_cb_open", return_value=None):
        orch._run_stage(
            "Test Stage",
            "testing...",
            result,
            stage_fn,
            required_output_fields=["prd"],
        )

    assert len(result.errors) == 1
    assert "prd" in result.errors[0].message


def test_run_stage_passes_when_required_field_present():
    """_run_stage does not record an error when the required field is populated."""
    orch = _make_orchestrator()
    result = _make_result()

    def stage_fn():
        result.prd = "A well-written PRD"

    with patch("orchestrator.console"), \
         patch.object(orch, "_critical_cb_open", return_value=None):
        orch._run_stage(
            "Test Stage",
            "testing...",
            result,
            stage_fn,
            required_output_fields=["prd"],
        )

    assert len(result.errors) == 0
