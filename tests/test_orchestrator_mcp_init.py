"""Tests for MCP init failure → graceful fallback behaviour.

Task 2 of T4-A: Orchestrator must survive MCPToolRegistry raising
at construction time (e.g., unreachable server).
"""
from unittest.mock import patch
import pytest


def _make_minimal_orchestrator(**kwargs):
    """Import and construct Orchestrator with minimal config."""
    from orchestrator import Orchestrator
    return Orchestrator(model="gpt-4.1", **kwargs)


def test_mcp_init_failure_does_not_crash():
    """If MCPToolRegistry raises during init, Orchestrator must still construct."""
    from tools import MCPToolRegistry
    with patch.object(MCPToolRegistry, "__init__", side_effect=RuntimeError("MCP unreachable")):
        orch = _make_minimal_orchestrator(
            mcp_servers=[{"name": "my-mcp", "command": "npx", "args": ["-y", "server"]}]
        )
    assert orch is not None


def test_mcp_init_failure_leaves_builtin_tools():
    """After MCP init failure, tool registry falls back to builtin tools only."""
    from tools import MCPToolRegistry, builtin_tools, CombinedToolRegistry
    with patch.object(MCPToolRegistry, "__init__", side_effect=RuntimeError("timeout")):
        orch = _make_minimal_orchestrator(
            mcp_servers=[{"name": "mcp", "command": "npx", "args": []}]
        )
    # _tool_registry must be the builtin_tools singleton (not a CombinedToolRegistry)
    assert orch._tool_registry is builtin_tools
    assert not isinstance(orch._tool_registry, CombinedToolRegistry)
    assert orch._rag_registry is None


def test_rag_mcp_init_failure_does_not_crash():
    """RAG MCP init failure should also be caught gracefully."""
    from tools import MCPToolRegistry
    with patch.object(MCPToolRegistry, "__init__", side_effect=ConnectionError("rag down")):
        orch = _make_minimal_orchestrator(
            mcp_servers=[{"name": "rag", "command": "npx", "args": []}]
        )
    assert orch._rag_registry is None
