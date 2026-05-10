"""Integration test: RedisDLQ end-to-end round-trip using fakeredis.

fakeredis does not support Lua eval, so nack() falls through to the Python
RMW path. The test verifies that the Python path produces the same correct
backoff and drain-skip behaviour as the Lua path would on real Redis.

Requires: pip install fakeredis
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

try:
    import fakeredis
except ImportError:
    pytest.skip("fakeredis not installed", allow_module_level=True)

from config_schema import DLQRedisConfig
from core.dead_letter import DLQEntry, RedisDLQ, _backoff_delay


def _make_redis_cfg() -> DLQRedisConfig:
    return DLQRedisConfig(
        url="redis://localhost:6379",  # not used — client is injected
        key="test:dlq",
    )


def _make_entry(suffix: str) -> DLQEntry:
    return DLQEntry(
        id=f"redis-entry-{suffix}",
        issue_number=3,
        tracker_repo="owner/tracker",
        label="ai-fix",
        model="gpt-4.1",
        num_engineers=2,
        failed_at="2026-05-10T00:00:00Z",
        error={"message": "redis test error"},
    )


def _make_dlq() -> RedisDLQ:
    client = fakeredis.FakeRedis()
    return RedisDLQ(cfg=_make_redis_cfg(), max_attempts=5, client=client)


def test_redis_dlq_full_cycle():
    """Full enqueue → drain → nack → timed drain cycle on Redis backend."""
    NOW = 3_000_000.0
    dlq = _make_dlq()

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

    # Nack entry-1 at NOW (falls through to Python RMW since fakeredis has no Lua eval)
    with patch("core.dead_letter._time") as mock_time:
        mock_time.time.return_value = NOW
        dlq.nack("redis-entry-1")

    # Drain at NOW: entry-1 hidden (retry_after in future)
    with patch("core.dead_letter._time") as mock_time:
        mock_time.time.return_value = NOW
        visible_after_nack = list(dlq.drain())
    visible_ids = {e.id for e in visible_after_nack}
    assert "redis-entry-1" not in visible_ids
    assert "redis-entry-2" in visible_ids
    assert "redis-entry-3" in visible_ids

    # one second before expiry — redis-entry-1 still hidden
    with patch("core.dead_letter._time") as mock_time:
        mock_time.time.return_value = NOW + _backoff_delay(2) - 1.0   # one second before boundary
        too_early = list(dlq.drain())
    assert "redis-entry-1" not in {e.id for e in too_early}
    assert "redis-entry-2" in {e.id for e in too_early}
    assert "redis-entry-3" in {e.id for e in too_early}

    # at exact expiry boundary — redis-entry-1 visible
    with patch("core.dead_letter._time") as mock_time:
        mock_time.time.return_value = NOW + _backoff_delay(2)
        at_expiry = list(dlq.drain())
    assert "redis-entry-1" in {e.id for e in at_expiry}


def test_redis_dlq_ack_removes_entry():
    """ack() removes the entry from Redis hash."""
    dlq = _make_dlq()
    entry = _make_entry("ack")
    dlq.enqueue(entry)

    dlq.ack("redis-entry-ack")

    with patch("core.dead_letter._time") as mock_time:
        mock_time.time.return_value = 0.0
        remaining = list(dlq.drain())
    assert not any(e.id == "redis-entry-ack" for e in remaining)


def test_redis_dlq_drain_empty():
    """drain() on an empty Redis hash returns empty list without raising."""
    dlq = _make_dlq()
    with patch("core.dead_letter._time") as mock_time:
        mock_time.time.return_value = 0.0
        result = list(dlq.drain())
    assert result == []


def test_redis_dlq_nack_at_max_attempts_discards():
    """Entry is removed from Redis when nack exceeds max_attempts."""
    NOW = 3_000_000.0
    client = fakeredis.FakeRedis()
    dlq = RedisDLQ(cfg=_make_redis_cfg(), max_attempts=1, client=client)

    entry = _make_entry("maxattempts")
    dlq.enqueue(entry)

    dlq.nack("redis-entry-maxattempts")  # attempt_count → 2, exceeds max_attempts=1 → discard

    with patch("core.dead_letter._time") as mock_time:
        mock_time.time.return_value = NOW + 99999.0
        remaining = list(dlq.drain())
    assert not any(e.id == "redis-entry-maxattempts" for e in remaining)
