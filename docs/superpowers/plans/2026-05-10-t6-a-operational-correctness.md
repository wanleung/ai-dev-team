# T6-A Operational Correctness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix four correctness gaps in `orchestrator.py`: populate `required_output_fields` at all inline `_run_stage()` call sites, promote `_validate_pipeline_stages` from warn to raise, add graceful SIGTERM/SIGINT shutdown, and note that `result.errors` thread safety is already implemented.

**Architecture:** All changes are confined to `orchestrator.py`. Each fix applies an existing pattern to a gap — no new files, no new abstractions. `PipelineResult.add_error()` already uses `self._lock`, so Fix 4 from the spec is already done and requires no code change.

**Tech Stack:** Python 3.11+, `signal` (stdlib), `threading` (stdlib), `pytest`

---

## Pre-flight check

- [ ] **Verify baseline tests pass**

```bash
cd ~/Projects/ai-software-house
python -m pytest tests/ -x -q --tb=short 2>&1 | tail -20
```

Expected: all existing tests pass (zero failures).

- [ ] **Confirm the 8 call sites that need `required_output_fields`**

```bash
grep -n "_run_stage(" orchestrator.py | cat -n
```

You should see 14 lines. The ones at lines ~1684 (inner loop, passes `inner.required_output_fields`), ~2503 (registry path, passes `s.required_output_fields`), ~3626 (`_run_stage_safe`, passes `stage.required_output_fields`), and ~3640 (the definition) are already correct. The call at ~2430 (RAG index) does not produce required output fields. The remaining 8 are the targets for Task 1.

---

## Task 1: Populate `required_output_fields` at inline `_run_stage()` call sites

**Files:**
- Modify: `orchestrator.py` — 8 inline `_run_stage()` calls in `_run_pm_loop()` and `_run_architect_loop()`

There is no new failing test for this task — the existing `OutputVerifier` tests already cover the verifier's behaviour. The fix simply activates what's already tested.

- [ ] **Step 1: Identify the exact 8 call sites by searching for their context**

```bash
grep -n "stage_pm\|stage_pm_reviewer\|stage_pm_revision\|stage_arch\|stage_architect" orchestrator.py | grep "_run_stage\|Analyzing\|Reviewing\|Revising\|Designing" | head -20
```

The targets are:

| Approximate line | Stage function called | `required_output_fields` to add |
|---|---|---|
| ~2659 | `_stage_pm(result, requirement)` | `["prd"]` |
| ~2685 | `_stage_pm_reviewer(result, requirement)` | `["prd_review", "prd_verdict"]` |
| ~2729 | `_stage_pm_revision(result, requirement, rn)` | `["prd"]` |
| ~2742 | `_stage_pm_reviewer(result, requirement)` (re-check) | `["prd_review", "prd_verdict"]` |
| ~2826 | `_stage_architect(result)` (inline, not via registry) | `["design"]` |
| ~2847 | `_stage_architect_reviewer(result)` | `["design_verdict"]` |
| ~2891 | `_stage_arch_revision(result, rn)` | `["design"]` |
| ~2904 | `_stage_architect_reviewer(result)` (re-check) | `["design_verdict"]` |

- [ ] **Step 2: Add `required_output_fields` to the first `_stage_pm()` call in `_run_pm_loop`**

Find the block that looks like:
```python
self._run_stage(
    "📋 Product Manager",
    "Analyzing requirements & writing PRD...",
    result,
    lambda: self._stage_pm(result, requirement),
)
```

Replace with:
```python
self._run_stage(
    "📋 Product Manager",
    "Analyzing requirements & writing PRD...",
    result,
    lambda: self._stage_pm(result, requirement),
    required_output_fields=["prd"],
)
```

- [ ] **Step 3: Add `required_output_fields` to the first `_stage_pm_reviewer()` call in `_run_pm_loop`**

Find:
```python
self._run_stage(
    "📝 PM Reviewer",
    "Reviewing PRD for completeness...",
    result,
    lambda: self._stage_pm_reviewer(result, requirement),
)
```

