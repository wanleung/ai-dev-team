"""Tests for DeadLetterQueue backends."""
from __future__ import annotations
import json
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch, call as mcall
import pytest

from config_schema import DLQConfig, DLQFileConfig, DLQRedisConfig, DLQSQSConfig
from core.dead_letter import (
    DLQEntry,
    FileDeadLetterQueue,
    NullDeadLetterQueue,
    RedisDLQ,
    SQSDeadLetterQueue,
    build_dlq,
)
from core.events import DLQEvent, set_emit_callback, reset_emit_callback


def _entry(**kwargs) -> DLQEntry:
    defaults = dict(
        id=str(uuid.uuid4()),
        issue_number=1,
        tracker_repo="owner/repo",
        label="feature-request",
        model="gpt-4.1",
        num_engineers=2,
        failed_at="2026-05-08T12:00:00Z",
        error={"code": "AGENT_TIMEOUT", "stage": "architect", "message": "timed out",
               "severity": "error", "timestamp": "2026-05-08T12:00:00Z", "context": {}},
    )
    defaults.update(kwargs)
    return DLQEntry(**defaults)


# ── FileDeadLetterQueue ────────────────────────────────────────────────────────

def test_file_dlq_enqueue_writes_json(tmp_path):
    dlq = FileDeadLetterQueue(tmp_path)
    e = _entry()
    dlq.enqueue(e)
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text())
    assert data["id"] == e.id
    assert data["issue_number"] == 1


def test_file_dlq_drain_yields_all(tmp_path):
    dlq = FileDeadLetterQueue(tmp_path)
    e1 = _entry(issue_number=1)
    e2 = _entry(issue_number=2)
    dlq.enqueue(e1)
    dlq.enqueue(e2)
    drained = list(dlq.drain())
    assert len(drained) == 2
    numbers = {e.issue_number for e in drained}
    assert numbers == {1, 2}


def test_file_dlq_ack_removes_file(tmp_path):
    dlq = FileDeadLetterQueue(tmp_path)
    e = _entry()
    dlq.enqueue(e)
    assert len(list(tmp_path.glob("*.json"))) == 1
    dlq.ack(e.id)
    assert len(list(tmp_path.glob("*.json"))) == 0


def test_file_dlq_nack_increments_attempt_count(tmp_path):
    dlq = FileDeadLetterQueue(tmp_path)
    e = _entry()
    dlq.enqueue(e)
    dlq.nack(e.id)
    files = list(tmp_path.glob("*.json"))
    data = json.loads(files[0].read_text())
    assert data["attempt_count"] == 2


def test_file_dlq_drain_empty(tmp_path):
    dlq = FileDeadLetterQueue(tmp_path)
    assert list(dlq.drain()) == []


def test_file_dlq_creates_dir(tmp_path):
    path = tmp_path / "sub" / "dlq"
    dlq = FileDeadLetterQueue(path)
    e = _entry()
    dlq.enqueue(e)
    assert path.exists()


# ── NullDeadLetterQueue ────────────────────────────────────────────────────────

def test_null_dlq_enqueue_is_noop():
    dlq = NullDeadLetterQueue()
    dlq.enqueue(_entry())  # should not raise


def test_null_dlq_drain_is_empty():
    dlq = NullDeadLetterQueue()
    assert list(dlq.drain()) == []


def test_null_dlq_ack_nack_are_noop():
    dlq = NullDeadLetterQueue()
    dlq.ack("any-id")
    dlq.nack("any-id")


# ── SQSDeadLetterQueue ────────────────────────────────────────────────────────

def test_sqs_dlq_enqueue_calls_send_message():
    mock_sqs = MagicMock()
    cfg = DLQSQSConfig(queue_url="https://sqs.eu-west-1.amazonaws.com/123/test")
    dlq = SQSDeadLetterQueue(cfg, client=mock_sqs)
    e = _entry()
    dlq.enqueue(e)
    mock_sqs.send_message.assert_called_once()
    kwargs = mock_sqs.send_message.call_args[1]
    assert kwargs["QueueUrl"] == cfg.queue_url
    payload = json.loads(kwargs["MessageBody"])
    assert payload["id"] == e.id


def test_sqs_dlq_drain_yields_entries():
    mock_sqs = MagicMock()
    e = _entry()
    mock_sqs.receive_message.side_effect = [
        {"Messages": [{"Body": json.dumps(e.__dict__), "ReceiptHandle": "rh-1"}]},
        {"Messages": []},
    ]
    cfg = DLQSQSConfig(queue_url="https://sqs.eu-west-1.amazonaws.com/123/test")
    dlq = SQSDeadLetterQueue(cfg, client=mock_sqs)
    drained = list(dlq.drain())
    assert len(drained) == 1
    assert drained[0].id == e.id


