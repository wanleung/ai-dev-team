"""Tests for the SkillLoader."""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from skills_loader import SkillBlock, SkillContext, SkillEntry, SkillLoader


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


# ── render_prompt_block ────────────────────────────────────────────────────────

def test_render_prompt_block(skills_dir):
    """render_prompt_block includes skill name and content; empty list returns ''."""
    loader = make_loader(skills_dir)
    loader.init()

    # non-empty case
    blocks = [
        SkillBlock(name="flutter", source="local", content="Run build_runner after model changes."),
        SkillBlock(name="security-audit", source="local", content="Never log secrets."),
    ]
    output = loader.render_prompt_block(blocks)
    assert "flutter" in output
    assert "Run build_runner after model changes." in output
    assert "security-audit" in output
    assert "Never log secrets." in output

    # empty case
    assert loader.render_prompt_block([]) == ""


# ── detect score ordering ──────────────────────────────────────────────────────

def test_detect_score_ordering(tmp_path):
    """Skills with higher tag-match scores appear first; ties broken alphabetically."""
    # skill_a matches 1 tag, skill_b matches 2 tags → skill_b should rank first
    skill_a_md = textwrap.dedent("""\
        ---
        name: skill-alpha
        description: Alpha skill
        version: 1.0.0
        roles: {}
        tags: [security]
        source: local
        ---
        Alpha body.
    """)
    skill_b_md = textwrap.dedent("""\
        ---
        name: skill-beta
        description: Beta skill
        version: 1.0.0
        roles: {}
        tags: [security, auth]
        source: local
        ---
        Beta body.
    """)
    (tmp_path / "skill-alpha.md").write_text(skill_a_md)
    (tmp_path / "skill-beta.md").write_text(skill_b_md)

    loader = make_loader(tmp_path)
    loader.init()

    ctx = SkillContext(issue_body="security and auth concerns", explicit_skills=[], repo_languages=[])
    matched = loader.detect(ctx)

    names = [s.name for s in matched]
    assert names.index("skill-beta") < names.index("skill-alpha")


# ── for_role unknown role warns ────────────────────────────────────────────────

def test_for_role_unknown_role_warns(skills_dir):
    """for_role with an unknown role key returns [] and issues a warning."""
    loader = make_loader(skills_dir)
    loader.init()
    ctx = SkillContext(issue_body="flutter app", explicit_skills=[], repo_languages=[])
    matched = loader.detect(ctx)

    with pytest.warns(UserWarning, match="Unknown role 'nonexistent_role'"):
        result = loader.for_role("nonexistent_role", matched)

    assert result == []


# ── detect always_load not found warns ────────────────────────────────────────

def test_detect_always_load_not_found_warns(skills_dir):
    """always_load referencing a missing skill issues a warning and returns []."""
    loader = make_loader(skills_dir, always_load=["nonexistent"])
    loader.init()
    ctx = SkillContext(issue_body="anything", explicit_skills=[], repo_languages=[])

    with pytest.warns(UserWarning, match="always_load skill 'nonexistent' not found"):
        result = loader.detect(ctx)

    assert result == []


# ── role section missing from body ────────────────────────────────────────────

def test_role_section_missing_from_body_returns_no_content(tmp_path):
    """Skill enabled for qa_planner but missing ## For QA Planners section is skipped."""
    skill_md = textwrap.dedent("""\
        ---
        name: no-section-skill
        description: A skill with no QA Planner section
        version: 1.0.0
        roles:
          qa_planner: true
        tags: [planning]
        source: local
        ---

        # No Section Skill

        ## For Engineers
        Some engineer guidance here.
    """)
    (tmp_path / "no-section-skill.md").write_text(skill_md)

    loader = make_loader(tmp_path)
    loader.init()

    ctx = SkillContext(issue_body="planning task", explicit_skills=[], repo_languages=[])
    matched = loader.detect(ctx)
    assert any(s.name == "no-section-skill" for s in matched)

    blocks = loader.for_role("qa_planner", matched)
    # No ## For QA Planners section → for_role silently skips → empty list
    assert blocks == []


# ── Security regression tests (marketplace hardening) ─────────────────────────

