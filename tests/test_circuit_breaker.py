"""Tests for CircuitBreaker state machine."""
from __future__ import annotations
import time
import pytest
from core.circuit_breaker import CircuitBreaker, CircuitOpenError


def _make(threshold=3, recovery_timeout_s=1):
    return CircuitBreaker("test", threshold=threshold, recovery_timeout_s=recovery_timeout_s)


# ── state transitions ─────────────────────────────────────────────────────────

def test_initial_state_is_closed():
    cb = _make()
    assert cb.state == "closed"


def test_stays_closed_on_success():
    cb = _make(threshold=3)
    for _ in range(10):
        cb.record_success()
    assert cb.state == "closed"


def test_opens_after_threshold_failures():
    cb = _make(threshold=3)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == "closed"
    cb.record_failure()
    assert cb.state == "open"


def test_open_rejects_call():
    cb = _make(threshold=1)
    cb.record_failure()
    assert cb.state == "open"
    with pytest.raises(CircuitOpenError):
        cb.call(lambda: "should not run")


def test_call_succeeds_when_closed():
    cb = _make()
    result = cb.call(lambda: 42)
    assert result == 42


def test_call_records_failure_on_exception():
    cb = _make(threshold=2)
    with pytest.raises(RuntimeError):
        cb.call(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert cb._failure_count == 1


def test_transitions_to_half_open_after_recovery_timeout():
    cb = _make(threshold=1, recovery_timeout_s=0)
    cb.record_failure()
    assert cb.state == "open"
    time.sleep(0.01)  # recovery_timeout_s=0 means any elapsed time qualifies
    assert cb.state == "half_open"


def test_half_open_success_closes():
    cb = _make(threshold=1, recovery_timeout_s=0)
    cb.record_failure()
    time.sleep(0.01)
    assert cb.state == "half_open"
    cb.record_success()
    assert cb.state == "closed"
    assert cb._failure_count == 0


def test_half_open_failure_reopens():
    cb = _make(threshold=1, recovery_timeout_s=0)
    cb.record_failure()
    time.sleep(0.01)
    assert cb.state == "half_open"
    cb.record_failure()
    assert cb.state == "open"


def test_success_resets_failure_count():
    cb = _make(threshold=5)
    cb.record_failure()
    cb.record_failure()
    assert cb._failure_count == 2
    cb.record_success()
    assert cb._failure_count == 0


def test_call_propagates_exception_and_records_failure():
    cb = _make(threshold=3)
    with pytest.raises(ValueError):
        cb.call(lambda: (_ for _ in ()).throw(ValueError("bad")))
    assert cb._failure_count == 1
    assert cb.state == "closed"


def test_circuit_open_error_contains_name():
    cb = _make(threshold=1)
    cb.record_failure()
    with pytest.raises(CircuitOpenError) as exc_info:
        cb.call(lambda: None)
    assert "test" in str(exc_info.value)


def test_half_open_probe_failure_reopens_when_threshold_gt_1():
    """A single probe failure in HALF_OPEN must re-open the circuit even when
    threshold > 1.  Regression test for the bug where _failure_count was reset
    to 0 instead of threshold-1, causing the circuit to close on a failed probe.
    """
    cb = _make(threshold=3, recovery_timeout_s=0)
    # Trip circuit open: need 3 consecutive failures.
    for _ in range(3):
        cb.record_failure()
    assert cb.state == "open"

    # Wait for recovery timeout to elapse so circuit enters HALF_OPEN.
    time.sleep(0.01)
    assert cb.state == "half_open"

    # One probe call that raises — should re-open the circuit.
    with pytest.raises(ValueError):
        cb.call(lambda: (_ for _ in ()).throw(ValueError("probe failed")))

    assert cb.state == "open", (
        "Circuit should be OPEN after a failed HALF_OPEN probe, "
        "regardless of threshold value"
    )
