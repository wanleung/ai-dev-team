"""Tests for RAG tool_registry wiring in agents and orchestrator."""
import sys
import os
from unittest.mock import MagicMock, patch
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.engineer import EngineerAgent
from agents.architect import ArchitectAgent
from agents.qa_engineer import QAEngineerAgent


def make_mock_registry():
    reg = MagicMock()
    reg.list_tools.return_value = []
    return reg


def test_engineer_uses_call_with_tools_when_registry_provided():
    """EngineerAgent uses call_with_tools when tool_registry is set."""
    agent = EngineerAgent(model="gpt-4o-mini", tool_registry=make_mock_registry())
    assert agent._tool_registry is not None

    with patch.object(agent, "call_with_tools", return_value="### FILE: foo.py\n```\npass\n```") as mock_cwt, \
         patch.object(agent, "call"):
        agent.run_module("design", {"name": "foo", "description": "bar"})
        assert mock_cwt.called


def test_engineer_uses_call_when_no_registry():
    """EngineerAgent uses call() when tool_registry is None."""
    agent = EngineerAgent(model="gpt-4o-mini")
    assert agent._tool_registry is None

    with patch.object(agent, "call", return_value="### FILE: foo.py\n```\npass\n```") as mock_call, \
         patch.object(agent, "call_with_tools"):
        agent.run_module("design", {"name": "foo", "description": "bar"})
        assert mock_call.called


def test_architect_uses_call_with_tools_when_registry_provided():
    """ArchitectAgent uses call_with_tools when tool_registry is set."""
    agent = ArchitectAgent(model="gpt-4o-mini", tool_registry=make_mock_registry())
    with patch.object(agent, "call_with_tools", return_value="# Design\n## Implementation Modules\n- foo") as mock_cwt, \
         patch.object(agent, "call"):
        agent.run("prd text")
        assert mock_cwt.called


def test_architect_uses_call_when_no_registry():
    """ArchitectAgent uses call() when tool_registry is None."""
    agent = ArchitectAgent(model="gpt-4o-mini")
    with patch.object(agent, "call", return_value="# Design\n## Implementation Modules\n- foo") as mock_call, \
         patch.object(agent, "call_with_tools"):
        agent.run("prd text")
        assert mock_call.called


def test_qa_engineer_uses_call_with_tools_when_registry_provided():
    """QAEngineerAgent uses call_with_tools when tool_registry is set."""
    agent = QAEngineerAgent(model="gpt-4o-mini", tool_registry=make_mock_registry())
    with patch.object(agent, "call_with_tools", return_value="## Test Plan\n```python\npass\n```") as mock_cwt, \
         patch.object(agent, "call"):
        agent.run(files={"foo.py": "x=1"}, prd="prd", project_name="proj")
        assert mock_cwt.called


def test_qa_engineer_uses_call_when_no_registry():
    """QAEngineerAgent uses call() when tool_registry is None."""
    agent = QAEngineerAgent(model="gpt-4o-mini")
    with patch.object(agent, "call", return_value="## Test Plan\n```python\npass\n```") as mock_call, \
         patch.object(agent, "call_with_tools"):
        agent.run(files={"foo.py": "x=1"}, prd="prd", project_name="proj")
        assert mock_call.called
