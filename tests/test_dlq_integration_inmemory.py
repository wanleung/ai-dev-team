"""Integration test: InMemoryDeadLetterQueue end-to-end round-trip.

Scenario: enqueue 3 entries → drain (all visible) → nack entry #1
(attempt_count bumps, retry_after set to future) → drain at original time
(entry #1 absent) → drain after retry window (entry #1 visible again).
"""
from __future__ import annotations

from unittest.mock import patch

from core.dead_letter import _backoff_delay, DLQEntry, InMemoryDeadLetterQueue


def _make_entry(suffix: str) -> DLQEntry:
    return DLQEntry(
        id=f"entry-{suffix}",
        issue_number=1,
        tracker_repo="owner/tracker",
        label="ai-fix",
        model="gpt-4.1",
        num_engineers=2,
        failed_at="2026-05-10T00:00:00Z",
        error={"message": "test error"},
    )


def test_inmemory_dlq_full_cycle():
    """Full enqueue → drain → nack → timed drain cycle on InMemory backend."""
    NOW = 1_000_000.0  # fixed epoch for determinism

    dlq = InMemoryDeadLetterQueue()

    e1 = _make_entry("1")
    e2 = _make_entry("2")
    e3 = _make_entry("3")

    # Enqueue all three
    dlq.enqueue(e1)
    dlq.enqueue(e2)
    dlq.enqueue(e3)

    # Drain at NOW: all 3 visible (retry_after=0.0 <= NOW)
    with patch("core.dead_letter._time") as mock_time:
        mock_time.time.return_value = NOW
        visible = list(dlq.drain())
    assert len(visible) == 3
    visible_ids = {e.id for e in visible}
    assert "entry-1" in visible_ids
    assert "entry-2" in visible_ids
    assert "entry-3" in visible_ids

    # Nack entry-1 at NOW → attempt_count becomes 2, retry_after = NOW + 60s
    # backoff for attempt_count=2: 30.0 * 2^(2-1) = 60 seconds
    with patch("core.dead_letter._time") as mock_time:
        mock_time.time.return_value = NOW
        dlq.nack("entry-1")

    # Verify internal state was mutated correctly
    assert dlq._store["entry-1"].attempt_count == 2, \
        "attempt_count must be incremented by nack"
    assert dlq._store["entry-1"].retry_after == NOW + _backoff_delay(2), \
        "retry_after must be set to NOW + _backoff_delay(2) = 60s"

    # Pin the exact backoff boundary: still hidden one second before, visible at exact expiry
    with patch("core.dead_letter._time") as mock_time:
        mock_time.time.return_value = NOW + _backoff_delay(2) - 1.0
        too_early = list(dlq.drain())
    assert "entry-1" not in {e.id for e in too_early}, \
        "entry-1 must still be hidden 1s before the backoff window closes"

    with patch("core.dead_letter._time") as mock_time:
        mock_time.time.return_value = NOW + _backoff_delay(2)
        at_expiry = list(dlq.drain())
    assert "entry-1" in {e.id for e in at_expiry}, \
        "entry-1 must be eligible exactly at retry_after (inclusive boundary)"

    # Drain at NOW: entry-1 is in the future (retry_after > NOW), should be absent
    with patch("core.dead_letter._time") as mock_time:
        mock_time.time.return_value = NOW
        visible_after_nack = list(dlq.drain())
    visible_ids_after_nack = {e.id for e in visible_after_nack}
    assert "entry-1" not in visible_ids_after_nack, "entry-1 must be hidden during backoff window"
    assert "entry-2" in visible_ids_after_nack
    assert "entry-3" in visible_ids_after_nack

    # Drain at NOW + 61s: entry-1 retry window expired (retry_after = NOW + 60s)
    with patch("core.dead_letter._time") as mock_time:
        mock_time.time.return_value = NOW + 61.0
        visible_after_window = list(dlq.drain())
    visible_ids_after_window = {e.id for e in visible_after_window}
    assert "entry-1" in visible_ids_after_window, "entry-1 must reappear after retry window"
    assert "entry-2" in visible_ids_after_window
    assert "entry-3" in visible_ids_after_window


def test_inmemory_dlq_ack_removes_entry():
    """ack() removes the entry from the queue permanently."""
    dlq = InMemoryDeadLetterQueue()
    entry = _make_entry("ack")
    dlq.enqueue(entry)

    dlq.ack("entry-ack")

    with patch("core.dead_letter._time") as mock_time:
        mock_time.time.return_value = 0.0
        remaining = list(dlq.drain())
    assert not any(e.id == "entry-ack" for e in remaining)


def test_inmemory_dlq_drain_empty():
    """drain() on an empty queue returns an empty iterator without raising."""
    dlq = InMemoryDeadLetterQueue()
    with patch("core.dead_letter._time") as mock_time:
        mock_time.time.return_value = 0.0
        result = list(dlq.drain())
    assert result == []
