"""Structured event types for observability across core components.

Usage:
    from core.events import emit_event, CircuitBreakerEvent, DLQEvent, DegradationEvent

    # Emit an event (default: structured logger.info call)
    emit_event(CircuitBreakerEvent(name="backend", state="open", failure_count=5))

    # Install custom sink (e.g. push to StatsD / CloudWatch)
    from core.events import set_emit_callback
    set_emit_callback(my_statsd_reporter)
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Literal

logger = logging.getLogger(__name__)

# ── Event dataclasses ─────────────────────────────────────────────────────────


@dataclass
class CircuitBreakerEvent:
    """Emitted on every circuit breaker state transition."""

    name: str
    state: str
    failure_count: int

    event_type: Literal["circuit_breaker"] = field(default="circuit_breaker", init=False)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        init=False,
    )


@dataclass
class DLQEvent:
    """Emitted on DLQ enqueue, ack, nack operations."""

    action: str
    entry_id: str
    backend: str
    attempt_count: int = 1

    event_type: Literal["dlq"] = field(default="dlq", init=False)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        init=False,
    )


@dataclass
class DegradationEvent:
    """Emitted when DegradationPolicy.apply() takes at least one action."""

    trigger: str
    actions_taken: list[str]

    event_type: Literal["degradation"] = field(default="degradation", init=False)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        init=False,
    )


AnyEvent = CircuitBreakerEvent | DLQEvent | DegradationEvent

# ── Emit callback ─────────────────────────────────────────────────────────────

_callback_lock = threading.Lock()
_DEFAULT_CALLBACK: Callable[[AnyEvent], None] | None = None


def _default_emit(event: AnyEvent) -> None:
    """Default handler: emit a structured log at INFO level."""
    logger.info(
        "event type=%s %s",
        event.event_type,
        {k: v for k, v in vars(event).items() if k != "event_type"},
    )


def set_emit_callback(callback: Callable[[AnyEvent], None]) -> None:
    """Install a custom event sink. Thread-safe."""
    global _DEFAULT_CALLBACK
    with _callback_lock:
        _DEFAULT_CALLBACK = callback


def reset_emit_callback() -> None:
    """Restore the default logging handler. Thread-safe."""
    global _DEFAULT_CALLBACK
    with _callback_lock:
        _DEFAULT_CALLBACK = None


def emit_event(event: AnyEvent) -> None:
    """Emit *event* to the registered callback (or the default logger)."""
    with _callback_lock:
        cb = _DEFAULT_CALLBACK
    try:
        if cb is not None:
            cb(event)
        else:
            _default_emit(event)
    except Exception as exc:  # pragma: no cover
        logger.debug("emit_event suppressed error: %s", exc, exc_info=True)
