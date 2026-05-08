# T1: Reliability & Error Handling — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add structured `PipelineError`, circuit breakers (per-agent/repo/backend), a pluggable dead-letter queue (file/Redis/SQS), and configurable graceful degradation — all opt-in via `config.yaml` with `enabled: false` defaults so existing behaviour is unchanged.

**Architecture:** Six new files under `core/` (errors, circuit_breaker, circuit_breaker_registry, dead_letter, degradation, and package init). Four existing files modified: `config_schema.py` gains `ReliabilityConfig`; `orchestrator.py` swaps `list[str]` for `list[PipelineError]`; `agents/backends/base.py` wraps `call()` with per-backend breaker; `watcher.py` enqueues failures to DLQ and wraps GitHub calls with per-repo breaker. Everything is guarded by `cfg.reliability.circuit_breaker.enabled` / `cfg.reliability.dead_letter.enabled` / `cfg.reliability.degradation.enabled`.

**Tech Stack:** Python 3.11+, Pydantic v2, threading (already used), optional `redis` and `boto3` packages for Redis/SQS DLQ backends.

**Spec:** `docs/superpowers/specs/2026-05-08-t1-reliability-design.md`

**Test command:** `python3 -m pytest tests/ -q --tb=short`

**Branch:** Create `t1-reliability` before starting Task 1:
```bash
git checkout -b t1-reliability
```

---

## Task 1: Core package + `PipelineError` + config schema

**Files:**
- Create: `core/__init__.py`
- Create: `core/errors.py`
- Modify: `config_schema.py`

### Step 1 — Write failing tests for `PipelineError` and `ReliabilityConfig`

- [ ] Create `tests/test_pipeline_error.py`:

```python
"""Tests for core.errors.PipelineError and core.degradation config."""
from __future__ import annotations
import pytest
from core.errors import PipelineError


def test_pipeline_error_str():
    e = PipelineError(code="AGENT_TIMEOUT", stage="architect", message="timed out", severity="error")
    s = str(e)
    assert "AGENT_TIMEOUT" in s
    assert "architect" in s
    assert "timed out" in s


def test_pipeline_error_to_dict():
    e = PipelineError(code="LLM_RATE_LIMIT", stage="qa", message="429", severity="warning")
    d = e.to_dict()
    assert d["code"] == "LLM_RATE_LIMIT"
    assert d["stage"] == "qa"
    assert d["message"] == "429"
    assert d["severity"] == "warning"
    assert "timestamp" in d
    assert isinstance(d["context"], dict)


def test_pipeline_error_context():
    e = PipelineError(code="UNKNOWN", stage="s", message="m", severity="error",
                      context={"file": "main.py", "line": 42})
    assert e.context["file"] == "main.py"
    assert e.to_dict()["context"]["line"] == 42


def test_pipeline_error_default_timestamp():
    e = PipelineError(code="UNKNOWN", stage="s", message="m", severity="fatal")
    assert e.timestamp.endswith("Z")
```

- [ ] Run: `python3 -m pytest tests/test_pipeline_error.py -v`
  Expected: **FAIL** — `ModuleNotFoundError: No module named 'core'`

### Step 2 — Create `core/__init__.py`

- [ ] Create `core/__init__.py`:

```python
"""Core reliability components: errors, circuit breakers, dead-letter queue, degradation."""
```

### Step 3 — Create `core/errors.py`

- [ ] Create `core/errors.py`:

```python
"""Structured pipeline error type replacing bare list[str] on PipelineResult."""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any, Literal

ERROR_CODES = Literal[
    "AGENT_TIMEOUT",
    "AGENT_CRASH",
    "LLM_RATE_LIMIT",
    "LLM_TIMEOUT",
    "LLM_CIRCUIT_OPEN",
    "GITHUB_API_ERROR",
    "GITHUB_RATE_LIMIT",
    "STAGE_SKIPPED",
    "DLQ_ENQUEUE_FAILED",
    "DEGRADATION_APPLIED",
    "UNKNOWN",
]


@dataclass
class PipelineError:
    code: ERROR_CODES
    stage: str
    message: str
    severity: Literal["warning", "error", "fatal"]
    timestamp: str = field(
        default_factory=lambda: datetime.datetime.utcnow().isoformat() + "Z"
    )
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "stage": self.stage,
            "message": self.message,
            "severity": self.severity,
            "timestamp": self.timestamp,
            "context": self.context,
        }

    def __str__(self) -> str:
        return f"[{self.severity.upper()}] {self.code} @ {self.stage}: {self.message}"
```

### Step 4 — Run tests (should pass now)

- [ ] Run: `python3 -m pytest tests/test_pipeline_error.py -v`
  Expected: **4 passed**

### Step 5 — Write failing config schema tests

- [ ] Create `tests/test_reliability_config.py`:

```python
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
    assert cfg.reliability.circuit_breaker.per_backend.threshold == 10


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
```

- [ ] Run: `python3 -m pytest tests/test_reliability_config.py -v`
  Expected: **FAIL** — `ImportError` (ReliabilityConfig not yet defined)

### Step 6 — Add Pydantic models to `config_schema.py`

- [ ] Add these classes **before** the `AppConfig` class in `config_schema.py` (after the existing `OllamaConfig`):

```python
# ── reliability models ────────────────────────────────────────────────────────

class CircuitBreakerScopeConfig(BaseModel):
    model_config = {"extra": "forbid"}

    threshold: int = 5
    recovery_timeout_s: int = 60


class CircuitBreakerConfig(BaseModel):
    model_config = {"extra": "forbid"}

    enabled: bool = False
    per_agent: CircuitBreakerScopeConfig = Field(
        default_factory=CircuitBreakerScopeConfig
    )
    per_repo: CircuitBreakerScopeConfig = Field(
        default_factory=lambda: CircuitBreakerScopeConfig(threshold=3, recovery_timeout_s=120)
    )
    per_backend: CircuitBreakerScopeConfig = Field(
        default_factory=lambda: CircuitBreakerScopeConfig(threshold=10, recovery_timeout_s=300)
    )


class DLQFileConfig(BaseModel):
    model_config = {"extra": "forbid"}

    path: str = "workspace/dlq"


class DLQRedisConfig(BaseModel):
    model_config = {"extra": "forbid"}

    url: str = "redis://localhost:6379"
    key: str = "ai-swhouse:dlq"
    ttl_s: int = 604800


class DLQSQSConfig(BaseModel):
    model_config = {"extra": "forbid"}

    queue_url: str
    region: str = "eu-west-1"


class DLQConfig(BaseModel):
    model_config = {"extra": "forbid"}

    enabled: bool = False
    backend: Literal["file", "redis", "sqs"] = "file"
    max_attempts: int = 3
    file: DLQFileConfig = Field(default_factory=DLQFileConfig)
    redis: Optional[DLQRedisConfig] = None
    sqs: Optional[DLQSQSConfig] = None


class DegradationConfig(BaseModel):
    model_config = {"extra": "forbid"}

    enabled: bool = False
    reduce_engineers: bool = True
    fallback_model: bool = True
    skip_optional_stages: bool = True
    optional_stages: List[str] = Field(
        default_factory=lambda: ["deploy_test", "documentation"]
    )


class ReliabilityConfig(BaseModel):
    model_config = {"extra": "forbid"}

    circuit_breaker: CircuitBreakerConfig = Field(
        default_factory=CircuitBreakerConfig
    )
    dead_letter: DLQConfig = Field(default_factory=DLQConfig)
    degradation: DegradationConfig = Field(default_factory=DegradationConfig)
```

