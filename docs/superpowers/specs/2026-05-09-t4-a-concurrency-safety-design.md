# T4-A: Concurrency & Startup Safety — Design

**Date:** 2026-05-09  
**Status:** Approved  
**Branch:** `t4-a-concurrency-safety`

## Problem

Three bugs that can cause data loss or crashes in production:

1. `result.errors` and `result.completed_stages` are mutated from multiple threads during parallel stage execution with no lock, risking list corruption.
2. `MCPToolRegistry(mcp_servers)` at orchestrator init is not wrapped in try/except — any MCP startup failure crashes the entire orchestrator with no fallback.
3. `_save_checkpoint(result)` is called from multiple threads during parallel execution; the result object can be mutated mid-serialisation.

## Architecture

All three fixes are confined to `orchestrator.py` and add no new dependencies.

### Fix 1 — PipelineResult mutation lock

`PipelineResult` is a `@dataclass`. Add a `_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False, compare=False)` field. Acquire it inside `add_error()` and any method that appends to `completed_stages` or `errors`.

**Why not a module-level lock:** each `PipelineResult` instance is independent; a per-instance lock avoids unnecessary contention across pipeline runs.

**Mutation points to protect:**
- `add_error()` — line ~399 (appends to `self.errors`)
- `self.completed_stages.append(...)` — called in `_run_stage()` on success path

### Fix 2 — MCP init fallback

Wrap both `MCPToolRegistry(mcp_servers)` (line 634) and `MCPToolRegistry(rag_servers)` (line 642) in `try/except Exception as exc`. On failure: log `[WARNING] MCP init failed: {exc} — continuing without MCP tools`, set `mcp_registry = None` / `rag_registry = None`. Existing null guards downstream already handle `None`.

### Fix 3 — Checkpoint write lock

Add `self._checkpoint_lock: threading.Lock = threading.Lock()` to `Orchestrator.__init__()`. In `_save_checkpoint()`, wrap the full method body (from building the checkpoint dict to `os.replace`) with `with self._checkpoint_lock:`. `_clear_checkpoint()` also acquires the same lock.

## Data Flow

```
ParallelExecutor (N threads)
  └─ _run_stage_safe()
       ├─ _run_stage() → result.add_error()     # acquires result._lock
       ├─ result.completed_stages.append()      # acquires result._lock
       └─ _save_checkpoint()                    # acquires self._checkpoint_lock
```

## Error Handling

- MCP fallback: structured log warning; existing code already handles `mcp_registry = None`
- Lock contention: threads block briefly; no deadlock risk (no nested locks)

## Testing

- `tests/test_pipeline_result_thread_safety.py` (new)
  - `test_add_error_concurrent` — 50 threads call `add_error()` simultaneously; assert `len(errors) == 50`
  - `test_completed_stages_concurrent` — same pattern for `completed_stages`
- `tests/test_orchestrator_mcp_init.py` (new)
  - `test_mcp_init_failure_does_not_crash` — patch `MCPToolRegistry` to raise; assert Orchestrator constructs without error and `mcp_registry` is None
- `tests/test_checkpoint_thread_safety.py` (new)  
  - `test_checkpoint_write_concurrent` — 10 threads call `_save_checkpoint()` simultaneously; assert no exception and final file is valid JSON

## Acceptance Criteria

- [ ] 50-thread stress test on `result.add_error()` produces exactly 50 errors, no duplicates/drops
- [ ] Orchestrator construction succeeds when MCP servers are unreachable
- [ ] Concurrent checkpoint writes produce valid (non-corrupt) checkpoint files
- [ ] All existing tests still pass
