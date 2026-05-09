"""Tests for loop verdict whitelist validation in _load_pipeline_yaml() (T4-B Task 2)."""
from __future__ import annotations

import pytest
import yaml
from pathlib import Path


def _make_orch():
    """Create a minimal stub Orchestrator sufficient for _load_pipeline_yaml()."""
    from orchestrator import Orchestrator
    o = Orchestrator.__new__(Orchestrator)
    o._stage_timeouts = {}
    return o


def _write_pipeline_yaml(tmp_path: Path, until: str) -> Path:
    """Write a minimal pipeline.yaml with a loop block using the given 'until' value."""
    content = {
        "stages": [
            {
                "loop": {
                    "stages": ["pm", "pm_reviewer"],
                    "until": until,
                    "max": 3,
                }
            }
        ]
    }
    p = tmp_path / "pipeline.yaml"
    p.write_text(yaml.dump(content))
    # config_path sibling — _load_pipeline_yaml uses Path(config_path).parent / "pipeline.yaml"
    config_path = tmp_path / "config.yaml"
    config_path.write_text("")
    return config_path


def test_invalid_loop_until_raises_config_error(tmp_path):
    """A typo in loop 'until' must raise an error at load time."""
    orch = _make_orch()
    config_path = _write_pipeline_yaml(tmp_path, until="APPROVD")  # typo
    with pytest.raises(ValueError, match="(?i)until|verdict|APPROVD"):
        orch._load_pipeline_yaml(str(config_path))


def test_valid_loop_until_approved_passes(tmp_path):
    """loop until: APPROVED must load without error."""
    orch = _make_orch()
    config_path = _write_pipeline_yaml(tmp_path, until="APPROVED")
    result = orch._load_pipeline_yaml(str(config_path))
    assert result is not None


def test_valid_loop_until_needs_revision_passes(tmp_path):
    """loop until: NEEDS_REVISION must load without error."""
    orch = _make_orch()
    config_path = _write_pipeline_yaml(tmp_path, until="NEEDS_REVISION")
    result = orch._load_pipeline_yaml(str(config_path))
    assert result is not None