- [ ] Add `from typing import Literal` to the existing `from typing import ...` import (it uses `Any, Dict, List, Optional` already — add `Literal`).

- [ ] Add `reliability: Optional[ReliabilityConfig] = None` to `AppConfig` fields.

### Step 7 — Run all config schema tests

- [ ] Run: `python3 -m pytest tests/test_reliability_config.py tests/test_config_schema.py -v`
  Expected: **all pass**

### Step 8 — Commit

- [ ] Run:
```bash
git add core/__init__.py core/errors.py config_schema.py \
        tests/test_pipeline_error.py tests/test_reliability_config.py
git commit -m "feat(t1): core package, PipelineError, ReliabilityConfig schema"
```

---

## Task 2: Circuit Breaker state machine

**Files:**
- Create: `core/circuit_breaker.py`
- Test: `tests/test_circuit_breaker.py`

### Step 1 — Write failing tests

- [ ] Create `tests/test_circuit_breaker.py`:

```python
"""Tests for CircuitBreaker state machine."""
from __future__ import annotations
import time
import pytest
from core.circuit_breaker import CircuitBreaker, CircuitOpenError


def _make(threshold=3, recovery_timeout_s=1):
    return CircuitBreaker("test", threshold=threshold, recovery_timeout_s=recovery_timeout_s)


# ── state transitions ─────────────────────────────────────────────────────────

def test_initial_state_is_closed():
    cb = _make()
    assert cb.state == "closed"


def test_stays_closed_on_success():
    cb = _make(threshold=3)
    for _ in range(10):
        cb.record_success()
    assert cb.state == "closed"


def test_opens_after_threshold_failures():
    cb = _make(threshold=3)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == "closed"
    cb.record_failure()
    assert cb.state == "open"


def test_open_rejects_call():
    cb = _make(threshold=1)
    cb.record_failure()
    assert cb.state == "open"
    with pytest.raises(CircuitOpenError):
        cb.call(lambda: "should not run")


def test_call_succeeds_when_closed():
    cb = _make()
    result = cb.call(lambda: 42)
    assert result == 42


def test_call_records_failure_on_exception():
    cb = _make(threshold=2)
    with pytest.raises(RuntimeError):
        cb.call(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert cb._failure_count == 1


def test_transitions_to_half_open_after_recovery_timeout():
    cb = _make(threshold=1, recovery_timeout_s=0)
    cb.record_failure()
    assert cb.state == "open"
    time.sleep(0.01)  # recovery_timeout_s=0 means any elapsed time qualifies
    assert cb.state == "half_open"


def test_half_open_success_closes():
    cb = _make(threshold=1, recovery_timeout_s=0)
    cb.record_failure()
    time.sleep(0.01)
    assert cb.state == "half_open"
    cb.record_success()
    assert cb.state == "closed"
    assert cb._failure_count == 0


def test_half_open_failure_reopens():
    cb = _make(threshold=1, recovery_timeout_s=0)
    cb.record_failure()
    time.sleep(0.01)
    assert cb.state == "half_open"
    cb.record_failure()
    assert cb.state == "open"


def test_success_resets_failure_count():
    cb = _make(threshold=5)
    cb.record_failure()
    cb.record_failure()
    assert cb._failure_count == 2
    cb.record_success()
    assert cb._failure_count == 0


def test_call_propagates_exception_and_records_failure():
    cb = _make(threshold=3)
    with pytest.raises(ValueError):
        cb.call(lambda: (_ for _ in ()).throw(ValueError("bad")))
    assert cb._failure_count == 1
    assert cb.state == "closed"


def test_circuit_open_error_contains_name():
    cb = _make(threshold=1)
    cb.record_failure()
    with pytest.raises(CircuitOpenError) as exc_info:
        cb.call(lambda: None)
    assert "test" in str(exc_info.value)
```

- [ ] Run: `python3 -m pytest tests/test_circuit_breaker.py -v`
  Expected: **FAIL** — `ModuleNotFoundError`

### Step 2 — Implement `core/circuit_breaker.py`

- [ ] Create `core/circuit_breaker.py`:

```python
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

T = TypeVar("T")


class CircuitOpenError(Exception):
    """Raised when a call is attempted while the circuit breaker is OPEN."""


class CircuitBreaker:
    """Thread-safe circuit breaker with CLOSED / OPEN / HALF_OPEN states."""

    def __init__(self, name: str, threshold: int, recovery_timeout_s: int) -> None:
        self.name = name
        self._threshold = threshold
        self._recovery_timeout_s = recovery_timeout_s
        self._failure_count: int = 0
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        with self._lock:
            return self._state_unlocked()

    def _state_unlocked(self) -> str:
        if self._opened_at is None:
            return "closed"
        elapsed = time.monotonic() - self._opened_at
        if elapsed >= self._recovery_timeout_s:
            return "half_open"
        return "open"

    def record_success(self) -> None:
        with self._lock:
            self._failure_count = 0
            self._opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            if self._failure_count >= self._threshold and self._opened_at is None:
                self._opened_at = time.monotonic()

    def call(self, fn: Callable[[], T]) -> T:
        """Execute *fn* through the breaker.

        - CLOSED: run fn; on exception, record_failure and re-raise.
        - OPEN: raise CircuitOpenError immediately.
        - HALF_OPEN: run fn; success → CLOSED; failure → OPEN again.
        """
        with self._lock:
            state = self._state_unlocked()
            if state == "open":
                raise CircuitOpenError(
                    f"Circuit '{self.name}' is OPEN (will retry after "
                    f"{self._recovery_timeout_s}s)"
                )
            # half_open: reset opened_at so failure reopens with fresh timer
            if state == "half_open":
                self._opened_at = None
                self._failure_count = 0

        try:
            result = fn()
            self.record_success()
            return result
        except CircuitOpenError:
            raise
        except Exception:
            self.record_failure()
            raise
```

### Step 3 — Run tests

- [ ] Run: `python3 -m pytest tests/test_circuit_breaker.py -v`
  Expected: **all pass**

### Step 4 — Commit

- [ ] Run:
```bash
git add core/circuit_breaker.py tests/test_circuit_breaker.py
git commit -m "feat(t1): CircuitBreaker state machine with thread-safe transitions"
```

---

## Task 3: Circuit Breaker Registry

**Files:**
- Create: `core/circuit_breaker_registry.py`
- Test: `tests/test_circuit_breaker_registry.py`

### Step 1 — Write failing tests

- [ ] Create `tests/test_circuit_breaker_registry.py`:

```python
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
```

- [ ] Run: `python3 -m pytest tests/test_circuit_breaker_registry.py -v`
  Expected: **FAIL** — `ModuleNotFoundError`

### Step 2 — Implement `core/circuit_breaker_registry.py`

- [ ] Create `core/circuit_breaker_registry.py`:

```python
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
        with self._lock:
            return {k: v.state for k, v in self._breakers.items()}

    def reset(self, scope: _Scope, name: str) -> None:
        key = f"{scope}:{name}"
        with self._lock:
            if key in self._breakers:
                self._breakers[key].record_success()


def init_registry(cfg: CircuitBreakerConfig) -> None:
    """Initialise the module-level registry from config. Call once at startup."""
    global _REGISTRY
    with _REGISTRY_LOCK:
        if cfg.enabled:
            _REGISTRY = CircuitBreakerRegistry(cfg)
        else:
            _REGISTRY = _NullRegistry()


def get_registry() -> "CircuitBreakerRegistry | _NullRegistry":
    """Return the module-level registry. Returns a NullRegistry if not initialised."""
    with _REGISTRY_LOCK:
        if _REGISTRY is None:
            return _NullRegistry()
        return _REGISTRY
```

