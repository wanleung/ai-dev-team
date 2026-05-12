# T13 Design: Low-Priority Coverage — base_agent, opencode_go, RepoAutoIndexer, refactor_agent, Integration Tests

**Date:** 2026-05-12
**Branch:** `t13-low-priority-coverage`
**PR target:** `master`

---

## Problem Statement

Six low-priority coverage gaps remain after T11–T12:

| Area | Coverage | Key gap |
|---|---|---|
| `agents/base_agent.py` | 85% | Memory injection, tool-call dispatch, MCP session handling |
| `agents/backends/opencode_go.py` | 62% | SSE drain + response assembly (the actual `call()` path) |
| `repo_context.py` | 74% | `RepoAutoIndexer.index()` subprocess path + fallback |
| `agents/refactor_agent.py` | 54% | LLM call + output parsing |
| `tests/integration/` | 2 files | No watcher→dispatch→orchestrator end-to-end test |

T13 closes all five gaps in a single branch.

---

## Task 1: `base_agent.py` Edge Paths

**File:** `tests/test_base_agent_extended.py` (new, or add to existing `test_base_agent.py`)

**Memory injection (lines 174–193):**

1. `test_call_injects_memory_into_prompt` — configure agent with a `memory_store` mock returning 2 entries; call `agent.call(prompt)`; verify memory entries appear in the constructed prompt
2. `test_call_skips_memory_injection_when_store_not_set` — no `memory_store` configured; verify prompt is unchanged
3. `test_call_skips_memory_injection_when_store_empty` — store returns `[]`; verify prompt unchanged

**Tool-call dispatch (lines 296–310):**

4. `test_call_with_tools_dispatches_tool_call` — mock LLM returns a tool-call response; verify the named tool function is called with correct args
5. `test_call_with_tools_returns_tool_result_to_llm` — verify tool result is fed back into the LLM as a follow-up message
6. `test_call_with_tools_raises_on_unknown_tool` — LLM requests tool not in the registry; verify `KeyError` or `ValueError` raised

**MCP session handling (lines 386–395):**

7. `test_build_backend_mcp_session_created` — config includes MCP server URL; verify `MCPSession` is instantiated and passed to backend
8. `test_build_backend_no_mcp_when_not_configured` — no MCP URL in config; verify no `MCPSession` created

---

## Task 2: `opencode_go.py` Call Loop

**File:** `tests/test_opencode_go_backend.py` (new)

**Approach:** Mock the subprocess / HTTP call that `opencode_go.py` makes; exercise the SSE drain and response assembly logic.

1. `test_call_returns_assembled_response` — mock SSE stream yields `{"type": "content", "text": "Hello"}` then `{"type": "done"}`; verify `call()` returns `"Hello"`
2. `test_call_handles_multi_chunk_sse` — stream yields 3 content chunks; verify response is concatenation
3. `test_call_handles_done_without_content` — stream yields only `{"type": "done"}`; verify returns empty string (not error)
4. `test_call_raises_on_subprocess_error` — subprocess exits with non-zero; verify `RuntimeError` or `subprocess.CalledProcessError` raised
5. `test_call_handles_tool_call_event` — stream yields `{"type": "tool_call", ...}` followed by `{"type": "tool_result", ...}`; verify these are passed through or handled per the implementation

---

## Task 3: `RepoAutoIndexer` Coverage

**File:** `tests/test_repo_context_extended.py` (new, or add to `test_repo_context.py`)

1. `test_auto_indexer_runs_subprocess_with_correct_args` — mock `subprocess.run`; construct `RepoAutoIndexer(workspace_dir=str(tmp_path))`; call `.index()`; verify subprocess was called with correct indexer command and workspace path
2. `test_auto_indexer_handles_indexer_not_found` — `subprocess.run` raises `FileNotFoundError`; verify `_log.warning` called and no exception propagates
3. `test_auto_indexer_handles_nonzero_exit` — subprocess returns exit code 1; verify warning logged and no exception propagates
4. `test_orchestrator_auto_indexes_when_rag_configured` — existing test (check it exists); if missing, add: construct orchestrator with `rag_registry` set; verify `RepoAutoIndexer.index()` is called during init or first run

---

## Task 4: `refactor_agent.py` Coverage

**File:** `tests/test_refactor_agent.py` (new, or add to existing)

1. `test_refactor_agent_calls_llm_with_source` — mock LLM; call `agent.run(source_code)`; verify source appears in prompt
2. `test_refactor_agent_returns_refactored_code` — mock returns refactored block; verify `run()` returns it
3. `test_refactor_agent_extracts_code_block` — LLM response wrapped in triple-backticks; verify agent strips the fences and returns clean code
4. `test_refactor_agent_handles_no_code_block` — LLM response has no fences; verify returns raw response (or raises, per actual implementation)
5. `test_refactor_agent_passes_context_to_prompt` — extra context dict is provided; verify context keys appear in prompt sent to LLM

---

## Task 5: Integration Tests

**File:** `tests/integration/test_pipeline_dispatch.py` (new)

**Scope:** Watcher → dispatch → Orchestrator flow, without real GitHub or LLM calls.

**Approach:** Use the existing `TestClient` pattern from `test_deployment.py` for the backend; mock `GithubClient` and `BaseAgent._call_backend`.

**Tests:**

1. `test_watcher_dispatch_creates_orchestrator_run`
   - Construct a `Watcher` with mocked GitHub (returns one open issue with correct pipeline label)
   - Call `_dispatch(issue)` directly
   - Assert: `Orchestrator.run()` is called (mock it); no exception

2. `test_watcher_dispatch_routes_to_correct_pipeline`
   - Issue labelled `ai-docs` → assert `Orchestrator` is constructed with the `ai-docs` pipeline config
   - Issue labelled `ai-standard` → assert `ai-standard.yaml` pipeline config used

3. `test_watcher_dispatch_handles_orchestrator_failure`
   - `Orchestrator.run()` raises `RuntimeError`
   - Assert: watcher catches it, adds `agent-failed` label to issue, does not propagate exception (watcher stays alive)

**File:** `tests/integration/test_dlq_retry_flow.py` (new)

**Tests:**

4. `test_dlq_retries_failed_item`
   - Enqueue a task to the in-memory DLQ
   - Trigger the retry loop
   - Assert: task is retried (callback called again); retry count incremented

5. `test_dlq_discards_after_max_retries`
   - Enqueue a task; set max retries to 2; retry callback always fails
   - Run retry loop 3 times
   - Assert: task is in `DISCARDED` state; `DLQ_DISCARD` event emitted

---

## Task 6: Final Verification

- Run all new test files in isolation
- Run full suite: 0 failures
- Verify `tests/integration/` now has 4 files (was 2)

---

## Acceptance Criteria

- [ ] `base_agent.py` memory injection, tool-call dispatch, and MCP session paths tested
- [ ] `opencode_go.py` SSE drain + response assembly path covered
- [ ] `RepoAutoIndexer.index()` subprocess invocation + error fallback tested
- [ ] `refactor_agent.py` LLM call + code block extraction tested
- [ ] Integration test suite expanded: watcher→dispatch, pipeline routing, DLQ retry flow
- [ ] Full suite: 0 failures
