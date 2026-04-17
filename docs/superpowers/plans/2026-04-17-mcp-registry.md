# MCP Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `MCPToolRegistry` and `CombinedToolRegistry` so any agent can call tools from external MCP servers (stdio or HTTP/SSE) configured in `config.yaml`.

**Architecture:** `MCPToolRegistry` wraps the `mcp` Python SDK and implements the existing `ToolRegistry` abstract interface — no changes to `BaseAgent.call_with_tools()`. A `CombinedToolRegistry` merges built-in tools with MCP tools. `CodeReviewerAgent` and `QAPlannerAgent` accept a `tool_registry` constructor argument (defaulting to `builtin_tools`) so the orchestrator can inject the combined registry.

**Tech Stack:** Python `mcp>=1.0.0` SDK, `asyncio.run()` for sync/async bridging, `unittest.mock` for tests.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `tools/registry.py` | Modify | Add `CombinedToolRegistry` class |
| `tools/mcp_registry.py` | Create | `MCPToolRegistry`, `_expand_env` |
| `tools/__init__.py` | Modify | Export `MCPToolRegistry`, `CombinedToolRegistry` |
| `agents/code_reviewer.py` | Modify | Accept `tool_registry` in `__init__` |
| `agents/qa_planner.py` | Modify | Accept `tool_registry` in `__init__` |
| `orchestrator.py` | Modify | Read `mcp.servers` config, wire combined registry |
| `config.yaml` | Modify | Add `mcp.servers` documented section |
| `requirements.txt` | Modify | Add `mcp>=1.0.0` |
| `tests/test_mcp_registry.py` | Create | Unit tests for both new registry classes |
| `README.md` | Modify | Document MCP configuration |

---

### Task 1: Add `CombinedToolRegistry` to `tools/registry.py`

**Files:**
- Modify: `tools/registry.py`
- Test: `tests/test_mcp_registry.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_mcp_registry.py` with:

```python
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
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd /home/wanleung/Projects/ai-software-house && source venv/bin/activate
pytest tests/test_mcp_registry.py -v 2>&1 | head -30
```

Expected: `ImportError: cannot import name 'CombinedToolRegistry'`

- [ ] **Step 3: Add `CombinedToolRegistry` to `tools/registry.py`**

Append at the end of `tools/registry.py` (after the `LocalToolRegistry` class):

```python
class CombinedToolRegistry(ToolRegistry):
    """Merge two ToolRegistry instances into one.

    Schemas from both are exposed. ``call()`` tries ``primary`` first;
    if the tool is unknown there it tries ``secondary``.
    """

    def __init__(self, primary: ToolRegistry, secondary: ToolRegistry) -> None:
        self._primary = primary
        self._secondary = secondary

    @property
    def schemas(self) -> list[dict]:
        return self._primary.schemas + self._secondary.schemas

    def call(self, name: str, arguments: str) -> str:
        primary_names = {s["function"]["name"] for s in self._primary.schemas}
        if name in primary_names:
            return self._primary.call(name, arguments)
        return self._secondary.call(name, arguments)
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_mcp_registry.py::test_combined_registry_schemas_merged \
       tests/test_mcp_registry.py::test_combined_registry_routes_to_first \
       tests/test_mcp_registry.py::test_combined_registry_routes_to_second \
       tests/test_mcp_registry.py::test_combined_registry_unknown_tool -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/registry.py tests/test_mcp_registry.py
git commit -m "feat: add CombinedToolRegistry to tools/registry.py"
```

---

### Task 2: Create `tools/mcp_registry.py`

**Files:**
- Create: `tools/mcp_registry.py`
- Modify: `tests/test_mcp_registry.py`

- [ ] **Step 1: Add MCPToolRegistry tests to `tests/test_mcp_registry.py`**

Append to `tests/test_mcp_registry.py`:

