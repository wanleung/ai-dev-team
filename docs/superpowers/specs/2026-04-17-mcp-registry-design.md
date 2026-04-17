# MCP Registry Design

**Date:** 2026-04-17  
**Status:** Approved  
**Scope:** Add `MCPToolRegistry` so agents can call tools exposed by any MCP server (stdio or HTTP/SSE), configured once in `config.yaml`.

---

## Problem

`LocalToolRegistry` hard-codes tools as Python functions. There is no way to consume tools from external MCP servers (e.g. `@modelcontextprotocol/server-github`, custom HTTP endpoints) without writing new Python wrappers for every tool.

---

## Approach

Client-side MCP via the `mcp` Python SDK. `MCPToolRegistry` connects to one or more MCP servers, fetches their tool schemas, and dispatches `call_with_tools` requests through the existing `ToolRegistry` abstraction. All five tool-calling backends (GitHub Models, Anthropic, opencode-zen non-Claude, opencode-go non-MiniMax, Ollama) work unchanged — the `call_with_tools` loop in `BaseAgent` is not modified.

---

## Architecture

```
config.yaml
  └─ mcp.servers[]          (list of ServerConfig dicts)
        │
        ▼
MCPToolRegistry.__init__()  (connects to each server, fetches tool list)
        │
        ├─ StdioServerConfig  →  mcp.client.stdio.stdio_client()
        └─ SSEServerConfig    →  mcp.client.sse.sse_client()
        │
        ▼
MCPToolRegistry.schemas      → OpenAI-compatible tool schema list
MCPToolRegistry.call()       → routes to correct server, returns string result
        │
        ▼
BaseAgent.call_with_tools()  (unchanged — consumes ToolRegistry interface)
```

---

## Components

### `tools/mcp_registry.py`

**`ServerConfig`** — `TypedDict` union, one per server:

```python
class StdioServerConfig(TypedDict):
    name: str          # short label used for namespacing
    type: Literal["stdio"]
    command: str       # e.g. "npx"
    args: list[str]    # e.g. ["-y", "@modelcontextprotocol/server-github"]
    env: dict[str, str]  # optional env overrides (supports ${VAR} expansion)

class SSEServerConfig(TypedDict):
    name: str
    type: Literal["sse"]
    url: str
    headers: dict[str, str]  # optional
```

**`MCPToolRegistry(ToolRegistry)`**

- Constructor accepts `servers: list[dict]` (raw config dicts).
- Calls `_connect_all()` synchronously using `asyncio.run()` (or `asyncio.get_event_loop().run_until_complete()` if a loop already exists).
- Stores `_tool_to_server: dict[str, str]` mapping tool name → server name.
- On tool name collision across servers, prefixes with `{server_name}__{tool_name}`.
- `schemas` property: returns merged list of OpenAI-compatible `{"type": "function", "function": {...}}` dicts.
- `call(name, arguments)`: resolves server from `_tool_to_server`, runs `session.call_tool()` via `asyncio.run()`, returns stringified content.
- Graceful error: if a server fails to connect, logs a warning and continues (other servers still work).

**`_expand_env(value: str) -> str`** — module-level helper that expands `${VAR}` references using `os.environ`.

### `config.yaml` — new top-level `mcp` key

```yaml
mcp:
  servers: []           # empty list = MCP disabled (default)
  # Example entries:
  # - name: github
  #   type: stdio
  #   command: npx
  #   args: ["-y", "@modelcontextprotocol/server-github"]
  #   env:
  #     GITHUB_TOKEN: "${GITHUB_TOKEN}"
  #
  # - name: search
  #   type: sse
  #   url: "https://mcp.example.com/sse"
  #   headers:
  #     Authorization: "Bearer ${MCP_API_KEY}"
```

### `tools/__init__.py`

Add `MCPToolRegistry` to exports.

### `orchestrator.py`

- Read `config.mcp.servers` (default `[]`) at `Orchestrator.__init__`.
- If list is non-empty: instantiate `MCPToolRegistry(servers)`, merge with `builtin_tools` into a `CombinedToolRegistry` (or simply extend `builtin_tools` schemas/routes by calling a `merge()` helper).
- Pass merged registry to any agent that calls `call_with_tools`.

**`CombinedToolRegistry`** — thin wrapper: accepts two `ToolRegistry` instances, delegates `schemas` (concatenated) and `call()` (tries first, falls back to second).

---

## Data Flow

1. `Orchestrator.__init__` reads `mcp.servers` from config.
2. `MCPToolRegistry` connects to each server (blocking, at startup).
3. Tools from MCP servers appear in `schemas` alongside built-in tools.
4. During a pipeline run, `agent.call_with_tools(prompt, tools=merged_registry)` is called.
5. The LLM returns a tool call; `BaseAgent` calls `merged_registry.call(name, args)`.
6. `CombinedToolRegistry` routes to `MCPToolRegistry` or `LocalToolRegistry`.
7. `MCPToolRegistry` dispatches async MCP call via `asyncio.run()`, returns string.

---

## Error Handling

| Scenario | Behaviour |
|---|---|
| Server fails to connect at startup | Warning logged; server skipped; other servers still available |
| Tool call raises exception | `[ToolError] {name} raised: {exc}` returned (consistent with `LocalToolRegistry`) |
| Unknown tool name | `[ToolError] Unknown tool: {name!r}` |
| `mcp` package not installed | `ImportError` with clear message: "Install `mcp` to use MCP servers: pip install mcp" |
| No servers configured | `MCPToolRegistry` not instantiated; `builtin_tools` used as-is |

---

## Testing

- `tests/test_mcp_registry.py` — unit tests with `unittest.mock` patching the `mcp` SDK:
  - `MCPToolRegistry` with stdio server: schemas fetched, tool called, result returned
  - `MCPToolRegistry` with SSE server: same
  - Name collision: tool prefixed with `server__`
  - Server connect failure: warning + graceful skip
  - `mcp` not installed: clear `ImportError`
  - `_expand_env`: `${VAR}` substitution
  - `CombinedToolRegistry`: routes to correct sub-registry

---

## Dependencies

```
mcp>=1.0.0      # MCP Python SDK (new requirement)
```

Add to `requirements.txt`. The `mcp` package is only imported inside `MCPToolRegistry` (lazy import), so the rest of the codebase is unaffected if `mcp` is not installed and MCP is not configured.

---

## Out of Scope

- Per-agent MCP server config (all agents share one registry)
- Anthropic server-side MCP (`betas=["mcp-client-2025-04-04"]`)
- OpenAI Responses API MCP
- MCP authentication flows beyond static headers/env vars
- MCP resource or prompt primitives (tools only)