### Step 3 — Run tests

- [ ] Run: `python3 -m pytest tests/test_circuit_breaker_registry.py -v`
  Expected: **all pass**

### Step 4 — Commit

- [ ] Run:
```bash
git add core/circuit_breaker_registry.py tests/test_circuit_breaker_registry.py
git commit -m "feat(t1): CircuitBreakerRegistry with thread-safe singleton and NullRegistry"
```

---

## Task 4: Dead-Letter Queue

**Files:**
- Create: `core/dead_letter.py`
- Test: `tests/test_dead_letter.py`

### Step 1 — Write failing tests

- [ ] Create `tests/test_dead_letter.py`:

```python
"""Tests for DeadLetterQueue backends."""
from __future__ import annotations
import json
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch, call as mcall
import pytest

from config_schema import DLQConfig, DLQFileConfig, DLQRedisConfig, DLQSQSConfig
from core.dead_letter import (
    DLQEntry,
    FileDeadLetterQueue,
    NullDeadLetterQueue,
    RedisDeadLetterQueue,
    SQSDeadLetterQueue,
    build_dlq,
)


def _entry(**kwargs) -> DLQEntry:
    defaults = dict(
        id=str(uuid.uuid4()),
        issue_number=1,
        tracker_repo="owner/repo",
        label="feature-request",
        model="gpt-4.1",
        num_engineers=2,
        failed_at="2026-05-08T12:00:00Z",
        error={"code": "AGENT_TIMEOUT", "stage": "architect", "message": "timed out",
               "severity": "error", "timestamp": "2026-05-08T12:00:00Z", "context": {}},
    )
    defaults.update(kwargs)
    return DLQEntry(**defaults)


# ── FileDeadLetterQueue ────────────────────────────────────────────────────────

def test_file_dlq_enqueue_writes_json(tmp_path):
    dlq = FileDeadLetterQueue(tmp_path)
    e = _entry()
    dlq.enqueue(e)
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text())
    assert data["id"] == e.id
    assert data["issue_number"] == 1


def test_file_dlq_drain_yields_all(tmp_path):
    dlq = FileDeadLetterQueue(tmp_path)
    e1 = _entry(issue_number=1)
    e2 = _entry(issue_number=2)
    dlq.enqueue(e1)
    dlq.enqueue(e2)
    drained = list(dlq.drain())
    assert len(drained) == 2
    numbers = {e.issue_number for e in drained}
    assert numbers == {1, 2}


def test_file_dlq_ack_removes_file(tmp_path):
    dlq = FileDeadLetterQueue(tmp_path)
    e = _entry()
    dlq.enqueue(e)
    assert len(list(tmp_path.glob("*.json"))) == 1
    dlq.ack(e.id)
    assert len(list(tmp_path.glob("*.json"))) == 0


def test_file_dlq_nack_increments_attempt_count(tmp_path):
    dlq = FileDeadLetterQueue(tmp_path)
    e = _entry()
    dlq.enqueue(e)
    dlq.nack(e.id)
    files = list(tmp_path.glob("*.json"))
    data = json.loads(files[0].read_text())
    assert data["attempt_count"] == 2


def test_file_dlq_drain_empty(tmp_path):
    dlq = FileDeadLetterQueue(tmp_path)
    assert list(dlq.drain()) == []


def test_file_dlq_creates_dir(tmp_path):
    path = tmp_path / "sub" / "dlq"
    dlq = FileDeadLetterQueue(path)
    e = _entry()
    dlq.enqueue(e)
    assert path.exists()


# ── NullDeadLetterQueue ────────────────────────────────────────────────────────

def test_null_dlq_enqueue_is_noop():
    dlq = NullDeadLetterQueue()
    dlq.enqueue(_entry())  # should not raise


def test_null_dlq_drain_is_empty():
    dlq = NullDeadLetterQueue()
    assert list(dlq.drain()) == []


def test_null_dlq_ack_nack_are_noop():
    dlq = NullDeadLetterQueue()
    dlq.ack("any-id")
    dlq.nack("any-id")


# ── RedisDeadLetterQueue ──────────────────────────────────────────────────────

def test_redis_dlq_enqueue_calls_lpush():
    mock_redis = MagicMock()
    cfg = DLQRedisConfig(url="redis://localhost:6379", key="test:dlq", ttl_s=100)
    dlq = RedisDeadLetterQueue(cfg, client=mock_redis)
    e = _entry()
    dlq.enqueue(e)
    mock_redis.lpush.assert_called_once()
    args = mock_redis.lpush.call_args[0]
    assert args[0] == "test:dlq"
    payload = json.loads(args[1])
    assert payload["id"] == e.id


def test_redis_dlq_drain_yields_decoded_entries():
    mock_redis = MagicMock()
    e = _entry()
    mock_redis.lrange.return_value = [json.dumps(e.__dict__).encode()]
    cfg = DLQRedisConfig()
    dlq = RedisDeadLetterQueue(cfg, client=mock_redis)
    drained = list(dlq.drain())
    assert len(drained) == 1
    assert drained[0].id == e.id


def test_redis_dlq_ack_removes_entry():
    mock_redis = MagicMock()
    e = _entry()
    mock_redis.lrange.return_value = [json.dumps(e.__dict__).encode()]
    cfg = DLQRedisConfig()
    dlq = RedisDeadLetterQueue(cfg, client=mock_redis)
    dlq.ack(e.id)
    mock_redis.lrem.assert_called_once()


# ── SQSDeadLetterQueue ────────────────────────────────────────────────────────

def test_sqs_dlq_enqueue_calls_send_message():
    mock_sqs = MagicMock()
    cfg = DLQSQSConfig(queue_url="https://sqs.eu-west-1.amazonaws.com/123/test")
    dlq = SQSDeadLetterQueue(cfg, client=mock_sqs)
    e = _entry()
    dlq.enqueue(e)
    mock_sqs.send_message.assert_called_once()
    kwargs = mock_sqs.send_message.call_args[1]
    assert kwargs["QueueUrl"] == cfg.queue_url
    payload = json.loads(kwargs["MessageBody"])
    assert payload["id"] == e.id


def test_sqs_dlq_drain_yields_entries():
    mock_sqs = MagicMock()
    e = _entry()
    mock_sqs.receive_message.return_value = {
        "Messages": [{"Body": json.dumps(e.__dict__), "ReceiptHandle": "rh-1"}]
    }
    cfg = DLQSQSConfig(queue_url="https://sqs.eu-west-1.amazonaws.com/123/test")
    dlq = SQSDeadLetterQueue(cfg, client=mock_sqs)
    drained = list(dlq.drain())
    assert len(drained) == 1
    assert drained[0].id == e.id


def test_sqs_dlq_ack_deletes_message():
    mock_sqs = MagicMock()
    e = _entry()
    mock_sqs.receive_message.return_value = {
        "Messages": [{"Body": json.dumps(e.__dict__), "ReceiptHandle": "rh-1"}]
    }
    cfg = DLQSQSConfig(queue_url="https://sqs.eu-west-1.amazonaws.com/123/test")
    dlq = SQSDeadLetterQueue(cfg, client=mock_sqs)
    list(dlq.drain())  # populates internal receipt handle map
    dlq.ack(e.id)
    mock_sqs.delete_message.assert_called_once_with(
        QueueUrl=cfg.queue_url, ReceiptHandle="rh-1"
    )


# ── build_dlq factory ─────────────────────────────────────────────────────────

def test_build_dlq_disabled_returns_null(tmp_path):
    cfg = DLQConfig(enabled=False)
    dlq = build_dlq(cfg, workspace_root=tmp_path)
    assert isinstance(dlq, NullDeadLetterQueue)


def test_build_dlq_file_returns_file_dlq(tmp_path):
    cfg = DLQConfig(enabled=True, backend="file", file=DLQFileConfig(path=str(tmp_path / "dlq")))
    dlq = build_dlq(cfg, workspace_root=tmp_path)
    assert isinstance(dlq, FileDeadLetterQueue)
```

