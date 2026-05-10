"""Tests for DLQ exponential backoff (T5-B Task 1).

Verifies that:
- DLQEntry has a retry_after field defaulting to 0.0
- nack() sets retry_after to a future timestamp using exponential backoff
- drain() skips entries whose retry_after is in the future
- InMemoryDeadLetterQueue behaves the same way
"""
import json
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from core.dead_letter import DLQEntry, FileDeadLetterQueue, InMemoryDeadLetterQueue


def _make_entry(attempt=1):
    return DLQEntry(
        id="entry-001",
        issue_number=1,
        tracker_repo="owner/repo",
        label="bug",
        model="gpt-4o",
        num_engineers=2,
        failed_at="2026-05-10T00:00:00Z",
        error={"code": "TIMEOUT"},
        attempt_count=attempt,
    )


def test_dlqentry_has_retry_after_field():
    """DLQEntry must have retry_after: float = 0.0."""
    entry = _make_entry()
    assert hasattr(entry, "retry_after")
    assert entry.retry_after == 0.0


def test_file_dlq_nack_sets_retry_after(tmp_path):
    """FileDeadLetterQueue.nack() writes retry_after > now() to the JSON file."""
    dlq = FileDeadLetterQueue(tmp_path, max_attempts=3)
    entry = _make_entry()
    dlq.enqueue(entry)

    before = time.time()
    dlq.nack(entry.id)

    f = tmp_path / f"{entry.id}.json"
    data = json.loads(f.read_text())
    assert "retry_after" in data
    assert data["retry_after"] > before  # must be in the future


def test_file_dlq_drain_skips_not_yet_due(tmp_path):
    """drain() must not yield entries whose retry_after is in the future."""
    dlq = FileDeadLetterQueue(tmp_path, max_attempts=3)
    entry = _make_entry()
    dlq.enqueue(entry)
    dlq.nack(entry.id)  # sets retry_after = now + 30s

    entries = list(dlq.drain())
    assert len(entries) == 0, "Entry should be skipped (retry_after in future)"


def test_file_dlq_drain_yields_when_due(tmp_path):
    """drain() yields entries whose retry_after <= now."""
    dlq = FileDeadLetterQueue(tmp_path, max_attempts=3)
    f = tmp_path / "entry-002.json"
    data = {
        "id": "entry-002",
        "issue_number": 2,
        "tracker_repo": "owner/repo",
        "label": "bug",
        "model": "gpt-4",
        "num_engineers": 1,
        "failed_at": "2026-01-01T00:00:00Z",
        "error": {},
        "attempt_count": 1,
        "stage_name": "pipeline",
        "target_repo": "",
        "retry_after": 0.0,  # in the past
    }
    f.write_text(json.dumps(data))
    entries = list(dlq.drain())
    assert len(entries) == 1
    assert entries[0].id == "entry-002"


def test_backoff_doubles_per_attempt(tmp_path):
    """retry_after grows exponentially: attempt 2→60s, attempt 3→120s, attempt 4→240s.

    After fixing the off-by-one bug, nack() computes the delay using the NEW
    attempt count (after increment). First nack: old=1 → new=2 → delay=60s.
    """
    dlq = FileDeadLetterQueue(tmp_path, max_attempts=5)
    entry = _make_entry(attempt=1)
    dlq.enqueue(entry)

    t0 = time.time()
    dlq.nack(entry.id)
    f = tmp_path / f"{entry.id}.json"
    data = json.loads(f.read_text())
    delay1 = data["retry_after"] - t0
    assert 55 <= delay1 <= 65, f"Attempt 1→2 delay should be ~60s (new_count=2), got {delay1:.1f}s"


def test_inmemory_dlq_drain_respects_retry_after():
    """InMemoryDeadLetterQueue.drain() skips entries with retry_after in future."""
    dlq = InMemoryDeadLetterQueue()
    entry = _make_entry()
    dlq.enqueue(entry)
    dlq.nack(entry.id)  # sets retry_after
    entries = list(dlq.drain())
    assert len(entries) == 0


@pytest.mark.parametrize("count,expected", [
    (0, 30.0),    # exercises max(1, 0) guard → treated as attempt 1
    (-1, 30.0),   # exercises max(1, -1) guard → treated as attempt 1
    (1, 30.0),
    (2, 60.0),
    (8, 3600.0),
    (100, 3600.0),
])
def test_backoff_delay_boundary_values(count, expected):
    """Verify _backoff_delay returns correct values at boundaries, including the overflow guard and cap."""
    from core.dead_letter import _backoff_delay
    assert _backoff_delay(count) == expected