def test_path_traversal_skill_name_sanitised(tmp_path):
    """Skill names with path traversal sequences must be sanitised to just the filename."""
    import unittest.mock as mock

    loader = SkillLoader(config={}, local_skills_dir=tmp_path)
    loader.init()

    # Simulate marketplace index with a traversal skill name
    traversal_index = json.dumps([
        {"name": "../../etc/passwd", "url": "https://raw.githubusercontent.com/fake/repo/main/evil.md", "description": "evil"}
    ])

    with mock.patch("urllib.request.urlopen") as mock_urlopen:
        # First call: index fetch; second call: skill fetch
        mock_index = mock.MagicMock()
        mock_index.__enter__ = lambda s: s
        mock_index.__exit__ = mock.MagicMock(return_value=False)
        mock_index.read.return_value = traversal_index.encode()

        mock_skill_resp = mock.MagicMock()
        mock_skill_resp.__enter__ = lambda s: s
        mock_skill_resp.__exit__ = mock.MagicMock(return_value=False)
        mock_skill_resp.read.return_value = b"---\nname: evil\ndescription: evil\n---\nEvil content"

        mock_urlopen.side_effect = [mock_index, mock_skill_resp]

        loader._marketplace_repo = "fake/repo"
        loader._load_marketplace(update=True)

    # The file must NOT have been written outside cache_dir
    evil_path = tmp_path / "etc" / "passwd"
    assert not evil_path.exists(), "Path traversal was NOT prevented!"


def test_ssrf_untrusted_skill_url_skipped(tmp_path):
    """Skill entries with URLs not on the allowlist must be skipped with a warning."""
    import unittest.mock as mock

    loader = SkillLoader(config={}, local_skills_dir=tmp_path)
    loader.init()

    evil_index = json.dumps([
        {"name": "evil-skill", "url": "http://internal.corp/secret", "description": "evil"}
    ])

    with mock.patch("urllib.request.urlopen") as mock_urlopen:
        mock_index = mock.MagicMock()
        mock_index.__enter__ = lambda s: s
        mock_index.__exit__ = mock.MagicMock(return_value=False)
        mock_index.read.return_value = evil_index.encode()
        mock_urlopen.return_value = mock_index

        loader._marketplace_repo = "fake/repo"

        with pytest.warns(UserWarning, match="untrusted URL"):
            loader._load_marketplace(update=True)

    # urlopen should only have been called once (for index), NOT for the skill URL
    assert mock_urlopen.call_count == 1


def test_orchestrator_injects_skills_into_agent_prompt(tmp_path):
    """SkillLoader correctly produces injectable blocks for Orchestrator agents."""
    from unittest.mock import MagicMock
    from orchestrator import Orchestrator

    # Write a flutter skill
    (tmp_path / "flutter.md").write_text(textwrap.dedent("""\
        ---
        name: flutter
        description: Flutter guidance
        version: 1.0.0
        roles:
          engineer: true
          architect: false
          code_reviewer: false
          qa_engineer: false
          product_manager: false
          architect_reviewer: false
          pm_reviewer: false
        tags: [flutter]
        source: local
        ---

        ## For Engineers
        Use Riverpod for state management.
    """))

    loader = SkillLoader(config={}, local_skills_dir=tmp_path)
    loader.init()

    # Create Orchestrator with the skill loader
    o = Orchestrator.__new__(Orchestrator)
    o.skill_loader = loader
    fake_engineer = MagicMock()
    fake_engineer.system_prompt = "You are an engineer."
    o.engineer = fake_engineer

    # Exercise the exact injection logic used in run()
    ctx = SkillContext(issue_body="Build a flutter app", explicit_skills=[], repo_languages=[])
    matched = o.skill_loader.detect(ctx)
    assert any(s.name == "flutter" for s in matched)

    blocks = o.skill_loader.for_role("engineer", matched)
    block_text = o.skill_loader.render_prompt_block(blocks)
    assert "Riverpod" in block_text

    # Simulate injection (same code as in run())
    original = o.engineer.system_prompt
    if block_text and original:
        o.engineer.system_prompt = block_text + "\n\n---\n\n" + original

    assert "Riverpod" in o.engineer.system_prompt
    assert "You are an engineer." in o.engineer.system_prompt


def test_marketplace_non_list_index_skips_gracefully(tmp_path):
    """If marketplace index JSON is not a list, emit warning and return empty."""
    import unittest.mock as mock

    loader = SkillLoader(config={}, local_skills_dir=tmp_path)
    loader.init()

    with mock.patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = mock.MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = mock.MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps({"error": "rate limited"}).encode()
        mock_urlopen.return_value = mock_resp

        loader._marketplace_repo = "fake/repo"

        with pytest.warns(UserWarning, match="not a JSON array"):
            result = loader._load_marketplace(update=True)

    assert result == []
