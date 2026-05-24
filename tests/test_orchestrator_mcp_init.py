"""Tests for MCP init failure → graceful fallback behaviour.

Task 2 of T4-A: Orchestrator must survive MCPToolRegistry raising
at construction time (e.g., unreachable server).
"""
from pathlib import Path
from unittest.mock import patch
import pytest


def _make_minimal_orchestrator(**kwargs):
    """Import and construct Orchestrator with minimal config."""
    from orchestrator import Orchestrator
    kwargs.setdefault("model", "gpt-4.1")
    return Orchestrator(**kwargs)


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


def test_init_core_attrs_sets_model_and_workspace():
    """_init_core_attrs must be callable directly and set scalar config attrs."""
    orch = _make_minimal_orchestrator(model="test-model-xyz")
    assert orch.model == "test-model-xyz"
    assert orch.workspace_dir == Path("./workspace")
    assert orch._checkpoint_lock is not None
    assert isinstance(orch.model_overrides, dict)


def test_make_agent_kwargs_returns_llm_key():
    """Promoted _mk closure must return dict with 'llm' key."""
    orch = _make_minimal_orchestrator(model="gpt-4.1")
    result = orch._make_agent_kwargs("product_manager")
    assert "llm" in result
    assert result["llm"] is not None


def test_resolve_agent_model_string_override():
    orch = _make_minimal_orchestrator(model="gpt-4.1")
    orch.model_overrides["pr_analyst"] = "gpt-4-turbo"
    assert orch._resolve_agent_model("pr_analyst") == "gpt-4-turbo"


def test_resolve_agent_model_dict_override():
    orch = _make_minimal_orchestrator(model="gpt-4.1")
    orch.model_overrides["pr_analyst"] = {"model": "gpt-4-turbo", "ollama_think": True}
    assert orch._resolve_agent_model("pr_analyst") == "gpt-4-turbo"


def test_resolve_agent_model_fallback():
    orch = _make_minimal_orchestrator(model="gpt-4.1")
    assert orch._resolve_agent_model("unknown_agent") == "gpt-4.1"


def test_build_product_stages_returns_stage_dict():
    """_build_product_stages returns all 5 product stages with callable fns."""
    from orchestrator import PipelineStage
    orch = _make_minimal_orchestrator()
    stages = orch._build_product_stages()
    assert set(stages) == {"pm", "pm_reviewer", "pr_analyst", "pr_creative", "pr_proposal"}
    for v in stages.values():
        assert isinstance(v, PipelineStage)
        assert callable(v.fn)
