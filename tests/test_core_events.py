# tests/test_core_events.py
import logging
from core.events import (
    CircuitBreakerEvent, DLQEvent, DegradationEvent,
    emit_event, set_emit_callback, reset_emit_callback,
)


def test_emit_event_calls_callback(caplog):
    """Default callback logs a structured message at INFO level."""
    with caplog.at_level(logging.INFO, logger="core.events"):
        emit_event(CircuitBreakerEvent(name="backend", state="open", failure_count=5))
    assert any("circuit_breaker" in r.message for r in caplog.records)


def test_set_emit_callback_replaces_default():
    """set_emit_callback installs a custom handler."""
    received = []
    set_emit_callback(received.append)
    try:
        evt = DLQEvent(action="enqueue", entry_id="abc", backend="redis")
        emit_event(evt)
        assert len(received) == 1
        assert received[0] is evt
    finally:
        reset_emit_callback()


def test_reset_emit_callback_restores_default(caplog):
    """reset_emit_callback restores the default logging handler."""
    set_emit_callback(lambda e: None)
    reset_emit_callback()
    with caplog.at_level(logging.INFO, logger="core.events"):
        emit_event(DegradationEvent(trigger="circuit_open", actions_taken=["reduce_engineers"]))
    assert any("degradation" in r.message for r in caplog.records)


def test_circuit_breaker_event_fields():
    evt = CircuitBreakerEvent(name="backend", state="half_open", failure_count=3)
    assert evt.event_type == "circuit_breaker"
    assert evt.name == "backend"
    assert evt.state == "half_open"
    assert evt.failure_count == 3


def test_dlq_event_fields():
    evt = DLQEvent(action="ack", entry_id="xyz", backend="file")
    assert evt.event_type == "dlq"
    assert evt.action == "ack"
    assert evt.entry_id == "xyz"
    assert evt.backend == "file"
    assert evt.attempt_count == 1


def test_degradation_event_fields():
    evt = DegradationEvent(trigger="budget_exceeded", actions_taken=["fallback_model"])
    assert evt.event_type == "degradation"
    assert evt.trigger == "budget_exceeded"
    assert evt.actions_taken == ["fallback_model"]


def test_public_interface_via_core_package():
    """Symbols are re-exported from core so callers need not import from core.events."""
    from core import CircuitBreakerEvent as CBE, emit_event as ee, set_emit_callback as sc
    assert CBE is CircuitBreakerEvent
    assert ee is emit_event
    assert sc is set_emit_callback
