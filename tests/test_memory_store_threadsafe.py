"""Thread-safety tests for MemoryStore (C2 fix).

These tests verify that MemoryStore is safe for concurrent use from multiple
threads, as occurs when parallel_issues > 1 in the orchestrator.
"""
from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest

from memory_store import MemoryStore


@pytest.fixture
def store(tmp_path):
    """MemoryStore backed by a temp file DB; closed after each test."""
    ms = MemoryStore(db_path=tmp_path / "mem.db")
    yield ms
    ms.close()


# ── Lock attribute ─────────────────────────────────────────────────────────────

class TestLockAttribute:
    def test_has_lock_attribute(self, store):
        """MemoryStore must expose a threading.Lock (or RLock) as _lock."""
        assert hasattr(store, "_lock"), "MemoryStore must have a _lock attribute"
        lock = store._lock
        # Must be acquirable and releasable
        lock.acquire()
        lock.release()

    def test_lock_is_lock_type(self, store):
        """_lock must be a real threading primitive, not a plain object."""
        # Both Lock and RLock expose acquire() and release()
        lock = store._lock
        assert callable(getattr(lock, "acquire", None)), "_lock.acquire must be callable"
        assert callable(getattr(lock, "release", None)), "_lock.release must be callable"


# ── WAL mode ──────────────────────────────────────────────────────────────────

class TestWALMode:
    def test_wal_journal_mode_enabled(self, store):
        """WAL mode should be enabled for better concurrent read/write throughput."""
        row = store._conn.execute("PRAGMA journal_mode").fetchone()
        assert row[0].lower() == "wal", f"Expected WAL mode, got {row[0]!r}"


# ── Concurrent saves ──────────────────────────────────────────────────────────

class TestConcurrentSaves:
    def test_concurrent_save_does_not_corrupt(self, store):
        """50 concurrent save() calls must all persist without error or data loss."""
        errors: list[str] = []
        threads: list[threading.Thread] = []

        def do_save(i: int) -> None:
            try:
                store.save(
                    repo="owner/repo",
                    summary=f"run summary {i:04d}",
                    run_id=f"run-{i:04d}",
                    mode="feature",
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"run-{i}: {exc}")

        for i in range(50):
            t = threading.Thread(target=do_save, args=(i,))
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Concurrent saves raised errors: {errors}"

        # All 50 rows must be present in the DB
        count = store._conn.execute(
            "SELECT COUNT(*) FROM runs WHERE repo='owner/repo' AND tier='run'"
        ).fetchone()[0]
        assert count == 50, f"Expected 50 rows, got {count}"

    def test_concurrent_save_to_multiple_repos(self, store):
        """Concurrent saves to different repos must not interfere with each other."""
        errors: list[str] = []
        threads: list[threading.Thread] = []

        def do_save(i: int) -> None:
            repo = f"owner/repo-{i % 5}"
            try:
                store.save(repo=repo, summary=f"summary {i}", run_id=f"run-{i}")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"thread-{i}: {exc}")

        for i in range(40):
            t = threading.Thread(target=do_save, args=(i,))
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Concurrent saves raised errors: {errors}"

        total = store._conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        assert total == 40, f"Expected 40 total rows, got {total}"


# ── Lock is held during save ───────────────────────────────────────────────────

class TestSaveLockUsage:
    def test_save_acquires_and_releases_lock(self, store):
        """save() must enter and exit _lock (via context manager protocol)."""
        from unittest.mock import MagicMock

        real_lock = store._lock
        mock_lock = MagicMock(wraps=real_lock)
        store._lock = mock_lock

        store.save(repo="owner/repo", summary="test save")

        # `with self._lock:` uses __enter__ / __exit__
        mock_lock.__enter__.assert_called()
        mock_lock.__exit__.assert_called()


# ── Lock is held during consolidation DB writes ───────────────────────────────

class TestConsolidateLockUsage:
    def test_consolidate_monthly_holds_lock_during_db_write(self, store):
        """consolidate_monthly() must enter _lock at least once (for DB write)."""
        from unittest.mock import MagicMock

        # Insert some run rows to consolidate
        store.save("owner/repo", "run 1")
        store.save("owner/repo", "run 2")

        real_lock = store._lock
        mock_lock = MagicMock(wraps=real_lock)
        store._lock = mock_lock

        llm_fn = MagicMock(return_value="consolidated monthly summary")
        store.consolidate_monthly("owner/repo", llm_fn)

        mock_lock.__enter__.assert_called()
        mock_lock.__exit__.assert_called()

    def test_consolidate_quarterly_holds_lock_during_db_write(self, store):
        """consolidate_quarterly() must enter _lock at least once (for DB write)."""
        from unittest.mock import MagicMock

        # Insert monthly rows to consolidate
        store.save("owner/repo", "monthly 1", tier="monthly")
        store.save("owner/repo", "monthly 2", tier="monthly")
        store.save("owner/repo", "monthly 3", tier="monthly")

        real_lock = store._lock
        mock_lock = MagicMock(wraps=real_lock)
        store._lock = mock_lock

        llm_fn = MagicMock(return_value="consolidated quarterly summary")
        store.consolidate_quarterly("owner/repo", llm_fn)

        mock_lock.__enter__.assert_called()
        mock_lock.__exit__.assert_called()


# ── TOCTOU race in concurrent consolidation ───────────────────────────────────

def test_concurrent_consolidate_monthly_no_duplicates(store):
    """Two concurrent consolidation calls must not produce duplicate monthly snapshots."""
    import threading

    # Save enough run rows to trigger consolidation (MONTHLY_THRESHOLD = 10)
    for i in range(12):
        store.save(repo="owner/repo", summary=f"run summary {i:04d}", run_id=f"run-{i:04d}")

    start_barrier = threading.Barrier(2)
    # Force both threads to finish the DB-read phase before either proceeds to
    # write, making the TOCTOU window deterministic.
    llm_barrier = threading.Barrier(2)
    results = []

    def slow_llm(prompt: str) -> str:
        llm_barrier.wait(timeout=5)  # ensures both threads have read rows before either writes
        return "consolidated monthly summary"

    def run_consolidate():
        start_barrier.wait()
        result = store.consolidate_monthly("owner/repo", llm_fn=slow_llm)
        results.append(result)

    threads = [threading.Thread(target=run_consolidate) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Verify: exactly 1 monthly snapshot, not 2
    count = store._conn.execute(
        "SELECT COUNT(*) FROM runs WHERE repo='owner/repo' AND tier='monthly'"
    ).fetchone()[0]
    assert count == 1, f"Expected 1 monthly snapshot, got {count}"