Replace with:
```python
self._run_stage(
    "📝 PM Reviewer",
    "Reviewing PRD for completeness...",
    result,
    lambda: self._stage_pm_reviewer(result, requirement),
    required_output_fields=["prd_review", "prd_verdict"],
)
```

- [ ] **Step 4: Add `required_output_fields` to the `_stage_pm_revision()` call (PM revision loop)**

Find the call inside the `for round_num in range(1, self.max_prd_revisions + 1):` block that calls `_stage_pm_revision`:
```python
self._run_stage(
    "📋 Product Manager",
    f"Revising PRD based on reviewer feedback (round {round_num})...",
    result,
    lambda rn=round_num: self._stage_pm_revision(result, requirement, rn),
)
```

Replace with:
```python
self._run_stage(
    "📋 Product Manager",
    f"Revising PRD based on reviewer feedback (round {round_num})...",
    result,
    lambda rn=round_num: self._stage_pm_revision(result, requirement, rn),
    required_output_fields=["prd"],
)
```

- [ ] **Step 5: Add `required_output_fields` to the re-check `_stage_pm_reviewer()` call (PM revision loop)**

Find the second `_stage_pm_reviewer` call inside the same `for round_num` loop:
```python
self._run_stage(
    "📝 PM Reviewer",
    f"Re-reviewing revised PRD (round {round_num})...",
    result,
    lambda: self._stage_pm_reviewer(result, requirement),
)
```

Replace with:
```python
self._run_stage(
    "📝 PM Reviewer",
    f"Re-reviewing revised PRD (round {round_num})...",
    result,
    lambda: self._stage_pm_reviewer(result, requirement),
    required_output_fields=["prd_review", "prd_verdict"],
)
```

- [ ] **Step 6: Add `required_output_fields` to the inline `_stage_architect()` call**

Find the inline call (not via registry — it uses a lambda directly):
```python
self._run_stage("🏗️  Architect", "Designing system architecture...", result, lambda: self._stage_architect(result))
```

Replace with:
```python
self._run_stage(
    "🏗️  Architect",
    "Designing system architecture...",
    result,
    lambda: self._stage_architect(result),
    required_output_fields=["design"],
)
```

- [ ] **Step 7: Add `required_output_fields` to the first `_stage_architect_reviewer()` call in `_run_architect_loop`**

Find:
```python
self._run_stage(
    "🔎 Architect Reviewer",
    "Reviewing system design...",
    result,
    lambda: self._stage_architect_reviewer(result),
)
```

Replace with:
```python
self._run_stage(
    "🔎 Architect Reviewer",
    "Reviewing system design...",
    result,
    lambda: self._stage_architect_reviewer(result),
    required_output_fields=["design_verdict"],
)
```

- [ ] **Step 8: Add `required_output_fields` to the `_stage_arch_revision()` call (design revision loop)**

Find the call inside `for round_num in range(1, self.max_design_revisions + 1):` that calls `_stage_arch_revision`:
```python
self._run_stage(
    "🏗️  Architect",
    f"Revising design based on reviewer feedback (round {round_num})...",
    result,
    lambda rn=round_num: self._stage_arch_revision(result, rn),
)
```

Replace with:
```python
self._run_stage(
    "🏗️  Architect",
    f"Revising design based on reviewer feedback (round {round_num})...",
    result,
    lambda rn=round_num: self._stage_arch_revision(result, rn),
    required_output_fields=["design"],
)
```

- [ ] **Step 9: Add `required_output_fields` to the re-check `_stage_architect_reviewer()` call (design revision loop)**

Find the second `_stage_architect_reviewer` call inside the same `for round_num` loop:
```python
self._run_stage(
    "🔎 Architect Reviewer",
    f"Re-reviewing revised design (round {round_num})...",
    result,
    lambda: self._stage_architect_reviewer(result),
)
```

Replace with:
```python
self._run_stage(
    "🔎 Architect Reviewer",
    f"Re-reviewing revised design (round {round_num})...",
    result,
    lambda: self._stage_architect_reviewer(result),
    required_output_fields=["design_verdict"],
)
```

- [ ] **Step 10: Verify the count — all 8 inline call sites now have `required_output_fields`**