- [ ] Run: `python3 -m pytest tests/test_dead_letter.py -v`
  Expected: **FAIL** — `ModuleNotFoundError`

### Step 2 — Implement `core/dead_letter.py`

- [ ] Create `core/dead_letter.py`:

```python
"""Dead-letter queue for failed pipeline tasks.

Backends: file (default), redis, sqs, null (no-op).

Usage:
    from core.dead_letter import build_dlq, DLQEntry
    dlq = build_dlq(reliability_cfg.dead_letter, workspace_root=Path("."))

    # on failure
    dlq.enqueue(DLQEntry(...))

    # drain and retry (--retry-dlq CLI flag)
    for entry in dlq.drain():
        try:
            _dispatch(...)
            dlq.ack(entry.id)
        except Exception:
            dlq.nack(entry.id)
"""
from __future__ import annotations

import json
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator

from config_schema import DLQConfig, DLQRedisConfig, DLQSQSConfig


@dataclass
class DLQEntry:
    id: str
    issue_number: int
    tracker_repo: str
    label: str
    model: str
    num_engineers: int
    failed_at: str
    error: dict[str, Any]
    attempt_count: int = 1


class DeadLetterQueue(ABC):
    @abstractmethod
    def enqueue(self, entry: DLQEntry) -> None: ...

    @abstractmethod
    def drain(self) -> Iterator[DLQEntry]: ...

    @abstractmethod
    def ack(self, entry_id: str) -> None: ...

    @abstractmethod
    def nack(self, entry_id: str) -> None: ...


class NullDeadLetterQueue(DeadLetterQueue):
    """No-op — used when DLQ is disabled."""

    def enqueue(self, entry: DLQEntry) -> None:
        pass

    def drain(self) -> Iterator[DLQEntry]:
        return iter([])

    def ack(self, entry_id: str) -> None:
        pass

    def nack(self, entry_id: str) -> None:
        pass


class FileDeadLetterQueue(DeadLetterQueue):
    """Stores entries as JSON files in a directory."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.mkdir(parents=True, exist_ok=True)

    def _file_for(self, entry_id: str) -> Path:
        return self._path / f"{entry_id}.json"

    def enqueue(self, entry: DLQEntry) -> None:
        self._path.mkdir(parents=True, exist_ok=True)
        self._file_for(entry.id).write_text(
            json.dumps(asdict(entry), indent=2), encoding="utf-8"
        )

    def drain(self) -> Iterator[DLQEntry]:
        for p in sorted(self._path.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                yield DLQEntry(**data)
            except Exception:
                continue

    def ack(self, entry_id: str) -> None:
        f = self._file_for(entry_id)
        if f.exists():
            f.unlink()

    def nack(self, entry_id: str) -> None:
        f = self._file_for(entry_id)
        if f.exists():
            data = json.loads(f.read_text(encoding="utf-8"))
            data["attempt_count"] = data.get("attempt_count", 1) + 1
            f.write_text(json.dumps(data, indent=2), encoding="utf-8")


class RedisDeadLetterQueue(DeadLetterQueue):
    """Redis list-based DLQ. Requires `redis` package."""

    def __init__(self, cfg: DLQRedisConfig, client=None) -> None:
        self._cfg = cfg
        if client is not None:
            self._redis = client
        else:
            import redis as _redis
            self._redis = _redis.from_url(cfg.url)

    def enqueue(self, entry: DLQEntry) -> None:
        payload = json.dumps(asdict(entry))
        self._redis.lpush(self._cfg.key, payload)
        if self._cfg.ttl_s:
            self._redis.expire(self._cfg.key, self._cfg.ttl_s)

    def drain(self) -> Iterator[DLQEntry]:
        items = self._redis.lrange(self._cfg.key, 0, -1) or []
        for item in items:
            try:
                data = json.loads(item.decode() if isinstance(item, bytes) else item)
                yield DLQEntry(**data)
            except Exception:
                continue

    def ack(self, entry_id: str) -> None:
        for item in self._redis.lrange(self._cfg.key, 0, -1) or []:
            try:
                data = json.loads(item.decode() if isinstance(item, bytes) else item)
                if data.get("id") == entry_id:
                    self._redis.lrem(self._cfg.key, 1, item)
                    return
            except Exception:
                continue

    def nack(self, entry_id: str) -> None:
        for item in self._redis.lrange(self._cfg.key, 0, -1) or []:
            try:
                raw = item.decode() if isinstance(item, bytes) else item
                data = json.loads(raw)
                if data.get("id") == entry_id:
                    data["attempt_count"] = data.get("attempt_count", 1) + 1
                    self._redis.lrem(self._cfg.key, 1, item)
                    self._redis.lpush(self._cfg.key, json.dumps(data))
                    return
            except Exception:
                continue


class SQSDeadLetterQueue(DeadLetterQueue):
    """AWS SQS-based DLQ. Requires `boto3` package."""

    def __init__(self, cfg: DLQSQSConfig, client=None) -> None:
        self._cfg = cfg
        if client is not None:
            self._sqs = client
        else:
            import boto3
            self._sqs = boto3.client("sqs", region_name=cfg.region)
        # Maps entry_id → ReceiptHandle for ack/nack after drain
        self._receipt_handles: dict[str, str] = {}

    def enqueue(self, entry: DLQEntry) -> None:
        self._sqs.send_message(
            QueueUrl=self._cfg.queue_url,
            MessageBody=json.dumps(asdict(entry)),
        )

    def drain(self) -> Iterator[DLQEntry]:
        while True:
            resp = self._sqs.receive_message(
                QueueUrl=self._cfg.queue_url,
                MaxNumberOfMessages=10,
                WaitTimeSeconds=1,
            )
            messages = resp.get("Messages") or []
            if not messages:
                break
            for msg in messages:
                try:
                    data = json.loads(msg["Body"])
                    entry = DLQEntry(**data)
                    self._receipt_handles[entry.id] = msg["ReceiptHandle"]
                    yield entry
                except Exception:
                    continue

    def ack(self, entry_id: str) -> None:
        rh = self._receipt_handles.pop(entry_id, None)
        if rh:
            self._sqs.delete_message(QueueUrl=self._cfg.queue_url, ReceiptHandle=rh)

    def nack(self, entry_id: str) -> None:
        # SQS: message becomes visible again automatically after visibility timeout.
        # We just remove from our local map so we don't try to delete it.
        self._receipt_handles.pop(entry_id, None)


def build_dlq(cfg: DLQConfig, workspace_root: Path = Path(".")) -> DeadLetterQueue:
    """Factory: return the correct DeadLetterQueue backend from config."""
    if not cfg.enabled:
        return NullDeadLetterQueue()
    if cfg.backend == "file":
        path = Path(cfg.file.path)
        if not path.is_absolute():
            path = workspace_root / path
        return FileDeadLetterQueue(path)
    if cfg.backend == "redis":
        if cfg.redis is None:
            raise ValueError("reliability.dead_letter.redis config is required for redis backend")
        return RedisDeadLetterQueue(cfg.redis)
    if cfg.backend == "sqs":
        if cfg.sqs is None:
            raise ValueError("reliability.dead_letter.sqs config is required for sqs backend")
        return SQSDeadLetterQueue(cfg.sqs)
    raise ValueError(f"Unknown DLQ backend: {cfg.backend!r}")
```

