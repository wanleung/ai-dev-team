"""Tests for MCPToolRegistry and CombinedToolRegistry."""
from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock

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


# ── MCPToolRegistry tests ─────────────────────────────────────────────────────

from tools.mcp_registry import MCPToolRegistry, _expand_env


# ── _expand_env ───────────────────────────────────────────────────────────────

def test_expand_env_substitutes_known_var(monkeypatch):
    monkeypatch.setenv("MY_TOKEN", "secret123")
    assert _expand_env("Bearer ${MY_TOKEN}") == "Bearer secret123"


def test_expand_env_leaves_unknown_var(monkeypatch):
    monkeypatch.delenv("MISSING_VAR", raising=False)
    assert _expand_env("${MISSING_VAR}") == "${MISSING_VAR}"


def test_expand_env_no_vars():
    assert _expand_env("plain string") == "plain string"


# ── MCPToolRegistry: mcp not installed ────────────────────────────────────────

def test_mcp_registry_import_error_when_mcp_missing(monkeypatch):
    import sys
    # Simulate mcp not being installed
    monkeypatch.setitem(sys.modules, "mcp", None)
    monkeypatch.setitem(sys.modules, "mcp.client.stdio", None)
    monkeypatch.setitem(sys.modules, "mcp.client.sse", None)

    import importlib
    import tools.mcp_registry as mod
    importlib.reload(mod)

    with pytest.raises(ImportError, match="pip install mcp"):
        mod.MCPToolRegistry([{"name": "s", "type": "stdio", "command": "npx", "args": []}])

    # restore
    for key in ["mcp", "mcp.client.stdio", "mcp.client.sse"]:
        sys.modules.pop(key, None)
    importlib.reload(mod)


# ── MCPToolRegistry: stdio server ─────────────────────────────────────────────

def _fake_tool(name: str, description: str = "desc") -> MagicMock:
    t = MagicMock()
    t.name = name
    t.description = description
    t.inputSchema = {"type": "object", "properties": {}, "required": []}
    return t


def _build_stdio_registry(monkeypatch, tools_list: list, call_return: str = "ok") -> "MCPToolRegistry":
    """Build an MCPToolRegistry backed by a mocked stdio MCP server."""
    list_result = MagicMock()
    list_result.tools = tools_list

    call_result = MagicMock()
    call_result.isError = False
    call_result.content = [MagicMock(text=call_return)]

    session = AsyncMock()
    session.initialize = AsyncMock(return_value=None)
    session.list_tools = AsyncMock(return_value=list_result)
    session.call_tool = AsyncMock(return_value=call_result)

    # async context manager for session
    cm_session = MagicMock()
    cm_session.__aenter__ = AsyncMock(return_value=session)
    cm_session.__aexit__ = AsyncMock(return_value=None)

    # async context manager for transport (yields (read, write) tuple)
    read_mock = MagicMock()
    write_mock = MagicMock()
    cm_transport = MagicMock()
    cm_transport.__aenter__ = AsyncMock(return_value=(read_mock, write_mock))
    cm_transport.__aexit__ = AsyncMock(return_value=None)

    import tools.mcp_registry as mod
    monkeypatch.setattr(mod, "_MCP_AVAILABLE", True)
    monkeypatch.setattr(mod, "_StdioServerParameters", MagicMock)
    monkeypatch.setattr(mod, "_stdio_client", lambda params: cm_transport)
    monkeypatch.setattr(mod, "_ClientSession", lambda r, w: cm_session)

    servers = [{"name": "srv", "type": "stdio", "command": "npx", "args": ["-y", "pkg"]}]
    return MCPToolRegistry(servers)


def test_mcp_registry_stdio_schemas(monkeypatch):
    reg = _build_stdio_registry(monkeypatch, [_fake_tool("my_tool")])
    names = [s["function"]["name"] for s in reg.schemas]
    assert "my_tool" in names


def test_mcp_registry_stdio_call(monkeypatch):
    reg = _build_stdio_registry(monkeypatch, [_fake_tool("my_tool")], call_return="hello")
    result = reg.call("my_tool", "{}")
    assert result == "hello"


def test_mcp_registry_unknown_tool_error(monkeypatch):
    reg = _build_stdio_registry(monkeypatch, [_fake_tool("my_tool")])
    result = reg.call("no_such_tool", "{}")
    assert "[ToolError]" in result