def test_sqs_dlq_ack_deletes_message():
    mock_sqs = MagicMock()
    e = _entry()
    mock_sqs.receive_message.side_effect = [
        {"Messages": [{"Body": json.dumps(e.__dict__), "ReceiptHandle": "rh-1"}]},
        {"Messages": []},
    ]
    cfg = DLQSQSConfig(queue_url="https://sqs.eu-west-1.amazonaws.com/123/test")
    dlq = SQSDeadLetterQueue(cfg, client=mock_sqs)
    list(dlq.drain())  # populates internal receipt handle map
    dlq.ack(e.id)
    mock_sqs.delete_message.assert_called_once_with(
        QueueUrl=cfg.queue_url, ReceiptHandle="rh-1"
    )


# ── build_dlq factory ─────────────────────────────────────────────────────────

def test_build_dlq_disabled_returns_null(tmp_path):
    cfg = DLQConfig(enabled=False)
    dlq = build_dlq(cfg, workspace_root=tmp_path)
    assert isinstance(dlq, NullDeadLetterQueue)


def test_build_dlq_file_returns_file_dlq(tmp_path):
    cfg = DLQConfig(enabled=True, backend="file", file=DLQFileConfig(path=str(tmp_path / "dlq")))
    dlq = build_dlq(cfg, workspace_root=tmp_path)
    assert isinstance(dlq, FileDeadLetterQueue)


# ── New tests ─────────────────────────────────────────────────────────────────

def test_file_enqueue_atomic(tmp_path):
    """No .tmp files should remain after enqueue completes."""
    dlq = FileDeadLetterQueue(tmp_path)
    e = _entry()
    dlq.enqueue(e)
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert tmp_files == [], f"Unexpected .tmp files left behind: {tmp_files}"
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_file_nack_max_attempts_discards(tmp_path):
    """Entry file should be deleted once attempt_count exceeds max_attempts."""
    dlq = FileDeadLetterQueue(tmp_path, max_attempts=3)
    e = _entry()
    dlq.enqueue(e)
    # nack 3 times — at attempt_count=4 (>3) the file should be gone
    dlq.nack(e.id)  # attempt_count → 2
    dlq.nack(e.id)  # attempt_count → 3
    dlq.nack(e.id)  # attempt_count → 4 > max_attempts=3, file deleted
    assert not (tmp_path / f"{e.id}.json").exists()


def test_sqs_nack_increments_attempt_count():
    """After drain + nack, the re-enqueued message body has attempt_count + 1."""
    mock_sqs = MagicMock()
    e = _entry(attempt_count=1)
    mock_sqs.receive_message.side_effect = [
        {"Messages": [{"Body": json.dumps(e.__dict__), "ReceiptHandle": "rh-1"}]},
        {"Messages": []},
    ]
    cfg = DLQSQSConfig(queue_url="https://sqs.eu-west-1.amazonaws.com/123/test")
    dlq = SQSDeadLetterQueue(cfg, client=mock_sqs)
    list(dlq.drain())
    dlq.nack(e.id)

    # delete_message should be called once for the original message
    mock_sqs.delete_message.assert_called_once_with(
        QueueUrl=cfg.queue_url, ReceiptHandle="rh-1"
    )
    # send_message should be called once with incremented attempt_count
    mock_sqs.send_message.assert_called_once()
    body = json.loads(mock_sqs.send_message.call_args[1]["MessageBody"])
    assert body["attempt_count"] == 2


def test_sqs_corrupt_message_deleted():
    """A message with invalid JSON body must be deleted to prevent re-delivery loops."""
    mock_sqs = MagicMock()
    mock_sqs.receive_message.side_effect = [
        {"Messages": [{"Body": "not-valid-json", "ReceiptHandle": "rh-corrupt"}]},
        {"Messages": []},
    ]
    cfg = DLQSQSConfig(queue_url="https://sqs.eu-west-1.amazonaws.com/123/test")
    dlq = SQSDeadLetterQueue(cfg, client=mock_sqs)
    entries = list(dlq.drain())
    assert entries == []
    mock_sqs.delete_message.assert_called_once_with(
        QueueUrl=cfg.queue_url, ReceiptHandle="rh-corrupt"
    )


