"""Tests for CircuitBreakerRegistry — thread-safe named breaker store."""
from __future__ import annotations
import threading
import pytest
from config_schema import CircuitBreakerConfig, CircuitBreakerScopeConfig
from core.circuit_breaker import CircuitBreaker, CircuitOpenError
from core.circuit_breaker_registry import CircuitBreakerRegistry, get_registry, init_registry


def _cfg(threshold=5, recovery_timeout_s=60) -> CircuitBreakerConfig:
    scope = CircuitBreakerScopeConfig(threshold=threshold, recovery_timeout_s=recovery_timeout_s)
    return CircuitBreakerConfig(enabled=True, per_agent=scope, per_repo=scope, per_backend=scope)


def test_get_or_create_returns_circuit_breaker():
    reg = CircuitBreakerRegistry(_cfg())
    cb = reg.get_or_create("agent", "my_agent")
    assert isinstance(cb, CircuitBreaker)
    assert cb.name == "agent:my_agent"


def test_same_scope_name_returns_same_instance():
    reg = CircuitBreakerRegistry(_cfg())
    cb1 = reg.get_or_create("agent", "my_agent")
    cb2 = reg.get_or_create("agent", "my_agent")
    assert cb1 is cb2


def test_different_scope_returns_different_instance():
    reg = CircuitBreakerRegistry(_cfg())
    cb1 = reg.get_or_create("agent", "my_agent")
    cb2 = reg.get_or_create("repo", "my_agent")
    assert cb1 is not cb2


def test_uses_correct_threshold_per_scope():
    scope_agent = CircuitBreakerScopeConfig(threshold=2, recovery_timeout_s=10)
    scope_repo = CircuitBreakerScopeConfig(threshold=7, recovery_timeout_s=120)
    cfg = CircuitBreakerConfig(enabled=True, per_agent=scope_agent, per_repo=scope_repo,
                               per_backend=CircuitBreakerScopeConfig())
    reg = CircuitBreakerRegistry(cfg)
    cb_agent = reg.get_or_create("agent", "x")
    cb_repo = reg.get_or_create("repo", "x")
    assert cb_agent._threshold == 2
    assert cb_repo._threshold == 7


def test_get_all_states():
    reg = CircuitBreakerRegistry(_cfg(threshold=1))
    reg.get_or_create("agent", "a")
    reg.get_or_create("backend", "b")
    states = reg.get_all_states()
    assert states["agent:a"] == "closed"
    assert states["backend:b"] == "closed"


def test_reset_closes_open_breaker():
    reg = CircuitBreakerRegistry(_cfg(threshold=1))
    cb = reg.get_or_create("agent", "x")
    cb.record_failure()
    assert cb.state == "open"
    reg.reset("agent", "x")
    assert cb.state == "closed"


def test_thread_safe_get_or_create():
    reg = CircuitBreakerRegistry(_cfg())
    results = []

    def worker():
        cb = reg.get_or_create("agent", "shared")
        results.append(id(cb))

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # All threads should get the same instance
    assert len(set(results)) == 1


def test_global_init_registry():
    cfg = _cfg()
    init_registry(cfg)
    reg = get_registry()
    assert reg is not None
    cb = reg.get_or_create("agent", "test_global")
    assert isinstance(cb, CircuitBreaker)


def test_get_registry_returns_null_registry_when_not_initialised(monkeypatch):
    import core.circuit_breaker_registry as mod
    monkeypatch.setattr(mod, "_REGISTRY", None)
    reg = get_registry()
    # NullRegistry: get_or_create returns a no-op breaker that never opens
    cb = reg.get_or_create("agent", "any")
    cb.record_failure()
    cb.record_failure()
    cb.record_failure()
    assert cb.state == "closed"  # NullRegistry breaker never opens