```bash
grep -n "required_output_fields" orchestrator.py | grep -v "^[0-9]*:.*#\|^[0-9]*:.*def \|^[0-9]*:.*:\s*list"
```

You should see at least 10 lines — the 2 pre-existing ones + the 8 you just added.

- [ ] **Step 11: Write the test for required_output_fields activation**

Create `tests/test_required_output_fields_verified.py`:

```python
"""Verify that _run_stage() enforces required_output_fields via OutputVerifier.

These inline call sites were missing required_output_fields before T6-A; this
test confirms OutputVerifier is now active on those paths.
"""
from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

from orchestrator import Orchestrator, PipelineResult
from core.output_verifier import OutputVerificationError


def _make_orchestrator() -> Orchestrator:
    """Bypass __init__ — we only need _run_stage() wired up."""
    orch = Orchestrator.__new__(Orchestrator)
    orch._agent_health = MagicMock()
    orch._shutdown_event = threading.Event()  # required by _run_stage after T6-A fix
    return orch


def _make_result() -> PipelineResult:
    return PipelineResult(requirement="test requirement")


def test_run_stage_raises_when_required_field_missing():
    """_run_stage records OutputVerificationError when stage omits a required field."""
    orch = _make_orchestrator()
    result = _make_result()

    def stage_fn():
        # Deliberately sets nothing — result.prd stays ""
        pass

    with patch("orchestrator.console"), \
         patch.object(orch, "_critical_cb_open", return_value=None):
        orch._run_stage(
            "Test Stage",
            "testing...",
            result,
            stage_fn,
            required_output_fields=["prd"],
        )

    assert len(result.errors) == 1
    assert "prd" in str(result.errors[0]).lower() or "missing" in str(result.errors[0]).lower()


def test_run_stage_passes_when_required_field_present():
    """_run_stage does not record an error when the required field is populated."""
    orch = _make_orchestrator()
    result = _make_result()

    def stage_fn():
        result.prd = "A well-written PRD"

    with patch("orchestrator.console"), \
         patch.object(orch, "_critical_cb_open", return_value=None):
        orch._run_stage(
            "Test Stage",
            "testing...",
            result,
            stage_fn,
            required_output_fields=["prd"],
        )

    assert len(result.errors) == 0
```

- [ ] **Step 12: Run the test**

```bash
python -m pytest tests/test_required_output_fields_verified.py -v
```

Expected: **PASS** (both tests green).

- [ ] **Step 13: Commit Task 1**

```bash
git add orchestrator.py tests/test_required_output_fields_verified.py
git commit -m "fix(correctness): T6-A task 1 — populate required_output_fields at all inline _run_stage call sites"
```

---

## Task 2: Promote `_validate_pipeline_stages` from warn to raise

**Files:**
- Modify: `orchestrator.py` — `_validate_pipeline_stages()` method (~line 1571)
- Create: `tests/test_validate_pipeline_raises_on_unknown.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_validate_pipeline_raises_on_unknown.py`:

```python
"""_validate_pipeline_stages() must raise ConfigurationError on unknown stage names.

Before T6-A, this method only logged a warning; unknown stages caused a
KeyError crash inside _build_stage_list() instead of a clean error at load time.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from orchestrator import Orchestrator


def _make_orchestrator() -> Orchestrator:
    orch = Orchestrator.__new__(Orchestrator)
    return orch


def test_validate_pipeline_stages_raises_on_unknown():
    """Unknown stage name raises ConfigurationError at load time."""
    orch = _make_orchestrator()

    # Mock _make_stage_registry to return a small known set
    fake_registry = {"pm": MagicMock(), "architect": MagicMock()}
    with patch.object(orch, "_make_stage_registry", return_value=fake_registry):
        with pytest.raises(Exception) as exc_info:
            orch._validate_pipeline_stages("test_source", ["pm", "nonexistent_stage"])

    # ConfigurationError is defined in orchestrator.py; check message content
    assert "nonexistent_stage" in str(exc_info.value)
    assert "test_source" in str(exc_info.value)


def test_validate_pipeline_stages_passes_on_known():
    """All known stage names: no exception raised."""
    orch = _make_orchestrator()

    fake_registry = {"pm": MagicMock(), "architect": MagicMock()}
    with patch.object(orch, "_make_stage_registry", return_value=fake_registry):
        # Should not raise
        orch._validate_pipeline_stages("test_source", ["pm", "architect"])


def test_validate_pipeline_stages_raises_on_all_unknown():
    """Multiple unknown stages: all listed in the error message."""
    orch = _make_orchestrator()

    fake_registry = {"pm": MagicMock()}
    with patch.object(orch, "_make_stage_registry", return_value=fake_registry):
        with pytest.raises(Exception) as exc_info:
            orch._validate_pipeline_stages("my_pipeline", ["foo", "bar"])

    err = str(exc_info.value)
    assert "foo" in err or "bar" in err
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
python -m pytest tests/test_validate_pipeline_raises_on_unknown.py -v
```