def test_sqs_drain_clears_stale_handles():
    """receipt_handles should only contain handles from the most recent drain call."""
    mock_sqs = MagicMock()
    e1 = _entry()
    e2 = _entry()
    # First drain yields e1; second drain yields e2
    mock_sqs.receive_message.side_effect = [
        {"Messages": [{"Body": json.dumps(e1.__dict__), "ReceiptHandle": "rh-stale"}]},
        {"Messages": []},
        {"Messages": [{"Body": json.dumps(e2.__dict__), "ReceiptHandle": "rh-fresh"}]},
        {"Messages": []},
    ]
    cfg = DLQSQSConfig(queue_url="https://sqs.eu-west-1.amazonaws.com/123/test")
    dlq = SQSDeadLetterQueue(cfg, client=mock_sqs)
    list(dlq.drain())  # first drain — populates e1 handle
    list(dlq.drain())  # second drain — should clear stale and only have e2
    assert e1.id not in dlq._receipt_handles
    assert dlq._receipt_handles.get(e2.id) == "rh-fresh"


def test_build_dlq_redis_backend(tmp_path):
    """build_dlq should return RedisDLQ when backend='redis'."""
    mock_redis_client = MagicMock()
    cfg = DLQConfig(
        enabled=True,
        backend="redis",
        redis=DLQRedisConfig(url="redis://localhost:6379", key="dlq:test"),
    )
    with patch("core.dead_letter.RedisDLQ.__init__", return_value=None) as mock_init:
        # Patch __init__ so we don't need a live Redis; check the class is instantiated
        dlq = build_dlq(cfg, workspace_root=tmp_path)
        mock_init.assert_called_once()
    # Alternatively, use a real client injection
    cfg2 = DLQConfig(
        enabled=True,
        backend="redis",
        redis=DLQRedisConfig(url="redis://localhost:6379", key="dlq:test"),
    )
    dlq2 = RedisDLQ(cfg2.redis, client=mock_redis_client, max_attempts=cfg2.max_attempts)
    assert isinstance(dlq2, RedisDLQ)


def test_build_dlq_returns_redis_dlq_for_redis_backend():
    """build_dlq() must return the O(1) hash-based RedisDLQ, not the old list-based class."""
    from core.dead_letter import build_dlq, RedisDLQ
    from config_schema import DLQConfig, DLQRedisConfig

    cfg = DLQConfig(
        enabled=True,
        backend="redis",
        redis=DLQRedisConfig(url="redis://localhost", key="test", ttl_s=None),
    )
    dlq = build_dlq(cfg)
    assert isinstance(dlq, RedisDLQ)


def test_build_dlq_unknown_backend_raises(tmp_path):
    """build_dlq should raise ValueError for an unrecognised backend name."""
    # Use model_construct to bypass Pydantic's Literal validator so the
    # ValueError in build_dlq itself is exercised.
    cfg = DLQConfig.model_construct(enabled=True, backend="kafka")
    with pytest.raises(ValueError, match="Unknown DLQ backend"):
        build_dlq(cfg, workspace_root=tmp_path)


def test_sqs_ack_expired_handle_no_raise():
    """SQS ack: if delete_message raises (expired handle), exception should be swallowed gracefully."""
    mock_sqs = MagicMock()
    mock_sqs.delete_message.side_effect = Exception("stale handle")
    
    e = _entry()
    mock_sqs.receive_message.side_effect = [
        {"Messages": [{"Body": json.dumps(e.__dict__), "ReceiptHandle": "rh-expired"}]},
        {"Messages": []},
    ]
    cfg = DLQSQSConfig(queue_url="https://sqs.eu-west-1.amazonaws.com/123/test")
    dlq = SQSDeadLetterQueue(cfg, client=mock_sqs)
    list(dlq.drain())  # populates internal receipt handle map
    
    # This should NOT raise an exception
    dlq.ack(e.id)
    
    # Verify delete_message was attempted
    mock_sqs.delete_message.assert_called_once_with(
        QueueUrl=cfg.queue_url, ReceiptHandle="rh-expired"
    )


def test_sqs_drain_drops_unknown_fields():
    """SQS drain: extra fields in message body must not raise TypeError or cause data loss."""
    mock_sqs = MagicMock()
    e = _entry()
    body = {**e.__dict__, "future_field": "unexpected", "another_unknown": 42}
    mock_sqs.receive_message.side_effect = [
        {"Messages": [{"Body": json.dumps(body), "ReceiptHandle": "rh-unknown"}]},
        {"Messages": []},
    ]
    cfg = DLQSQSConfig(queue_url="https://sqs.eu-west-1.amazonaws.com/123/test")
    dlq = SQSDeadLetterQueue(cfg, client=mock_sqs)
    drained = list(dlq.drain())
    assert len(drained) == 1, "Entry with unknown fields should still be yielded"
    assert drained[0].id == e.id


