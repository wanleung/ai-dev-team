"""Tests for circuit breaker cascade skip behaviour (T4-B Task 3)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _make_orch():
    """Create a minimal stub Orchestrator for CB cascade tests."""
    from orchestrator import Orchestrator
    o = Orchestrator.__new__(Orchestrator)
    o._agent_health = MagicMock()
    o._stage_timeouts = {}
    return o


def test_pipeline_stage_has_is_critical_field():
    """PipelineStage dataclass must have is_critical field defaulting to False."""
    from orchestrator import PipelineStage
    stage = PipelineStage(
        name="test",
        label="test",
        description="test",
        checkpoint_key="test",
        fn=lambda r: None,
    )
    assert hasattr(stage, "is_critical")
    assert stage.is_critical is False


def test_pm_and_architect_marked_critical():
    """pm and architect stages must be marked is_critical=True in stage registry."""
    orch = _make_orch()
    registry = orch._make_stage_registry()
    pm_stage = registry.get("pm")
    arch_stage = registry.get("architect")
    assert pm_stage is not None and pm_stage.is_critical is True, (
        f"Expected pm.is_critical=True, got {getattr(pm_stage, 'is_critical', 'MISSING')}"
    )
    assert arch_stage is not None and arch_stage.is_critical is True, (
        f"Expected architect.is_critical=True, got {getattr(arch_stage, 'is_critical', 'MISSING')}"
    )


def test_downstream_stage_skipped_when_critical_cb_open():
    """When a critical stage CB is open, _run_stage must record a cascade skip error."""
    from orchestrator import PipelineResult
    orch = _make_orch()
    result = PipelineResult(requirement="test")

    # Mock _critical_cb_open to simulate an open CB on the 'pm' critical stage
    with patch.object(orch, "_critical_cb_open", return_value="pm"):
        orch._run_stage(
            "⚙️ engineer",
            "Running engineer",
            result,
            lambda: None,
        )

    # The stage must have recorded a cascade skip error mentioning 'pm'
    assert len(result.errors) >= 1, "Expected at least one error to be recorded"
    messages = [
        (e.message if hasattr(e, "message") else str(e)).lower()
        for e in result.errors
    ]
    assert any("pm" in msg for msg in messages), (
        f"Expected an error message containing 'pm'. Got: {messages}"
    )
