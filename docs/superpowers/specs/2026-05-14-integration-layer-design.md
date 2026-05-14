# Integration Layer Design — MCP + REST API for ai-software-house

**Date:** 2026-05-14  
**Status:** Approved

## Problem

`ai-software-house` pipelines are currently triggered only via the GitHub label watcher or the `main.py` CLI. There is no programmatic interface for external tools (Copilot CLI, Claude Code, OpenCode, web UIs, chatbots) to trigger requirements, watch progress, or inspect results.

## Goal

A single server process (`aisw_server.py`) that exposes:
1. A **REST API** (FastAPI) — curl/chatbot/web-UI friendly
2. An **MCP server** (auto-generated from the REST routes via `fastapi_mcp`) — native tool-use for Copilot CLI, Claude Code, OpenCode

Both surfaces share one async job runner and one SQLite job store. The existing `watcher.py` is unchanged and can run in parallel.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    aisw_server.py                       │
│                                                         │
│  ┌──────────────────┐    ┌──────────────────────────┐  │
│  │   FastAPI REST    │    │  MCP layer (fastapi_mcp)  │  │
│  │  POST /runs       │    │  auto-bridged from routes  │  │
│  │  GET  /runs       │    │  tool: run_pipeline        │  │
│  │  GET  /runs/{id}  │    │  tool: list_runs           │  │
│  │  GET  /runs/{id}/ │    │  tool: get_run             │  │
│  │       stream      │    │  tool: stream_run_logs     │  │
│  │  DELETE /runs/{id}│    │  tool: cancel_run          │  │
│  │  GET  /health     │    └──────────────────────────┘  │
│  └────────┬─────────┘                                   │
│           │                                             │
│           ▼                                             │
│  ┌──────────────────────────────────────────────────┐  │
│  │              Async Job Runner                     │  │
│  │  ThreadPoolExecutor (wraps sync Orchestrator)    │  │
│  │  Captures stdout/stderr → per-job log file       │  │
│  └──────────────────┬───────────────────────────────┘  │
│           │                     │                       │
│           ▼                     ▼                       │
│  ┌─────────────┐    ┌─────────────────────────────┐   │
│  │  SQLite      │    │  logs/jobs/{run_id}.log      │   │
│  │  jobs.db     │    │  (streamed via SSE)          │   │
│  └─────────────┘    └─────────────────────────────┘   │
│           │                                             │
│           ▼                                             │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Orchestrator.from_config() / Orchestrator()     │  │
│  │  (existing — no changes to orchestrator.py)      │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

---

## Components

### `aisw_server.py`

Main entrypoint. Starts Uvicorn with the FastAPI app. Registers `fastapi_mcp` at startup to auto-generate MCP tools from all REST routes.

```
python aisw_server.py              # uses aisw_server.yaml
python aisw_server.py --port 9000  # override port
```

### FastAPI app (`server/app.py`)

Route definitions, auth middleware, SSE streaming endpoint.

**Auth:** `X-API-Key` header checked on every request (except `/health`). Key is loaded from `aisw_server.yaml` or `AISW_API_KEY` env var.

### Job Runner (`server/job_runner.py`)

- `submit_job(req) -> run_id` — enqueues a job in `ThreadPoolExecutor`
- `cancel_job(run_id)` — sets `status=cancelled` if still queued; sends interrupt signal if running
- `get_job(run_id) -> JobRecord` — reads from SQLite
- `list_jobs(limit=50) -> [JobRecord]` — reads recent jobs from SQLite
- `stream_logs(run_id) -> AsyncGenerator[str]` — opens log file, yields lines, polls for new lines while job is running, closes when done or cancelled

Each job runs `Orchestrator.run()` in a `ThreadPoolExecutor` thread. stdout/stderr are redirected to `logs/jobs/{run_id}.log`.

### Job Store (`server/job_store.py`)

SQLite-backed. Table: `jobs`.

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | UUID |
| `status` | TEXT | `queued / running / done / failed / cancelled / interrupted` |
| `requirement` | TEXT | Full requirement text |
| `repo` | TEXT | Target repo |
| `pipeline` | TEXT | Pipeline label used |
| `engineers` | INTEGER | Number of engineers |
| `created_at` | TEXT | ISO timestamp |
| `updated_at` | TEXT | ISO timestamp |
| `result_json` | TEXT | Serialised `PipelineResult` (set on completion) |
| `log_path` | TEXT | Absolute path to log file |

On server start, any jobs with `status=running` are set to `status=interrupted` (they cannot be resumed).

### Config (`aisw_server.yaml`)

```yaml
server:
  host: 0.0.0.0
  port: 8765
  api_key: "change-me"           # or set AISW_API_KEY env var

defaults:
  repo: "owner/default-repo"     # used if POST /runs omits repo
  pipeline: "ai-feature"
  engineers: 2
  config_yaml: "config.yaml"     # path to existing orchestrator config.yaml
```

---

## REST API

### `POST /runs`

Submit a requirement.

