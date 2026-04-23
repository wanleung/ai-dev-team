"""Tests for FrameworkDocsLoader."""
import json
from pathlib import Path
import pytest
from framework_docs import FrameworkDocsLoader


@pytest.fixture
def tmp_project(tmp_path):
    return tmp_path


def _loader(config_override=None):
    cfg = {
        "framework_docs": {
            "check_agents_md": True,
            "frameworks": {
                "nextjs": {
                    "detect_file": "package.json",
                    "detect_key": '"next"',
                    "bundled_docs": "node_modules/next/dist/docs/",
                },
                "flutter": {
                    "detect_file": "pubspec.yaml",
                    "detect_key": "flutter:",
                    "rag_hint": "Use search_docs for Flutter API docs.",
                },
            },
        }
    }
    if config_override:
        cfg.update(config_override)
    return FrameworkDocsLoader(config=cfg)


def test_agents_md_injected(tmp_project):
    (tmp_project / "AGENTS.md").write_text("# AGENTS\nRead bundled docs first.")
    loader = _loader()
    ctx = loader.load(tmp_project)
    assert "Read bundled docs first." in ctx
    assert "AGENTS.md" in ctx


def test_claude_md_fallback(tmp_project):
    (tmp_project / "CLAUDE.md").write_text("# CLAUDE\nCustom instructions.")
    loader = _loader()
    ctx = loader.load(tmp_project)
    assert "Custom instructions." in ctx


def test_agents_md_takes_priority_over_claude_md(tmp_project):
    (tmp_project / "AGENTS.md").write_text("agents content")
    (tmp_project / "CLAUDE.md").write_text("claude content")
    loader = _loader()
    ctx = loader.load(tmp_project)
    assert "agents content" in ctx
    assert "claude content" not in ctx


def test_empty_project_returns_empty(tmp_project):
    loader = _loader()
    ctx = loader.load(tmp_project)
    assert ctx == ""


def test_nextjs_framework_detected_no_bundled_docs(tmp_project):
    pkg = {"dependencies": {"next": "^14.0.0", "react": "^18.0.0"}}
    (tmp_project / "package.json").write_text(json.dumps(pkg))
    loader = _loader()
    ctx = loader.load(tmp_project)
    # No bundled docs dir exists, but should still note detection
    assert "next" in ctx.lower()


def test_nextjs_bundled_docs_indexed(tmp_project):
    pkg = {"dependencies": {"next": "^14.0.0"}}
    (tmp_project / "package.json").write_text(json.dumps(pkg))
    docs_dir = tmp_project / "node_modules" / "next" / "dist" / "docs"
    docs_dir.mkdir(parents=True)
    (docs_dir / "routing.md").write_text("# Routing\nUse app/ directory.")
    (docs_dir / "data-fetching.md").write_text("# Data Fetching\nUse fetch() in server components.")
    loader = _loader()
    ctx = loader.load(tmp_project)
    assert "Routing" in ctx or "Data Fetching" in ctx


def test_flutter_rag_hint_injected(tmp_project):
    (tmp_project / "pubspec.yaml").write_text("name: myapp\nflutter:\n  uses-material-design: true\n")
    loader = _loader()
    ctx = loader.load(tmp_project)
    assert "Use search_docs for Flutter API docs." in ctx


def test_check_agents_md_disabled(tmp_project):
    (tmp_project / "AGENTS.md").write_text("should be ignored")
    loader = FrameworkDocsLoader(config={"framework_docs": {"check_agents_md": False}})
    ctx = loader.load(tmp_project)
    assert ctx == ""


def test_framework_docs_disabled_entirely(tmp_project):
    (tmp_project / "AGENTS.md").write_text("should be ignored")
    loader = FrameworkDocsLoader(config={})
    ctx = loader.load(tmp_project)
    assert ctx == ""
