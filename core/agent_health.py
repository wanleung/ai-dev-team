"""Agent health monitoring — tracks consecutive failures per named stage."""
from __future__ import annotations

import threading


class AgentHealthMonitor:
    """Track consecutive failure counts per agent/stage name.

    Thread-safe. Designed to be held on the orchestrator and queried
    from _run_stage() after each success or failure.
    """

    def __init__(self, failure_threshold: int = 3) -> None:
        self._threshold = failure_threshold
        self._failures: dict[str, int] = {}
        self._lock = threading.Lock()

    def record_failure(self, name: str) -> None:
        """Increment the consecutive failure counter for *name*."""
        with self._lock:
            self._failures[name] = self._failures.get(name, 0) + 1

    def record_success(self, name: str) -> None:
        """Reset the consecutive failure counter for *name*."""
        with self._lock:
            self._failures.pop(name, None)

    def failure_count(self, name: str) -> int:
        """Return the current consecutive failure count for *name*."""
        with self._lock:
            return self._failures.get(name, 0)

    def is_unhealthy(self, name: str) -> bool:
        """Return True when the failure count meets or exceeds the threshold."""
        return self.failure_count(name) >= self._threshold
