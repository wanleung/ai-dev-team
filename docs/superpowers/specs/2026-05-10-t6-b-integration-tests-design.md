# T6-B Design: Critical Integration Tests

**Date:** 2026-05-10  
**Branch:** `t6-b-integration-tests`  
**Tier:** T6 — post-merge hardening, second PR

---

## Problem

The test suite covers individual units well but has no integration tests for three runtime-critical paths:

1. **Checkpoint save/resume** — no test verifies that a pipeline interrupted mid-run resumes from the correct stage on restart, not from scratch.
2. **Parallel stage fan-out** — `MAX_PARALLEL_STAGES` and the semaphore cap added in T5-A have no test that exercises concurrent dispatch and completion of multiple stages.
3. **DLQ round-trips** — all three backends (InMemory, File, Redis) have unit tests for individual operations (enqueue, nack, drain) but no test that runs an end-to-end enqueue → nack → backoff → drain → reprocess cycle.

The 30:1 code-to-test ratio means these paths are exercised only in production.

---

## Architecture

Five new test files, one per scenario, all under `tests/`. Each test uses only public APIs and existing fixtures/fakes (fakeredis, `tmp_path`). No orchestrator internals are patched unless strictly necessary for determinism.

---

## Test 1: Checkpoint save/resume

**File:** `tests/test_checkpoint_save_resume.py`

**Scenario:**
1. Create a minimal `Orchestrator` with a 3-stage pipeline: `stage_a`, `stage_b`, `stage_c`.
2. `stage_a` and `stage_b` succeed and write checkpoint files.
3. Simulate a crash by injecting a failure in `stage_b`'s post-checkpoint hook.
4. Restart the orchestrator with the same checkpoint directory.
5. Assert that `stage_a` is skipped (checkpoint present), `stage_b` is re-run (checkpoint incomplete), and `stage_c` runs after.

**Key assertions:**
- `stage_a` function is NOT called on the second run.
- `stage_b` function IS called on the second run.
- Final `PipelineResult` is equivalent to a clean run.

**Implementation notes:**
- Use `tmp_path` fixture for the checkpoint directory.
- Stage functions are `MagicMock` callables; wrap them in lambdas to set expected fields on `result`.
- Inject failure via a flag that the first `stage_b` call checks.

---

## Test 2: Parallel stage fan-out

**File:** `tests/test_parallel_stage_fan_out.py`

**Scenario:**
1. Set `MAX_PARALLEL_STAGES = 2`.
2. Create a pipeline with 4 independent stages, each sleeping 50 ms.
3. Run the pipeline and record concurrency via a threading counter.
4. Assert that at most 2 stages ran simultaneously (semaphore cap respected).
5. Assert that all 4 stages completed.

**Key assertions:**
- `max_concurrent` observed during run ≤ 2.
- All 4 stages reached "done" status.
- Total wall-clock time < 4 × 50 ms (i.e., parallelism actually happened).

**Implementation notes:**
- Use `threading.Event` + counter protected by a lock to track peak concurrency.
- Patch `MAX_PARALLEL_STAGES` in the orchestrator module during the test.
- Use `monkeypatch` or direct attribute override for the semaphore.

---

## Test 3: DLQ integration — InMemory backend

**File:** `tests/test_dlq_integration_inmemory.py`

**Scenario:**
1. Enqueue 3 entries.
2. Drain — all 3 returned.
3. Nack entry #1 (attempt_count=1 → retry_after = now + 30 s).
4. Drain at `now` — entry #1 NOT returned (future retry_after).
5. Advance time to `now + 31 s`.
6. Drain — entry #1 returned again.

**Key assertions:**
- Entry #1 is absent from drain at `now`.
- Entry #1 is present from drain at `now + 31 s`.
- Entries #2 and #3 are always returned (retry_after=0).

**Implementation notes:**
- Use `unittest.mock.patch("time.time", side_effect=[now, now, now + 31.0])` for time control.
- `now` = any fixed float (e.g., 1_000_000.0).

---

## Test 4: DLQ integration — File backend

**File:** `tests/test_dlq_integration_file.py`

**Scenario:** Same end-to-end cycle as Test 3, using `FileDLQ` with `tmp_path`.

**Additional assertions:**
- After nack, the `.dlq` file on disk contains the updated `retry_after` value.
- After final drain, entry #1 is removed from disk.

**Implementation notes:**
- Verify JSON content of the `.dlq` file after nack to confirm persistence.
- Use same time-patching approach as Test 3.

---

## Test 5: DLQ integration — Redis backend

**File:** `tests/test_dlq_integration_redis.py`

**Scenario:** Same end-to-end cycle as Test 3, using `RedisDLQ` with `fakeredis.FakeRedis`.

**Key assertions:**
- Nack falls through to Python RMW path (fakeredis has no Lua eval support).
- Drain correctly skips the future-retry entry.
- Drain returns the entry after time advances.

**Implementation notes:**
- Use `fakeredis.FakeRedis()` — no server required.
- Import `fakeredis` (already a dev dependency from T5-A tests).
- Same time-patching approach as Tests 3 and 4.

---

## Error Handling

| Scenario | Expected behaviour in tests |
|----------|----------------------------|
| Checkpoint file missing | Pipeline re-runs from the beginning — verified by stage call counts |
| Checkpoint file corrupt (invalid JSON) | Orchestrator logs warning, treats as no checkpoint — verify with `caplog` |
| DLQ drain on empty queue | Returns empty list — no exception |
| DLQ nack on unknown entry | Raises `KeyError` or silently no-ops depending on backend — test each |

---

## Constraints

- No new production code — tests only.
- All tests must pass without a running Redis instance (use `fakeredis`).
- All tests must pass without filesystem permissions beyond `tmp_path`.
- Tests may not use `time.sleep()` for synchronisation — use `threading.Event.wait()` or mock time.
- Each test file is independently runnable (`pytest tests/test_<name>.py`).

---

## Success Criteria

- `pytest tests/test_checkpoint_save_resume.py tests/test_parallel_stage_fan_out.py tests/test_dlq_integration_*.py` passes with zero failures.
- No existing tests are broken.
- Each test file documents its scenario in a module-level docstring.
