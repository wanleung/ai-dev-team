# T3-C: Core Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire two isolated core subsystems into the main execution loop: (1) `AgentHealthMonitor.is_unhealthy()` should automatically open the circuit breaker for that agent (not just print a warning); (2) the two-stage review gate pattern from the superpowers `subagent-driven-development` skill should be applied to pipeline outputs — a lightweight `OutputVerifier` checks structured output fields before the stage is marked complete.

**Architecture:**
- Task 1: In `orchestrator.py._run_stage()`, when `_agent_health.is_unhealthy(name)`, call `get_registry().get_or_create("agent", name).record_failure()` enough times to trip the breaker (or add a `force_open()` method to `CircuitBreaker`). The CB will then block subsequent calls to the same agent, triggering the fallback backend chain.
- Task 2: Add `core/output_verifier.py` — a lightweight `OutputVerifier` that checks `PipelineResult` fields (not None, not empty string) after each stage runs. Called from `_run_stage()` after success. Configurable per-stage via a `required_fields: list[str]` on `PipelineStage`. Inspired by the superpowers "verification-before-completion" skill principle: evidence before assertions.

**Tech Stack:** Python 3.11+, pytest. No new dependencies.

**Branch:** `t3-c-integration` (from master)

---

### Task 1: Wire `AgentHealthMonitor` → Circuit Breaker auto-open

**Files:**
- Modify: `core/circuit_breaker.py` (add `force_open()` method)
- Modify: `orchestrator.py` (`_run_stage()` ~line 3579 health check block)
- Test: `tests/test_agent_health.py` (add 2 tests)