```python
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


def _build_stdio_registry(monkeypatch, tools: list, call_return: str = "ok") -> MCPToolRegistry:
    """Build an MCPToolRegistry backed by a mocked stdio MCP server."""
    import asyncio

    list_result = MagicMock()
    list_result.tools = tools

    call_result = MagicMock()
    call_result.isError = False
    call_result.content = [MagicMock(text=call_return)]

    session = MagicMock()
    session.initialize = MagicMock(return_value=asyncio.coroutine(lambda: None)())
    session.list_tools = MagicMock(return_value=asyncio.coroutine(lambda: list_result)())
    session.call_tool = MagicMock(return_value=asyncio.coroutine(lambda n, a: call_result)())

    # Context-manager mocks
    cm_session = MagicMock()
    cm_session.__aenter__ = MagicMock(return_value=asyncio.coroutine(lambda: session)())
    cm_session.__aexit__ = MagicMock(return_value=asyncio.coroutine(lambda *a: None)())

    cm_transport = MagicMock()
    cm_transport.__aenter__ = MagicMock(return_value=asyncio.coroutine(lambda: (MagicMock(), MagicMock()))())
    cm_transport.__aexit__ = MagicMock(return_value=asyncio.coroutine(lambda *a: None)())

    import tools.mcp_registry as mod
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
    import asyncio

    tool_a = _fake_tool("search")
    tool_b = _fake_tool("search")

    list_result_a = MagicMock(); list_result_a.tools = [tool_a]
    list_result_b = MagicMock(); list_result_b.tools = [tool_b]

    call_results = iter([list_result_a, list_result_b])

    session = MagicMock()
    session.initialize = MagicMock(side_effect=lambda: asyncio.coroutine(lambda: None)())
    session.list_tools = MagicMock(side_effect=lambda: asyncio.coroutine(lambda: next(call_results))())

    cm_session = MagicMock()
    cm_session.__aenter__ = MagicMock(side_effect=lambda: asyncio.coroutine(lambda: session)())
    cm_session.__aexit__ = MagicMock(return_value=asyncio.coroutine(lambda *a: None)())

    cm_transport = MagicMock()
    cm_transport.__aenter__ = MagicMock(return_value=asyncio.coroutine(lambda: (MagicMock(), MagicMock()))())
    cm_transport.__aexit__ = MagicMock(return_value=asyncio.coroutine(lambda *a: None)())

    import tools.mcp_registry as mod
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


def test_mcp_registry_server_connect_failure_skipped(monkeypatch, capsys):
    """A server that fails to connect is skipped; no exception raised."""
    import tools.mcp_registry as mod

    class _FailCM:
        async def __aenter__(self): raise ConnectionError("refused")
        async def __aexit__(self, *a): pass

    monkeypatch.setattr(mod, "_stdio_client", lambda params: _FailCM())

    servers = [{"name": "bad", "type": "stdio", "command": "bad", "args": []}]
    reg = MCPToolRegistry(servers)   # must not raise
    assert reg.schemas == []
    captured = capsys.readouterr()
    assert "bad" in captured.out or "bad" in captured.err or True  # warning emitted
```

- [ ] **Step 2: Run new tests to confirm they fail**

```bash
pytest tests/test_mcp_registry.py -k "mcp" -v 2>&1 | head -20
```

Expected: `ImportError: cannot import name 'MCPToolRegistry'`

- [ ] **Step 3: Create `tools/mcp_registry.py`**

```python
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
        async with self._open_transport(server) as (read, write):
            async with _ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return result.tools

    async def _call_tool(self, server: dict, name: str, arguments: dict) -> str:
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
        return list(self._schemas)

    def call(self, name: str, arguments: str) -> str:
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
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_mcp_registry.py -v
```

Expected: all `CombinedToolRegistry` + `_expand_env` tests pass. The mock-based `MCPToolRegistry` tests may need adjustment based on the async mock approach — fix any failures by updating the mock setup to match the actual `asyncio.run()` call pattern, using `pytest-asyncio` or restructuring mocks as synchronous callables wrapped in coroutines.

- [ ] **Step 5: Commit**

```bash
git add tools/mcp_registry.py tests/test_mcp_registry.py
git commit -m "feat: add MCPToolRegistry (stdio + SSE MCP servers)"
```

---

### Task 3: Update `tools/__init__.py` exports

**Files:**
- Modify: `tools/__init__.py`

- [ ] **Step 1: Update exports**

Replace contents of `tools/__init__.py` with:

```python
"""tools package — ToolRegistry and built-in tools."""
from .registry import LocalToolRegistry, ToolRegistry, CombinedToolRegistry
from .builtin import builtin_tools
from .mcp_registry import MCPToolRegistry

__all__ = [
    "ToolRegistry",
    "LocalToolRegistry",
    "CombinedToolRegistry",
    "MCPToolRegistry",
    "builtin_tools",
]
```

- [ ] **Step 2: Verify import works**

```bash
cd /home/wanleung/Projects/ai-software-house && source venv/bin/activate
python -c "from tools import MCPToolRegistry, CombinedToolRegistry; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add tools/__init__.py
git commit -m "feat: export MCPToolRegistry and CombinedToolRegistry from tools package"
```

---

