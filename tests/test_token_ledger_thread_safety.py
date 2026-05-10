"""Thread-safety tests for TokenLedger — Task 1 of T5-A concurrency plan."""
import threading
from agents.token_ledger import TokenLedger, get_ledger, set_ledger


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
