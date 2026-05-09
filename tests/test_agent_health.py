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
