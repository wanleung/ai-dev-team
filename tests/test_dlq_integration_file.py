"""Integration test: FileDeadLetterQueue end-to-end round-trip.

Same scenario as InMemory but verifies disk persistence: after nack, the
.json file on disk contains the updated retry_after value; after ack, the
file is deleted.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from core.dead_letter import _backoff_delay, DLQEntry, FileDeadLetterQueue


def _make_entry(suffix: str) -> DLQEntry:
    return DLQEntry(
        id=f"file-entry-{suffix}",
        issue_number=2,
        tracker_repo="owner/tracker",
        label="ai-fix",
        model="gpt-4.1",
        num_engineers=2,
        failed_at="2026-05-10T00:00:00Z",
        error={"message": "file test error"},
    )


def test_file_dlq_full_cycle(tmp_path: Path):
    """Full enqueue → drain → nack → timed drain cycle on File backend."""
    NOW = 2_000_000.0

    dlq = FileDeadLetterQueue(path=tmp_path / "dlq")

    e1 = _make_entry("1")
    e2 = _make_entry("2")
    e3 = _make_entry("3")

    dlq.enqueue(e1)
    dlq.enqueue(e2)
    dlq.enqueue(e3)

    # Drain at NOW: all 3 visible
    with patch("core.dead_letter._time") as mock_time:
        mock_time.time.return_value = NOW
        visible = list(dlq.drain())
    assert len(visible) == 3

    # Nack file-entry-1 at NOW
    with patch("core.dead_letter._time") as mock_time:
        mock_time.time.return_value = NOW
        dlq.nack("file-entry-1")

    # Verify disk: retry_after updated in the JSON file
    dlq_file = tmp_path / "dlq" / "file-entry-1.json"
    assert dlq_file.exists(), "DLQ file must still exist after nack (not at max_attempts yet)"
    disk_data = json.loads(dlq_file.read_text(encoding="utf-8"))
    assert disk_data["attempt_count"] == 2
    assert disk_data["retry_after"] > NOW, "retry_after must be in the future after nack"
    assert disk_data["retry_after"] == NOW + _backoff_delay(2), \
        "retry_after must be NOW + _backoff_delay(2)"

    # Drain at NOW: file-entry-1 hidden (future retry_after)
    with patch("core.dead_letter._time") as mock_time:
        mock_time.time.return_value = NOW
        visible_after_nack = list(dlq.drain())
    assert not any(e.id == "file-entry-1" for e in visible_after_nack)
    assert any(e.id == "file-entry-2" for e in visible_after_nack)

    # Boundary: still hidden one second before backoff window closes
    with patch("core.dead_letter._time") as mock_time:
        mock_time.time.return_value = NOW + _backoff_delay(2) - 1.0
        too_early = list(dlq.drain())
    assert "file-entry-1" not in {e.id for e in too_early}

    # Boundary: visible at exact backoff boundary (inclusive)
    with patch("core.dead_letter._time") as mock_time:
        mock_time.time.return_value = NOW + _backoff_delay(2)
        at_expiry = list(dlq.drain())
    assert "file-entry-1" in {e.id for e in at_expiry}

    # Drain at NOW + 61s: file-entry-1 reappears
    with patch("core.dead_letter._time") as mock_time:
        mock_time.time.return_value = NOW + 61.0
        visible_after_window = list(dlq.drain())
    assert any(e.id == "file-entry-1" for e in visible_after_window)

    # Ack file-entry-1: file deleted from disk
    dlq.ack("file-entry-1")
    assert not dlq_file.exists(), "DLQ file must be deleted after ack"


def test_file_dlq_nack_at_max_attempts_discards(tmp_path: Path):
    """Entry is discarded (file deleted) when nack exceeds max_attempts."""
    dlq = FileDeadLetterQueue(path=tmp_path / "dlq", max_attempts=1)

    entry = _make_entry("max")
    dlq.enqueue(entry)

    dlq_file = tmp_path / "dlq" / "file-entry-max.json"
    assert dlq_file.exists()

    dlq.nack("file-entry-max")  # attempt_count → 2, exceeds max_attempts=1 → discard

    assert not dlq_file.exists(), "Entry must be discarded when max_attempts exceeded"


def test_file_dlq_drain_empty(tmp_path: Path):
    """drain() on an empty directory returns empty list without raising."""
    dlq = FileDeadLetterQueue(path=tmp_path / "empty_dlq")
    with patch("core.dead_letter._time") as mock_time:
        mock_time.time.return_value = 0.0
        result = list(dlq.drain())
    assert result == []