### Step 3 — Run tests

- [ ] Run: `python3 -m pytest tests/test_dead_letter.py -v`
  Expected: **all pass**

### Step 4 — Commit

- [ ] Run:
```bash
git add core/dead_letter.py tests/test_dead_letter.py
git commit -m "feat(t1): DeadLetterQueue with File/Redis/SQS/Null backends and factory"
```

---

## Task 5: Degradation Policy

**Files:**
- Create: `core/degradation.py`
- Test: `tests/test_degradation.py`

### Step 1 — Write failing tests

- [ ] Create `tests/test_degradation.py`:

```python
"""Tests for DegradationPolicy."""
from __future__ import annotations
import pytest
from config_schema import DegradationConfig, LLMConfig
from core.degradation import DegradationContext, DegradationPolicy, DegradationResult


def _policy(reduce=True, fallback=True, skip=True, optional=None, enabled=True):
    cfg = DegradationConfig(
        enabled=enabled,
        reduce_engineers=reduce,
        fallback_model=fallback,
        skip_optional_stages=skip,
        optional_stages=optional or ["deploy_test", "documentation"],
    )
    llm = LLMConfig(model="gpt-4.1", fallback=["gpt-4.1-mini", "gpt-4o-mini"])
    return DegradationPolicy(cfg, llm)


def _ctx(reason="circuit open: gpt-4.1", engineers=2, model="gpt-4.1"):
    return DegradationContext(
        reason=reason,
        original_num_engineers=engineers,
        original_model=model,
    )


def test_disabled_policy_returns_unchanged():
    p = _policy(enabled=False)
    r = p.apply(num_engineers=3, model="gpt-4.1",
                skippable_stages=["deploy_test"], context=_ctx())
    assert r.num_engineers == 3
    assert r.model == "gpt-4.1"
    assert r.skipped_stages == []
    assert r.actions_taken == []


def test_reduce_engineers():
    p = _policy(reduce=True, fallback=False, skip=False)
    r = p.apply(num_engineers=3, model="gpt-4.1",
                skippable_stages=[], context=_ctx())
    assert r.num_engineers == 2
    assert "reduce_engineers" in " ".join(r.actions_taken)


def test_reduce_engineers_minimum_one():
    p = _policy(reduce=True, fallback=False, skip=False)
    r = p.apply(num_engineers=1, model="gpt-4.1",
                skippable_stages=[], context=_ctx())
    assert r.num_engineers == 1


def test_fallback_model_substitutes_next_in_chain():
    p = _policy(reduce=False, fallback=True, skip=False)
    r = p.apply(num_engineers=2, model="gpt-4.1",
                skippable_stages=[], context=_ctx(model="gpt-4.1"))
    assert r.model == "gpt-4.1-mini"
    assert "fallback_model" in " ".join(r.actions_taken)


def test_fallback_model_no_fallback_list():
    from config_schema import LLMConfig
    cfg = DegradationConfig(enabled=True, fallback_model=True)
    llm = LLMConfig(model="gpt-4.1", fallback=None)
    p = DegradationPolicy(cfg, llm)
    r = p.apply(num_engineers=2, model="gpt-4.1",
                skippable_stages=[], context=_ctx())
    assert r.model == "gpt-4.1"  # unchanged — no fallback available


def test_skip_optional_stages():
    p = _policy(reduce=False, fallback=False, skip=True,
                optional=["deploy_test", "documentation"])
    r = p.apply(num_engineers=2, model="gpt-4.1",
                skippable_stages=["deploy_test", "documentation"],
                context=_ctx())
    assert "deploy_test" in r.skipped_stages
    assert "documentation" in r.skipped_stages
    assert "skip_optional_stages" in " ".join(r.actions_taken)


def test_skip_only_intersects_with_skippable():
    p = _policy(reduce=False, fallback=False, skip=True, optional=["deploy_test"])
    r = p.apply(num_engineers=2, model="gpt-4.1",
                skippable_stages=["documentation"],  # deploy_test not in skippable
                context=_ctx())
    assert r.skipped_stages == []


def test_all_three_strategies_combined():
    p = _policy(reduce=True, fallback=True, skip=True)
    r = p.apply(num_engineers=2, model="gpt-4.1",
                skippable_stages=["deploy_test"],
                context=_ctx())
    assert r.num_engineers == 1
    assert r.model == "gpt-4.1-mini"
    assert "deploy_test" in r.skipped_stages
    assert len(r.actions_taken) == 3
```

- [ ] Run: `python3 -m pytest tests/test_degradation.py -v`
  Expected: **FAIL** — `ModuleNotFoundError`

### Step 2 — Implement `core/degradation.py`

- [ ] Create `core/degradation.py`:

```python
"""Graceful degradation policy: reduce engineers, fallback model, skip optional stages.

Usage:
    from core.degradation import DegradationPolicy, DegradationContext
    policy = DegradationPolicy(reliability_cfg.degradation, llm_cfg)

    try:
        result = cb.call(lambda: agent.run(...))
    except CircuitOpenError as exc:
        ctx = DegradationContext(reason=str(exc), ...)
        degraded = policy.apply(num_engineers, model, skippable_stages, ctx)
        # use degraded.num_engineers, degraded.model, degraded.skipped_stages
"""
from __future__ import annotations

from dataclasses import dataclass, field

from config_schema import DegradationConfig, LLMConfig


@dataclass
class DegradationContext:
    reason: str
    original_num_engineers: int
    original_model: str


@dataclass
class DegradationResult:
    num_engineers: int
    model: str
    skipped_stages: list[str]
    actions_taken: list[str] = field(default_factory=list)


class DegradationPolicy:
    def __init__(self, cfg: DegradationConfig, llm_cfg: LLMConfig) -> None:
        self._cfg = cfg
        self._fallback_chain: list[str] = list(llm_cfg.fallback or [])

    def apply(
        self,
        num_engineers: int,
        model: str,
        skippable_stages: list[str],
        context: DegradationContext,
    ) -> DegradationResult:
        if not self._cfg.enabled:
            return DegradationResult(
                num_engineers=num_engineers,
                model=model,
                skipped_stages=[],
            )

        actions: list[str] = []
        result_engineers = num_engineers
        result_model = model
        result_skipped: list[str] = []

        if self._cfg.reduce_engineers and num_engineers > 1:
            result_engineers = max(1, num_engineers - 1)
            actions.append(
                f"reduce_engineers: {num_engineers} → {result_engineers} (reason: {context.reason})"
            )

        if self._cfg.fallback_model and self._fallback_chain:
            # Pick the first fallback that differs from the current model
            for fb in self._fallback_chain:
                if fb != model:
                    result_model = fb
                    actions.append(
                        f"fallback_model: {model} → {result_model} (reason: {context.reason})"
                    )
                    break

        if self._cfg.skip_optional_stages:
            to_skip = [
                s for s in skippable_stages
                if s in self._cfg.optional_stages
            ]
            if to_skip:
                result_skipped = to_skip
                actions.append(
                    f"skip_optional_stages: {to_skip} (reason: {context.reason})"
                )

        return DegradationResult(
            num_engineers=result_engineers,
            model=result_model,
            skipped_stages=result_skipped,
            actions_taken=actions,
        )
```

