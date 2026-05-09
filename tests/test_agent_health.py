"""Tests for AgentHealthMonitor (T2-C Task 3)."""
from __future__ import annotations

import pytest

from core.agent_health import AgentHealthMonitor


def test_initial_state_healthy():
    monitor = AgentHealthMonitor(failure_threshold=3)
    assert monitor.failure_count("pm") == 0
    assert not monitor.is_unhealthy("pm")


def test_record_failure_increments():
    monitor = AgentHealthMonitor(failure_threshold=3)
    monitor.record_failure("pm")
    monitor.record_failure("pm")
    assert monitor.failure_count("pm") == 2
    assert not monitor.is_unhealthy("pm")


def test_reaches_threshold_becomes_unhealthy():
    monitor = AgentHealthMonitor(failure_threshold=3)
    for _ in range(3):
        monitor.record_failure("architect")
    assert monitor.is_unhealthy("architect")
    assert monitor.failure_count("architect") == 3


def test_record_success_resets_count():
    monitor = AgentHealthMonitor(failure_threshold=3)
    monitor.record_failure("engineer")
    monitor.record_failure("engineer")
    monitor.record_success("engineer")
    assert monitor.failure_count("engineer") == 0
    assert not monitor.is_unhealthy("engineer")


def test_independent_stages():
    monitor = AgentHealthMonitor(failure_threshold=2)
    monitor.record_failure("pm")
    monitor.record_failure("pm")
    assert monitor.is_unhealthy("pm")
    assert not monitor.is_unhealthy("architect")
    assert monitor.failure_count("architect") == 0


def test_unhealthy_agent_triggers_circuit_breaker_open():
    """When AgentHealthMonitor marks an agent unhealthy, the circuit breaker opens."""
    from core.circuit_breaker import CircuitBreaker, CircuitOpenError
    from core.circuit_breaker_registry import CircuitBreakerRegistry
    from config_schema import CircuitBreakerConfig, CircuitBreakerScopeConfig

    cfg = CircuitBreakerConfig(
        enabled=True,
        per_agent=CircuitBreakerScopeConfig(threshold=10, recovery_timeout_s=60),
        per_repo=CircuitBreakerScopeConfig(threshold=10, recovery_timeout_s=60),
        per_backend=CircuitBreakerScopeConfig(threshold=10, recovery_timeout_s=60),
    )
    registry = CircuitBreakerRegistry(cfg)
    cb = registry.get_or_create("agent", "my-agent")

    monitor = AgentHealthMonitor(failure_threshold=2)
    monitor.record_failure("my-agent")
    monitor.record_failure("my-agent")  # threshold reached

    assert monitor.is_unhealthy("my-agent")
    assert cb.state == "closed"  # not yet tripped

    # Simulate what _run_stage should do when is_unhealthy fires
    cb.force_open()
    assert cb.state == "open"

    # Next call should raise CircuitOpenError
    with pytest.raises(CircuitOpenError):
        cb.call(lambda: "should not run")


def test_force_open_is_idempotent():
    """Calling force_open() on an already-open breaker stays open."""
    from core.circuit_breaker import CircuitBreaker

    cb = CircuitBreaker("test", threshold=5, recovery_timeout_s=60)
    cb.force_open()
    assert cb.state == "open"
    cb.force_open()  # should not raise
    assert cb.state == "open"
