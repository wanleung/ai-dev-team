# T1: Reliability & Error Handling — Design Spec

> **For agentic workers:** This is a spec document. Use superpowers:writing-plans to create the implementation plan, then superpowers:subagent-driven-development to execute it.

**Track:** T1 of 6 (full roadmap: T1 Reliability → T2 Security → T3 Observability → T4 Agent Quality → T5 Pipeline → T6 Operations)

**Goal:** Add structured error handling, circuit breakers (per-agent, per-repo, per-LLM-backend), a pluggable dead-letter queue (file/Redis/SQS), and configurable graceful degradation — all opt-in via `config.yaml` with sane defaults of disabled.

---

## 1. Structured Error Handling

### 1.1 `PipelineError` Dataclass

Replace the current `errors: list[str]` on `PipelineResult` with a structured type.

**New file:** `core/errors.py`

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Literal
import datetime

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
    stage: str                   # e.g. "architect", "engineer_1", "qa"
    message: str
    severity: Literal["warning", "error", "fatal"]
    timestamp: str = field(default_factory=lambda: datetime.datetime.utcnow().isoformat() + "Z")
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
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

### 1.2 `PipelineResult` Changes

`orchestrator.py` currently has `errors: list[str]`. Change to `errors: list[PipelineError]`. The `__str__` on `PipelineError` ensures all existing logging/display code continues to work. Add a helper:

```python
def has_fatal(self) -> bool:
    return any(e.severity == "fatal" for e in self.errors)
```

### 1.3 Backwards Compatibility

`add_error(message: str)` convenience method is kept but now wraps the string as `PipelineError(code="UNKNOWN", stage="unknown", message=message, severity="error")`. This means existing callers need no immediate changes.

---

## 2. Circuit Breaker

### 2.1 Design

**New file:** `core/circuit_breaker.py`

Three states: `CLOSED` (normal) → `OPEN` (failing, reject calls) → `HALF_OPEN` (probe one call after recovery timeout).

```python
class CircuitBreaker:
    def __init__(self, name: str, threshold: int, recovery_timeout_s: int): ...

    def call(self, fn: Callable, *args, **kwargs) -> Any:
        """Execute fn through the breaker. Raises CircuitOpenError if OPEN."""

    def record_success(self) -> None: ...
    def record_failure(self) -> None: ...

    @property
    def state(self) -> Literal["closed", "open", "half_open"]: ...
```

**`CircuitOpenError`** — raised when a call is attempted while the circuit is OPEN. Callers catch this and apply degradation policy.

### 2.2 Registry

**New file:** `core/circuit_breaker_registry.py`

```python
class CircuitBreakerRegistry:
    """Thread-safe registry of named circuit breakers."""

    def get_or_create(
        self,
        scope: Literal["agent", "repo", "backend"],
        name: str,
        cfg: CircuitBreakerConfig,
    ) -> CircuitBreaker: ...

    def get_all_states(self) -> dict[str, str]: ...  # for metrics/health
    def reset(self, scope: str, name: str) -> None: ...  # for admin/testing
```

### 2.3 Integration Points

- **`Orchestrator._call_agent()`** — wraps each agent call through `registry.get_or_create("agent", agent_name, cfg).call(fn)`. On `CircuitOpenError`, logs `PipelineError(code="LLM_CIRCUIT_OPEN", ...)` and applies degradation.
- **`agents/backends/`** — each backend's `call()` / `complete()` wraps the HTTP request through `registry.get_or_create("backend", model_name, cfg).call(fn)`.
- **`watcher.py`** — wraps `_get_issues_by_label()` and GitHub label calls through `registry.get_or_create("repo", tracker_repo, cfg).call(fn)`.

### 2.4 Config Schema

```yaml
reliability:
  circuit_breaker:
    enabled: false          # master switch
    per_agent:
      threshold: 5          # failures before opening
      recovery_timeout_s: 60
    per_repo:
      threshold: 3
      recovery_timeout_s: 120
    per_backend:
      threshold: 10
      recovery_timeout_s: 300
```

Add `CircuitBreakerConfig`, `CircuitBreakerScopeConfig`, and `ReliabilityConfig` Pydantic models to `config_schema.py`.

---

## 3. Dead-Letter Queue

### 3.1 Design

**New file:** `core/dead_letter.py`