# ── RedisDLQ (hash-based O(1) backend) ───────────────────────────────────────

import fakeredis


def _make_entry(entry_id: str = "e1") -> DLQEntry:
    return DLQEntry(
        id=entry_id,
        issue_number=1,
        tracker_repo="owner/repo",
        label="ai-dev",
        model="gpt-4o",
        num_engineers=1,
        failed_at="2026-01-01T00:00:00Z",
        error={"message": "boom"},
    )


def _make_redis_dlq(max_attempts: int = 3) -> RedisDLQ:
    cfg = DLQRedisConfig(url="redis://localhost", key="test_dlq", ttl_s=None)
    client = fakeredis.FakeRedis()
    return RedisDLQ(cfg, max_attempts=max_attempts, client=client)


def test_redis_dlq_ack_is_o1():
    """ack() removes exactly the targeted entry without scanning others."""
    dlq = _make_redis_dlq()
    e1 = _make_entry("e1")
    e2 = _make_entry("e2")
    dlq.enqueue(e1)
    dlq.enqueue(e2)

    dlq.ack("e1")

    remaining = list(dlq.drain())
    assert len(remaining) == 1
    assert remaining[0].id == "e2"


def test_redis_dlq_nack_increments_attempt_count():
    dlq = _make_redis_dlq(max_attempts=3)
    entry = _make_entry("e1")
    dlq.enqueue(entry)

    # fakeredis does not support Lua eval, so nack() falls back to the Python
    # read-modify-write path which sets retry_after = time.time() + backoff.
    # Freeze time so that:
    #   • nack sees t=0  → retry_after = 0 + 60 = 60
    #   • drain sees t=86400 → 60 ≤ 86400, entry is immediately drainable
    with patch("core.dead_letter._time") as mock_time:
        mock_time.time.side_effect = [0.0, 86400.0]
        dlq.nack("e1")
        items = list(dlq.drain())

    assert len(items) == 1
    assert items[0].attempt_count == 2


def test_redis_dlq_nack_drops_entry_when_max_attempts_exceeded():
    dlq = _make_redis_dlq(max_attempts=2)
    entry = _make_entry("e1")
    dlq.enqueue(entry)
    dlq.nack("e1")   # attempt_count → 2 (== max_attempts, still kept)
    dlq.nack("e1")   # attempt_count → 3 (> max_attempts, drop)

    assert list(dlq.drain()) == []


def test_redis_dlq_ack_unknown_id_is_noop():
    dlq = _make_redis_dlq()
    dlq.enqueue(_make_entry("e1"))
    dlq.ack("nonexistent")   # must not raise
    assert len(list(dlq.drain())) == 1


def test_redis_dlq_nack_unknown_id_is_noop():
    dlq = _make_redis_dlq()
    dlq.enqueue(_make_entry("e1"))
    dlq.nack("nonexistent")   # must not raise
    assert len(list(dlq.drain())) == 1


# ── DLQ event emission ────────────────────────────────────────────────────────


def test_dlq_enqueue_emits_event(tmp_path):
    events = []
    set_emit_callback(events.append)
    try:
        cfg = DLQConfig(enabled=True, backend="file", file=DLQFileConfig(path=str(tmp_path / "dlq")))
        dlq = build_dlq(cfg, workspace_root=tmp_path)
        entry = DLQEntry(id="e1", issue_number=1, tracker_repo="r", label="ai-dev",
                         model="gpt-4o", num_engineers=1, failed_at="2026-01-01T00:00:00Z",
                         error={"msg": "fail"})
        dlq.enqueue(entry)
        assert any(isinstance(e, DLQEvent) and e.action == "enqueue" and e.entry_id == "e1"
                   for e in events), f"Expected enqueue event, got: {events}"
    finally:
        reset_emit_callback()


