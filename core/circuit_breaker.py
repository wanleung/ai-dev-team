"""Circuit breaker pattern: CLOSED → OPEN → HALF_OPEN → CLOSED.

Usage:
    cb = CircuitBreaker("gpt-4o", threshold=5, recovery_timeout_s=60)
    try:
        result = cb.call(lambda: backend.call(messages))
    except CircuitOpenError:
        # circuit is open — apply fallback
        ...
"""
from __future__ import annotations

import threading
import time
from typing import Callable, TypeVar

from core.events import CircuitBreakerEvent, emit_event

T = TypeVar("T")

# Minimum elapsed time before an open circuit can transition to half_open.
# This prevents sub-millisecond Python overhead from immediately moving the
# state to half_open when recovery_timeout_s=0 is used in tests.
_MIN_RECOVERY_S: float = 0.001  # 1 ms


class CircuitOpenError(Exception):
    """Raised when a call is attempted while the circuit breaker is OPEN."""


class CircuitBreaker:
    """Thread-safe circuit breaker with CLOSED / OPEN / HALF_OPEN states.

    State transitions:
    - CLOSED → OPEN: after ``threshold`` consecutive failures.
    - OPEN → HALF_OPEN: after ``recovery_timeout_s`` seconds have elapsed.
    - HALF_OPEN → CLOSED: on a successful call.
    - HALF_OPEN → OPEN: on a failed call.

    Args:
        name: Identifier for this breaker (used in error messages).
        threshold: Number of consecutive failures required to open the circuit.
        recovery_timeout_s: Seconds to wait in OPEN state before entering HALF_OPEN.
    """

    def __init__(self, name: str, threshold: int, recovery_timeout_s: int) -> None:
        self.name = name
        self._threshold = threshold
        self._recovery_timeout_s = recovery_timeout_s
        self._failure_count: int = 0
        self._opened_at: float | None = None
        self._was_half_open: bool = False
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        """Return the current state: ``'closed'``, ``'open'``, or ``'half_open'``."""
        with self._lock:
            return self._state_unlocked()

    def _state_unlocked(self) -> str:
        """Compute the current state without acquiring the lock (caller must hold it)."""
        if self._opened_at is None:
            return "closed"
        elapsed = time.monotonic() - self._opened_at
        threshold = max(float(self._recovery_timeout_s), _MIN_RECOVERY_S)
        if elapsed >= threshold:
            return "half_open"
        return "open"

    def record_success(self) -> None:
        """Record a successful outcome, resetting the failure count and closing the circuit.

        Only emits a CircuitBreakerEvent when transitioning from HALF_OPEN → CLOSED.
        Successful calls while already CLOSED do not emit (no state change occurred).
        """
        with self._lock:
            prior_was_half_open = self._was_half_open
            self._was_half_open = False
            self._failure_count = 0
            self._opened_at = None
        if prior_was_half_open:
            emit_event(CircuitBreakerEvent(
                name=self.name,
                state="closed",
                failure_count=0,
            ))

    def force_open(self) -> None:
        """Immediately trip the circuit breaker to OPEN state.

        Used by AgentHealthMonitor to open the breaker when an agent exceeds
        its consecutive-failure threshold, without requiring the breaker's own
        threshold to be reached.

        Emits a CircuitBreakerEvent if transitioning from a non-open state.
        Calling this method when the circuit is already OPEN is a no-op.
        """
        with self._lock:
            prior_state = self._state_unlocked()
            if prior_state != "open":
                self._failure_count = self._threshold
                self._opened_at = time.monotonic()
        if prior_state != "open":
            emit_event(CircuitBreakerEvent(
                name=self.name,
                state="open",
                failure_count=self._failure_count,
            ))

    def record_failure(self) -> None:
        """Record a failed outcome; opens (or re-opens) the circuit once ``threshold`` is reached.

        Calling this while the circuit is already open or half-open resets the
        recovery timer so that a failure during a probe (half_open) correctly
        transitions back to OPEN with a fresh countdown.
        """
        opened_now = False
        failure_count_snapshot = 0
        with self._lock:
            prior_state = self._state_unlocked()
            self._failure_count += 1
            if self._failure_count >= self._threshold:
                # Always refresh the timer: covers both closed→open and
                # half_open→open (re-open) transitions.
                self._opened_at = time.monotonic()
                if prior_state != "open":  # genuine transition: closed or half_open → open
                    opened_now = True
                    failure_count_snapshot = self._failure_count
        if opened_now:
            emit_event(CircuitBreakerEvent(
                name=self.name,
                state="open",
                failure_count=failure_count_snapshot,
            ))

    def call(self, fn: Callable[[], T]) -> T:
        """Execute *fn* through the circuit breaker.

        Behaviour by state:

        - **CLOSED**: Run *fn*. On exception: ``record_failure()`` and re-raise.
        - **OPEN**: Raise :exc:`CircuitOpenError` immediately without calling *fn*.
        - **HALF_OPEN**: Run *fn*. On success: transition to CLOSED.
          On exception: transition back to OPEN and re-raise.

        The lock is released before *fn()* is invoked to prevent deadlock when
        *fn* itself calls :meth:`record_success` or :meth:`record_failure`.

        Args:
            fn: Zero-argument callable to execute through the breaker.

        Returns:
            The return value of *fn*.

        Raises:
            CircuitOpenError: If the circuit is currently OPEN.
            Exception: Any exception raised by *fn* (after recording the failure).
        """
        with self._lock:
            state = self._state_unlocked()
            if state == "open":
                raise CircuitOpenError(
                    f"Circuit '{self.name}' is OPEN (will retry after "
                    f"{self._recovery_timeout_s}s)"
                )
            # HALF_OPEN: reset opened_at so a subsequent failure reopens with
            # a fresh timer, and reset failure count for a clean probe attempt.
            if state == "half_open":
                self._was_half_open = True
                self._opened_at = None
                self._failure_count = self._threshold - 1  # one probe failure re-opens immediately
        # Lock is released here — safe to call fn() without holding it.
        try:
            result = fn()
            self.record_success()
            return result
        except CircuitOpenError:
            raise
        except Exception:
            self.record_failure()
            raise