**Context:** When `_agent_health.is_unhealthy(name)` returns True (3 consecutive failures by default), the orchestrator currently prints a yellow warning but takes no protective action. The circuit breaker for that agent sits at 0 failures. Fix: add `CircuitBreaker.force_open()` and call it from `_run_stage()` when health threshold is crossed. Future calls to the same agent will hit `CircuitOpenError`, which `FallbackLLMBackend` uses to switch to the next backend.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_agent_health.py`:

```python
def test_unhealthy_agent_triggers_circuit_breaker_open(tmp_path):
    """When AgentHealthMonitor marks an agent unhealthy, the circuit breaker opens."""
    from core.agent_health import AgentHealthMonitor
    from core.circuit_breaker import CircuitBreaker, CircuitOpenError
    from core.circuit_breaker_registry import CircuitBreakerRegistry
    from config_schema import CircuitBreakerConfig, PerScopeConfig

    cfg = CircuitBreakerConfig(
        enabled=True,
        per_agent=PerScopeConfig(threshold=10, recovery_timeout_s=60),
        per_repo=PerScopeConfig(threshold=10, recovery_timeout_s=60),
        per_backend=PerScopeConfig(threshold=10, recovery_timeout_s=60),
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
    import pytest
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
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/wanleung/Projects/ai-software-house
python3 -m pytest tests/test_agent_health.py::test_unhealthy_agent_triggers_circuit_breaker_open tests/test_agent_health.py::test_force_open_is_idempotent -v
```

Expected: `AttributeError: 'CircuitBreaker' object has no attribute 'force_open'`

- [ ] **Step 3: Add `force_open()` to `CircuitBreaker`**

In `core/circuit_breaker.py`, add this method to the `CircuitBreaker` class after `record_failure()`:

```python
def force_open(self) -> None:
    """Immediately trip the circuit breaker to OPEN state.

    Used by AgentHealthMonitor to open the breaker when an agent exceeds
    its consecutive-failure threshold, without requiring the breaker's own
    threshold to be reached.

    Emits a CircuitBreakerEvent if transitioning from a non-open state.
    """
    with self._lock:
        prior_state = self._state_unlocked()
        if prior_state != "open":
            self._failure_count = self._threshold  # ensure _state_unlocked returns "open"
            self._last_failure_time = time.monotonic()
            _cb_emit(
                name=self.name,
                event="tripped",
                state="open",
                failure_count=self._failure_count,
            )
```

Note: check the actual field names in `core/circuit_breaker.py` before implementing — `_failure_count`, `_threshold`, and `_last_failure_time` must match the real attribute names.

- [ ] **Step 4: Run tests to confirm `force_open` works**

```bash
python3 -m pytest tests/test_agent_health.py -v
```

Expected: All pass (existing + 2 new).

- [ ] **Step 5: Wire health monitor → CB in `_run_stage()`**

In `orchestrator.py`, find the `is_unhealthy` block (around line 3579):

**Before:**
```python
                if hasattr(self, "_agent_health"):
                    self._agent_health.record_failure(name)
                    if self._agent_health.is_unhealthy(name):
                        console.print(
                            f"  ⚠️  [yellow]{name} has failed "
                            f"{self._agent_health.failure_count(name)} consecutive times — "
                            f"consider applying degradation policy[/yellow]"
                        )
```

**After:**
```python
                if hasattr(self, "_agent_health"):
                    self._agent_health.record_failure(name)
                    if self._agent_health.is_unhealthy(name):
                        console.print(
                            f"  ⚠️  [yellow]{name} has failed "
                            f"{self._agent_health.failure_count(name)} consecutive times — "
                            f"tripping circuit breaker for '{name}'[/yellow]"
                        )
                        from core.circuit_breaker_registry import get_registry
                        get_registry().get_or_create("agent", name).force_open()
```

- [ ] **Step 6: Run full test suite to verify no regressions**

```bash
python3 -m pytest tests/test_agent_health.py tests/test_circuit_breaker.py tests/test_orchestrator_deploy_loop.py tests/test_orchestrator_parallel.py -v
```

Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add core/circuit_breaker.py orchestrator.py tests/test_agent_health.py
git commit -m "feat(health): wire AgentHealthMonitor to auto-open circuit breaker on threshold"
```

---

### Task 2: Add `OutputVerifier` — stage output validation gate

**Files:**
- Create: `core/output_verifier.py`
- Modify: `orchestrator.py` (`PipelineStage` dataclass ~line 444; `_run_stage()` ~line 3560)
- Test: `tests/test_output_verifier.py` (new)

**Context:** Inspired by the superpowers `verification-before-completion` skill: "NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE." Pipeline stages currently mark themselves complete as soon as they return without raising. But agents sometimes return silently with empty fields (e.g. `result.prd = None`, `result.architecture = ""`). Add an `OutputVerifier` that checks specified `PipelineResult` fields after each stage and raises `ValueError` if a required field is falsy. This turns silent data-quality failures into explicit stage failures.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_output_verifier.py
"""Tests for OutputVerifier — post-stage field validation gate."""
from __future__ import annotations

import pytest
from core.output_verifier import OutputVerifier, OutputVerificationError


def _make_result(**kwargs):
    """Return a minimal namespace object for testing."""
    class _R:
        pass
    r = _R()
    for k, v in kwargs.items():
        setattr(r, k, v)
    return r


def test_verify_passes_when_all_fields_present():
    """No exception when all required fields are non-empty."""
    result = _make_result(prd="A product doc", architecture="Arch diagram")
    verifier = OutputVerifier(required_fields=["prd", "architecture"])
    verifier.verify(result, stage_name="architect")  # should not raise


def test_verify_raises_on_none_field():
    """OutputVerificationError raised when a required field is None."""
    result = _make_result(prd=None)
    verifier = OutputVerifier(required_fields=["prd"])
    with pytest.raises(OutputVerificationError, match="prd"):
        verifier.verify(result, stage_name="product_manager")


def test_verify_raises_on_empty_string_field():
    """OutputVerificationError raised when a required field is an empty string."""
    result = _make_result(architecture="")
    verifier = OutputVerifier(required_fields=["architecture"])
    with pytest.raises(OutputVerificationError, match="architecture"):
        verifier.verify(result, stage_name="architect")


def test_verify_raises_on_empty_list_field():
    """OutputVerificationError raised when a required field is an empty list."""
    result = _make_result(modules=[])
    verifier = OutputVerifier(required_fields=["modules"])
    with pytest.raises(OutputVerificationError, match="modules"):
        verifier.verify(result, stage_name="tier_review")


def test_verify_skips_missing_attribute_with_warning():
    """If the result object lacks the field entirely, warn but do not raise."""
    import warnings
    result = _make_result()  # no attributes
    verifier = OutputVerifier(required_fields=["prd"])
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        verifier.verify(result, stage_name="product_manager")
    assert any("prd" in str(warning.message) for warning in w)


def test_empty_required_fields_always_passes():
    """OutputVerifier with no required_fields is a no-op."""
    result = _make_result()
    verifier = OutputVerifier(required_fields=[])
    verifier.verify(result, stage_name="any_stage")  # should not raise
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python3 -m pytest tests/test_output_verifier.py -v
```

Expected: `ModuleNotFoundError: No module named 'core.output_verifier'`

- [ ] **Step 3: Create `core/output_verifier.py`**

```python
"""Stage output verification gate.

Inspired by the superpowers verification-before-completion principle:
"NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE."

After a pipeline stage runs successfully, OutputVerifier checks that the
PipelineResult fields the stage is responsible for are non-falsy. If any
required field is absent or empty, it raises OutputVerificationError so the
stage is treated as failed rather than silently completing with missing data.
"""
from __future__ import annotations

import warnings


class OutputVerificationError(ValueError):
    """Raised when a required PipelineResult field is missing or empty after a stage."""

    def __init__(self, stage_name: str, field: str) -> None:
        super().__init__(
            f"[{stage_name}] Required output field '{field}' is empty or None after stage completed. "
            f"The stage may have failed silently."
        )
        self.stage_name = stage_name
        self.field = field


class OutputVerifier:
    """Checks that named PipelineResult fields are non-falsy after a stage completes.

    Args:
        required_fields: List of attribute names on PipelineResult that must be
            non-falsy (not None, not empty string, not empty list/dict).
    """

    def __init__(self, required_fields: list[str]) -> None:
        self._required = required_fields

    def verify(self, result: object, stage_name: str) -> None:
        """Assert that all required fields on *result* are non-falsy.

        Args:
            result: A PipelineResult (or any object) to inspect.
            stage_name: Human-readable stage identifier for error messages.

        Raises:
            OutputVerificationError: If any required field is None, empty string,
                or empty collection.
        """
        for field in self._required:
            if not hasattr(result, field):
                warnings.warn(
                    f"[output_verifier] Stage '{stage_name}' declares required field "
                    f"'{field}' but PipelineResult has no such attribute — skipping check.",
                    stacklevel=2,
                )
                continue
            value = getattr(result, field)
            if not value:
                raise OutputVerificationError(stage_name, field)
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/test_output_verifier.py -v
```

Expected: All 6 pass.

- [ ] **Step 5: Add `required_fields` to `PipelineStage` and wire `OutputVerifier` into `_run_stage()`**

In `orchestrator.py`, find the `PipelineStage` dataclass (around line 444) and add the new field:

```python
@dataclass
class PipelineStage:
    name: str
    label: str
    description: str
    checkpoint_key: str
    fn: Callable
    skip_if: Callable | None = None
    stop_if: Callable | None = None
    loop_stages: list[str] = field(default_factory=list)
    loop_until: str = ""
    loop_max: int = 5
    parallel_group: str | None = None
    timeout_s: float | None = None
    # Fields that must be non-empty on PipelineResult after this stage completes.
    # Empty list = no verification (default, backward-compatible).
    required_output_fields: list[str] = field(default_factory=list)
```

In `_run_stage()`, after the success path (after `console.print(f"  ✅ [green]{name}[/green] complete")`), add verification:

```python
            console.print(f"  ✅ [green]{name}[/green] complete")
            if hasattr(self, "_agent_health"):
                self._agent_health.record_success(name)
```

becomes:

```python
            console.print(f"  ✅ [green]{name}[/green] complete")
            if hasattr(self, "_agent_health"):
                self._agent_health.record_success(name)
```

Note: `_run_stage()` doesn't currently receive the `PipelineStage` object — it receives `name`, `description`, `result`, and `fn`. The `required_output_fields` check needs to be wired from the call site in `run()` or `_run_stage_safe()`. The cleanest approach: pass `required_output_fields` as an optional argument to `_run_stage()`.

Update `_run_stage()` signature:

```python
def _run_stage(
    self,
    name: str,
    description: str,
    result: PipelineResult,
    fn: Callable,
    timeout_s: float | None = None,
    required_output_fields: list[str] | None = None,
) -> None:
```

After the success line inside `_run_stage()`:

```python
            console.print(f"  ✅ [green]{name}[/green] complete")
            if required_output_fields:
                from core.output_verifier import OutputVerifier, OutputVerificationError
                try:
                    OutputVerifier(required_output_fields).verify(result, name)
                except OutputVerificationError as ove:
                    result.add_error(str(ove))
                    console.print(f"  ❌ [red]{ove}[/red]")
                    return
            if hasattr(self, "_agent_health"):
                self._agent_health.record_success(name)
```

Update the call sites in `run()` to pass `required_output_fields`:

```python
# Sequential stage call in run():
self._run_stage(
    s.label, s.description, result,
    lambda ss=s: ss.fn(result),
    required_output_fields=s.required_output_fields,
)

# In _run_stage_safe():
self._run_stage(
    stage.label, stage.description, result,
    lambda s=stage: s.fn(result),
    required_output_fields=stage.required_output_fields,
)

# In _run_loop_stage():
self._run_stage(
    inner.label, inner.description, result,
    lambda s=inner: s.fn(result),
    timeout_s=inner.timeout_s,
    required_output_fields=inner.required_output_fields,
)
```

- [ ] **Step 6: Add `required_output_fields` to two key stages in `_make_stage_registry()`**

In `_make_stage_registry()`, annotate the stages most likely to silently fail:

```python
"product_manager": PipelineStage(
    name="product_manager",
    ...
    required_output_fields=["prd"],
),
"architect": PipelineStage(
    name="architect",
    ...
    required_output_fields=["architecture"],
),
```

- [ ] **Step 7: Run regression tests**

```bash
python3 -m pytest tests/test_output_verifier.py tests/test_orchestrator_parallel.py tests/test_orchestrator_deploy_loop.py tests/test_orchestrator_stage_timeout.py -v
```

Expected: All pass.

- [ ] **Step 8: Commit**

```bash
git add core/output_verifier.py orchestrator.py tests/test_output_verifier.py
git commit -m "feat(verification): add OutputVerifier gate after pipeline stage success"
```

---

### Task 3: Update `core/__init__.py` to export new symbols

**Files:**
- Modify: `core/__init__.py`

- [ ] **Step 1: Add exports**

In `core/__init__.py`, add:

```python
from core.output_verifier import OutputVerifier, OutputVerificationError
```

- [ ] **Step 2: Run all core tests**

```bash
python3 -m pytest tests/test_agent_health.py tests/test_circuit_breaker.py tests/test_output_verifier.py -v
```

Expected: All pass.

- [ ] **Step 3: Commit**

```bash
git add core/__init__.py
git commit -m "chore(core): export OutputVerifier from core/__init__.py"
```

---

### Task 4: Branch, push, PR

- [ ] **Step 1: Create branch and push**

```bash
git checkout -b t3-c-integration master
git push -u origin t3-c-integration
```

- [ ] **Step 2: Create PR**

```bash
gh pr create \
  --title "feat(integration): T3-C — health monitor→CB wiring and OutputVerifier gate" \
  --body "## Summary
Two integration improvements connecting previously isolated subsystems:

### 1. AgentHealthMonitor → Circuit Breaker auto-open
When \`AgentHealthMonitor.is_unhealthy(name)\` fires (3 consecutive failures), the orchestrator now calls \`cb.force_open()\` on the agent's circuit breaker. This blocks subsequent calls to the same agent, triggering \`FallbackLLMBackend\` to switch to the next backend — turning health warnings into protective action.

### 2. OutputVerifier stage gate
Inspired by the superpowers \`verification-before-completion\` principle. Adds \`core/output_verifier.py\` — a lightweight verifier that checks named \`PipelineResult\` fields are non-falsy after a stage completes. Wired into \`_run_stage()\` via \`required_output_fields\` on \`PipelineStage\`. Applied to \`product_manager\` (checks \`result.prd\`) and \`architect\` (checks \`result.architecture\`) by default.

## Test Plan
- [ ] \`tests/test_agent_health.py\` — 2 new tests for force_open + CB wiring
- [ ] \`tests/test_output_verifier.py\` — 6 new tests for OutputVerifier
- [ ] All existing orchestrator tests still pass" \
  --base master
```