def test_dlq_ack_emits_event(tmp_path):
    events = []
    set_emit_callback(events.append)
    try:
        cfg = DLQConfig(enabled=True, backend="file", file=DLQFileConfig(path=str(tmp_path / "dlq")))
        dlq = build_dlq(cfg, workspace_root=tmp_path)
        entry = DLQEntry(id="e2", issue_number=2, tracker_repo="r", label="ai-dev",
                         model="gpt-4o", num_engineers=1, failed_at="2026-01-01T00:00:00Z",
                         error={})
        dlq.enqueue(entry)
        events.clear()
        dlq.ack("e2")
        assert any(isinstance(e, DLQEvent) and e.action == "ack" and e.entry_id == "e2"
                   for e in events), f"Expected ack event, got: {events}"
    finally:
        reset_emit_callback()


def _make_file_dlq_and_entry(tmp_path, entry_id="e1"):
    cfg = DLQConfig(enabled=True, backend="file", file=DLQFileConfig(path=str(tmp_path / "dlq")))
    dlq = build_dlq(cfg, workspace_root=tmp_path)
    entry = DLQEntry(id=entry_id, issue_number=1, tracker_repo="r", label="ai-dev",
                     model="gpt-4o", num_engineers=1, failed_at="2026-01-01T00:00:00Z",
                     error={})
    return dlq, entry


def test_file_dlq_nack_emits_event_update_path(tmp_path):
    """nack emits when entry survives (attempt_count < max_attempts)."""
    events = []
    set_emit_callback(events.append)
    try:
        dlq, entry = _make_file_dlq_and_entry(tmp_path)
        dlq.enqueue(entry)
        events.clear()
        dlq.nack(entry.id)
        assert any(isinstance(e, DLQEvent) and e.action == "nack" and e.entry_id == entry.id
                   for e in events), f"Expected nack event, got: {events}"
    finally:
        reset_emit_callback()


def test_file_dlq_nack_emits_event_discard_path(tmp_path):
    """nack emits even when entry is discarded (attempt_count > max_attempts)."""
    events = []
    set_emit_callback(events.append)
    try:
        dlq = FileDeadLetterQueue(Path(tmp_path / "dlq"), max_attempts=1)
        entry = DLQEntry(id="discard", issue_number=1, tracker_repo="r", label="ai-dev",
                         model="gpt-4o", num_engineers=1, failed_at="2026-01-01T00:00:00Z",
                         error={}, attempt_count=1)
        dlq.enqueue(entry)
        dlq.nack(entry.id)  # attempt_count → 2 > max_attempts=1 → discard
        events.clear()
        # enqueue fresh entry to test the discard path specifically
        entry2 = DLQEntry(id="discard2", issue_number=2, tracker_repo="r", label="ai-dev",
                          model="gpt-4o", num_engineers=1, failed_at="2026-01-01T00:00:00Z",
                          error={}, attempt_count=1)
        dlq.enqueue(entry2)
        dlq.nack(entry2.id)  # discard path
        assert any(isinstance(e, DLQEvent) and e.action == "nack" and e.entry_id == "discard2"
                   for e in events), f"Expected nack event on discard path, got: {events}"
    finally:
        reset_emit_callback()


def test_redis_dlq_enqueue_emits_event():
    """redis backend emits enqueue event with backend='redis'."""
    events = []
    set_emit_callback(events.append)
    try:
        dlq = _make_redis_dlq()
        entry = _make_entry("redis-e1")
        dlq.enqueue(entry)
        assert any(isinstance(e, DLQEvent) and e.action == "enqueue"
                   and e.entry_id == "redis-e1" and e.backend == "redis"
                   for e in events), f"Expected redis enqueue event, got: {events}"
    finally:
        reset_emit_callback()


def test_redis_dlq_ack_emits_event():
    """redis backend emits ack event."""
    events = []
    set_emit_callback(events.append)
    try:
        dlq = _make_redis_dlq()
        dlq.enqueue(_make_entry("redis-e2"))
        events.clear()
        dlq.ack("redis-e2")
        assert any(isinstance(e, DLQEvent) and e.action == "ack" and e.entry_id == "redis-e2"
                   for e in events), f"Expected redis ack event, got: {events}"
    finally:
        reset_emit_callback()


def test_redis_dlq_ack_unknown_id_emits_no_event():
    """redis ack() on unknown entry_id must not emit a phantom event."""
    events = []
    set_emit_callback(events.append)
    try:
        dlq = _make_redis_dlq()
        dlq.ack("nonexistent-id")
        assert not any(isinstance(e, DLQEvent) and e.action == "ack" for e in events), \
            f"Expected no ack event for unknown id, got: {events}"
    finally:
        reset_emit_callback()