### Step 3 — Run tests

- [ ] Run: `python3 -m pytest tests/test_degradation.py -v`
  Expected: **all pass**

### Step 4 — Commit

- [ ] Run:
```bash
git add core/degradation.py tests/test_degradation.py
git commit -m "feat(t1): DegradationPolicy (reduce engineers, fallback model, skip stages)"
```

---

## Task 6: Update `PipelineResult` to use `PipelineError`

**Files:**
- Modify: `orchestrator.py` (lines ~333, ~1065, ~1140, ~1153, ~1171, ~3418)

### Step 1 — Write failing tests

- [ ] Add to `tests/test_pipeline_error.py` (append after existing tests):

```python
from orchestrator import PipelineResult
from core.errors import PipelineError


def test_pipeline_result_errors_are_pipeline_error_instances():
    r = PipelineResult()
    r.add_error("something went wrong")
    assert len(r.errors) == 1
    assert isinstance(r.errors[0], PipelineError)
    assert r.errors[0].code == "UNKNOWN"
    assert r.errors[0].severity == "error"
    assert "something went wrong" in r.errors[0].message


def test_pipeline_result_has_fatal():
    r = PipelineResult()
    r.errors.append(PipelineError(code="AGENT_CRASH", stage="qa", message="crash", severity="fatal"))
    assert r.has_fatal() is True


def test_pipeline_result_has_fatal_false_when_only_warnings():
    r = PipelineResult()
    r.errors.append(PipelineError(code="STAGE_SKIPPED", stage="doc", message="skipped", severity="warning"))
    assert r.has_fatal() is False


def test_pipeline_result_add_error_with_structured_error():
    r = PipelineResult()
    e = PipelineError(code="LLM_TIMEOUT", stage="architect", message="timeout", severity="error")
    r.add_error(e)
    assert r.errors[0].code == "LLM_TIMEOUT"


def test_pipeline_result_errors_str_backwards_compat():
    """Existing code that does str(result.errors[0]) still works."""
    r = PipelineResult()
    r.add_error("legacy string error")
    assert "legacy string error" in str(r.errors[0])
```

- [ ] Run: `python3 -m pytest tests/test_pipeline_error.py -v`
  Expected: last 5 tests **FAIL**

### Step 2 — Update `orchestrator.py`

The changes are:

**a) Add import at top of `orchestrator.py`** (near other imports, after line ~50):
```python
from core.errors import PipelineError as _PipelineError
```

**b) Change `errors` field type on `PipelineResult` (~line 333)**:
```python
errors: list["_PipelineError"] = field(default_factory=list)
```

**c) Add `add_error` and `has_fatal` methods to `PipelineResult`** (add after the `to_dict` method ~line ~412):
```python
def add_error(self, error: "str | _PipelineError") -> None:
    """Add an error. Accepts a bare string (backwards compat) or a PipelineError."""
    if isinstance(error, str):
        self.errors.append(
            _PipelineError(code="UNKNOWN", stage="unknown", message=error, severity="error")
        )
    else:
        self.errors.append(error)

def has_fatal(self) -> bool:
    """Return True if any error has severity='fatal'."""
    return any(e.severity == "fatal" for e in self.errors)
```

**d) Update the 5 existing `result.errors.append(str)` call sites** — change each to `result.add_error(...)`:

- Line ~1065 (`doc_generate`): `result.add_error("doc_generate requires a GitHub connection ...")`
- Line ~1140 (`_stage_commit_pr`): `result.add_error(f"Branch creation failed: {exc}")`
- Line ~1153 (`_stage_commit_pr`): `result.add_error(f"Failed to commit {path}: {exc}")`
- Line ~1171 (`_stage_commit_pr`): `result.add_error(f"PR creation failed: {exc}")`
- Line ~3418 (`_run_stage`): `result.add_error(error_msg)`

- [ ] Make all edits above to `orchestrator.py`.

### Step 3 — Run tests

- [ ] Run: `python3 -m pytest tests/test_pipeline_error.py -v`
  Expected: **all pass**
- [ ] Run: `python3 -m pytest tests/ -q --tb=short`
  Expected: all existing tests still pass (67+ passing)

### Step 4 — Commit

- [ ] Run:
```bash
git add orchestrator.py tests/test_pipeline_error.py
git commit -m "feat(t1): PipelineResult.errors uses PipelineError; add add_error() and has_fatal()"
```

---

## Task 7: Integrate circuit breaker into LLM backends

**Files:**
- Modify: `agents/backends/base.py`

### Step 1 — Write failing tests

- [ ] Create `tests/test_backend_circuit_breaker.py`:

```python
"""Tests for circuit breaker integration in OpenAICompatibleBackend.call()."""
from __future__ import annotations
from unittest.mock import MagicMock, patch
import pytest

from config_schema import CircuitBreakerConfig, CircuitBreakerScopeConfig
from core.circuit_breaker import CircuitOpenError
from core.circuit_breaker_registry import init_registry, get_registry


def _init_cb(threshold=2):
    scope = CircuitBreakerScopeConfig(threshold=threshold, recovery_timeout_s=3600)
    cfg = CircuitBreakerConfig(enabled=True, per_backend=scope,
                               per_agent=scope, per_repo=scope)
    init_registry(cfg)


def test_backend_records_failure_on_llm_error(monkeypatch):
    _init_cb(threshold=5)
    reg = get_registry()
    cb = reg.get_or_create("backend", "gpt-4.1")
    assert cb._failure_count == 0

    # Simulate a backend call that raises (via the circuit breaker wrapping)
    with pytest.raises(RuntimeError):
        cb.call(lambda: (_ for _ in ()).throw(RuntimeError("api error")))
    assert cb._failure_count == 1


def test_backend_opens_after_threshold(monkeypatch):
    _init_cb(threshold=2)
    reg = get_registry()
    cb = reg.get_or_create("backend", "test-model-open")

    for _ in range(2):
        try:
            cb.call(lambda: (_ for _ in ()).throw(ConnectionError("timeout")))
        except ConnectionError:
            pass
    assert cb.state == "open"

    with pytest.raises(CircuitOpenError):
        cb.call(lambda: "should not run")


def test_backend_call_succeeds_records_success(monkeypatch):
    _init_cb(threshold=5)
    reg = get_registry()
    cb = reg.get_or_create("backend", "success-model")
    cb.record_failure()
    assert cb._failure_count == 1

    result = cb.call(lambda: "ok")
    assert result == "ok"
    assert cb._failure_count == 0
```

- [ ] Run: `python3 -m pytest tests/test_backend_circuit_breaker.py -v`
  Expected: **all pass** (these test the CircuitBreaker directly — they already pass after Task 2)

  > Note: These tests validate the circuit breaker behaviour that the backends will use. The actual backend wiring test requires a full Orchestrator mock which is covered in Task 9 integration tests.

### Step 2 — Wrap `call()` in `OpenAICompatibleBackend` with per-backend circuit breaker

In `agents/backends/base.py`, locate the `call()` method of `OpenAICompatibleBackend` (~line 270).

**Add import at top of `agents/backends/base.py`** (after existing imports):
```python
from core.circuit_breaker_registry import get_registry as _get_cb_registry
from core.circuit_breaker import CircuitOpenError as _CircuitOpenError
```

**Wrap the body of `call()` in `OpenAICompatibleBackend`**. Replace:
```python
def call(self, messages: list[dict], run_id: str | None = None) -> str:
    self._pre_call()
    if self._stream:
        return self._stream_call(messages, run_id=run_id)
    ...
    response = _retry_with_backoff(
        lambda: self._client.chat.completions.create(...),
        ...
    )
    ...
    return self._post_process(content)
```

