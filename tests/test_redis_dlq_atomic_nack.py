"""Atomic Redis DLQ nack tests — Task 3 of T5-A concurrency plan."""
import json
import pytest
from unittest.mock import MagicMock, patch
from redis.exceptions import ResponseError
from config_schema import DLQRedisConfig
from core.dead_letter import RedisDLQ


def _make_redis_dlq(redis_mock):
    cfg = DLQRedisConfig(key="dlq:test")
    dlq = RedisDLQ(cfg, redis_client=redis_mock)
    return dlq


def test_nack_uses_lua_eval():
    """RedisDLQ.nack() calls redis.eval() with the Lua script."""
    redis_mock = MagicMock()
    redis_mock.eval.return_value = 1  # attempt_count returned by Lua
    dlq = _make_redis_dlq(redis_mock)
    dlq.nack("entry-001")
    assert redis_mock.eval.called
    call_args = redis_mock.eval.call_args
    assert "attempt_count" in call_args[0][0] or "ARGV" in call_args[0][0]


def test_nack_falls_back_on_response_error():
    """Falls back to Python-level read-modify-write on ResponseError."""
    redis_mock = MagicMock()
    redis_mock.eval.side_effect = ResponseError("NOSCRIPT")
    entry_data = json.dumps({"attempt_count": 1, "id": "entry-002"})
    redis_mock.hget.return_value = entry_data.encode()
    dlq = _make_redis_dlq(redis_mock)
    dlq.nack("entry-002")
    assert redis_mock.hset.called or redis_mock.hdel.called


def test_nack_does_not_raise_on_missing_entry():
    """nack() on a non-existent entry is a no-op."""
    redis_mock = MagicMock()
    redis_mock.eval.return_value = None
    dlq = _make_redis_dlq(redis_mock)
    dlq.nack("does-not-exist")  # should not raise
