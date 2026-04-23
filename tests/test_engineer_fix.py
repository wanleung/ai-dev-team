"""Tests for EngineerAgent.fix_failures()."""
from unittest.mock import MagicMock, patch
import pytest
from agents.engineer import EngineerAgent


def _make_agent():
    agent = EngineerAgent.__new__(EngineerAgent)
    agent._tool_registry = None
    return agent


def test_fix_failures_returns_parsed_files():
    agent = _make_agent()
    agent.call = MagicMock(return_value=(
        "### FILE: app/models/user.py\n"
        "class User:\n    pass\n"
    ))
    patches = agent.fix_failures(
        failure_output="FAILED tests/test_user.py::test_create",
        all_files={"app/models/user.py": "# broken", "app/main.py": "# ok"},
        design="System design here.",
        project_name="MyApp",
    )
    assert "app/models/user.py" in patches
    assert "class User" in patches["app/models/user.py"]


def test_fix_failures_returns_empty_on_no_file_blocks():
    agent = _make_agent()
    agent.call = MagicMock(return_value="I could not identify the issue.")
    patches = agent.fix_failures(
        failure_output="FAILED tests/test_user.py",
        all_files={"app/main.py": "# code"},
        design="design",
    )
    assert patches == {}


def test_fix_failures_prompt_includes_failure_output():
    agent = _make_agent()
    captured_prompt = []
    agent.call = MagicMock(side_effect=lambda p: captured_prompt.append(p) or "")
    agent.fix_failures(
        failure_output="AssertionError: expected 1 got 2",
        all_files={"app/main.py": "x = 1"},
        design="design",
    )
    assert "AssertionError: expected 1 got 2" in captured_prompt[0]


def test_fix_failures_prompt_includes_all_files():
    agent = _make_agent()
    captured_prompt = []
    agent.call = MagicMock(side_effect=lambda p: captured_prompt.append(p) or "")
    agent.fix_failures(
        failure_output="err",
        all_files={"app/foo.py": "def foo(): pass", "app/bar.py": "x = 1"},
        design="design",
    )
    assert "app/foo.py" in captured_prompt[0]
    assert "app/bar.py" in captured_prompt[0]
    assert "def foo(): pass" in captured_prompt[0]


def test_fix_failures_prepends_framework_context():
    agent = _make_agent()
    captured_prompt = []
    agent.call = MagicMock(side_effect=lambda p: captured_prompt.append(p) or "")
    agent.fix_failures(
        failure_output="err",
        all_files={},
        design="design",
        framework_context="## Next.js Docs\n\nUse App Router.",
    )
    prompt = captured_prompt[0]
    assert prompt.startswith("## Framework Documentation")
    assert "Next.js Docs" in prompt