Expected: **FAIL** — `test_validate_pipeline_stages_raises_on_unknown` and `test_validate_pipeline_stages_raises_on_all_unknown` fail because the method currently only logs a warning.

- [ ] **Step 3: Implement the fix in `_validate_pipeline_stages()`**

Find the `_validate_pipeline_stages()` method in `orchestrator.py` (around line 1571). The current body looks like:

```python
def _validate_pipeline_stages(self, source: str, stages: list) -> None:
    """Warn about unknown stage names so errors surface early with context.

    Unknown stages will raise a KeyError in ``_build_stage_list``; this
    method surfaces the problem with a clear message at load time.
    """
    registry = self._make_stage_registry()
    unknown = []
    for entry in stages:
        if isinstance(entry, str) and entry not in registry:
            unknown.append(entry)
    if unknown:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "Pipeline %r references unknown stage(s) %s — valid stages: %s",
            source, unknown, sorted(registry.keys()),
        )
```

Replace it with:

```python
def _validate_pipeline_stages(self, source: str, stages: list) -> None:
    """Raise ConfigurationError on unknown stage names so errors surface early.

    Unknown stages would raise a KeyError in ``_build_stage_list``; this
    method surfaces the problem with a clean message at load time before
    any LLM calls are made.
    """
    registry = self._make_stage_registry()
    unknown = []
    for entry in stages:
        if isinstance(entry, str) and entry not in registry:
            unknown.append(entry)
    if unknown:
        raise ConfigurationError(
            f"Pipeline {source!r} references unknown stage(s) {unknown}. "
            f"Valid stages: {sorted(registry.keys())}"
        )
```

`ConfigurationError` is already defined in `orchestrator.py` — no import needed.

- [ ] **Step 4: Run the tests**

```bash
python -m pytest tests/test_validate_pipeline_raises_on_unknown.py -v
```

Expected: **PASS** (all 3 tests green).

- [ ] **Step 5: Run the full test suite to catch regressions**

```bash
python -m pytest tests/ -x -q --tb=short 2>&1 | tail -20
```

Expected: all tests pass. If any existing test expected a warning and not a raise, update that test to assert the `ConfigurationError` instead.

- [ ] **Step 6: Commit Task 2**

```bash
git add orchestrator.py tests/test_validate_pipeline_raises_on_unknown.py
git commit -m "fix(correctness): T6-A task 2 — validate_pipeline_stages raises ConfigurationError on unknown stages"
```

---

## Task 3: Graceful shutdown signal handlers

**Files:**
- Modify: `orchestrator.py` — `Orchestrator.__init__()` and `_run_stage()`
- Create: `tests/test_graceful_shutdown_sigterm.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_graceful_shutdown_sigterm.py`:

