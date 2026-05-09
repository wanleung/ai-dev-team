"""Core reliability components: errors, circuit breakers, dead-letter queue, degradation."""
from core.events import (
    CircuitBreakerEvent,
    DLQEvent,
    DegradationEvent,
    AnyEvent,
    emit_event,
    set_emit_callback,
    reset_emit_callback,
)
from core.output_verifier import OutputVerifier, OutputVerificationError