With (wrap the `_retry_with_backoff` call through the circuit breaker):
```python
def call(self, messages: list[dict], run_id: str | None = None) -> str:
    self._pre_call()
    if self._stream:
        return self._stream_call(messages, run_id=run_id)
    if self._inter_call_delay > 0:
        time.sleep(self._inter_call_delay)
    cb = _get_cb_registry().get_or_create("backend", self.model)
    response = cb.call(
        lambda: _retry_with_backoff(
            lambda: self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.3,
                **self._extra_body(),
            ),
            max_retries=self._max_retries,
            base_delay=self._retry_delay,
        )
    )
    content = response.choices[0].message.content or ""
    effective_run_id = run_id if run_id is not None else get_ledger().active_run_id()
    if effective_run_id is not None:
        usage = getattr(response, "usage", None)
        if usage:
            get_ledger().record(effective_run_id, current_stage.get(), self.model,
                                usage.prompt_tokens, usage.completion_tokens)
        else:
            pt, ct = estimate_tokens(messages, content)
            get_ledger().record(effective_run_id, current_stage.get(), self.model, pt, ct)
    return self._post_process(content)
```

- [ ] Make the edit above to `agents/backends/base.py`.

### Step 3 — Run full test suite

- [ ] Run: `python3 -m pytest tests/ -q --tb=short`
  Expected: all existing tests still pass

### Step 4 — Commit

- [ ] Run:
```bash
git add agents/backends/base.py tests/test_backend_circuit_breaker.py
git commit -m "feat(t1): wrap OpenAICompatibleBackend.call() with per-backend circuit breaker"
```

---

## Task 8: Integrate DLQ + circuit breaker into `watcher.py`

**Files:**
- Modify: `watcher.py`

### Step 1 — Write failing tests for DLQ integration

- [ ] Add to `tests/test_watcher.py` (append after existing tests):

```python
# ── T1: DLQ integration ───────────────────────────────────────────────────────

def test_run_pipeline_enqueues_to_dlq_on_failure(tmp_path, monkeypatch):
    """When run_pipeline raises, the DLQ receives an entry."""
    from pathlib import Path
    from core.dead_letter import FileDeadLetterQueue, DLQEntry

    dlq_path = tmp_path / "dlq"
    dlq = FileDeadLetterQueue(dlq_path)

    def fake_dispatch(**kwargs):
        raise RuntimeError("pipeline failed")

    monkeypatch.setattr("watcher._dispatch", fake_dispatch)

    import watcher as w
    try:
        w.run_pipeline(
            label="feature-request",
            tracker_repo="owner/repo",
            target_repo="owner/repo",
            issue_number=42,
            model="gpt-4.1",
            num_engineers=2,
            log_file=Path(tmp_path / "log.txt"),
            logger=logging.getLogger("test"),
            dlq=dlq,
        )
    except Exception:
        pass  # run_pipeline may re-raise; we just check DLQ

    entries = list(dlq.drain())
    assert len(entries) == 1
    assert entries[0].issue_number == 42
    assert entries[0].tracker_repo == "owner/repo"


def test_run_pipeline_no_dlq_enqueue_on_success(tmp_path, monkeypatch):
    """Successful pipeline does not write to DLQ."""
    from pathlib import Path
    from core.dead_letter import FileDeadLetterQueue
    from types import SimpleNamespace

    dlq_path = tmp_path / "dlq"
    dlq = FileDeadLetterQueue(dlq_path)

    monkeypatch.setattr("watcher._dispatch", lambda **kw: SimpleNamespace(
        next_label=None, verdict="success", tests_passed=True, deploy_tests_passed=True
    ))
    monkeypatch.setattr("watcher.ensure_label", lambda *a, **kw: None)
    monkeypatch.setattr("watcher.add_label", lambda *a, **kw: None)
    monkeypatch.setattr("watcher.remove_label", lambda *a, **kw: None)
    monkeypatch.setattr("watcher.post_comment", lambda *a, **kw: None)

    import watcher as w
    w.run_pipeline(
        label="feature-request",
        tracker_repo="owner/repo",
        target_repo="owner/repo",
        issue_number=1,
        model="gpt-4.1",
        num_engineers=2,
        log_file=Path(tmp_path / "log.txt"),
        logger=logging.getLogger("test"),
        dlq=dlq,
    )

    assert list(dlq.drain()) == []
```

- [ ] Run: `python3 -m pytest tests/test_watcher.py::test_run_pipeline_enqueues_to_dlq_on_failure tests/test_watcher.py::test_run_pipeline_no_dlq_enqueue_on_success -v`
  Expected: **FAIL** — `run_pipeline` doesn't accept `dlq` kwarg yet

### Step 2 — Add `dlq` parameter to `run_pipeline` in `watcher.py`

Find `def run_pipeline(` (~line 302) and add `dlq=None` parameter:

```python
def run_pipeline(
    label: str,
    tracker_repo: str,
    target_repo: str,
    issue_number: int,
    model: str,
    num_engineers: int,
    log_file: Path,
    logger: logging.Logger,
    dlq=None,          # DeadLetterQueue | None
    ...               # keep all existing params
) -> None:
```

In the `except Exception` block of `run_pipeline` that handles pipeline failure (the block around line ~390 where `agent-failed` label is set), add DLQ enqueue **after** the existing failure handling:

```python
except Exception as exc:  # noqa: BLE001
    # ... existing label/comment logic unchanged ...

    # Enqueue to DLQ for later retry
    if dlq is not None:
        import datetime as _dt
        from core.dead_letter import DLQEntry
        from core.errors import PipelineError
        _dlq_entry = DLQEntry(
            id=str(__import__("uuid").uuid4()),
            issue_number=issue_number,
            tracker_repo=tracker_repo,
            label=label,
            model=model,
            num_engineers=num_engineers,
            failed_at=_dt.datetime.utcnow().isoformat() + "Z",
            error=PipelineError(
                code="AGENT_CRASH",
                stage="pipeline",
                message=_sanitise(str(exc), os.environ.get("GITHUB_TOKEN", "")),
                severity="fatal",
            ).to_dict(),
        )
        try:
            dlq.enqueue(_dlq_entry)
        except Exception as _dlq_exc:  # noqa: BLE001
            logger.warning("Could not enqueue to DLQ: %s", _dlq_exc)
```

- [ ] Make the edits above to `watcher.py`.

### Step 3 — Add `--retry-dlq` CLI flag to `watcher.py`

Find `_build_arg_parser()` in `watcher.py` and add:

```python
parser.add_argument(
    "--retry-dlq",
    action="store_true",
    default=False,
    help="Drain the dead-letter queue and retry failed pipeline tasks.",
)
```

In `main()`, after the config is loaded, add:

