"""Tests for SkillLoader raising on missing dependency (T5-B Task 4).

Verifies that:
- _resolve_dependencies() raises ValueError when a depends_on skill is not in skill_map
- No error when all deps are present
- No error when a skill has no deps
"""
import pytest
from unittest.mock import patch, MagicMock
from skills_loader import SkillLoader, SkillEntry
from dataclasses import field as dc_field


def _entry(name, depends_on=None):
    return SkillEntry(
        name=name,
        description="test",
        version="1.0.0",
        roles=["developer"],
        tags=[],
        source="test.md",
        raw_body="",
        depends_on=depends_on or [],
        min_version="",
        required_roles=[],
    )


def test_raises_when_dependency_not_loaded():
    """_resolve_dependencies() raises ValueError when a depends_on skill is missing."""
    loader = SkillLoader.__new__(SkillLoader)
    skill_a = _entry("skill-a", depends_on=["skill-b"])
    skill_map = {"skill-a": skill_a}  # skill-b not loaded

    with pytest.raises(ValueError, match="skill-b"):
        loader._resolve_dependencies([skill_a], skill_map)


def test_no_error_when_all_deps_loaded():
    """_resolve_dependencies() succeeds when all deps are in skill_map."""
    loader = SkillLoader.__new__(SkillLoader)
    skill_a = _entry("skill-a", depends_on=["skill-b"])
    skill_b = _entry("skill-b")
    skill_map = {"skill-a": skill_a, "skill-b": skill_b}

    result = loader._resolve_dependencies([skill_a], skill_map)
    names = [s.name for s in result]
    assert "skill-b" in names
    assert "skill-a" in names
    assert names.index("skill-b") < names.index("skill-a")


def test_no_error_when_no_deps():
    """_resolve_dependencies() works fine for skills with no deps."""
    loader = SkillLoader.__new__(SkillLoader)
    skill_a = _entry("skill-a")
    skill_map = {"skill-a": skill_a}
    result = loader._resolve_dependencies([skill_a], skill_map)
    assert len(result) == 1