def test_mcp_registry_name_collision_prefixed(monkeypatch):
    """When two servers expose the same tool name, second is prefixed."""
    tool_a = _fake_tool("search")
    tool_b = _fake_tool("search")

    list_result_a = MagicMock(); list_result_a.tools = [tool_a]
    list_result_b = MagicMock(); list_result_b.tools = [tool_b]
    results = [list_result_a, list_result_b]

    session = AsyncMock()
    session.initialize = AsyncMock(return_value=None)
    session.list_tools = AsyncMock(side_effect=results)

    cm_session = MagicMock()
    cm_session.__aenter__ = AsyncMock(return_value=session)
    cm_session.__aexit__ = AsyncMock(return_value=None)

    read_mock = MagicMock()
    write_mock = MagicMock()
    cm_transport = MagicMock()
    cm_transport.__aenter__ = AsyncMock(return_value=(read_mock, write_mock))
    cm_transport.__aexit__ = AsyncMock(return_value=None)

    import tools.mcp_registry as mod
    monkeypatch.setattr(mod, "_MCP_AVAILABLE", True)
    monkeypatch.setattr(mod, "_StdioServerParameters", MagicMock)
    monkeypatch.setattr(mod, "_stdio_client", lambda params: cm_transport)
    monkeypatch.setattr(mod, "_ClientSession", lambda r, w: cm_session)

    servers = [
        {"name": "srv1", "type": "stdio", "command": "npx", "args": []},
        {"name": "srv2", "type": "stdio", "command": "npx", "args": []},
    ]
    reg = MCPToolRegistry(servers)
    names = [s["function"]["name"] for s in reg.schemas]
    assert "search" in names
    assert "srv2__search" in names


def test_mcp_registry_server_connect_failure_skipped(monkeypatch):
    """A server that fails to connect is skipped; no exception raised."""
    import warnings
    import tools.mcp_registry as mod

    class _FailCM:
        async def __aenter__(self): raise ConnectionError("refused")
        async def __aexit__(self, *a): pass

    monkeypatch.setattr(mod, "_MCP_AVAILABLE", True)
    monkeypatch.setattr(mod, "_StdioServerParameters", MagicMock)
    monkeypatch.setattr(mod, "_stdio_client", lambda params: _FailCM())

    servers = [{"name": "bad", "type": "stdio", "command": "bad", "args": []}]
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        reg = MCPToolRegistry(servers)
    assert reg.schemas == []
    assert any("bad" in str(warning.message) for warning in w)


def test_mcp_registry_call_returns_tool_error_on_server_error(monkeypatch):
    """When server returns isError=True, call() returns a [ToolError] string."""
    call_result = MagicMock()
    call_result.isError = True
    call_result.content = []

    list_result = MagicMock()
    list_result.tools = [_fake_tool("my_tool")]

    session = AsyncMock()
    session.initialize = AsyncMock(return_value=None)
    session.list_tools = AsyncMock(return_value=list_result)
    session.call_tool = AsyncMock(return_value=call_result)

    cm_session = MagicMock()
    cm_session.__aenter__ = AsyncMock(return_value=session)
    cm_session.__aexit__ = AsyncMock(return_value=None)

    read_mock = MagicMock()
    write_mock = MagicMock()
    cm_transport = MagicMock()
    cm_transport.__aenter__ = AsyncMock(return_value=(read_mock, write_mock))
    cm_transport.__aexit__ = AsyncMock(return_value=None)

    import tools.mcp_registry as mod
    monkeypatch.setattr(mod, "_MCP_AVAILABLE", True)
    monkeypatch.setattr(mod, "_StdioServerParameters", MagicMock)
    monkeypatch.setattr(mod, "_stdio_client", lambda params: cm_transport)
    monkeypatch.setattr(mod, "_ClientSession", lambda r, w: cm_session)

    servers = [{"name": "srv", "type": "stdio", "command": "npx", "args": []}]
    reg = MCPToolRegistry(servers)
    result = reg.call("my_tool", "{}")
    assert "[ToolError]" in result


def test_mcp_registry_sse_schemas(monkeypatch):
    """SSE transport: schemas are fetched via _sse_client."""
    list_result = MagicMock()
    list_result.tools = [_fake_tool("sse_tool")]

    session = AsyncMock()
    session.initialize = AsyncMock(return_value=None)
    session.list_tools = AsyncMock(return_value=list_result)

    cm_session = MagicMock()
    cm_session.__aenter__ = AsyncMock(return_value=session)
    cm_session.__aexit__ = AsyncMock(return_value=None)

    read_mock = MagicMock()
    write_mock = MagicMock()
    cm_transport = MagicMock()
    cm_transport.__aenter__ = AsyncMock(return_value=(read_mock, write_mock))
    cm_transport.__aexit__ = AsyncMock(return_value=None)

    import tools.mcp_registry as mod
    monkeypatch.setattr(mod, "_MCP_AVAILABLE", True)
    monkeypatch.setattr(mod, "_sse_client", lambda url, headers=None: cm_transport)
    monkeypatch.setattr(mod, "_ClientSession", lambda r, w: cm_session)

    servers = [{"name": "remote", "type": "sse", "url": "https://mcp.example.com/sse"}]
    reg = MCPToolRegistry(servers)
    names = [s["function"]["name"] for s in reg.schemas]
    assert "sse_tool" in names
