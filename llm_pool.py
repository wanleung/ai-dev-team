"""LLMPoolManager — per-backend semaphore pools for safe concurrent LLM access.

Each LLM backend (ollama, openai, opencode-zen, etc.) has its own
``threading.Semaphore`` whose count is set from ``config.yaml`` under
``llm.pools.<backend>``. Agents acquire a slot before making a call:

    with get_pool().acquire("ollama"):
        response = backend.call(messages)

The default for ``ollama`` is 1 (single connection — safe for local
GPU/CPU resources). All other backends default to 5.

Thread-safe. The pool is a process-wide singleton so every worker thread
in the watcher shares the same semaphores.
"""
from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger(__name__)

# Default per-backend limits when not specified in config
_DEFAULT_LIMITS = {
    "ollama": 1,
}
_FALLBACK_LIMIT = 5


def _coerce_limit(backend: str, raw, fallback: int) -> int:
    """Coerce a raw limit value to a positive int, warning on bad input.

    Returns ``fallback`` for None, non-int, zero, or negative values to
    prevent deadlocks (limit=0) or ValueError (limit<0 in Semaphore).
    """
    try:
        n = int(raw)
    except (TypeError, ValueError):
        logger.warning(
            "LLM pool limit for %r is not an integer (%r); using default %d",
            backend, raw, fallback,
        )
        return fallback
    if n < 1:
        logger.warning(
            "LLM pool limit for %r must be >= 1 (got %d); using default %d",
            backend, n, fallback,
        )
        return fallback
    return n


class LLMPoolManager:
    """Holds one ``threading.Semaphore`` per backend name."""

    def __init__(self, limits: Optional[dict] = None):
        raw_limits = dict(limits or {})
        self._limits: dict = {}
        for backend, raw in raw_limits.items():
            fb = _DEFAULT_LIMITS.get(backend, _FALLBACK_LIMIT)
            self._limits[backend] = _coerce_limit(backend, raw, fb)
        self._semaphores: dict[str, threading.Semaphore] = {}
        self._lock = threading.Lock()

    def limit_for(self, backend: str) -> int:
        """Return the configured limit for ``backend``."""
        if backend in self._limits:
            return self._limits[backend]
        return _DEFAULT_LIMITS.get(backend, _FALLBACK_LIMIT)

    def _semaphore_for(self, backend: str) -> threading.Semaphore:
        with self._lock:
            sem = self._semaphores.get(backend)
            if sem is None:
                sem = threading.Semaphore(self.limit_for(backend))
                self._semaphores[backend] = sem
            return sem

    @contextmanager
    def acquire(self, backend: str):
        """Context manager: acquire a slot for ``backend`` and release on exit."""
        sem = self._semaphore_for(backend)
        sem.acquire()
        try:
            yield
        finally:
            sem.release()


# ── Process-wide singleton ────────────────────────────────────────────────
_POOL: Optional[LLMPoolManager] = None
_POOL_LOCK = threading.Lock()


def get_pool() -> LLMPoolManager:
    """Return the global LLMPoolManager, creating a default one if unset."""
    global _POOL
    with _POOL_LOCK:
        if _POOL is None:
            _POOL = LLMPoolManager()
        return _POOL


def set_pool(pool: Optional[LLMPoolManager]) -> None:
    """Install a global LLMPoolManager (or reset to None)."""
    global _POOL
    with _POOL_LOCK:
        _POOL = pool
