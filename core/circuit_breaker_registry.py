"""Thread-safe registry of named circuit breakers + module-level singleton.

Usage (application startup):
    from core.circuit_breaker_registry import init_registry, get_registry
    init_registry(reliability_cfg.circuit_breaker)

Usage (call sites):
    from core.circuit_breaker_registry import get_registry
    cb = get_registry().get_or_create("agent", agent_name)
    result = cb.call(lambda: agent.run(...))
"""
from __future__ import annotations

import threading
from typing import Literal

from config_schema import CircuitBreakerConfig
from core.circuit_breaker import CircuitBreaker

_Scope = Literal["agent", "repo", "backend"]

# Module-level singleton — None until init_registry() is called.
_REGISTRY: "CircuitBreakerRegistry | _NullRegistry | None" = None
_REGISTRY_LOCK = threading.Lock()


class _NullBreaker(CircuitBreaker):
    """A breaker that never opens. Used when registry is not initialised."""

    def __init__(self, name: str) -> None:
        super().__init__(name, threshold=10**9, recovery_timeout_s=0)

    def force_open(self) -> None:
        """No-op: a null breaker never trips open, even when forced."""


class _NullRegistry:
    """No-op registry returned when reliability config is disabled/absent."""

    def get_or_create(self, scope: _Scope, name: str) -> CircuitBreaker:
        return _NullBreaker(f"{scope}:{name}")

    def get_all_states(self) -> dict[str, str]:
        return {}

    def reset(self, scope: _Scope, name: str) -> None:
        pass


class CircuitBreakerRegistry:
    """Thread-safe store of named CircuitBreaker instances."""

    def __init__(self, cfg: CircuitBreakerConfig) -> None:
        self._cfg = cfg
        self._breakers: dict[str, CircuitBreaker] = {}
        self._lock = threading.Lock()

    def get_or_create(self, scope: _Scope, name: str) -> CircuitBreaker:
        """Return an existing breaker for the given scope/name, or create one.

        Args:
            scope: One of ``"agent"``, ``"repo"``, or ``"backend"``.
            name: The identifier within the scope (e.g. agent name, repo slug).

        Returns:
            The :class:`~core.circuit_breaker.CircuitBreaker` for this key.
        """
        key = f"{scope}:{name}"
        with self._lock:
            if key not in self._breakers:
                scope_cfg = getattr(self._cfg, f"per_{scope}")
                self._breakers[key] = CircuitBreaker(
                    key,
                    threshold=scope_cfg.threshold,
                    recovery_timeout_s=scope_cfg.recovery_timeout_s,
                )
            return self._breakers[key]

    def get_all_states(self) -> dict[str, str]:
        """Return a snapshot of every breaker's current state.

        Returns:
            Mapping of ``"scope:name"`` → state string (``"closed"`` / ``"open"`` / ``"half_open"``).
        """
        with self._lock:
            return {k: v.state for k, v in self._breakers.items()}

    def reset(self, scope: _Scope, name: str) -> None:
        """Force-close a named breaker, clearing its failure count.

        Args:
            scope: One of ``"agent"``, ``"repo"``, or ``"backend"``.
            name: The identifier within the scope.
        """
        key = f"{scope}:{name}"
        with self._lock:
            if key in self._breakers:
                self._breakers[key].record_success()


def init_registry(cfg: CircuitBreakerConfig) -> None:
    """Initialise the module-level registry from config. Call once at startup.

    If ``cfg.enabled`` is ``False``, installs a :class:`_NullRegistry` that
    returns no-op breakers so call sites need no awareness of whether the
    feature is enabled.

    Args:
        cfg: The :class:`~config_schema.CircuitBreakerConfig` section of the
             application's reliability configuration.
    """
    global _REGISTRY
    with _REGISTRY_LOCK:
        if cfg.enabled:
            _REGISTRY = CircuitBreakerRegistry(cfg)
        else:
            _REGISTRY = _NullRegistry()


def get_registry() -> "CircuitBreakerRegistry | _NullRegistry":
    """Return the module-level registry. Returns a NullRegistry if not initialised.

    Returns:
        The active :class:`CircuitBreakerRegistry`, or a :class:`_NullRegistry`
        whose breakers never open when the registry has not yet been initialised.
    """
    with _REGISTRY_LOCK:
        if _REGISTRY is None:
            return _NullRegistry()
        return _REGISTRY