def test_redis_dlq_nack_emits_event():
    """redis backend emits nack event with correct attempt_count."""
    events = []
    set_emit_callback(events.append)
    try:
        dlq = _make_redis_dlq(max_attempts=3)
        dlq.enqueue(_make_entry("redis-e3"))
        events.clear()
        dlq.nack("redis-e3")
        nack_events = [e for e in events if isinstance(e, DLQEvent) and e.action == "nack"]
        assert len(nack_events) == 1, f"Expected exactly 1 nack event, got: {events}"
        assert nack_events[0].entry_id == "redis-e3"
        assert nack_events[0].attempt_count == 2
    finally:
        reset_emit_callback()


def _make_sqs_dlq_with_entry(entry_id="sqs-e1"):
    """Return (dlq, mock_sqs, entry) with the entry already drained so ack/nack work."""
    mock_sqs = MagicMock()
    entry = DLQEntry(id=entry_id, issue_number=1, tracker_repo="r", label="ai-dev",
                     model="gpt-4o", num_engineers=1, failed_at="2026-01-01T00:00:00Z",
                     error={})
    import json as _json
    mock_sqs.receive_message.side_effect = [
        {"Messages": [{"Body": _json.dumps(
            {"id": entry_id, "issue_number": 1, "tracker_repo": "r", "label": "ai-dev",
             "model": "gpt-4o", "num_engineers": 1, "failed_at": "2026-01-01T00:00:00Z",
             "error": {}, "target_repo": "", "attempt_count": 1}
        ), "ReceiptHandle": "rh-1"}]},
        {"Messages": []},
    ]
    cfg = DLQSQSConfig(queue_url="https://sqs.eu-west-1.amazonaws.com/123/test")
    dlq = SQSDeadLetterQueue(cfg, client=mock_sqs)
    list(dlq.drain())  # populate receipt handles
    return dlq, mock_sqs, entry


def test_sqs_dlq_enqueue_emits_event():
    """sqs backend emits enqueue event with backend='sqs'."""
    events = []
    set_emit_callback(events.append)
    try:
        mock_sqs = MagicMock()
        cfg = DLQSQSConfig(queue_url="https://sqs.eu-west-1.amazonaws.com/123/test")
        dlq = SQSDeadLetterQueue(cfg, client=mock_sqs)
        entry = DLQEntry(id="sqs-enq", issue_number=1, tracker_repo="r", label="ai-dev",
                         model="gpt-4o", num_engineers=1, failed_at="2026-01-01T00:00:00Z",
                         error={})
        dlq.enqueue(entry)
        assert any(isinstance(e, DLQEvent) and e.action == "enqueue"
                   and e.entry_id == "sqs-enq" and e.backend == "sqs"
                   for e in events), f"Expected sqs enqueue event, got: {events}"
    finally:
        reset_emit_callback()


def test_sqs_dlq_nack_emits_exactly_one_event():
    """Regression: nack() must emit exactly one DLQEvent(action='nack'), not also 'enqueue'."""
    events = []
    set_emit_callback(events.append)
    try:
        dlq, _, _ = _make_sqs_dlq_with_entry("sqs-nack")
        dlq.nack("sqs-nack")
        dlq_events = [e for e in events if isinstance(e, DLQEvent)]
        assert len(dlq_events) == 1, \
            f"Expected exactly 1 DLQEvent from nack(), got {len(dlq_events)}: {dlq_events}"
        assert dlq_events[0].action == "nack"
        assert dlq_events[0].entry_id == "sqs-nack"
        assert dlq_events[0].backend == "sqs"
    finally:
        reset_emit_callback()


# ── stage_name field ─────────────────────────────────────────────────────────

def test_dlq_entry_stage_name_field():
    """DLQEntry accepts and stores a stage_name field."""
    entry = DLQEntry(
        id="test-1",
        issue_number=1,
        tracker_repo="owner/tracker",
        label="ai-task",
        model="gpt-4.1",
        num_engineers=2,
        failed_at="2026-05-09T00:00:00Z",
        error={"code": "STAGE_ERROR", "message": "boom"},
        stage_name="architect",
    )
    assert entry.stage_name == "architect"


def test_dlq_entry_stage_name_defaults_to_pipeline():
    """DLQEntry.stage_name defaults to 'pipeline' for backward compatibility."""
    entry = DLQEntry(
        id="test-2",
        issue_number=2,
        tracker_repo="owner/tracker",
        label="ai-task",
        model="gpt-4.1",
        num_engineers=2,
        failed_at="2026-05-09T00:00:00Z",
        error={},
    )
    assert entry.stage_name == "pipeline"
