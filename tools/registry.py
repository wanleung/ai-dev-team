"""
ToolRegistry — registers tools as OpenAI function-calling schemas and dispatches calls.

Design for MCP migration (Option B):
    Replace LocalToolRegistry with MCPToolRegistry — override `call()` and `schemas`
    to route through an MCP client instead of local Python functions.
    All agent code stays identical; only the registry implementation changes.

Usage:
    registry = LocalToolRegistry()

    @registry.tool(
        name="run_linter",
        description="Run ruff linter on Python source code",
        parameters={
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python source code to lint"},
                "filename": {"type": "string", "description": "Filename for context"},
            },
            "required": ["code"],
        },
    )
    def run_linter(code: str, filename: str = "code.py") -> str:
        ...

    result = agent.call_with_tools("Review this code", tools=registry)
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Callable


class ToolRegistry(ABC):
    """Abstract base — swap LocalToolRegistry for MCPToolRegistry for MCP support."""

    @property
    @abstractmethod
    def schemas(self) -> list[dict]:
        """Return OpenAI-compatible tool schema list."""

    @abstractmethod
    def call(self, name: str, arguments: str) -> str:
        """Execute a tool by name with JSON-encoded arguments string."""


class LocalToolRegistry(ToolRegistry):
    """Dispatch tool calls to local Python functions.

    MCP migration path:
        class MCPToolRegistry(ToolRegistry):
            def __init__(self, server_url: str): ...
            @property
            def schemas(self): return self._mcp_client.list_tools()
            def call(self, name, arguments):
                return self._mcp_client.call_tool(name, json.loads(arguments))
    """

    def __init__(self) -> None:
        self._functions: dict[str, Callable] = {}
        self._schemas: list[dict] = []

    def tool(
        self,
        name: str,
        description: str,
        parameters: dict,
    ) -> Callable:
        """Decorator — register a Python function as an LLM-callable tool.

        Args:
            name:        Tool name (must be a valid Python identifier).
            description: Plain-English description shown to the LLM.
            parameters:  JSON Schema object describing the function parameters.
        """
        def decorator(func: Callable) -> Callable:
            self._functions[name] = func
            self._schemas.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": parameters,
                },
            })
            return func
        return decorator

    @property
    def schemas(self) -> list[dict]:
        return list(self._schemas)

    def call(self, name: str, arguments: str) -> str:
        """Execute the named tool and return its result as a string."""
        if name not in self._functions:
            return f"[ToolError] Unknown tool: {name!r}"
        try:
            kwargs = json.loads(arguments) if arguments else {}
            result = self._functions[name](**kwargs)
            return str(result)
        except Exception as exc:  # noqa: BLE001
            return f"[ToolError] {name} raised: {exc}"

    def __repr__(self) -> str:
        names = list(self._functions)
        return f"LocalToolRegistry(tools={names})"


class CombinedToolRegistry(ToolRegistry):
    """Merge two ToolRegistry instances into one.

    Schemas from both are exposed. ``call()`` tries ``primary`` first;
    if the tool is unknown there it tries ``secondary``.
    """

    def __init__(self, primary: ToolRegistry, secondary: ToolRegistry) -> None:
        self._primary = primary
        self._secondary = secondary
        self._primary_names = {s["function"]["name"] for s in primary.schemas}

    @property
    def schemas(self) -> list[dict]:
        primary = self._primary.schemas
        secondary = self._secondary.schemas
        overlap = [s["function"]["name"] for s in secondary if s["function"]["name"] in self._primary_names]
        if overlap:
            import warnings
            warnings.warn(
                f"CombinedToolRegistry: name collision in secondary registry: {overlap}",
                stacklevel=2,
            )
        return primary + [s for s in secondary if s["function"]["name"] not in self._primary_names]

    def call(self, name: str, arguments: str) -> str:
        if name in self._primary_names:
            return self._primary.call(name, arguments)
        return self._secondary.call(name, arguments)

    def __repr__(self) -> str:
        return f"CombinedToolRegistry(primary={self._primary!r}, secondary={self._secondary!r})"
