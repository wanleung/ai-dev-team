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
    RedisDeadLetterQueue,
    SQSDeadLetterQueue,
    build_dlq,
)


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


# ── RedisDeadLetterQueue ──────────────────────────────────────────────────────

def test_redis_dlq_enqueue_calls_lpush():
    mock_redis = MagicMock()
    cfg = DLQRedisConfig(url="redis://localhost:6379", key="test:dlq", ttl_s=100)
    dlq = RedisDeadLetterQueue(cfg, client=mock_redis)
    e = _entry()
    dlq.enqueue(e)
    mock_redis.lpush.assert_called_once()
    args = mock_redis.lpush.call_args[0]
    assert args[0] == "test:dlq"
    payload = json.loads(args[1])
    assert payload["id"] == e.id


def test_redis_dlq_drain_yields_decoded_entries():
    mock_redis = MagicMock()
    e = _entry()
    mock_redis.lrange.return_value = [json.dumps(e.__dict__).encode()]
    cfg = DLQRedisConfig()
    dlq = RedisDeadLetterQueue(cfg, client=mock_redis)
    drained = list(dlq.drain())
    assert len(drained) == 1
    assert drained[0].id == e.id


def test_redis_dlq_ack_removes_entry():
    mock_redis = MagicMock()
    e = _entry()
    mock_redis.lrange.return_value = [json.dumps(e.__dict__).encode()]
    cfg = DLQRedisConfig()
    dlq = RedisDeadLetterQueue(cfg, client=mock_redis)
    dlq.ack(e.id)
    mock_redis.lrem.assert_called_once()


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
    """build_dlq should return RedisDeadLetterQueue when backend='redis'."""
    mock_redis_client = MagicMock()
    cfg = DLQConfig(
        enabled=True,
        backend="redis",
        redis=DLQRedisConfig(url="redis://localhost:6379", key="dlq:test"),
    )
    with patch("core.dead_letter.RedisDeadLetterQueue.__init__", return_value=None) as mock_init:
        # Patch __init__ so we don't need a live Redis; check the class is instantiated
        dlq = build_dlq(cfg, workspace_root=tmp_path)
        mock_init.assert_called_once()
    # Alternatively, use a real client injection
    cfg2 = DLQConfig(
        enabled=True,
        backend="redis",
        redis=DLQRedisConfig(url="redis://localhost:6379", key="dlq:test"),
    )
    dlq2 = RedisDeadLetterQueue(cfg2.redis, client=mock_redis_client, max_attempts=cfg2.max_attempts)
    assert isinstance(dlq2, RedisDeadLetterQueue)


def test_build_dlq_unknown_backend_raises(tmp_path):
    """build_dlq should raise ValueError for an unrecognised backend name."""
    # Use model_construct to bypass Pydantic's Literal validator so the
    # ValueError in build_dlq itself is exercised.
    cfg = DLQConfig.model_construct(enabled=True, backend="kafka")
    with pytest.raises(ValueError, match="Unknown DLQ backend"):
        build_dlq(cfg, workspace_root=tmp_path)


def test_redis_nack_max_attempts_discards():
    """Redis backend: after max_attempts nacks, entry should be removed from Redis."""
    mock_redis = MagicMock()
    cfg = DLQRedisConfig(url="redis://localhost:6379", key="test:dlq")
    dlq = RedisDeadLetterQueue(cfg, client=mock_redis, max_attempts=2)
    
    e = _entry(attempt_count=2)
    mock_redis.lrange.return_value = [json.dumps(e.__dict__).encode()]
    
    # First nack: attempt_count=2 → 3 > max_attempts=2, should be removed
    dlq.nack(e.id)
    
    # Verify lrem was called to remove the entry (not re-added)
    mock_redis.lrem.assert_called_once()
    # Verify lpush was NOT called to re-add it
    mock_redis.lpush.assert_not_called()


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
