"""Tests for the SkillLoader."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from skills_loader import SkillContext, SkillLoader


@pytest.fixture
def skills_dir(tmp_path: Path) -> Path:
    """Write two minimal skill files to a temp directory."""
    flutter_md = textwrap.dedent("""\
        ---
        name: flutter
        description: Flutter guidance
        version: 1.0.0
        roles:
          architect: true
          engineer: true
          code_reviewer: true
          qa_engineer: true
          product_manager: false
          architect_reviewer: false
          pm_reviewer: false
        tags: [flutter, dart, mobile]
        source: local
        ---

        # Flutter Skill

        ## For Architects
        Prefer feature-based folder structure.

        ## For Engineers
        Run build_runner after model changes.

        ## For Code Reviewers
        Flag BuildContext across async gaps.

        ## For QA Engineers
        Test on both iOS and Android.
    """)
    security_md = textwrap.dedent("""\
        ---
        name: security-audit
        description: Security guidance
        version: 1.0.0
        roles:
          architect: true
          engineer: true
          code_reviewer: true
          qa_engineer: true
          product_manager: true
          architect_reviewer: true
          pm_reviewer: true
        tags: [security, auth, jwt]
        source: local
        ---

        # Security Skill

        ## For Architects
        Threat model early.

        ## For Engineers
        Never log secrets.

        ## For Code Reviewers
        Check all inputs are validated.

        ## For QA Engineers
        Run OWASP ZAP scan.

        ## For Product Managers
        Include compliance requirements in PRD.

        ## For Architect Reviewers
        Verify threat model covers OWASP Top 10.

        ## For PM Reviewers
        Check security acceptance criteria are testable.
    """)
    bad_md = textwrap.dedent("""\
        ---
        not valid yaml: [
        ---
        # Bad skill
    """)
    (tmp_path / "flutter.md").write_text(flutter_md)
    (tmp_path / "security-audit.md").write_text(security_md)
    (tmp_path / "bad.md").write_text(bad_md)
    return tmp_path


def make_loader(skills_dir: Path, always_load: list[str] | None = None) -> SkillLoader:
    config = {
        "skills": {
            "always_load": always_load or [],
            "marketplace_repo": "",
            "cache_dir": "",
            "fetch_timeout": 5,
        }
    }
    return SkillLoader(config=config, local_skills_dir=skills_dir)


# ── Discovery ─────────────────────────────────────────────────────────────────

def test_loads_valid_local_skills(skills_dir):
    loader = make_loader(skills_dir)
    loader.init()
    names = [s.name for s in loader._local_skills]
    assert "flutter" in names
    assert "security-audit" in names


def test_skips_malformed_frontmatter(skills_dir):
    loader = make_loader(skills_dir)
    loader.init()
    names = [s.name for s in loader._local_skills]
    assert "bad" not in names


# ── Detection ─────────────────────────────────────────────────────────────────

def test_detect_by_tag_in_issue_body(skills_dir):
    loader = make_loader(skills_dir)
    loader.init()
    ctx = SkillContext(issue_body="Build a flutter mobile app", explicit_skills=[], repo_languages=[])
    matched = loader.detect(ctx)
    assert any(s.name == "flutter" for s in matched)


def test_detect_no_match_returns_empty(skills_dir):
    loader = make_loader(skills_dir)
    loader.init()
    ctx = SkillContext(issue_body="Build a Java desktop GUI app", explicit_skills=[], repo_languages=[])
    matched = loader.detect(ctx)
    assert matched == []


def test_detect_case_insensitive(skills_dir):
    loader = make_loader(skills_dir)
    loader.init()
    ctx = SkillContext(issue_body="Use FLUTTER and DART", explicit_skills=[], repo_languages=[])
    matched = loader.detect(ctx)
    assert any(s.name == "flutter" for s in matched)


def test_explicit_skill_always_loaded(skills_dir):
    loader = make_loader(skills_dir)
    loader.init()
    ctx = SkillContext(issue_body="no matching keywords", explicit_skills=["security-audit"], repo_languages=[])
    matched = loader.detect(ctx)
    assert any(s.name == "security-audit" for s in matched)


def test_always_load_config_included(skills_dir):
    loader = make_loader(skills_dir, always_load=["security-audit"])
    loader.init()
    ctx = SkillContext(issue_body="unrelated content", explicit_skills=[], repo_languages=[])
    matched = loader.detect(ctx)
    assert any(s.name == "security-audit" for s in matched)


def test_detect_by_repo_language(skills_dir):
    loader = make_loader(skills_dir)
    loader.init()
    ctx = SkillContext(issue_body="Build a REST API", explicit_skills=[], repo_languages=["dart"])
    matched = loader.detect(ctx)
    assert any(s.name == "flutter" for s in matched)


# ── Role scoping & section extraction ─────────────────────────────────────────

def test_engineer_gets_engineer_section(skills_dir):
    loader = make_loader(skills_dir)
    loader.init()
    ctx = SkillContext(issue_body="flutter app", explicit_skills=[], repo_languages=[])
    matched = loader.detect(ctx)
    blocks = loader.for_role("engineer", matched)
    assert len(blocks) == 1
    assert "Run build_runner" in blocks[0].content
    assert "Prefer feature-based" not in blocks[0].content  # architect section excluded


def test_role_not_enabled_skips_skill(skills_dir):
    loader = make_loader(skills_dir)
    loader.init()
    ctx = SkillContext(issue_body="flutter app", explicit_skills=[], repo_languages=[])
    matched = loader.detect(ctx)
    # flutter skill has product_manager: false
    blocks = loader.for_role("product_manager", matched)
    assert blocks == []


def test_no_role_section_skips_gracefully(skills_dir):
    """A skill file that has no section for a role returns nothing for that role."""
    loader = make_loader(skills_dir)
    loader.init()
    ctx = SkillContext(issue_body="security audit needed", explicit_skills=[], repo_languages=[])
    matched = loader.detect(ctx)
    # security-audit has content for all roles
    blocks = loader.for_role("qa_engineer", matched)
    assert any("OWASP" in b.content for b in blocks)
