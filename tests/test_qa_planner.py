"""Tests for QAPlannerAgent."""
from __future__ import annotations

import pytest

from agents.qa_planner import QAPlannerAgent
from tools import LocalToolRegistry, builtin_tools


class TestQAPlannerToolRegistry:
    """Test tool_registry injection in QAPlannerAgent."""

    def test_qa_planner_uses_default_builtin_tools(self):
        """When tool_registry=None (default), self._tool_registry is builtin_tools."""
        agent = QAPlannerAgent(model="gpt-4.1")
        assert agent._tool_registry is builtin_tools

    def test_qa_planner_accepts_custom_tool_registry(self):
        """When a custom tool_registry is passed, self._tool_registry is that registry."""
        custom = LocalToolRegistry()
        agent = QAPlannerAgent(model="gpt-4.1", tool_registry=custom)
        assert agent._tool_registry is custom
        assert agent._tool_registry is not builtin_tools

    def test_qa_planner_explicit_none_uses_builtin(self):
        """When tool_registry=None explicitly, self._tool_registry is builtin_tools."""
        agent = QAPlannerAgent(model="gpt-4.1", tool_registry=None)
        assert agent._tool_registry is builtin_tools
