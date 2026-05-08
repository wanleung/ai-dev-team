"""Integration tests: circuit breaker → degradation; failure → DLQ."""
from __future__ import annotations
import datetime
import uuid

import pytest

from config_schema import (
    CircuitBreakerConfig, CircuitBreakerScopeConfig,
    DegradationConfig, LLMConfig,
)
from core.circuit_breaker import CircuitOpenError
from core.circuit_breaker_registry import CircuitBreakerRegistry
from core.dead_letter import FileDeadLetterQueue, DLQEntry
from core.degradation import DegradationContext, DegradationPolicy


def test_circuit_opens_after_threshold_failures():
    """After `threshold` failures the breaker state becomes 'open'."""
    scope = CircuitBreakerScopeConfig(threshold=2, recovery_timeout_s=3600)
    cb_cfg = CircuitBreakerConfig(enabled=True, per_backend=scope,
                                  per_agent=scope, per_repo=scope)
    reg = CircuitBreakerRegistry(cb_cfg)
    cb = reg.get_or_create("backend", "gpt-4.1")

    for _ in range(2):
        try:
            cb.call(lambda: (_ for _ in ()).throw(ConnectionError("timeout")))
        except ConnectionError:
            pass

    assert cb.state == "open"


def test_degradation_policy_reduces_engineers_and_picks_fallback():
    """DegradationPolicy.apply() reduces engineers, picks fallback model, skips optional stages."""
    deg_cfg = DegradationConfig(
        enabled=True, reduce_engineers=True, fallback_model=True,
        skip_optional_stages=True,
        optional_stages=["deploy_test"],  # explicit, not relying on default
    )
    llm_cfg = LLMConfig(model="gpt-4.1", fallback=["gpt-4.1-mini"])
    policy = DegradationPolicy(deg_cfg, llm_cfg)
    ctx = DegradationContext(reason="circuit open: gpt-4.1",
                             original_num_engineers=2, original_model="gpt-4.1")
    result = policy.apply(num_engineers=2, model="gpt-4.1",
                          skippable_stages=["deploy_test"], context=ctx)

    assert result.num_engineers == 1
    assert result.model == "gpt-4.1-mini"
    assert "deploy_test" in result.skipped_stages


def test_file_dlq_full_cycle(tmp_path):
    """Enqueue → drain → ack removes entry; nack increments attempt_count."""
    dlq = FileDeadLetterQueue(tmp_path / "dlq")

    entry = DLQEntry(
        id=str(uuid.uuid4()),
        issue_number=99,
        tracker_repo="owner/repo",
        label="feature-request",
        model="gpt-4.1",
        num_engineers=2,
        failed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        error={"code": "AGENT_CRASH", "stage": "pipeline", "message": "crash",
               "severity": "fatal", "timestamp": "", "context": {}},
    )
    dlq.enqueue(entry)
    drained = list(dlq.drain())
    assert len(drained) == 1
    assert drained[0].issue_number == 99

    # nack — should still be there with incremented count
    dlq.nack(entry.id)
    drained2 = list(dlq.drain())
    assert len(drained2) == 1
    assert drained2[0].attempt_count == 2

    # ack — should be gone
    dlq.ack(entry.id)
    assert list(dlq.drain()) == []


def test_null_dlq_never_raises():
    from core.dead_letter import NullDeadLetterQueue
    dlq = NullDeadLetterQueue()
    entry = DLQEntry(
        id=str(uuid.uuid4()), issue_number=1, tracker_repo="o/r",
        label="x", model="m", num_engineers=1,
        failed_at="2026-01-01T00:00:00Z",
        error={},
    )
    dlq.enqueue(entry)
    assert list(dlq.drain()) == []
    dlq.ack(entry.id)
    dlq.nack(entry.id)
