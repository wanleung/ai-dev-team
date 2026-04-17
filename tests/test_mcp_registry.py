"""Tests for MCPToolRegistry and CombinedToolRegistry."""
from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock

from tools.registry import LocalToolRegistry, CombinedToolRegistry


# ── CombinedToolRegistry tests ────────────────────────────────────────────────

def _make_registry(tool_name: str, return_value: str) -> LocalToolRegistry:
    reg = LocalToolRegistry()

    @reg.tool(
        name=tool_name,
        description=f"Test tool {tool_name}",
        parameters={"type": "object", "properties": {}, "required": []},
    )
    def _tool():
        return return_value

    return reg


def test_combined_registry_schemas_merged():
    a = _make_registry("tool_a", "a_result")
    b = _make_registry("tool_b", "b_result")
    combined = CombinedToolRegistry(a, b)
    names = [s["function"]["name"] for s in combined.schemas]
    assert "tool_a" in names
    assert "tool_b" in names


def test_combined_registry_routes_to_first():
    a = _make_registry("tool_a", "from_a")
    b = _make_registry("tool_b", "from_b")
    combined = CombinedToolRegistry(a, b)
    assert combined.call("tool_a", "{}") == "from_a"


def test_combined_registry_routes_to_second():
    a = _make_registry("tool_a", "from_a")
    b = _make_registry("tool_b", "from_b")
    combined = CombinedToolRegistry(a, b)
    assert combined.call("tool_b", "{}") == "from_b"


def test_combined_registry_unknown_tool():
    a = _make_registry("tool_a", "a")
    b = _make_registry("tool_b", "b")
    combined = CombinedToolRegistry(a, b)
    result = combined.call("no_such_tool", "{}")
    assert "[ToolError]" in result
