# Token Counter & Cost Tracking — Design Spec

**Date:** 2026-05-05  
**Status:** Approved

---

## Problem

AI Software House runs multi-stage LLM pipelines on behalf of clients. There is no record of how many tokens are consumed per run, per stage, or per model — making it impossible to attribute costs or charge clients accurately.

---

## Goals

- Track token usage (prompt + completion) for every LLM call in the pipeline
- Break down usage by run, stage, and model
- Calculate USD cost using a configurable pricing table
- Persist records to a local SQLite database
- Post a usage summary to the GitHub issue comment at pipeline end
- Require zero changes to agent logic (all instrumentation in backends)

---

## Architecture

A `TokenLedger` singleton collects `UsageRecord` events emitted by LLM backends. It is the single point of accumulation; no agent or orchestrator code needs to know about it except to call `ledger.start_run()` / `ledger.finish_run()` at pipeline boundaries.

```
Orchestrator.run()
  └── ledger.start_run(run_id, project_name, repo)
        └── per LLM call in any backend:
              ledger.record(run_id, stage, model, prompt_tokens, completion_tokens)
        └── pipeline end:
              ledger.finish_run(run_id)
              ledger.flush_to_db(db_path)
              ledger.github_summary(run_id) → post to issue comment
```

---

## Components

### `agents/token_ledger.py`

**`UsageRecord`** (dataclass):
| Field | Type | Description |
|---|---|---|
| `run_id` | str | UUID for this pipeline run |
| `stage` | str | Pipeline stage name (e.g. `"pm"`, `"architect"`) |
| `model` | str | Model name as passed to the backend |
| `prompt_tokens` | int | Input token count |
| `completion_tokens` | int | Output token count |
| `cost_usd` | float | Calculated cost (prompt + completion × price) |
| `timestamp` | datetime | UTC time of the call |

**`TokenLedger`** (class):
- `start_run(run_id, project_name, repo)` — initialise a run
- `record(run_id, stage, model, prompt_tokens, completion_tokens)` — add a usage event; calculates cost from pricing table
- `finish_run(run_id)` — mark run complete, record end time
- `summary(run_id) -> dict` — returns per-stage and per-model breakdown + totals
- `flush_to_db(db_path)` — upserts run + all events into SQLite
- `format_github_comment(run_id) -> str` — renders Markdown table for GitHub

**Token estimation (streaming fallback)**:  
When `response.usage` is not available (streaming), estimate via `tiktoken`:
- prompt tokens: count of all input messages
- completion tokens: count of the collected reply string
- Model encoding: `cl100k_base` for all models (safe default; accurate for GPT-4/3.5 family, reasonable estimate for others)
- Ollama/local models: tiktoken estimate used; cost = $0.00

---

### `agents/backends/base.py` changes

After each call, emit to the global ledger:

- **Non-stream `call()`**: `response.usage` provides exact `prompt_tokens` / `completion_tokens`
- **Stream `_stream_call()`**: tiktoken estimate on input messages + collected reply
- **`call_with_tools()`**: accumulate usage across all tool turns

The current `stage` name is passed via a thread-local / context variable set by the orchestrator at stage entry.

---

### SQLite Schema (`token_usage.db`)

```sql
CREATE TABLE runs (
    run_id TEXT PRIMARY KEY,
    project_name TEXT,
    github_repo TEXT,
    started_at TEXT,
    finished_at TEXT,
    total_prompt_tokens INTEGER,
    total_completion_tokens INTEGER,
    total_cost_usd REAL
);

CREATE TABLE usage_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT REFERENCES runs(run_id),
    stage TEXT,
    model TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    cost_usd REAL,
    ts TEXT
);
```

---

### GitHub Issue Comment

Posted at pipeline end (if `post_to_github: true` and an issue number exists):

```markdown
## 💰 Token Usage — Astronomy Gadget CMS
| Stage      | Model        | In (tokens) | Out (tokens) | Cost (USD) |
|------------|--------------|-------------|--------------|------------|
| pm         | gpt-4.1      | 2,100       | 800          | $0.0182    |
| architect  | qwen3.6-plus | 4,500       | 1,200        | $0.0041    |
| qa_write   | thinker      | 3,200       | 950          | $0.00      |
| **Total**  |              | **18,400**  | **6,300**    | **$0.14**  |

_Tracked by AI Software House · Run ID: `abc-1234`_
```

---

### `config.yaml` additions

```yaml
cost_tracking:
  enabled: true
  db_path: "./token_usage.db"
  post_to_github: true         # post summary to the GitHub issue on completion
  pricing:                     # USD per 1M tokens: [input, output]
    gpt-4.1:        [2.00, 8.00]
    gpt-4.1-mini:   [0.40, 1.60]
    qwen3.6-plus:   [0.50, 1.50]
    qwen3.5-plus:   [0.30, 1.20]
    thinker:        [0.00, 0.00]   # local Ollama = free
    coder:          [0.00, 0.00]
    fast:           [0.00, 0.00]
    default:        [2.00, 8.00]   # fallback for unlisted models
```

---

## Orchestrator Integration

- `Orchestrator.__init__` initialises the global `TokenLedger` with pricing from config
- `Orchestrator.run()` calls `ledger.start_run()` at entry and `ledger.finish_run()` + `ledger.flush_to_db()` + optional GitHub comment at exit (even on error)
- Stage name context is set via a context variable before each stage `fn()` call so backends can self-report which stage they're in without being passed explicit arguments

---

## `PipelineResult` additions

```python
token_usage: dict = field(default_factory=dict)   # summary dict from ledger.summary()
total_cost_usd: float = 0.0
run_id: str = ""
```

---

## Out of Scope

- Multi-tenant billing API or invoice generation
- Real-time per-request cost streaming to a UI
- Per-organisation cost aggregation across runs (can query SQLite directly)

---

## Testing

- Unit tests for `TokenLedger`: record, summary, flush, format_github_comment
- Unit tests for backend emission: mock response with `.usage`, verify ledger receives correct values
- Unit test for tiktoken streaming fallback
- Integration test: run a minimal pipeline, assert `result.total_cost_usd > 0` and DB row exists