```python
@dataclass
class DLQEntry:
    id: str                      # uuid4
    issue_number: int
    tracker_repo: str
    label: str
    model: str
    num_engineers: int
    failed_at: str               # ISO timestamp
    error: dict                  # PipelineError.to_dict()
    attempt_count: int = 1

class DeadLetterQueue(ABC):
    @abstractmethod
    def enqueue(self, entry: DLQEntry) -> None: ...

    @abstractmethod
    def drain(self) -> Iterator[DLQEntry]: ...

    @abstractmethod
    def ack(self, entry_id: str) -> None: ...   # remove after successful retry

    @abstractmethod
    def nack(self, entry_id: str) -> None: ...  # increment attempt_count, re-enqueue


class FileDeadLetterQueue(DeadLetterQueue):
    """Stores entries as JSON files in workspace/dlq/. Default backend."""

class RedisDeadLetterQueue(DeadLetterQueue):
    """Uses a Redis list. Requires `redis` package (optional import)."""

class SQSDeadLetterQueue(DeadLetterQueue):
    """Uses AWS SQS. Requires `boto3` package (optional import)."""


def build_dlq(cfg: DLQConfig) -> DeadLetterQueue:
    """Factory: returns the configured backend. Returns NullDeadLetterQueue if disabled."""
```

`NullDeadLetterQueue` — no-op implementation used when DLQ is disabled (avoids None checks everywhere).

### 3.2 Integration

- **`watcher.py`**: on pipeline failure (after all retries exhausted), call `dlq.enqueue(DLQEntry(...))`.
- **`watcher.py` `--retry-dlq` flag**: drain the DLQ, re-dispatch each entry via `_dispatch()`, `ack` on success, `nack` on failure.

### 3.3 Config Schema

```yaml
reliability:
  dead_letter:
    enabled: false
    backend: file               # file | redis | sqs
    max_attempts: 3             # entries with attempt_count >= this are dropped
    file:
      path: workspace/dlq
    redis:
      url: "redis://localhost:6379"
      key: "ai-swhouse:dlq"
      ttl_s: 604800             # 7 days
    sqs:
      queue_url: "https://sqs.eu-west-1.amazonaws.com/123/ai-swhouse-dlq"
      region: "eu-west-1"
```

---

## 4. Graceful Degradation

### 4.1 Design

**New file:** `core/degradation.py`

```python
@dataclass
class DegradationContext:
    reason: str                          # e.g. "circuit open: gpt-4o"
    original_num_engineers: int
    original_model: str

class DegradationPolicy:
    def __init__(self, cfg: DegradationConfig, llm_cfg: LLMConfig): ...

    def apply(
        self,
        num_engineers: int,
        model: str,
        skippable_stages: list[str],
        context: DegradationContext,
    ) -> DegradationResult: ...

@dataclass
class DegradationResult:
    num_engineers: int
    model: str
    skipped_stages: list[str]
    actions_taken: list[str]   # human-readable log of what changed
```

### 4.2 Degradation Strategies (all configurable, applied in order)

1. **`reduce_engineers`** — if `num_engineers > 1`, reduce to `max(1, num_engineers - 1)`.
2. **`fallback_model`** — if `llm.fallback` list is configured, substitute the next model in the fallback chain.
3. **`skip_optional_stages`** — mark stages in `degradation.optional_stages` list as skipped; `PipelineError(code="STAGE_SKIPPED", severity="warning")` is recorded.

### 4.3 Integration

`Orchestrator` receives a `DegradationPolicy` instance. On catching `CircuitOpenError`, it calls `policy.apply(...)` and continues with the degraded parameters. A `PipelineError(code="DEGRADATION_APPLIED", severity="warning")` is appended.

### 4.4 Config Schema

```yaml
reliability:
  degradation:
    enabled: false
    reduce_engineers: true
    fallback_model: true
    skip_optional_stages: true
    optional_stages:
      - deploy_test
      - documentation
```

---

## 5. Config Schema Changes (`config_schema.py`)

Add these Pydantic models and wire into `AppConfig`:

