"""Thread-safety tests for TokenLedger — Task 1 of T5-A concurrency plan."""
import threading
import time

import pytest

from agents.token_ledger import TokenLedger, active_run_id_var, get_ledger, set_ledger


@pytest.fixture(autouse=True)
def _reset_active_run_id_var():
    """Undo any active_run_id_var.set() made directly in the test thread.

    A worker thread spawned with threading.Thread gets its own copy of the
    ContextVar context, so sets made *inside* a spawned thread never leak —
    but a test that calls active_run_id_var.set() directly (simulating what
    Orchestrator._initialize_run() does, without spawning a real thread for
    it) sets it in pytest's own test-running thread, which would otherwise
    leak into every later test sharing that thread.
    """
    token = active_run_id_var.set(None)
    yield
    active_run_id_var.reset(token)


def test_concurrent_record_does_not_raise():
    """50 threads recording simultaneously must not raise or corrupt totals."""
    ledger = TokenLedger()
    run_id = "run-concurrent"
    ledger.start_run(run_id, "proj", "repo")
    errors = []

    def worker(i):
        try:
            ledger.record(run_id, f"stage-{i}", "gpt-4o", 100, 50)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Errors during concurrent record: {errors}"
    summary = ledger.summary(run_id)
    assert summary["total_events"] == 50


def test_concurrent_set_get_ledger():
    """Concurrent set_ledger/get_ledger must not raise."""
    original = get_ledger()
    errors = []

    def swapper():
        try:
            new = TokenLedger()
            set_ledger(new)
            _ = get_ledger()
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=swapper) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    set_ledger(original)
    assert not errors


def test_start_run_idempotent_under_concurrency():
    """Two threads calling start_run with same run_id must not corrupt state."""
    ledger = TokenLedger()
    errors = []

    def starter():
        try:
            ledger.start_run("run-x", "proj", "repo")
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=starter) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors


# ── Concurrent pipelines relying on the implicit run_id fallback ───────────
# The bug this reproduces: BaseAgent.call() never threads an explicit run_id
# down to the backend, so every real LLM call resolves its run_id via
# TokenLedger.active_run_id(). The above tests never exercise that fallback
# — they all pass an explicit run_id, which is not what real agent code
# does. Two pipelines overlapping in the same process (watcher's
# parallel_issues) each need active_run_id() to resolve to *their own*
# run_id, not whichever one happens to have started most recently or
# finished last.

def test_active_run_id_isolated_per_thread_when_two_runs_overlap():
    """Each of two concurrent pipeline threads must see only its own run_id
    from active_run_id() — mirroring what a real LLM call site does when it
    relies on the implicit fallback instead of passing run_id explicitly.
    """
    ledger = TokenLedger()
    seen: dict[str, str | None] = {}
    barrier = threading.Barrier(2)

    def pipeline(run_id: str, key: str):
        ledger.start_run(run_id, "proj", "repo")
        active_run_id_var.set(run_id)
        barrier.wait()  # make sure both runs are active before either reads
        time.sleep(0.05)
        seen[key] = ledger.active_run_id()  # the call a backend makes with no explicit run_id
        ledger.finish_run(run_id)

    t1 = threading.Thread(target=pipeline, args=("run-A", "a"))
    t2 = threading.Thread(target=pipeline, args=("run-B", "b"))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert seen["a"] == "run-A"
    assert seen["b"] == "run-B"


def test_active_run_id_falls_back_to_scan_when_contextvar_unset():
    """A caller outside any pipeline thread (ContextVar never set) still gets
    the old best-effort behaviour rather than None."""
    ledger = TokenLedger()
    ledger.start_run("run-only", "proj", "repo")
    assert ledger.active_run_id() == "run-only"


def test_second_run_finishing_does_not_blank_the_firsts_contextvar_result():
    """Regression for the exact production symptom: once every run in the
    dict-scan fallback has finished, active_run_id() used to return None —
    silently dropping any record() call still in flight. With the
    ContextVar set, a run that's still executing keeps seeing its own id
    even after a sibling run (started later, finished earlier) completes.
    """
    ledger = TokenLedger()
    ledger.start_run("run-first", "proj", "repo")
    active_run_id_var.set("run-first")

    # A second run starts and finishes while the first is still "active"
    # in this thread's context.
    second_ledger_view = ledger  # same ledger, simulating the shared singleton
    second_ledger_view.start_run("run-second", "proj", "repo")
    second_ledger_view.finish_run("run-second")

    # The dict-scan fallback would now return None (nothing left unfinished
    # in this toy scenario, or the wrong id in a real overlapping one) —
    # the ContextVar must still win.
    assert ledger.active_run_id() == "run-first"
