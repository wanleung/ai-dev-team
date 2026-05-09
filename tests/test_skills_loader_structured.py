"""Tests for SkillEntry structured fields and build_structured_prompt() (T2-E)."""
from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from skills_loader import SkillLoader, SkillContext


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


# ── Feature 1: depends_on topological sort ─────────────────────────────────────

def _make_skill(tmp_path, name, depends_on=None, tags=None, version="1.0.0"):
    """Helper: write a minimal skill file and return its path."""
    deps_str = ""
    if depends_on:
        deps_str = f"depends_on: [{', '.join(depends_on)}]\n"
    tags_str = f"tags: [{', '.join(tags or [])}]\n"
    content = (
        f"---\nname: {name}\ndescription: {name} skill\nversion: {version}\n"
        f"roles: {{engineer: true}}\n{deps_str}{tags_str}---\n\n# {name}\nContent of {name}.\n"
    )
    skill_file = tmp_path / f"{name}.md"
    skill_file.write_text(content)
    return skill_file


def test_detect_pulls_in_dependency_not_directly_matched(tmp_path):
    """detect() includes skill B when skill A depends_on B, even if B has no tag match."""
    _make_skill(tmp_path, "base-skill", tags=["base"])
    _make_skill(tmp_path, "advanced-skill", depends_on=["base-skill"], tags=["advanced"])

    loader = SkillLoader(local_skills_dir=tmp_path).init()
    ctx = SkillContext(issue_body="advanced", explicit_skills=[], repo_languages=[])
    result = loader.detect(ctx)

    names = [s.name for s in result]
    assert "base-skill" in names, "Dependency should be pulled in automatically"
    assert "advanced-skill" in names


def test_detect_dependency_ordered_before_dependent(tmp_path):
    """detect() places base-skill before advanced-skill when advanced depends_on base."""
    _make_skill(tmp_path, "base-skill", tags=["base"])
    _make_skill(tmp_path, "advanced-skill", depends_on=["base-skill"], tags=["advanced"])

    loader = SkillLoader(local_skills_dir=tmp_path).init()
    ctx = SkillContext(issue_body="base advanced", explicit_skills=[], repo_languages=[])
    result = loader.detect(ctx)

    names = [s.name for s in result]
    assert names.index("base-skill") < names.index("advanced-skill"), (
        f"base-skill must come before advanced-skill, got: {names}"
    )


def test_detect_raises_on_circular_dependency(tmp_path):
    """detect() raises ValueError when skills have a circular dependency."""
    _make_skill(tmp_path, "skill-x", depends_on=["skill-y"], tags=["x"])
    _make_skill(tmp_path, "skill-y", depends_on=["skill-x"], tags=["y"])

    loader = SkillLoader(local_skills_dir=tmp_path).init()
    ctx = SkillContext(issue_body="x y", explicit_skills=[], repo_languages=[])
    with pytest.raises(ValueError, match="[Cc]ircular"):
        loader.detect(ctx)


# ── Feature 2: required_roles enforcement ──────────────────────────────────────

def test_for_role_excludes_skill_when_role_not_in_required_roles(tmp_path):
    """for_role() skips a skill if role is not listed in required_roles."""
    content = (
        "---\nname: arch-only\ndescription: arch only\nversion: 1.0.0\n"
        "roles: {engineer: true, architect: true}\n"
        "required_roles: [architect]\n"
        "---\n\n## For Architects\nArch content.\n\n## For Engineers\nEng content.\n"
    )
    (tmp_path / "arch-only.md").write_text(content)

    loader = SkillLoader(local_skills_dir=tmp_path).init()
    ctx = SkillContext(issue_body="", explicit_skills=["arch-only"], repo_languages=[])
    matched = loader.detect(ctx)

    # engineer role: arch-only has required_roles=[architect], engineer is NOT in it → skip
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        blocks = loader.for_role("engineer", matched)
    assert blocks == [], f"Expected no blocks for engineer, got: {blocks}"
    assert any("required_roles" in str(warning.message) for warning in w)


def test_for_role_includes_skill_when_role_in_required_roles(tmp_path):
    """for_role() includes the skill when role IS listed in required_roles."""
    content = (
        "---\nname: arch-only\ndescription: arch only\nversion: 1.0.0\n"
        "roles: {engineer: true, architect: true}\n"
        "required_roles: [architect]\n"
        "---\n\n## For Architects\nArch content.\n"
    )
    (tmp_path / "arch-only.md").write_text(content)

    loader = SkillLoader(local_skills_dir=tmp_path).init()
    ctx = SkillContext(issue_body="", explicit_skills=["arch-only"], repo_languages=[])
    matched = loader.detect(ctx)

    blocks = loader.for_role("architect", matched)
    assert len(blocks) == 1
    assert "Arch content" in blocks[0].content


# ── Feature 3: min_version semver enforcement ──────────────────────────────────

def test_detect_excludes_skill_below_min_version(tmp_path):
    """detect() excludes a skill whose version is below min_version."""
    content = (
        "---\nname: old-skill\ndescription: desc\nversion: 1.1.0\n"
        "min_version: 2.0.0\nroles: {engineer: true}\ntags: [python]\n"
        "---\n\nContent.\n"
    )
    (tmp_path / "old-skill.md").write_text(content)

    loader = SkillLoader(local_skills_dir=tmp_path).init()
    ctx = SkillContext(issue_body="python", explicit_skills=[], repo_languages=[])

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = loader.detect(ctx)

    assert all(s.name != "old-skill" for s in result), "Skill below min_version should be excluded"
    assert any("min_version" in str(warning.message) for warning in w)


def test_detect_includes_skill_meeting_min_version(tmp_path):
    """detect() includes a skill whose version meets min_version."""
    content = (
        "---\nname: new-skill\ndescription: desc\nversion: 2.1.0\n"
        "min_version: 2.0.0\nroles: {engineer: true}\ntags: [python]\n"
        "---\n\nContent.\n"
    )
    (tmp_path / "new-skill.md").write_text(content)

    loader = SkillLoader(local_skills_dir=tmp_path).init()
    ctx = SkillContext(issue_body="python", explicit_skills=[], repo_languages=[])
    result = loader.detect(ctx)

    assert any(s.name == "new-skill" for s in result), "Skill meeting min_version should be included"
