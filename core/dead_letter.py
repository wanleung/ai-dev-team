"""Dead-letter queue for failed pipeline tasks.

Backends: file (default), redis, sqs, null (no-op).

Usage:
    from core.dead_letter import build_dlq, DLQEntry
    dlq = build_dlq(reliability_cfg.dead_letter, workspace_root=Path("."))

    # on failure
    dlq.enqueue(DLQEntry(...))

    # drain and retry (--retry-dlq CLI flag)
    for entry in dlq.drain():
        try:
            _dispatch(...)
            dlq.ack(entry.id)
        except Exception:
            dlq.nack(entry.id)
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, replace as dc_replace
from pathlib import Path
from typing import Any, Iterator

from config_schema import DLQConfig, DLQRedisConfig, DLQSQSConfig


@dataclass
class DLQEntry:
    """Represents a single failed pipeline task stored in the dead-letter queue."""

    id: str
    issue_number: int
    tracker_repo: str
    label: str
    model: str
    num_engineers: int
    failed_at: str
    error: dict[str, Any]
    target_repo: str = ""
    attempt_count: int = 1


class DeadLetterQueue(ABC):
    """Abstract base class for DLQ backends."""

    @abstractmethod
    def enqueue(self, entry: DLQEntry) -> None:
        """Persist a failed entry to the queue."""
        ...

    @abstractmethod
    def drain(self) -> Iterator[DLQEntry]:
        """Yield all entries currently in the queue (without removing them)."""
        ...

    @abstractmethod
    def ack(self, entry_id: str) -> None:
        """Acknowledge successful processing — removes the entry from the queue."""
        ...

    @abstractmethod
    def nack(self, entry_id: str) -> None:
        """Negative-acknowledge — marks the entry for retry (increments attempt_count)."""
        ...


class NullDeadLetterQueue(DeadLetterQueue):
    """No-op backend — used when DLQ is disabled."""

    def enqueue(self, entry: DLQEntry) -> None:
        """Discard the entry silently."""
        pass

    def drain(self) -> Iterator[DLQEntry]:
        """Always yields nothing."""
        return iter([])

    def ack(self, entry_id: str) -> None:
        """No-op."""
        pass

    def nack(self, entry_id: str) -> None:
        """No-op."""
        pass


class FileDeadLetterQueue(DeadLetterQueue):
    """Stores each DLQ entry as an individual JSON file inside a directory.

    Args:
        path: Directory to store DLQ JSON files in. Created automatically if absent.
        max_attempts: Entries that exceed this count are discarded on nack.
    """

    def __init__(self, path: Path, max_attempts: int = 3) -> None:
        self._path = Path(path)
        self._max_attempts = max_attempts
        self._path.mkdir(parents=True, exist_ok=True)

    def _file_for(self, entry_id: str) -> Path:
        """Return the expected file path for the given entry id."""
        return self._path / f"{entry_id}.json"

    def enqueue(self, entry: DLQEntry) -> None:
        """Write the entry to a JSON file named by its id (atomic via tmp + rename)."""
        self._path.mkdir(parents=True, exist_ok=True)
        target = self._file_for(entry.id)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(entry), indent=2), encoding="utf-8")
        tmp.replace(target)

    def drain(self) -> Iterator[DLQEntry]:
        """Yield all entries found in the directory, skipping corrupt files."""
        for p in sorted(self._path.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                yield DLQEntry(**data)
            except Exception:
                continue

    def ack(self, entry_id: str) -> None:
        """Delete the JSON file for the given entry id."""
        f = self._file_for(entry_id)
        if f.exists():
            f.unlink()

    def nack(self, entry_id: str) -> None:
        """Increment attempt_count; discard entry if max_attempts exceeded (atomic write)."""
        f = self._file_for(entry_id)
        if f.exists():
            data = json.loads(f.read_text(encoding="utf-8"))
            data["attempt_count"] = data.get("attempt_count", 1) + 1
            if data["attempt_count"] > self._max_attempts:
                f.unlink(missing_ok=True)
                return
            tmp = f.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(f)


class RedisDeadLetterQueue(DeadLetterQueue):
    """Redis list-based DLQ backend.

    Entries are stored as JSON strings in a Redis list. Requires the ``redis`` package.

    Args:
        cfg: Redis DLQ configuration (url, key, ttl_s).
        client: Optional pre-built Redis client (mainly for testing).
        max_attempts: Entries that exceed this count are discarded on nack.
    """

    def __init__(self, cfg: DLQRedisConfig, client=None, max_attempts: int = 3) -> None:
        self._cfg = cfg
        self._max_attempts = max_attempts
        if client is not None:
            self._redis = client
        else:
            import redis as _redis  # lazy import — optional dependency
            self._redis = _redis.from_url(cfg.url)

    def enqueue(self, entry: DLQEntry) -> None:
        """Push the entry JSON to the head of the Redis list."""
        payload = json.dumps(asdict(entry))
        self._redis.lpush(self._cfg.key, payload)
        if self._cfg.ttl_s:
            self._redis.expire(self._cfg.key, self._cfg.ttl_s)

    def drain(self) -> Iterator[DLQEntry]:
        """Yield all entries in the Redis list without removing them."""
        items = self._redis.lrange(self._cfg.key, 0, -1) or []
        for item in items:
            try:
                raw = item.decode() if isinstance(item, bytes) else item
                data = json.loads(raw)
                yield DLQEntry(**data)
            except Exception:
                continue

    def ack(self, entry_id: str) -> None:
        """Remove the entry with the given id from the Redis list."""
        for item in self._redis.lrange(self._cfg.key, 0, -1) or []:
            try:
                raw = item.decode() if isinstance(item, bytes) else item
                data = json.loads(raw)
                if data.get("id") == entry_id:
                    self._redis.lrem(self._cfg.key, 1, item)
                    return
            except Exception:
                continue

    def nack(self, entry_id: str) -> None:
        """Increment attempt_count and re-push; discard if max_attempts exceeded."""
        for item in self._redis.lrange(self._cfg.key, 0, -1) or []:
            try:
                raw = item.decode() if isinstance(item, bytes) else item
                data = json.loads(raw)
                if data.get("id") == entry_id:
                    data["attempt_count"] = data.get("attempt_count", 1) + 1
                    self._redis.lrem(self._cfg.key, 1, item)
                    if data["attempt_count"] <= self._max_attempts:
                        self._redis.lpush(self._cfg.key, json.dumps(data))
                    return
            except Exception:
                continue


class SQSDeadLetterQueue(DeadLetterQueue):
    """AWS SQS-based DLQ backend.

    Entries are sent as JSON message bodies. Requires the ``boto3`` package.

    Note:
        ``max_attempts`` is not enforced by this backend; configure a SQS Redrive
        Policy on the queue with ``maxReceiveCount`` instead.

    Args:
        cfg: SQS DLQ configuration (queue_url, region).
        client: Optional pre-built SQS client (mainly for testing).
    """

    def __init__(self, cfg: DLQSQSConfig, client=None) -> None:
        self._cfg = cfg
        if client is not None:
            self._sqs = client
        else:
            import boto3  # lazy import — optional dependency
            self._sqs = boto3.client("sqs", region_name=cfg.region)
        # Maps entry_id → ReceiptHandle for ack/nack after drain
        self._receipt_handles: dict[str, str] = {}
        # Maps entry_id → DLQEntry for nack re-enqueue with incremented count
        self._entries: dict[str, DLQEntry] = {}

    def enqueue(self, entry: DLQEntry) -> None:
        """Send the entry as a JSON message to the SQS queue."""
        self._sqs.send_message(
            QueueUrl=self._cfg.queue_url,
            MessageBody=json.dumps(asdict(entry)),
        )

    def drain(self) -> Iterator[DLQEntry]:
        """Poll the SQS queue in batches and yield entries until the queue is empty.

        Receipt handles and entries are cached internally so that subsequent calls
        to :meth:`ack` and :meth:`nack` can reference the correct message.
        Stale handles from previous drain calls are cleared at the start.
        """
        self._receipt_handles.clear()
        self._entries.clear()
        while True:
            resp = self._sqs.receive_message(
                QueueUrl=self._cfg.queue_url,
                MaxNumberOfMessages=10,
                WaitTimeSeconds=1,
            )
            messages = resp.get("Messages") or []
            if not messages:
                break
            for msg in messages:
                try:
                    data = json.loads(msg["Body"])
                    entry = DLQEntry(**data)
                    self._receipt_handles[entry.id] = msg["ReceiptHandle"]
                    self._entries[entry.id] = entry
                    yield entry
                except Exception:
                    # Poison message: delete immediately to avoid infinite re-delivery loop.
                    try:
                        self._sqs.delete_message(
                            QueueUrl=self._cfg.queue_url,
                            ReceiptHandle=msg["ReceiptHandle"],
                        )
                    except Exception:
                        pass
                    continue

    def ack(self, entry_id: str) -> None:
        """Delete the SQS message associated with the given entry id."""
        rh = self._receipt_handles.pop(entry_id, None)
        self._entries.pop(entry_id, None)
        if rh:
            try:
                self._sqs.delete_message(QueueUrl=self._cfg.queue_url, ReceiptHandle=rh)
            except Exception:
                pass  # Handle expired; message will re-appear and be re-processed

    def nack(self, entry_id: str) -> None:
        """Delete original SQS message and re-enqueue with incremented attempt_count.

        If the entry data is unavailable (e.g. not populated by drain), the
        receipt handle is simply released and SQS will re-deliver via visibility
        timeout.
        """
        rh = self._receipt_handles.pop(entry_id, None)
        entry = self._entries.pop(entry_id, None)
        if rh is None:
            return
        if entry is None:
            # Fallback: just release the message (visibility timeout will re-queue it)
            return
        updated = dc_replace(entry, attempt_count=entry.attempt_count + 1)
        # Delete original
        try:
            self._sqs.delete_message(QueueUrl=self._cfg.queue_url, ReceiptHandle=rh)
        except Exception:
            # Handle expired; original message will re-appear via visibility timeout.
            # Do NOT call enqueue — that would create a duplicate.
            return
        # Re-enqueue with updated count
        self.enqueue(updated)


def build_dlq(cfg: DLQConfig, workspace_root: Path = Path(".")) -> DeadLetterQueue:
    """Factory function: return the correct DeadLetterQueue backend from config.

    Args:
        cfg: Top-level DLQ configuration block.
        workspace_root: Used to resolve relative file paths.

    Returns:
        A concrete :class:`DeadLetterQueue` instance.

    Raises:
        ValueError: If a required backend config block is missing or the
            backend name is unknown.
    """
    if not cfg.enabled:
        return NullDeadLetterQueue()

    if cfg.backend == "file":
        path = Path(cfg.file.path)
        if not path.is_absolute():
            path = workspace_root / path
        return FileDeadLetterQueue(path, max_attempts=cfg.max_attempts)

    if cfg.backend == "redis":
        if cfg.redis is None:
            raise ValueError(
                "reliability.dead_letter.redis config is required for redis backend"
            )
        return RedisDeadLetterQueue(cfg.redis, max_attempts=cfg.max_attempts)

    if cfg.backend == "sqs":
        if cfg.sqs is None:
            raise ValueError(
                "reliability.dead_letter.sqs config is required for sqs backend"
            )
        return SQSDeadLetterQueue(cfg.sqs)

    raise ValueError(f"Unknown DLQ backend: {cfg.backend!r}")
