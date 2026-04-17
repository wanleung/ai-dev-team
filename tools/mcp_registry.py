"""MCPToolRegistry — wraps MCP servers as a ToolRegistry.

Connects to stdio or HTTP/SSE MCP servers, fetches their tool schemas,
and dispatches tool calls through the standard ToolRegistry interface.

Usage:
    servers = [
        {"name": "github", "type": "stdio", "command": "npx",
         "args": ["-y", "@modelcontextprotocol/server-github"],
         "env": {"GITHUB_TOKEN": "${GITHUB_TOKEN}"}},
        {"name": "search", "type": "sse",
         "url": "https://mcp.example.com/sse"},
    ]
    registry = MCPToolRegistry(servers)
    result = agent.call_with_tools("Search for X", tools=registry)
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import warnings
from typing import Any

from tools.registry import ToolRegistry

# Lazy imports — only resolved when MCPToolRegistry is instantiated.
# This lets the rest of the codebase import this module without requiring
# the mcp package to be installed.
try:
    from mcp import ClientSession as _ClientSession
    from mcp import StdioServerParameters as _StdioServerParameters
    from mcp.client.stdio import stdio_client as _stdio_client
    from mcp.client.sse import sse_client as _sse_client
    _MCP_AVAILABLE = True
except ImportError:
    _MCP_AVAILABLE = False
    _ClientSession = None  # type: ignore[assignment]
    _StdioServerParameters = None  # type: ignore[assignment]
    _stdio_client = None  # type: ignore[assignment]
    _sse_client = None  # type: ignore[assignment]

_ENV_RE = re.compile(r"\$\{([^}]+)\}")


def _expand_env(value: str) -> str:
    """Expand ``${VAR}`` references using ``os.environ``.

    Unknown variables are left as-is (not replaced with empty string).
    """
    def _replace(m: re.Match) -> str:
        return os.environ.get(m.group(1), m.group(0))
    return _ENV_RE.sub(_replace, value)


def _expand_env_dict(d: dict[str, str]) -> dict[str, str]:
    """Expand all values in a dict using environment variable substitution."""
    return {k: _expand_env(v) for k, v in d.items()}


class MCPToolRegistry(ToolRegistry):
    """ToolRegistry backed by one or more MCP servers (stdio or SSE).

    All connections are made synchronously at construction time via
    ``asyncio.run()``. Each tool call also reconnects synchronously —
    this avoids keeping long-lived async sessions across thread boundaries.

    Args:
        servers: List of server config dicts. Each must have at least
                 ``name`` and ``type`` (``"stdio"`` or ``"sse"``).
                 Stdio servers also need ``command`` and ``args``.
                 SSE servers need ``url``.
    """

    def __init__(self, servers: list[dict[str, Any]]) -> None:
        if not _MCP_AVAILABLE:
            raise ImportError(
                "The 'mcp' package is required to use MCP servers. "
                "Install it with: pip install mcp"
            )
        self._servers = servers
        self._schemas: list[dict] = []
        # Maps tool name → server config dict for routing calls.
        self._tool_to_server: dict[str, dict] = {}
        asyncio.run(self._connect_all())

    async def _connect_all(self) -> None:
        """Connect to all configured MCP servers and fetch their tool lists."""
        for server in self._servers:
            try:
                tools = await self._list_tools(server)
            except Exception as exc:
                warnings.warn(
                    f"[MCPToolRegistry] Could not connect to MCP server "
                    f"'{server.get('name', '?')}': {exc}. Skipping.",
                    stacklevel=2,
                )
                continue

            for tool in tools:
                raw_name = tool.name
                # Prefix on collision
                if raw_name in self._tool_to_server:
                    raw_name = f"{server['name']}__{tool.name}"

                self._tool_to_server[raw_name] = server
                self._schemas.append({
                    "type": "function",
                    "function": {
                        "name": raw_name,
                        "description": tool.description or "",
                        "parameters": tool.inputSchema or {
                            "type": "object", "properties": {}
                        },
                    },
                })

    async def _list_tools(self, server: dict) -> list:
        """Open a transport connection, initialize the session, and list tools."""
        async with self._open_transport(server) as (read, write):
            async with _ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return result.tools

    async def _call_tool(self, server: dict, name: str, arguments: dict) -> str:
        """Open a transport connection and call a named tool with given arguments."""
        # Strip prefix if the tool was registered with one.
        bare_name = name.split("__", 1)[-1]
        async with self._open_transport(server) as (read, write):
            async with _ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(bare_name, arguments)
                if result.isError:
                    return f"[ToolError] MCP server returned an error for '{name}'"
                parts = []
                for block in result.content:
                    if hasattr(block, "text"):
                        parts.append(block.text)
                    else:
                        parts.append(str(block))
                return "\n".join(parts)

    def _open_transport(self, server: dict):
        """Return the appropriate async context manager for read/write streams."""
        stype = server.get("type", "stdio")
        if stype == "stdio":
            params = _StdioServerParameters(
                command=server["command"],
                args=server.get("args", []),
                env={**os.environ, **_expand_env_dict(server.get("env", {}))},
            )
            return _stdio_client(params)
        elif stype == "sse":
            headers = _expand_env_dict(server.get("headers", {}))
            return _sse_client(server["url"], headers=headers or None)
        else:
            raise ValueError(f"Unknown MCP server type: {stype!r}. Use 'stdio' or 'sse'.")

    @property
    def schemas(self) -> list[dict]:
        """Return OpenAI-compatible tool schema list for all registered tools."""
        return list(self._schemas)

    def call(self, name: str, arguments: str) -> str:
        """Execute a tool by name with JSON-encoded arguments string.

        Args:
            name:      Tool name as registered (may be prefixed on collision).
            arguments: JSON string of keyword arguments.

        Returns:
            String result from the MCP server, or a ``[ToolError]`` message.
        """
        if name not in self._tool_to_server:
            return f"[ToolError] Unknown tool: {name!r}"
        try:
            kwargs = json.loads(arguments) if arguments else {}
            server = self._tool_to_server[name]
            return asyncio.run(self._call_tool(server, name, kwargs))
        except Exception as exc:
            return f"[ToolError] {name} raised: {exc}"

    def __repr__(self) -> str:
        names = list(self._tool_to_server)
        return f"MCPToolRegistry(tools={names})"