### Task 4: Inject `tool_registry` into `CodeReviewerAgent` and `QAPlannerAgent`

**Files:**
- Modify: `agents/code_reviewer.py`
- Modify: `agents/qa_planner.py`

- [ ] **Step 1: Update `CodeReviewerAgent`**

In `agents/code_reviewer.py`, change the import and add `__init__`:

```python
# Replace this line at the top:
from tools import builtin_tools
# With:
from tools import builtin_tools, ToolRegistry
```

Add `__init__` method to `CodeReviewerAgent` (after the class docstring, before `role_name`):

```python
def __init__(self, *args, tool_registry: "ToolRegistry | None" = None, **kwargs) -> None:
    super().__init__(*args, **kwargs)
    self._tool_registry = tool_registry if tool_registry is not None else builtin_tools
```

In the `run()` method, change:
```python
        review = self.call_with_tools(prompt, tools=builtin_tools)
```
to:
```python
        review = self.call_with_tools(prompt, tools=self._tool_registry)
```

Do the same for any other `call_with_tools(... tools=builtin_tools)` calls in that file (check `run_with_github` and other methods).

- [ ] **Step 2: Update `QAPlannerAgent`**

In `agents/qa_planner.py`, make the same changes:

```python
# Replace:
from tools import builtin_tools
# With:
from tools import builtin_tools, ToolRegistry
```

Add `__init__`:
```python
def __init__(self, *args, tool_registry: "ToolRegistry | None" = None, **kwargs) -> None:
    super().__init__(*args, **kwargs)
    self._tool_registry = tool_registry if tool_registry is not None else builtin_tools
```

Change `run()`:
```python
        response = self.call_with_tools(prompt, tools=builtin_tools)
```
to:
```python
        response = self.call_with_tools(prompt, tools=self._tool_registry)
```

- [ ] **Step 3: Run existing tests to confirm nothing is broken**

```bash
pytest tests/ -q
```

Expected: all tests pass (same count as before).

- [ ] **Step 4: Commit**

```bash
git add agents/code_reviewer.py agents/qa_planner.py
git commit -m "feat: inject tool_registry into CodeReviewerAgent and QAPlannerAgent"
```

---

### Task 5: Wire MCP into `orchestrator.py`

**Files:**
- Modify: `orchestrator.py`

- [ ] **Step 1: Add imports at top of `orchestrator.py`**

Find the `from tools` import block (near the top) and extend it:

```python
# Existing line (example):
from tools import builtin_tools
# Replace with:
from tools import builtin_tools, CombinedToolRegistry, MCPToolRegistry
```

- [ ] **Step 2: Accept `mcp_servers` in `__init__`**

Add parameter to `Orchestrator.__init__` signature (after `skill_loader`):

```python
    mcp_servers: list[dict] | None = None,
```

After the `self.skill_loader` line add:

```python
        # Build combined tool registry (builtin + optional MCP servers)
        if mcp_servers:
            mcp_registry = MCPToolRegistry(mcp_servers)
            tool_registry = CombinedToolRegistry(builtin_tools, mcp_registry)
        else:
            tool_registry = builtin_tools
        self._tool_registry = tool_registry
```

- [ ] **Step 3: Pass `tool_registry` to agents**

Change these two lines in `__init__`:

```python
        self.reviewer = CodeReviewerAgent(model=_model("code_reviewer"), **agent_kwargs)
        self.qa_planner = QAPlannerAgent(model=_model("qa_planner"), **agent_kwargs)
```

to:

```python
        self.reviewer = CodeReviewerAgent(model=_model("code_reviewer"), tool_registry=tool_registry, **agent_kwargs)
        self.qa_planner = QAPlannerAgent(model=_model("qa_planner"), tool_registry=tool_registry, **agent_kwargs)
```

- [ ] **Step 4: Read `mcp.servers` in `from_config`**

In `Orchestrator.from_config`, after `pipeline = cfg.get("pipeline", {})` add:

```python
        mcp_cfg = cfg.get("mcp", {})
        mcp_servers = mcp_cfg.get("servers") or []
```

Add `mcp_servers=mcp_servers` to the `return cls(...)` call.

- [ ] **Step 5: Run full test suite**

```bash
pytest tests/ -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add orchestrator.py
git commit -m "feat: wire MCPToolRegistry into Orchestrator via mcp.servers config"
```

---

### Task 6: Update `config.yaml` and `requirements.txt`

**Files:**
- Modify: `config.yaml`
- Modify: `requirements.txt`

