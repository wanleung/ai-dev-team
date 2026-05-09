"""Tests for SkillEntry structured fields and build_structured_prompt() (T2-E)."""
from __future__ import annotations

import warnings
from pathlib import Path

import warnings
from pathlib import Path

from skills_loader import SkillLoader


SAMPLE_SKILL_MD = """---
name: test-skill
description: A test skill
version: 2.0.0
roles:
  engineer: true
  qa: false
tags:
  - python
required_roles:
  - engineer
depends_on:
  - base-skill
min_version: 1.5.0
---
## Engineer

This is the engineer-scoped content.

## QA

This is the QA section.
"""

UNKNOWN_KEY_MD = """---
name: bad-skill
description: Has unknown keys
unknown_field: oops
another_bad: yep
---
Body content.
"""


def _make_loader(tmp_path: Path, content: str, name: str = "skill.md") -> tuple:
    """Write a skill file and return (loader, path)."""
    p = tmp_path / name
    p.write_text(content)
    loader = SkillLoader(config={}, local_skills_dir=tmp_path)
    loader.init()
    return loader, p


def test_required_roles_parsed(tmp_path):
    loader, _ = _make_loader(tmp_path, SAMPLE_SKILL_MD)
    entry = loader._local_skills[0]
    assert entry.required_roles == ["engineer"]


def test_depends_on_parsed(tmp_path):
    loader, _ = _make_loader(tmp_path, SAMPLE_SKILL_MD)
    entry = loader._local_skills[0]
    assert entry.depends_on == ["base-skill"]


def test_min_version_parsed(tmp_path):
    loader, _ = _make_loader(tmp_path, SAMPLE_SKILL_MD)
    entry = loader._local_skills[0]
    assert entry.min_version == "1.5.0"


def test_unknown_frontmatter_keys_warn(tmp_path):
    p = tmp_path / "bad.md"
    p.write_text(UNKNOWN_KEY_MD)
    loader = SkillLoader(config={}, local_skills_dir=tmp_path)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        loader.init()
    assert any("unknown_field" in str(w.message) or "another_bad" in str(w.message) for w in caught)


def test_build_structured_prompt_extracts_role_section(tmp_path):
    loader, _ = _make_loader(tmp_path, SAMPLE_SKILL_MD)
    entry = loader._local_skills[0]
    result = loader.build_structured_prompt(entry, "engineer")
    assert "engineer-scoped content" in result
    assert "QA section" not in result


def test_build_structured_prompt_fallback(tmp_path):
    """When no matching section exists, returns the full raw_body."""
    loader, _ = _make_loader(tmp_path, SAMPLE_SKILL_MD)
    entry = loader._local_skills[0]
    result = loader.build_structured_prompt(entry, "nonexistent_role")
    assert "engineer-scoped content" in result  # full body returned


def test_build_structured_prompt_empty_section_returns_empty(tmp_path):
    """A found but empty role section returns '' not the full body fallback."""
    md = """---
name: empty-section-skill
description: Has an empty engineer section
---
## Engineer

## QA

This is the QA section.
"""
    loader, _ = _make_loader(tmp_path, md)
    entry = loader._local_skills[0]
    result = loader.build_structured_prompt(entry, "engineer")
    assert result == ""
    assert "QA section" not in result
