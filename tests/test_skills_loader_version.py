"""Tests for semver-aware min_version using packaging.version (T5-B Task 2).

Verifies that:
- Stable release > release candidate (PEP 440 semantics)
- Empty min_version always passes
- Invalid version strings fall back gracefully without raising
"""
import pytest
from skills_loader import SkillLoader


def _check(version, min_version):
    return SkillLoader._check_min_version(version, min_version)


def test_stable_greater_than_rc():
    """1.2.0 >= 1.2.0-rc1 must be True (stable > pre-release)."""
    assert _check("1.2.0", "1.2.0-rc1") is True


def test_rc_not_greater_than_stable():
    """1.2.0-rc1 >= 1.2.0 must be False (pre-release < stable)."""
    assert _check("1.2.0-rc1", "1.2.0") is False


def test_standard_semver_ordering():
    """Standard ordering still works."""
    assert _check("2.0.0", "1.9.9") is True
    assert _check("1.0.0", "2.0.0") is False
    assert _check("1.2.3", "1.2.3") is True


def test_empty_min_version_always_passes():
    """Empty min_version means no constraint."""
    assert _check("0.0.1", "") is True
    assert _check("1.2.0-rc1", "") is True


def test_invalid_version_falls_back_gracefully():
    """Invalid version strings don't crash — fall back to tuple comparison."""
    # Should not raise
    result = _check("not-a-version", "1.0.0")
    assert isinstance(result, bool)