```python
class CircuitBreakerScopeConfig(BaseModel):
    threshold: int = 5
    recovery_timeout_s: int = 60

class CircuitBreakerConfig(BaseModel):
    enabled: bool = False
    per_agent: CircuitBreakerScopeConfig = Field(default_factory=CircuitBreakerScopeConfig)
    per_repo: CircuitBreakerScopeConfig = Field(default_factory=lambda: CircuitBreakerScopeConfig(threshold=3, recovery_timeout_s=120))
    per_backend: CircuitBreakerScopeConfig = Field(default_factory=lambda: CircuitBreakerScopeConfig(threshold=10, recovery_timeout_s=300))

class DLQFileConfig(BaseModel):
    path: str = "workspace/dlq"

class DLQRedisConfig(BaseModel):
    url: str = "redis://localhost:6379"
    key: str = "ai-swhouse:dlq"
    ttl_s: int = 604800

class DLQSQSConfig(BaseModel):
    queue_url: str
    region: str = "eu-west-1"

class DLQConfig(BaseModel):
    enabled: bool = False
    backend: Literal["file", "redis", "sqs"] = "file"
    max_attempts: int = 3
    file: DLQFileConfig = Field(default_factory=DLQFileConfig)
    redis: Optional[DLQRedisConfig] = None
    sqs: Optional[DLQSQSConfig] = None

class DegradationConfig(BaseModel):
    enabled: bool = False
    reduce_engineers: bool = True
    fallback_model: bool = True
    skip_optional_stages: bool = True
    optional_stages: list[str] = Field(default_factory=lambda: ["deploy_test", "documentation"])

class ReliabilityConfig(BaseModel):
    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)
    dead_letter: DLQConfig = Field(default_factory=DLQConfig)
    degradation: DegradationConfig = Field(default_factory=DegradationConfig)

# In AppConfig:
reliability: Optional[ReliabilityConfig] = None
```

---

## 6. New Files Summary

| File | Responsibility |
|------|---------------|
| `core/__init__.py` | Package init |
| `core/errors.py` | `PipelineError` dataclass, `ERROR_CODES` |
| `core/circuit_breaker.py` | `CircuitBreaker`, `CircuitOpenError` state machine |
| `core/circuit_breaker_registry.py` | Thread-safe registry of named breakers |
| `core/dead_letter.py` | `DeadLetterQueue` ABC + File/Redis/SQS/Null backends |
| `core/degradation.py` | `DegradationPolicy`, `DegradationResult` |

### Modified Files

| File | Change |
|------|--------|
| `config_schema.py` | Add `ReliabilityConfig` and sub-models; add to `AppConfig` |
| `orchestrator.py` | `errors: list[PipelineError]`; integrate circuit breaker + degradation |
| `watcher.py` | Integrate DLQ on pipeline failure; circuit breaker for GitHub API calls; `--retry-dlq` flag |
| `agents/backends/*.py` | Wrap HTTP calls through `per_backend` circuit breaker |

---

## 7. Testing Strategy

### Unit Tests (`tests/test_circuit_breaker.py`)
- CLOSED → OPEN after threshold failures
- OPEN → HALF_OPEN after recovery_timeout_s
- HALF_OPEN → CLOSED on success; → OPEN on failure
- `CircuitOpenError` raised when OPEN
- Registry returns same breaker for same scope+name
- Registry is thread-safe (concurrent calls)

### Unit Tests (`tests/test_dead_letter.py`)
- `FileDeadLetterQueue`: enqueue writes JSON, drain reads all, ack deletes, nack increments count
- `RedisDeadLetterQueue`: mock redis client, verify lpush/lrange/lrem calls
- `SQSDeadLetterQueue`: mock boto3, verify send_message/receive_message/delete_message
- `NullDeadLetterQueue`: all methods are no-ops
- `build_dlq`: returns correct backend based on config

### Unit Tests (`tests/test_degradation.py`)
- `reduce_engineers`: 2→1; already at 1→stays 1
- `fallback_model`: substitutes from `llm.fallback` list
- `skip_optional_stages`: adds stages to skipped_stages
- All three combined: actions_taken lists all changes
- Disabled policy: returns original values unchanged

### Unit Tests (`tests/test_pipeline_error.py`)
- `PipelineError.to_dict()` round-trips correctly
- `__str__` format matches expected pattern
- `has_fatal()` returns True only when fatal error present

### Integration Tests (`tests/test_reliability_integration.py`)
- Circuit open → degradation activates → pipeline continues with fewer engineers
- All retries exhausted → DLQ receives entry
- `--retry-dlq` drains DLQ and re-dispatches

### Regression
- All existing 67 tests must still pass
- `add_error(str)` backwards-compat wrapper works

---

## 8. Acceptance Criteria

1. `PipelineError` replaces `list[str]` on `PipelineResult`; all callers updated
2. `CircuitBreaker` transitions states correctly (unit tests green)
3. `CircuitBreakerRegistry` is thread-safe (concurrent test green)
4. All three circuit breaker scopes (agent/repo/backend) integrate at correct call sites
5. File, Redis, SQS, and Null DLQ backends work; `build_dlq` factory returns correct type
6. `--retry-dlq` flag drains file DLQ and re-dispatches
7. `DegradationPolicy` applies all three strategies in combination
8. All config fields are optional with `enabled: false` defaults (no behaviour change without config)
9. Existing 67 tests still pass