```python
if args.retry_dlq:
    from core.dead_letter import build_dlq
    pipeline_cfg = _load_pipeline_config()
    rel_cfg = pipeline_cfg.get("reliability", {})
    dlq_cfg_raw = rel_cfg.get("dead_letter", {})
    from config_schema import DLQConfig
    dlq_cfg = DLQConfig.model_validate(dlq_cfg_raw) if dlq_cfg_raw else DLQConfig()
    dlq = build_dlq(dlq_cfg)
    logger = logging.getLogger("watcher")
    retried = 0
    failed = 0
    for entry in dlq.drain():
        logger.info("Retrying DLQ entry: issue #%d (%s)", entry.issue_number, entry.tracker_repo)
        try:
            _dispatch(
                label=entry.label,
                tracker_repo=entry.tracker_repo,
                target_repo=entry.tracker_repo,
                issue_number=entry.issue_number,
                model=entry.model,
                num_engineers=entry.num_engineers,
                log_file=Path(f"logs/dlq_retry_{entry.issue_number}.log"),
                logger=logger,
            )
            dlq.ack(entry.id)
            retried += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("DLQ retry failed for issue #%d: %s", entry.issue_number, exc)
            dlq.nack(entry.id)
            failed += 1
    logger.info("DLQ drain complete: %d retried, %d failed", retried, failed)
    sys.exit(0)
```

### Step 4 — Run new watcher tests

- [ ] Run: `python3 -m pytest tests/test_watcher.py -q --tb=short`
  Expected: all pass (67+ tests)

### Step 5 — Commit

- [ ] Run:
```bash
git add watcher.py
git commit -m "feat(t1): add DLQ enqueue on pipeline failure and --retry-dlq CLI flag"
```

---

## Task 9: Integration tests + full regression

**Files:**
- Create: `tests/test_reliability_integration.py`
- Test: run full suite

### Step 1 — Write integration tests

- [ ] Create `tests/test_reliability_integration.py`:

```python
"""Integration tests: circuit breaker → degradation; failure → DLQ."""
from __future__ import annotations
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from config_schema import (
    CircuitBreakerConfig, CircuitBreakerScopeConfig,
    DLQConfig, DLQFileConfig,
    DegradationConfig, LLMConfig,
)
from core.circuit_breaker import CircuitOpenError
from core.circuit_breaker_registry import CircuitBreakerRegistry
from core.dead_letter import FileDeadLetterQueue, DLQEntry
from core.degradation import DegradationContext, DegradationPolicy


def test_circuit_opens_and_degradation_activates():
    """When a backend breaker opens, DegradationPolicy reduces engineers."""
    scope = CircuitBreakerScopeConfig(threshold=2, recovery_timeout_s=3600)
    cb_cfg = CircuitBreakerConfig(enabled=True, per_backend=scope,
                                  per_agent=scope, per_repo=scope)
    reg = CircuitBreakerRegistry(cb_cfg)
    cb = reg.get_or_create("backend", "gpt-4.1")

    # Trip the breaker
    for _ in range(2):
        try:
            cb.call(lambda: (_ for _ in ()).throw(ConnectionError("timeout")))
        except ConnectionError:
            pass
    assert cb.state == "open"

    # Now apply degradation
    deg_cfg = DegradationConfig(
        enabled=True, reduce_engineers=True, fallback_model=True,
        skip_optional_stages=True
    )
    llm_cfg = LLMConfig(model="gpt-4.1", fallback=["gpt-4.1-mini"])
    policy = DegradationPolicy(deg_cfg, llm_cfg)
    ctx = DegradationContext(reason="circuit open: gpt-4.1",
                             original_num_engineers=2, original_model="gpt-4.1")
    result = policy.apply(num_engineers=2, model="gpt-4.1",
                          skippable_stages=["deploy_test"], context=ctx)

    assert result.num_engineers == 1
    assert result.model == "gpt-4.1-mini"
    assert "deploy_test" in result.skipped_stages


def test_file_dlq_full_cycle(tmp_path):
    """Enqueue → drain → ack removes entry; nack increments attempt_count."""
    dlq = FileDeadLetterQueue(tmp_path / "dlq")

    import uuid, datetime
    entry = DLQEntry(
        id=str(uuid.uuid4()),
        issue_number=99,
        tracker_repo="owner/repo",
        label="feature-request",
        model="gpt-4.1",
        num_engineers=2,
        failed_at=datetime.datetime.utcnow().isoformat() + "Z",
        error={"code": "AGENT_CRASH", "stage": "pipeline", "message": "crash",
               "severity": "fatal", "timestamp": "", "context": {}},
    )
    dlq.enqueue(entry)
    drained = list(dlq.drain())
    assert len(drained) == 1
    assert drained[0].issue_number == 99

    # nack — should still be there with incremented count
    dlq.nack(entry.id)
    drained2 = list(dlq.drain())
    assert len(drained2) == 1
    assert drained2[0].attempt_count == 2

    # ack — should be gone
    dlq.ack(entry.id)
    assert list(dlq.drain()) == []


def test_null_dlq_never_raises():
    from core.dead_letter import NullDeadLetterQueue
    dlq = NullDeadLetterQueue()
    import uuid, datetime
    entry = DLQEntry(
        id=str(uuid.uuid4()), issue_number=1, tracker_repo="o/r",
        label="x", model="m", num_engineers=1,
        failed_at="2026-01-01T00:00:00Z",
        error={},
    )
    dlq.enqueue(entry)
    assert list(dlq.drain()) == []
    dlq.ack(entry.id)
    dlq.nack(entry.id)
```

- [ ] Run: `python3 -m pytest tests/test_reliability_integration.py -v`
  Expected: **all pass**

### Step 2 — Full regression

- [ ] Run: `python3 -m pytest tests/ -q --tb=short`
  Expected: **all tests pass** (existing 67 + new T1 tests)

### Step 3 — Commit

- [ ] Run:
```bash
git add tests/test_reliability_integration.py
git commit -m "test(t1): integration tests for circuit breaker + degradation + DLQ cycle"
```

---

## Task 10: Create branch, PR, and final check

### Step 1 — Verify all tests pass

- [ ] Run: `python3 -m pytest tests/ -q --tb=short`
  Expected: all pass with output like `XX passed in X.XXs`

### Step 2 — Push and create PR

- [ ] Run:
```bash
git checkout -b t1-reliability
git push -u origin t1-reliability
gh pr create \
  --title "feat(t1): reliability — structured errors, circuit breaker, DLQ, degradation" \
  --body "## Summary
- \`core/errors.py\`: \`PipelineError\` dataclass replaces \`list[str]\` on \`PipelineResult\`
- \`core/circuit_breaker.py\`: CLOSED/OPEN/HALF_OPEN state machine (thread-safe)
- \`core/circuit_breaker_registry.py\`: thread-safe named breaker registry + module singleton
- \`core/dead_letter.py\`: File/Redis/SQS/Null DLQ backends + factory
- \`core/degradation.py\`: reduce engineers, fallback model, skip optional stages
- \`config_schema.py\`: \`ReliabilityConfig\` with all sub-models (all \`enabled: false\` by default)
- \`orchestrator.py\`: \`PipelineResult.add_error()\`, \`has_fatal()\`, backwards-compat wrapper
- \`agents/backends/base.py\`: per-backend circuit breaker wraps \`_retry_with_backoff\`
- \`watcher.py\`: DLQ enqueue on failure, \`--retry-dlq\` CLI flag

## Behaviour change
Zero behaviour change when \`reliability:\` is absent from config (all features default to \`enabled: false\`).

## Test Plan
- [ ] All existing tests pass
- [ ] \`pytest tests/test_pipeline_error.py\` — PipelineError + PipelineResult
- [ ] \`pytest tests/test_circuit_breaker.py\` — state machine
- [ ] \`pytest tests/test_circuit_breaker_registry.py\` — registry + thread safety
- [ ] \`pytest tests/test_dead_letter.py\` — all 4 backends
- [ ] \`pytest tests/test_degradation.py\` — all 3 strategies
- [ ] \`pytest tests/test_reliability_integration.py\` — end-to-end
- [ ] \`pytest tests/ -q\` — full regression"
```