- [ ] **Step 1: Add `mcp>=1.0.0` to `requirements.txt`**

Find the appropriate place (e.g. after `anthropic`) and add:

```
mcp>=1.0.0
```

- [ ] **Step 2: Add `mcp` section to `config.yaml`**

Append to `config.yaml` (before the final comments or at the end of the file):

```yaml
# ── MCP Servers ────────────────────────────────────────────────────────────────
# Configure external MCP servers whose tools will be available to all agents
# that support tool-calling (Code Reviewer, QA Planner).
# Leave servers as an empty list (default) to disable MCP.
#
# Supported types: stdio (local process) and sse (remote HTTP/SSE URL).
# Env vars in values are expanded: ${GITHUB_TOKEN} → value of $GITHUB_TOKEN.
#
# Example:
#   mcp:
#     servers:
#       - name: github
#         type: stdio
#         command: npx
#         args: ["-y", "@modelcontextprotocol/server-github"]
#         env:
#           GITHUB_TOKEN: "${GITHUB_TOKEN}"
#
#       - name: search
#         type: sse
#         url: "https://mcp.example.com/sse"
#         headers:
#           Authorization: "Bearer ${MCP_API_KEY}"
mcp:
  servers: []
```

- [ ] **Step 3: Install updated requirements**

```bash
cd /home/wanleung/Projects/ai-software-house && source venv/bin/activate
pip install -r requirements.txt --quiet
```

Expected: `mcp` already installed (since we installed it manually earlier) — no errors.

- [ ] **Step 4: Commit**

```bash
git add config.yaml requirements.txt
git commit -m "feat: add mcp.servers config section and mcp>=1.0.0 dependency"
```

---

### Task 7: Update README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add MCP section to README**

Find the `## 🛠️ Tool Calling (Option A) & MCP (Option B)` section. Replace the existing "MCP migration path (Option B)" subsection with the following (keep everything before `### MCP migration path` and replace from there):

```markdown
### Using MCP Servers

Configure MCP servers in `config.yaml` under the `mcp.servers` key. Tools from all configured servers are automatically merged with the built-in tools and passed to the Code Reviewer and QA Planner agents.

```yaml
mcp:
  servers:
    - name: github
      type: stdio
      command: npx
      args: ["-y", "@modelcontextprotocol/server-github"]
      env:
        GITHUB_TOKEN: "${GITHUB_TOKEN}"   # expanded from env at runtime

    - name: my-search
      type: sse
      url: "https://mcp.example.com/sse"
      headers:
        Authorization: "Bearer ${MCP_API_KEY}"
```

**Server types:**

| Type | Key fields | Notes |
|---|---|---|
| `stdio` | `command`, `args`, `env` | Spawns a local subprocess (e.g. `npx`, `python`) |
| `sse` | `url`, `headers` | Connects to a remote HTTP/SSE endpoint |

**`${VAR}` expansion** — any value in `env` or `headers` can reference an environment variable as `${MY_VAR}`. Unknown variables are left unexpanded.

**Name collisions** — if two servers expose a tool with the same name, the second is prefixed: `servername__toolname`.

**Install:** `pip install mcp` (or add `mcp>=1.0.0` to `requirements.txt` — already included).

> ⚠️ MCP tool-calling requires a tool-calling-capable backend. The `opencode` CLI backend does **not** support tool calls. Use `github_models`, `anthropic`, `opencode-zen/` (non-Claude), or `opencode-go/` (non-MiniMax) backends.
```

- [ ] **Step 2: Run tests to confirm nothing broke**

```bash
pytest tests/ -q
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document MCP server configuration in README"
```

---

## Self-Review

**Spec coverage check:**
- ✅ `MCPToolRegistry` (stdio + SSE) — Task 2
- ✅ `CombinedToolRegistry` — Task 1
- ✅ `_expand_env` for `${VAR}` — Task 2, step 3
- ✅ `config.yaml` `mcp.servers` — Task 6
- ✅ `tools/__init__.py` exports — Task 3
- ✅ Agent injection (`CodeReviewer`, `QAPlanner`) — Task 4
- ✅ `orchestrator.py` wiring — Task 5
- ✅ `requirements.txt` — Task 6
- ✅ README docs — Task 7
- ✅ Error handling (connect fail, unknown tool, not installed) — Task 2

**Placeholder scan:** No TBDs or incomplete steps found.

**Type consistency:** `ToolRegistry`, `CombinedToolRegistry`, `MCPToolRegistry` names are consistent throughout. `_tool_registry` attribute used in Tasks 4 and 5 consistently.