**Request:**
```json
{
  "requirement": "Build a REST API for a bookmark manager",
  "repo": "owner/my-repo",       // optional — falls back to defaults.repo
  "pipeline": "ai-feature",      // optional — falls back to defaults.pipeline
  "engineers": 2                 // optional — falls back to defaults.engineers
}
```

**Response 202:**
```json
{
  "run_id": "a1b2c3d4-...",
  "status": "queued",
  "stream_url": "/runs/a1b2c3d4-.../stream"
}
```

### `GET /runs`

List recent runs.

**Response 200:**
```json
[
  {
    "run_id": "...",
    "status": "done",
    "requirement": "Build a bookmark manager...",
    "repo": "owner/my-repo",
    "pipeline": "ai-feature",
    "created_at": "2026-05-14T14:00:00Z",
    "updated_at": "2026-05-14T14:12:00Z"
  }
]
```

### `GET /runs/{id}`

Full run detail including result.

**Response 200:**
```json
{
  "run_id": "...",
  "status": "done",
  "requirement": "...",
  "repo": "...",
  "pipeline": "...",
  "engineers": 2,
  "created_at": "...",
  "updated_at": "...",
  "result": {
    "verdict": "approved",
    "pr_url": "https://github.com/...",
    "tests_passed": true,
    "deploy_tests_passed": null
  },
  "log_lines": 1423
}
```

### `GET /runs/{id}/stream`

Server-Sent Events stream. Each event is one log line.

```
event: log
data: [PM] Analysing requirement...

event: log
data: [Engineer 1] Writing auth module...

event: done
data: {"verdict": "approved", "pr_url": "https://..."}
```

If the run is already complete, replays all log lines then sends `event: done`.  
If the run is cancelled or failed, ends with `event: error`.

### `DELETE /runs/{id}`

Cancel a job. Returns 200 if cancelled, 409 if already complete.

### `GET /health`

```json
{"status": "ok", "version": "1.0"}
```

---

## MCP Integration

`fastapi_mcp` is mounted at startup and auto-generates MCP tool definitions from all FastAPI routes. The MCP server is reachable at:

```
http://localhost:8765/mcp
```

Generated tools:

| MCP Tool | Maps to |
|---|---|
| `run_pipeline` | `POST /runs` |
| `list_runs` | `GET /runs` |
| `get_run` | `GET /runs/{id}` |
| `cancel_run` | `DELETE /runs/{id}` |
| `stream_run_logs` | `GET /runs/{id}/stream` (returns buffered log text for MCP clients that don't support streaming) |

### Connecting from tools

**Copilot CLI** — add to `~/.copilot/config.yaml`:
```yaml
mcp_servers:
  - name: ai-software-house
    url: http://localhost:8765/mcp
    headers:
      X-API-Key: "your-key"
```

**Claude Code / claude.ai** — add MCP server at `http://localhost:8765/mcp`.

**OpenCode** — add to `~/.opencode/config.json`:
```json
{
  "mcpServers": {
    "aisw": {
      "url": "http://localhost:8765/mcp",
      "headers": { "X-API-Key": "your-key" }
    }
  }
}
```

**curl:**
```bash
curl -X POST http://localhost:8765/runs \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"requirement": "Build a bookmark manager REST API", "repo": "me/my-repo"}'
```

---

## File Layout

```
aisw_server.py              # entrypoint (uvicorn startup + fastapi_mcp mount)
aisw_server.yaml            # server config
server/
  __init__.py
  app.py                    # FastAPI app + route definitions
  job_runner.py             # ThreadPoolExecutor + log capture
  job_store.py              # SQLite CRUD for jobs table
  models.py                 # Pydantic request/response models
  auth.py                   # X-API-Key middleware
logs/
  jobs/                     # per-run log files ({run_id}.log)
```

New dependencies (add to `requirements.txt`):
- `fastapi`
- `uvicorn[standard]`
- `fastapi-mcp`
- `pydantic`

---

## Error Handling

| Case | Behaviour |
|---|---|
| Invalid API key | 401 Unauthorized |
| `run_id` not found | 404 Not Found |
| Orchestrator raises exception | Job status → `failed`; exception traceback written to log file |
| Server restart with running jobs | Jobs set to `interrupted` on startup; client sees `status=interrupted` on `GET /runs/{id}` |
| `cancel_run` on already-done job | 409 Conflict with message |

---

## Testing

- `tests/test_aisw_server.py` — unit tests for routes using FastAPI `TestClient`, mocking `job_runner`
- `tests/test_job_store.py` — unit tests for SQLite CRUD (in-memory SQLite for test isolation)
- `tests/test_job_runner.py` — unit tests for job lifecycle (mock `Orchestrator.run`)
- SSE streaming tested with an async test client

---

## Out of Scope (MVP)

- WebSocket support (SSE is sufficient)
- Multi-tenant / per-user job isolation
- Job queue persistence across executor restarts (jobs marked `interrupted`, not retried)
- Web UI (this is the backend layer; a separate frontend can be built on top)
- Rate limiting