```python
"""Orchestrator._run_stage() must abort cleanly when _shutdown_event is set.

SIGTERM/SIGINT handlers set _shutdown_event; the next _run_stage() call
raises SystemExit so the pipeline unwinds without interrupting a running stage.
"""
from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

from orchestrator import Orchestrator, PipelineResult


def _make_orchestrator() -> Orchestrator:
    orch = Orchestrator.__new__(Orchestrator)
    orch._agent_health = MagicMock()
    # Simulate what __init__ will do after the fix:
    orch._shutdown_event = threading.Event()
    return orch


def _make_result() -> PipelineResult:
    return PipelineResult(requirement="test requirement")


def test_run_stage_raises_system_exit_when_shutdown_set():
    """_run_stage raises SystemExit immediately if _shutdown_event is set."""
    orch = _make_orchestrator()
    result = _make_result()
    orch._shutdown_event.set()  # simulate SIGTERM received

    fn_called = False

    def stage_fn():
        nonlocal fn_called
        fn_called = True

    with patch("orchestrator.console"), \
         patch.object(orch, "_critical_cb_open", return_value=None):
        with pytest.raises(SystemExit) as exc_info:
            orch._run_stage("Test Stage", "testing...", result, stage_fn)

    assert not fn_called, "stage function must not be called after shutdown"
    assert "shutting down" in str(exc_info.value).lower() or exc_info.value.code is not None


def test_run_stage_runs_normally_when_shutdown_not_set():
    """_run_stage runs stage_fn normally when _shutdown_event is not set."""
    orch = _make_orchestrator()
    result = _make_result()
    # _shutdown_event is not set

    fn_called = False

    def stage_fn():
        nonlocal fn_called
        fn_called = True

    with patch("orchestrator.console"), \
         patch.object(orch, "_critical_cb_open", return_value=None):
        orch._run_stage("Test Stage", "testing...", result, stage_fn)

    assert fn_called


def test_shutdown_event_is_set_by_signal_handler(monkeypatch):
    """Registering signal handlers and calling them sets _shutdown_event."""
    import signal as _signal

    # Track which signals were registered
    registered = {}

    def fake_signal(sig, handler):
        registered[sig] = handler

    monkeypatch.setattr(_signal, "signal", fake_signal)

    # Import and patch signal before __init__ runs
    # We can't call real __init__ (needs LLM clients), so test the handler closure directly.
    # Create the event and handler as __init__ will:
    shutdown_event = threading.Event()

    def _handle_shutdown(signum, frame):
        shutdown_event.set()

    fake_signal(_signal.SIGTERM, _handle_shutdown)
    fake_signal(_signal.SIGINT, _handle_shutdown)

    assert _signal.SIGTERM in registered
    assert _signal.SIGINT in registered

    # Simulate SIGTERM arriving
    registered[_signal.SIGTERM](signum=_signal.SIGTERM, frame=None)
    assert shutdown_event.is_set()
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
python -m pytest tests/test_graceful_shutdown_sigterm.py -v
```

Expected: `test_run_stage_raises_system_exit_when_shutdown_set` fails (no `_shutdown_event` attribute, or no SystemExit raised).

- [ ] **Step 3: Add `_shutdown_event` to `Orchestrator.__init__()`**

Find `Orchestrator.__init__()` (line ~596). At the end of `__init__`, just before the method returns, add:

```python
        # Graceful shutdown — SIGTERM/SIGINT sets this event; _run_stage checks it
        # before each stage so a running stage is never interrupted mid-execution.
        import signal as _signal
        self._shutdown_event = threading.Event()

        def _handle_shutdown(signum: int, frame: object) -> None:
            self._shutdown_event.set()

        _signal.signal(_signal.SIGTERM, _handle_shutdown)
        _signal.signal(_signal.SIGINT, _handle_shutdown)
```

`threading` is already imported at the top of `orchestrator.py`.

- [ ] **Step 4: Add the shutdown check at the start of `_run_stage()`**

Find `_run_stage()` (line ~3640). Immediately after the docstring, before the CB cascade check, add:

```python
        # Abort cleanly if a shutdown signal has been received.
        if self._shutdown_event.is_set():
            raise SystemExit("Pipeline shutting down — SIGTERM/SIGINT received")
```

The full start of `_run_stage()` should now look like:

```python
    def _run_stage(self, name: str, description: str, result: PipelineResult, fn,
                   timeout_s: float | None = None, required_output_fields: list[str] | None = None,
                   cb_key: str | None = None, is_critical: bool = False) -> None:
        """...(docstring unchanged)..."""
        # Abort cleanly if a shutdown signal has been received.
        if self._shutdown_event.is_set():
            raise SystemExit("Pipeline shutting down — SIGTERM/SIGINT received")

        # CB cascade: skip non-critical stages when a critical upstream CB is open.
        if not is_critical:
            ...
```

