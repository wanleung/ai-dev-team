"""Integration tests for Dead Letter Queue retry flow.

Tests the DLQ retry mechanism including enqueueing failed items, retry with
incremented attempt counts, max_attempts enforcement, successful retries,
and state persistence across different backend implementations.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.dead_letter import (
    DLQEntry,
    FileDeadLetterQueue,
    InMemoryDeadLetterQueue,
    NullDeadLetterQueue,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_dlq_entry() -> DLQEntry:
    """Create a sample DLQ entry for testing."""
    return DLQEntry(
        id="test-entry-001",
        issue_number=42,
        tracker_repo="test-org/tracker",
        label="feature",
        model="gpt-4.1",
        num_engineers=3,
        failed_at="2024-01-15T10:30:00Z",
        error={"message": "API timeout", "code": 504},
        target_repo="test-org/target",
        attempt_count=1,
        stage_name="architect",
        retry_after=0.0,
    )


@pytest.fixture
def file_dlq(tmp_path: Path) -> FileDeadLetterQueue:
    """Create a file-based DLQ in a temporary directory."""
    dlq_path = tmp_path / "dlq"
    return FileDeadLetterQueue(dlq_path, max_attempts=3)


@pytest.fixture
def inmemory_dlq() -> InMemoryDeadLetterQueue:
    """Create an in-memory DLQ for testing."""
    return InMemoryDeadLetterQueue()


# ---------------------------------------------------------------------------
# Tests: Basic Operations
# ---------------------------------------------------------------------------


def test_dlq_enqueue_stores_entry(file_dlq: FileDeadLetterQueue, sample_dlq_entry: DLQEntry) -> None:
    """Test that enqueueing an entry stores it persistently."""
    # Enqueue entry
    file_dlq.enqueue(sample_dlq_entry)

    # Verify file was created
    expected_file = file_dlq._file_for(sample_dlq_entry.id)
    assert expected_file.exists()

    # Verify content
    data = json.loads(expected_file.read_text())
    assert data["id"] == sample_dlq_entry.id
    assert data["issue_number"] == sample_dlq_entry.issue_number
    assert data["attempt_count"] == 1


def test_dlq_drain_yields_enqueued_entries(
    file_dlq: FileDeadLetterQueue,
    sample_dlq_entry: DLQEntry,
) -> None:
    """Test that drain yields all enqueued entries."""
    # Enqueue multiple entries
    entry1 = sample_dlq_entry
    entry2 = DLQEntry(
        id="test-entry-002",
        issue_number=43,
        tracker_repo="test-org/tracker",
        label="bugfix",
        model="gpt-4.1",
        num_engineers=2,
        failed_at="2024-01-15T11:00:00Z",
        error={"message": "Connection error"},
        attempt_count=1,
    )

    file_dlq.enqueue(entry1)
    file_dlq.enqueue(entry2)

    # Drain and verify
    entries = list(file_dlq.drain())
    assert len(entries) == 2
    entry_ids = {e.id for e in entries}
    assert "test-entry-001" in entry_ids
    assert "test-entry-002" in entry_ids


def test_dlq_ack_removes_entry(file_dlq: FileDeadLetterQueue, sample_dlq_entry: DLQEntry) -> None:
    """Test that acknowledging an entry removes it from the queue."""
    # Enqueue entry
    file_dlq.enqueue(sample_dlq_entry)
    assert file_dlq._file_for(sample_dlq_entry.id).exists()

    # Acknowledge (successful retry)
    file_dlq.ack(sample_dlq_entry.id)

    # Verify file was deleted
    assert not file_dlq._file_for(sample_dlq_entry.id).exists()

    # Verify drain returns nothing
    entries = list(file_dlq.drain())
    assert len(entries) == 0


# ---------------------------------------------------------------------------
# Tests: Retry Flow with attempt_count
# ---------------------------------------------------------------------------


def test_dlq_nack_increments_attempt_count(
    file_dlq: FileDeadLetterQueue,
    sample_dlq_entry: DLQEntry,
) -> None:
    """Test that nack increments attempt_count for retry."""
    # Enqueue entry with attempt_count=1
    file_dlq.enqueue(sample_dlq_entry)

    # Patch backoff to return 0 so entries are immediately available
    with patch("core.dead_letter._backoff_delay", return_value=0.0):
        # Nack (failed retry)
        file_dlq.nack(sample_dlq_entry.id)

    # Drain and verify attempt_count incremented
    entries = list(file_dlq.drain())
    assert len(entries) == 1
    assert entries[0].attempt_count == 2


def test_dlq_multiple_nacks_increment_count(
    file_dlq: FileDeadLetterQueue,
    sample_dlq_entry: DLQEntry,
) -> None:
    """Test that multiple nacks continue incrementing attempt_count."""
    file_dlq.enqueue(sample_dlq_entry)

    with patch("core.dead_letter._backoff_delay", return_value=0.0):
        # First retry failure
        file_dlq.nack(sample_dlq_entry.id)
        entries = list(file_dlq.drain())
        assert entries[0].attempt_count == 2

        # Second retry failure
        file_dlq.nack(sample_dlq_entry.id)
        entries = list(file_dlq.drain())
        assert entries[0].attempt_count == 3


def test_dlq_exceeding_max_attempts_discards_entry(
    file_dlq: FileDeadLetterQueue,
    sample_dlq_entry: DLQEntry,
) -> None:
    """Test that entries exceeding max_attempts are discarded (DISCARDED state)."""
    # DLQ configured with max_attempts=3
    file_dlq.enqueue(sample_dlq_entry)  # attempt_count=1

    with patch("core.dead_letter._backoff_delay", return_value=0.0):
        # Fail twice more: attempt_count -> 2, then 3
        file_dlq.nack(sample_dlq_entry.id)
        file_dlq.nack(sample_dlq_entry.id)

        # Verify entry still exists at attempt_count=3
        entries = list(file_dlq.drain())
        assert len(entries) == 1
        assert entries[0].attempt_count == 3

        # Fail one more time: attempt_count would be 4, exceeds max_attempts=3
        file_dlq.nack(sample_dlq_entry.id)

    # Verify entry is now DISCARDED (removed from queue)
    entries = list(file_dlq.drain())
    assert len(entries) == 0

    # Verify file was deleted
    assert not file_dlq._file_for(sample_dlq_entry.id).exists()


def test_dlq_successful_retry_after_nack(
    file_dlq: FileDeadLetterQueue,
    sample_dlq_entry: DLQEntry,
) -> None:
    """Test that a successful retry after nack removes the entry."""
    file_dlq.enqueue(sample_dlq_entry)

    with patch("core.dead_letter._backoff_delay", return_value=0.0):
        # First retry fails
        file_dlq.nack(sample_dlq_entry.id)
        entries = list(file_dlq.drain())
        assert len(entries) == 1
        assert entries[0].attempt_count == 2

    # Second retry succeeds
    file_dlq.ack(sample_dlq_entry.id)

    # Verify entry is removed
    entries = list(file_dlq.drain())
    assert len(entries) == 0


# ---------------------------------------------------------------------------
# Tests: InMemoryDLQ Backend
# ---------------------------------------------------------------------------


def test_inmemory_dlq_basic_operations(
    inmemory_dlq: InMemoryDeadLetterQueue,
    sample_dlq_entry: DLQEntry,
) -> None:
    """Test basic enqueue/drain/ack operations on in-memory DLQ."""
    # Enqueue
    inmemory_dlq.enqueue(sample_dlq_entry)

    # Drain
    entries = list(inmemory_dlq.drain())
    assert len(entries) == 1
    assert entries[0].id == sample_dlq_entry.id

    # Ack
    inmemory_dlq.ack(sample_dlq_entry.id)
    entries = list(inmemory_dlq.drain())
    assert len(entries) == 0


def test_inmemory_dlq_nack_with_backoff(
    inmemory_dlq: InMemoryDeadLetterQueue,
    sample_dlq_entry: DLQEntry,
) -> None:
    """Test that in-memory DLQ nack sets retry_after with exponential backoff."""
    inmemory_dlq.enqueue(sample_dlq_entry)

    # Nack and verify retry_after is set in the future
    before_nack = time.time()
    inmemory_dlq.nack(sample_dlq_entry.id)

    # Drain should skip entries not yet due (retry_after > now)
    entries_immediate = list(inmemory_dlq.drain())

    # Verify attempt_count incremented
    # Note: drain filters by retry_after, but we can inspect _store directly
    stored_entry = inmemory_dlq._store.get(sample_dlq_entry.id)
    assert stored_entry is not None
    assert stored_entry.attempt_count == 2
    assert stored_entry.retry_after > before_nack

    # If retry_after is in the future, drain might not yield it yet
    # (depends on backoff delay; for attempt_count=2, backoff is typically small)


def test_inmemory_dlq_retry_after_filtering(inmemory_dlq: InMemoryDeadLetterQueue) -> None:
    """Test that drain filters entries based on retry_after timestamp."""
    # Create entries with different retry_after times
    entry_ready = DLQEntry(
        id="ready",
        issue_number=1,
        tracker_repo="test/repo",
        label="test",
        model="gpt-4.1",
        num_engineers=1,
        failed_at="2024-01-01T00:00:00Z",
        error={},
        retry_after=0.0,  # Available immediately
    )
    entry_future = DLQEntry(
        id="future",
        issue_number=2,
        tracker_repo="test/repo",
        label="test",
        model="gpt-4.1",
        num_engineers=1,
        failed_at="2024-01-01T00:00:00Z",
        error={},
        retry_after=time.time() + 3600,  # 1 hour in the future
    )

    inmemory_dlq.enqueue(entry_ready)
    inmemory_dlq.enqueue(entry_future)

    # Drain should only yield ready entry
    entries = list(inmemory_dlq.drain())
    assert len(entries) == 1
    assert entries[0].id == "ready"


# ---------------------------------------------------------------------------
# Tests: NullDLQ (no-op backend)
# ---------------------------------------------------------------------------


def test_null_dlq_ignores_all_operations(sample_dlq_entry: DLQEntry) -> None:
    """Test that NullDLQ is a no-op backend."""
    null_dlq = NullDeadLetterQueue()

    # Enqueue does nothing
    null_dlq.enqueue(sample_dlq_entry)

    # Drain always returns empty
    entries = list(null_dlq.drain())
    assert len(entries) == 0

    # Ack and nack are no-ops (should not raise)
    null_dlq.ack(sample_dlq_entry.id)
    null_dlq.nack(sample_dlq_entry.id)


# ---------------------------------------------------------------------------
# Tests: State Persistence (File Backend)
# ---------------------------------------------------------------------------


def test_file_dlq_persistence_across_instances(tmp_path: Path, sample_dlq_entry: DLQEntry) -> None:
    """Test that file DLQ state persists across different instances."""
    dlq_path = tmp_path / "dlq_persist"

    # Instance 1: enqueue entry
    dlq1 = FileDeadLetterQueue(dlq_path, max_attempts=3)
    dlq1.enqueue(sample_dlq_entry)

    # Instance 2: drain entry (simulates restart)
    dlq2 = FileDeadLetterQueue(dlq_path, max_attempts=3)
    entries = list(dlq2.drain())
    assert len(entries) == 1
    assert entries[0].id == sample_dlq_entry.id
    assert entries[0].attempt_count == 1


def test_file_dlq_nack_persists_updated_count(tmp_path: Path, sample_dlq_entry: DLQEntry) -> None:
    """Test that nack updates are persisted to disk."""
    dlq_path = tmp_path / "dlq_nack_persist"
    dlq = FileDeadLetterQueue(dlq_path, max_attempts=3)

    dlq.enqueue(sample_dlq_entry)
    dlq.nack(sample_dlq_entry.id)

    # Read file directly to verify persistence
    entry_file = dlq._file_for(sample_dlq_entry.id)
    data = json.loads(entry_file.read_text())
    assert data["attempt_count"] == 2


# ---------------------------------------------------------------------------
# Tests: Edge Cases
# ---------------------------------------------------------------------------


def test_dlq_nack_nonexistent_entry(file_dlq: FileDeadLetterQueue) -> None:
    """Test that nack on non-existent entry is handled gracefully."""
    # Should not raise exception
    file_dlq.nack("nonexistent-id")


def test_dlq_ack_nonexistent_entry(file_dlq: FileDeadLetterQueue) -> None:
    """Test that ack on non-existent entry is handled gracefully."""
    # Should not raise exception
    file_dlq.ack("nonexistent-id")


def test_file_dlq_corrupt_json_skipped(tmp_path: Path, sample_dlq_entry: DLQEntry) -> None:
    """Test that drain skips corrupt JSON files gracefully."""
    dlq_path = tmp_path / "dlq_corrupt"
    dlq = FileDeadLetterQueue(dlq_path, max_attempts=3)

    # Enqueue valid entry
    dlq.enqueue(sample_dlq_entry)

    # Create a corrupt JSON file
    corrupt_file = dlq_path / "corrupt-entry.json"
    corrupt_file.write_text("{ invalid json }", encoding="utf-8")

    # Drain should skip corrupt file and return only valid entry
    entries = list(dlq.drain())
    assert len(entries) == 1
    assert entries[0].id == sample_dlq_entry.id


def test_file_dlq_creates_directory_if_not_exists(tmp_path: Path) -> None:
    """Test that FileDeadLetterQueue creates directory on initialization."""
    dlq_path = tmp_path / "new_dlq_dir"
    assert not dlq_path.exists()

    dlq = FileDeadLetterQueue(dlq_path, max_attempts=3)

    # Verify directory was created
    assert dlq_path.exists()
    assert dlq_path.is_dir()


def test_file_dlq_atomic_write_via_tmp_rename(tmp_path: Path, sample_dlq_entry: DLQEntry) -> None:
    """Test that enqueue uses atomic write (tmp + rename) for safety."""
    dlq_path = tmp_path / "dlq_atomic"
    dlq = FileDeadLetterQueue(dlq_path, max_attempts=3)

    dlq.enqueue(sample_dlq_entry)

    # Verify no .tmp files left behind
    tmp_files = list(dlq_path.glob("*.tmp"))
    assert len(tmp_files) == 0

    # Verify final .json file exists
    json_files = list(dlq_path.glob("*.json"))
    assert len(json_files) == 1


# ---------------------------------------------------------------------------
# Tests: Integration Scenarios
# ---------------------------------------------------------------------------


def test_dlq_full_retry_lifecycle(file_dlq: FileDeadLetterQueue, sample_dlq_entry: DLQEntry) -> None:
    """Test complete DLQ lifecycle: enqueue -> retry failure -> retry success."""
    # Initial failure
    file_dlq.enqueue(sample_dlq_entry)
    assert len(list(file_dlq.drain())) == 1

    with patch("core.dead_letter._backoff_delay", return_value=0.0):
        # First retry fails
        file_dlq.nack(sample_dlq_entry.id)
        entries = list(file_dlq.drain())
        assert len(entries) == 1
        assert entries[0].attempt_count == 2

    # Second retry succeeds
    file_dlq.ack(sample_dlq_entry.id)
    assert len(list(file_dlq.drain())) == 0


def test_dlq_max_attempts_enforcement_scenario(
    file_dlq: FileDeadLetterQueue,
    sample_dlq_entry: DLQEntry,
) -> None:
    """Test realistic scenario where entry hits max_attempts and is discarded."""
    # Enqueue entry (attempt 1)
    file_dlq.enqueue(sample_dlq_entry)

    with patch("core.dead_letter._backoff_delay", return_value=0.0):
        # Simulate 3 retry failures
        for expected_attempt in [2, 3, None]:  # None = discarded after 3rd nack
            file_dlq.nack(sample_dlq_entry.id)
            entries = list(file_dlq.drain())

            if expected_attempt is None:
                # After 3rd nack, attempt_count would be 4, exceeding max_attempts=3
                assert len(entries) == 0  # Entry discarded
            else:
                assert len(entries) == 1
                assert entries[0].attempt_count == expected_attempt


def test_dlq_mixed_operations_multiple_entries(
    file_dlq: FileDeadLetterQueue,
    sample_dlq_entry: DLQEntry,
) -> None:
    """Test DLQ handles multiple entries with mixed operations correctly."""
    entry1 = sample_dlq_entry
    entry2 = DLQEntry(
        id="test-entry-002",
        issue_number=43,
        tracker_repo="test-org/tracker",
        label="bugfix",
        model="gpt-4.1",
        num_engineers=2,
        failed_at="2024-01-15T11:00:00Z",
        error={"message": "Rate limit"},
        attempt_count=2,  # Already retried once
    )
    entry3 = DLQEntry(
        id="test-entry-003",
        issue_number=44,
        tracker_repo="test-org/tracker",
        label="feature",
        model="claude-sonnet-4",
        num_engineers=1,
        failed_at="2024-01-15T12:00:00Z",
        error={"message": "Internal error"},
        attempt_count=1,
    )

    # Enqueue all entries
    file_dlq.enqueue(entry1)
    file_dlq.enqueue(entry2)
    file_dlq.enqueue(entry3)
    assert len(list(file_dlq.drain())) == 3

    # entry1: successful retry
    file_dlq.ack(entry1.id)

    with patch("core.dead_letter._backoff_delay", return_value=0.0):
        # entry2: retry fails (attempt_count: 2 -> 3)
        file_dlq.nack(entry2.id)

        # entry3: retry fails (attempt_count: 1 -> 2)
        file_dlq.nack(entry3.id)

    # Verify state
    entries = list(file_dlq.drain())
    assert len(entries) == 2

    entry_map = {e.id: e for e in entries}
    assert entry2.id in entry_map
    assert entry_map[entry2.id].attempt_count == 3
    assert entry3.id in entry_map
    assert entry_map[entry3.id].attempt_count == 2
