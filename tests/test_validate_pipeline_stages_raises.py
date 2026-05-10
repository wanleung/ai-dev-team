"""Verify _validate_pipeline_stages raises ConfigurationError for unknown stages.

Before T6-A, it only logged a warning. Now it must raise so misconfigured
pipelines are caught at load time rather than failing silently at runtime.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from orchestrator import Orchestrator
from core.exceptions import ConfigurationError


def _make_orchestrator() -> Orchestrator:
    """Bypass __init__ — we only need _validate_pipeline_stages and _make_stage_registry."""
    orch = Orchestrator.__new__(Orchestrator)
    orch._agent_health = MagicMock()
    # _make_stage_registry() reads _stage_timeouts to apply per-stage overrides
    orch._stage_timeouts = {}
    return orch


def test_unknown_stage_raises_configuration_error():
    """An unknown stage name must raise ConfigurationError."""
    orch = _make_orchestrator()
    with pytest.raises(ConfigurationError, match="unknown_stage_xyz"):
        orch._validate_pipeline_stages("test-source", ["unknown_stage_xyz"])


def test_known_stages_do_not_raise():
    """Valid stage names must not raise."""
    orch = _make_orchestrator()
    # Get the actual registry keys to pick a valid one
    registry = orch._make_stage_registry()
    valid_stage = next(iter(registry))
    orch._validate_pipeline_stages("test-source", [valid_stage])  # must not raise


def test_empty_stage_list_does_not_raise():
    """An empty list must not raise."""
    orch = _make_orchestrator()
    orch._validate_pipeline_stages("test-source", [])  # must not raise


def test_mixed_raises_on_first_unknown():
    """A list with one valid and one invalid stage must raise on the invalid one."""
    orch = _make_orchestrator()
    registry = orch._make_stage_registry()
    valid_stage = next(iter(registry))
    with pytest.raises(ConfigurationError, match="bad_stage"):
        orch._validate_pipeline_stages("test-source", [valid_stage, "bad_stage"])


def test_all_unknowns_reported_together():
    """Multiple unknown stages must all appear in the error message."""
    orch = _make_orchestrator()
    with pytest.raises(ConfigurationError) as exc_info:
        orch._validate_pipeline_stages("test-source", ["bad_one", "bad_two"])
    msg = str(exc_info.value)
    assert "bad_one" in msg
    assert "bad_two" in msg


def test_loop_inner_stage_raises():
    """Unknown stage inside a loop block must also be validated."""
    orch = _make_orchestrator()
    loop_block = {"loop": {"max": 3, "until": "APPROVED", "stages": ["totally_unknown_inner"]}}
    with pytest.raises(ConfigurationError, match="totally_unknown_inner"):
        orch._validate_pipeline_stages("test-source", [loop_block])