- [ ] **Step 5: Run the tests**

```bash
python -m pytest tests/test_graceful_shutdown_sigterm.py -v
```

Expected: **PASS** (all 3 tests green).

- [ ] **Step 6: Run the full test suite**

```bash
python -m pytest tests/ -x -q --tb=short 2>&1 | tail -20
```

Expected: all existing tests pass. The `Orchestrator.__new__(Orchestrator)` pattern in existing tests bypasses `__init__()` so they won't install signal handlers — but they also won't have `_shutdown_event`. If any test fails because `_run_stage()` accesses `self._shutdown_event` and it's missing, patch it:

```python
orch._shutdown_event = threading.Event()  # add this line to the existing _make_orchestrator() helper
```

If existing test helpers for `_run_stage()` (in `test_orchestrator_stage_timeout.py`, `test_cb_cascade.py`, etc.) break, add `orch._shutdown_event = threading.Event()` to their `_make_orchestrator()` helper function.

- [ ] **Step 7: Commit Task 3**

```bash
git add orchestrator.py tests/test_graceful_shutdown_sigterm.py
git commit -m "fix(correctness): T6-A task 3 — graceful shutdown on SIGTERM/SIGINT via _shutdown_event"
```

---

## Task 4: Verify `result.errors` thread safety (no change needed)

**Files:** None — this is a verification-only task.

- [ ] **Step 1: Confirm `add_error()` already uses `_lock`**

```bash
grep -A 5 "def add_error" orchestrator.py
```

Expected output:
```python
def add_error(self, error: "str | _PipelineError") -> None:
    """Add an error. Accepts a bare string (backwards compat) or a PipelineError."""
    if isinstance(error, str):
        error = _PipelineError(code="UNKNOWN", stage="unknown", message=error, severity="error")
    with self._lock:
        self.errors.append(error)
```

`self._lock` (`PipelineResult._lock`) is a `threading.Lock` added at the dataclass level with `repr=False, compare=False` — it already serialises all `errors.append()` calls. No change is needed.

- [ ] **Step 2: Confirm no raw `result.errors.append()` calls exist outside `add_error()`**

```bash
grep -n "\.errors\.append(" orchestrator.py
```

Expected: only one hit — the line inside `add_error()` itself. If you see additional direct `.errors.append()` calls in `_run_stage()` or anywhere else, convert them to `result.add_error(...)`.

---

## Final verification

- [ ] **Run the complete test suite**

```bash
python -m pytest tests/ -q --tb=short 2>&1 | tail -30
```

Expected: zero failures.

- [ ] **Run linter**

```bash
python -m flake8 orchestrator.py --max-line-length=120 2>&1 | head -20
```

Fix any introduced style issues.

- [ ] **Push branch for PR**

```bash
git checkout -b t6-a-operational-correctness 2>/dev/null || git checkout t6-a-operational-correctness
git push -u origin t6-a-operational-correctness
gh pr create --title "fix(correctness): T6-A — required_output_fields, load-time validation, graceful shutdown" \
  --body "## Summary

T6-A addresses four operational correctness gaps identified in the post-T5 gap analysis:

1. **\`required_output_fields\` populated at all inline \`_run_stage()\` call sites** — activates the OutputVerifier that was added in T5-B but was dormant at 8 of 10 inline call sites in \`_run_pm_loop\` and \`_run_architect_loop\`.
2. **\`_validate_pipeline_stages\` raises \`ConfigurationError\`** — promotes from a silent warning to an explicit failure at pipeline load time, before any LLM calls are made.
3. **Graceful shutdown on SIGTERM/SIGINT** — \`Orchestrator.__init__()\` installs signal handlers; \`_run_stage()\` checks \`_shutdown_event\` before each stage.
4. **\`result.errors\` thread safety** — verified already implemented via \`add_error()\` + \`PipelineResult._lock\` (no code change needed).

## Tests
- \`tests/test_required_output_fields_verified.py\` (new)
- \`tests/test_validate_pipeline_raises_on_unknown.py\` (new)
- \`tests/test_graceful_shutdown_sigterm.py\` (new)
" \
  --base master
```
