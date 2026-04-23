"""Integration tests for the Framework Docs Awareness feature.

Tests verify the full pipeline:
  - FrameworkDocsLoader correctly detects frameworks and produces context strings
  - Orchestrator.from_config wires FrameworkDocsLoader correctly
  - EngineerAgent incorporates framework_context in prompts
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

# Ensure project root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from framework_docs import FrameworkDocsLoader
from agents.engineer import EngineerAgent

# Path to the project root (where config.yaml lives)
PROJECT_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_config() -> dict:
    """Load config.yaml from the project root."""
    config_path = PROJECT_ROOT / "config.yaml"
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# ---------------------------------------------------------------------------
# Test 1: Orchestrator wires FrameworkDocsLoader from config.yaml
# ---------------------------------------------------------------------------

def test_orchestrator_loads_framework_docs_loader():
    """Orchestrator.from_config sets a FrameworkDocsLoader with non-empty config."""
    # Import here to avoid side effects at module level
    from orchestrator import Orchestrator

    orig_dir = os.getcwd()
    try:
        os.chdir(PROJECT_ROOT)
        orchestrator = Orchestrator.from_config("config.yaml")
    finally:
        os.chdir(orig_dir)

    assert isinstance(orchestrator.framework_docs_loader, FrameworkDocsLoader), (
        "orchestrator.framework_docs_loader must be a FrameworkDocsLoader instance"
    )
    assert orchestrator.framework_docs_loader._cfg, (
        "FrameworkDocsLoader._cfg must be non-empty (config was loaded)"
    )


# ---------------------------------------------------------------------------
# Test 2: EngineerAgent prompt includes ## Framework Documentation section
# ---------------------------------------------------------------------------

def test_engineer_prompt_includes_framework_section():
    """When framework_context is provided, run_module injects '## Framework Documentation'."""
    # Build a minimal loader with a nextjs config
    minimal_config = {
        "framework_docs": {
            "check_agents_md": False,
            "frameworks": [
                {
                    "name": "nextjs",
                    "detect": ["package.json"],
                    "summary": "Next.js test summary",
                }
            ],
        }
    }
    loader = FrameworkDocsLoader(config=minimal_config)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        # Create package.json so the framework is detected
        (tmp_path / "package.json").write_text('{"name": "test-app"}', encoding="utf-8")

        context = loader.load(tmp_path)

    # Verify the loader returned the framework summary
    assert "Next.js test summary" in context, (
        f"Expected 'Next.js test summary' in loader output, got: {context!r}"
    )

    # Now verify EngineerAgent builds a prompt that includes the framework section
    agent = EngineerAgent(model="gpt-4o-mini")
    captured_prompt: list[str] = []

    def _fake_call(prompt: str, **kwargs) -> str:
        captured_prompt.append(prompt)
        return "### FILE: dummy.py\n```python\npass\n```\n"

    with patch.object(agent, "call", side_effect=_fake_call):
        agent.run_module(
            design="# Design\n## Implementation Modules\n- dummy",
            module={"name": "dummy", "description": "test module"},
            project_name="TestProject",
            framework_context=context,
        )

    assert captured_prompt, "call() was never invoked — check run_module logic"
    assert "## Framework Documentation" in captured_prompt[0], (
        "Expected '## Framework Documentation' in the engineer prompt when "
        f"framework_context is non-empty. Prompt was:\n{captured_prompt[0][:500]}"
    )


# ---------------------------------------------------------------------------
# Test 3: Scaffold hint returned when no framework files match
# ---------------------------------------------------------------------------

def test_framework_context_empty_when_no_match():
    """FrameworkDocsLoader returns the scaffold hint when config is present but nothing detected."""
    minimal_config = {
        "framework_docs": {
            "check_agents_md": False,
            "frameworks": [
                {
                    "name": "nextjs",
                    "detect": ["package.json"],
                    "summary": "Next.js test summary",
                }
            ],
        }
    }
    loader = FrameworkDocsLoader(config=minimal_config)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        # No package.json — framework should NOT be detected

        result = loader.load(tmp_path)

    # Result should be the scaffold hint, NOT empty and NOT the framework summary
    assert result, "Expected a non-empty scaffold hint, got empty string"
    assert "Next.js test summary" not in result, (
        "Framework summary should NOT appear when no detection file is present"
    )
    # The scaffold hint should contain the canonical hint text
    assert "No framework-specific docs found" in result, (
        f"Expected scaffold hint text in result, got: {result!r}"
    )


# ---------------------------------------------------------------------------
# Test 4: config.yaml has exactly 6 frameworks defined
# ---------------------------------------------------------------------------

def test_orchestrator_from_config_has_six_frameworks():
    """config.yaml framework_docs.frameworks list has exactly 6 entries."""
    cfg = _load_config()
    loader = FrameworkDocsLoader(config=cfg)

    frameworks = loader._cfg.get("frameworks", [])
    assert len(frameworks) == 6, (
        f"Expected 6 frameworks in config.yaml, found {len(frameworks)}: "
        f"{[fw.get('name') for fw in frameworks]}"
    )
