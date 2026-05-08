"""Tests for ReliabilityConfig Pydantic models in config_schema."""
from __future__ import annotations
import pytest
from pydantic import ValidationError
from config_schema import AppConfig, ReliabilityConfig


def test_reliability_not_required():
    """AppConfig validates without reliability key — backwards compat."""
    cfg = AppConfig.model_validate({"llm": {"model": "gpt-4.1"}})
    assert cfg.reliability is None


def test_reliability_defaults():
    cfg = AppConfig.model_validate({
        "llm": {"model": "gpt-4.1"},
        "reliability": {},
    })
    assert cfg.reliability is not None
    assert cfg.reliability.circuit_breaker.enabled is False
    assert cfg.reliability.dead_letter.enabled is False
    assert cfg.reliability.degradation.enabled is False


def test_circuit_breaker_scope_config():
    cfg = AppConfig.model_validate({
        "llm": {"model": "gpt-4.1"},
        "reliability": {
            "circuit_breaker": {
                "enabled": True,
                "per_agent": {"threshold": 3, "recovery_timeout_s": 30},
            }
        },
    })
    assert cfg.reliability.circuit_breaker.enabled is True
    assert cfg.reliability.circuit_breaker.per_agent.threshold == 3
    assert cfg.reliability.circuit_breaker.per_agent.recovery_timeout_s == 30
    # per_repo and per_backend keep their defaults
    assert cfg.reliability.circuit_breaker.per_repo.threshold == 3
    assert cfg.reliability.circuit_breaker.per_repo.recovery_timeout_s == 120
    assert cfg.reliability.circuit_breaker.per_backend.threshold == 10
    assert cfg.reliability.circuit_breaker.per_backend.recovery_timeout_s == 300


def test_dlq_file_config():
    cfg = AppConfig.model_validate({
        "llm": {"model": "gpt-4.1"},
        "reliability": {
            "dead_letter": {
                "enabled": True,
                "backend": "file",
                "file": {"path": "workspace/dlq"},
            }
        },
    })
    assert cfg.reliability.dead_letter.enabled is True
    assert cfg.reliability.dead_letter.backend == "file"
    assert cfg.reliability.dead_letter.file.path == "workspace/dlq"


def test_dlq_backend_invalid():
    with pytest.raises(ValidationError):
        AppConfig.model_validate({
            "llm": {"model": "gpt-4.1"},
            "reliability": {"dead_letter": {"backend": "invalid"}},
        })


def test_degradation_config():
    cfg = AppConfig.model_validate({
        "llm": {"model": "gpt-4.1"},
        "reliability": {
            "degradation": {
                "enabled": True,
                "skip_optional_stages": True,
                "optional_stages": ["deploy_test"],
            }
        },
    })
    assert cfg.reliability.degradation.enabled is True
    assert cfg.reliability.degradation.optional_stages == ["deploy_test"]


def test_dlq_redis_backend_requires_redis_config():
    with pytest.raises(ValidationError):
        AppConfig.model_validate({
            "llm": {"model": "gpt-4.1"},
            "reliability": {"dead_letter": {"enabled": True, "backend": "redis"}},
        })
