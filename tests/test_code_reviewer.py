"""Tests for CodeReviewerAgent."""
from __future__ import annotations

import pytest

from agents.code_reviewer import CodeReviewerAgent
from tools import LocalToolRegistry, builtin_tools


class TestCodeReviewerToolRegistry:
    """Test tool_registry injection in CodeReviewerAgent."""

    def test_code_reviewer_uses_default_builtin_tools(self):
        """When tool_registry=None (default), self._tool_registry is builtin_tools."""
        agent = CodeReviewerAgent(model="gpt-4.1")
        assert agent._tool_registry is builtin_tools

    def test_code_reviewer_accepts_custom_tool_registry(self):
        """When a custom tool_registry is passed, self._tool_registry is that registry."""
        custom = LocalToolRegistry()
        agent = CodeReviewerAgent(model="gpt-4.1", tool_registry=custom)
        assert agent._tool_registry is custom
        assert agent._tool_registry is not builtin_tools

    def test_code_reviewer_explicit_none_uses_builtin(self):
        """When tool_registry=None explicitly, self._tool_registry is builtin_tools."""
        agent = CodeReviewerAgent(model="gpt-4.1", tool_registry=None)
        assert agent._tool_registry is builtin_tools
