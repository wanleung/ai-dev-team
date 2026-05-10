# T5-A: Concurrency & Resource Safety — Design Spec

**Date:** 2026-05-10
**Status:** Approved

## Problem

Four post-T4 concurrency and resource safety gaps remain:

1. `TokenLedger` mutates shared dicts (`_runs`, `_events`, `_totals`) without a lock — concurrent pipelines corrupt each other.
2. Timed-out stages leave `ThreadPoolExecutor` threads running forever — zombie threads accumulate unboundedly.
3. `RedisDLQ.nack()` uses `hget → hset` which is non-atomic — concurrent nacks on the same entry undercount attempts.
4. Parallel stage groups create `ThreadPoolExecutor(max_workers=len(runnable))` with no upper bound — large pipeline YAML can spawn unbounded threads.

---

## Design

### 1. Thread-Safe TokenLedger

**Problem:** `TokenLedger` instance methods mutate `self._runs`, `self._events`, and `self._totals` without any lock. The global `_ledger` / `set_ledger()` pattern also has no synchronisation.

**Fix:**
- Add `self._lock: threading.Lock = threading.Lock()` to `TokenLedger.__init__()`.
- Wrap every method that reads or writes `_runs`, `_events`, or `_totals` with `with self._lock:` — this covers `start_run()`, `record()`, `finish_run()`, `summary()`, and `export_csv()`.
- Add a module-level `_ledger_lock: threading.Lock = threading.Lock()` in `agents/token_ledger.py`.
- Wrap `get_ledger()` and `set_ledger()` with `with _ledger_lock:`.
- `BudgetExceededError` is raised inside `record()` while the lock is held — this is safe because `Lock` is non-reentrant and the error propagates out before any re-entry.

**Scope:** `agents/token_ledger.py` only.

### 2. Zombie Thread Tracking

**Problem:** When a stage exceeds its timeout, `_run_stage()` calls `executor.shutdown(wait=False)` and moves on — but the background thread continues running until the LLM call returns. Over a long-running process, these threads accumulate.

**Fix (pragmatic — Python cannot kill threads):**
- Add a module-level `_leaked_threads: list[threading.Thread]` and `_leaked_thread_lock: threading.Lock` in `orchestrator.py`.
- Before `executor.shutdown(wait=False)`, retrieve the running thread from the executor internals (`executor._threads`) and append it to `_leaked_threads` with a label `f"{stage_name}@{time.monotonic():.0f}"`.
- Log at `WARNING` level: `"Stage '{name}' timed out — background thread running. Leaked thread count: {n}"`.
- Add `get_leaked_thread_count() -> int` helper (used in tests and surfaced in `_log_final_summary()`).
- **No behaviour change** — the thread still runs to completion (LLM call can't be cancelled). Tracking gives operators visibility.

**Scope:** `orchestrator.py` only.

### 3. Atomic Redis DLQ nack

**Problem:** `RedisDLQ.nack()` does `hget → mutate → hset` — not atomic. Two concurrent nacks on the same `entry_id` produce a race.

**Fix:**
- Replace the Python-level read-modify-write with a Redis Lua script that runs atomically on the server.
- The script: if the entry exists, increment `attempt_count`; if it exceeds `max_attempts`, delete it; else write back.
- Use `redis.eval(LUA_NACK_SCRIPT, 1, key, entry_id, max_attempts)`.
- Fall back to the existing non-atomic path if `eval` raises `ResponseError` (e.g. Redis Cluster script routing).
- No change to `FileDeadLetterQueue.nack()` — it already uses atomic `tmp → rename`.

**Scope:** `core/dead_letter.py` only.

### 4. Cap Parallel Stage Workers

**Problem:** `ThreadPoolExecutor(max_workers=len(runnable))` — if a pipeline YAML defines 20 parallel stages, 20 threads are spawned simultaneously.

**Fix:**
- Add `MAX_PARALLEL_STAGES: int = int(os.getenv("AI_MAX_PARALLEL_STAGES", "8"))` as a module-level constant in `orchestrator.py`.
- Change line 2436 to: `ThreadPoolExecutor(max_workers=min(len(runnable), MAX_PARALLEL_STAGES))`.
- No other `ThreadPoolExecutor` sites changed (they use `self.num_engineers` / `self.num_senior_engineers` which are already config-driven).

**Scope:** `orchestrator.py` only.

---

## Files Modified

| File | Change |
|------|--------|
| `agents/token_ledger.py` | Add `_lock` to `TokenLedger`; add `_ledger_lock` module global |
| `orchestrator.py` | Add `_leaked_threads` tracker; add `MAX_PARALLEL_STAGES` cap |
| `core/dead_letter.py` | Replace `RedisDLQ.nack()` with Lua atomic script |

---

## Tests

- `tests/test_token_ledger_thread_safety.py` — 50-thread concurrent `record()` stress test; concurrent `set_ledger()`/`get_ledger()` test
- `tests/test_zombie_thread_tracking.py` — mock timeout path; assert leaked thread count increments and warning is logged
- `tests/test_redis_dlq_atomic_nack.py` — mock `redis.eval`; assert Lua script called; assert fallback path on `ResponseError`
- `tests/test_parallel_stage_cap.py` — assert `max_workers=min(n, MAX_PARALLEL_STAGES)` via mock executor

---

## Non-Goals

- Cancelling LLM HTTP calls mid-flight (not possible without aiohttp/asyncio refactor)
- SQS or File DLQ atomicity changes (already safe)
- Changes to `_save_checkpoint()` (already protected by T4-A `_checkpoint_lock`)
