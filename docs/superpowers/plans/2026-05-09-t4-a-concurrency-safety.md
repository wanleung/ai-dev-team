# T4-A: Concurrency & Startup Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three thread-safety bugs: concurrent mutation of PipelineResult lists, unguarded MCP initialisation, and checkpoint write races during parallel stage execution.

**Architecture:** Add a per-instance `threading.Lock` to `PipelineResult` protecting all list mutations; add `_checkpoint_lock` to `Orchestrator` protecting checkpoint writes; wrap MCP init in try/except with graceful fallback.

**Tech Stack:** Python 3.11+, `threading` (stdlib), `pytest`, `orchestrator.py`, `tools/mcp_registry.py`

---

## File Map

| File | Change |
|------|--------|
| `orchestrator.py` | Add `_lock` to `PipelineResult`; add `add_completed_stage()` method; protect `add_error()`; add `_checkpoint_lock` to `Orchestrator.__init__`; wrap `_save_checkpoint()` and `_clear_checkpoint()`; wrap MCP init |
| `tests/test_pipeline_result_thread_safety.py` | New: concurrent stress tests for `add_error()` and `add_completed_stage()` |
| `tests/test_orchestrator_mcp_init.py` | New: MCP init failure → graceful fallback |
| `tests/test_checkpoint_thread_safety.py` | New: concurrent checkpoint write safety |

---

### Task 1: Thread-safe PipelineResult mutations

**Files:**
- Modify: `orchestrator.py:286-412` (PipelineResult class)
- Create: `tests/test_pipeline_result_thread_safety.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_pipeline_result_thread_safety.py
import threading
import pytest
from orchestrator import PipelineResult


def test_add_error_concurrent():
    """50 threads calling add_error simultaneously must produce exactly 50 errors."""
    result = PipelineResult(requirement="test")
    barrier = threading.Barrier(50)

    def worker(i):
        barrier.wait()
        result.add_error(f"error-{i}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(result.errors) == 50


def test_add_completed_stage_concurrent():
    """50 threads calling add_completed_stage simultaneously must produce exactly 50 entries."""
    result = PipelineResult(requirement="test")
    barrier = threading.Barrier(50)

    def worker(i):
        barrier.wait()
        result.add_completed_stage(f"stage-{i}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(result.completed_stages) == 50


def test_add_error_and_stage_concurrent_no_deadlock():
    """Mixed concurrent calls to add_error and add_completed_stage must not deadlock."""
    result = PipelineResult(requirement="test")
    barrier = threading.Barrier(20)

    def add_err(i):
        barrier.wait()
        result.add_error(f"e-{i}")

    def add_stage(i):
        barrier.wait()
        result.add_completed_stage(f"s-{i}")

    threads = (
        [threading.Thread(target=add_err, args=(i,)) for i in range(10)]
        + [threading.Thread(target=add_stage, args=(i,)) for i in range(10)]
    )
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(result.errors) == 10
    assert len(result.completed_stages) == 10
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/wanleung/Projects/ai-software-house
python3 -m pytest tests/test_pipeline_result_thread_safety.py -v
```

Expected: `AttributeError: 'PipelineResult' object has no attribute 'add_completed_stage'` or race-induced count mismatch.

- [ ] **Step 3: Add `_lock` and `add_completed_stage()` to `PipelineResult`**

In `orchestrator.py`, the `PipelineResult` dataclass starts at line 286. Find the `errors: list[...]` field (around line 325) and add the lock field immediately after it:

```python
# After: errors: list["_PipelineError"] = field(default_factory=list)
_lock: threading.Lock = field(
    default_factory=threading.Lock, init=False, repr=False, compare=False
)
```

Then update `add_error()` (around line 399) to acquire the lock:

```python
def add_error(self, error: "str | _PipelineError") -> None:
    """Add an error. Accepts a bare string (backwards compat) or a PipelineError."""
    if isinstance(error, str):
        error = _PipelineError(code="UNKNOWN", stage="unknown", message=error, severity="error")
    with self._lock:
        self.errors.append(error)
```

Add `add_completed_stage()` immediately after `add_error()`:

```python
def add_completed_stage(self, key: str) -> None:
    """Thread-safe append to completed_stages."""
    with self._lock:
        self.completed_stages.append(key)
```

- [ ] **Step 4: Replace all `result.completed_stages.append(...)` calls with `result.add_completed_stage(...)`**

Find all call sites:
```bash
grep -n "completed_stages.append" orchestrator.py
```

For each line found (expect ~15 occurrences), replace:
```python
# Before:
result.completed_stages.append("pm")
# After:
result.add_completed_stage("pm")
```

Same pattern for all occurrences — the argument stays identical, only the method changes.

- [ ] **Step 5: Run tests to confirm they pass**

```bash
python3 -m pytest tests/test_pipeline_result_thread_safety.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 6: Run full test suite to check for regressions**

```bash
python3 -m pytest tests/ -x -q 2>/dev/null | tail -5
```

Expected: no new failures.

- [ ] **Step 7: Commit**

```bash
git add orchestrator.py tests/test_pipeline_result_thread_safety.py
git commit -m "fix(concurrency): thread-safe PipelineResult mutations

- Add _lock field (threading.Lock) to PipelineResult dataclass
- Protect add_error() with lock acquisition
- Add add_completed_stage() method as thread-safe replacement for
  direct completed_stages.append() calls
- Replace all ~15 completed_stages.append() call sites

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 2: MCP initialisation fallback

**Files:**
- Modify: `orchestrator.py:633-643` (Orchestrator.__init__ MCP block)
- Create: `tests/test_orchestrator_mcp_init.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_orchestrator_mcp_init.py
from unittest.mock import patch, MagicMock
import pytest


def _make_minimal_orchestrator(**kwargs):
    """Import and construct Orchestrator with minimal config."""
    from orchestrator import Orchestrator
    minimal_config = {
        "llm": {"backend": "openai", "model": "gpt-4o", "api_key": "test"},
        "github": {"token": "gh_test", "owner": "o", "repo": "r"},
    }
    return Orchestrator(config=minimal_config, **kwargs)


def test_mcp_init_failure_does_not_crash():
    """If MCPToolRegistry raises during init, Orchestrator must still construct."""
    from tools import MCPToolRegistry
    with patch.object(MCPToolRegistry, "__init__", side_effect=RuntimeError("MCP unreachable")):
        orch = _make_minimal_orchestrator(
            mcp_servers=[{"name": "my-mcp", "command": "npx", "args": ["-y", "server"]}]
        )
    assert orch is not None


def test_mcp_init_failure_leaves_builtin_tools():
    """After MCP init failure, tool registry falls back to builtin tools only."""
    from tools import MCPToolRegistry, builtin_tools
    with patch.object(MCPToolRegistry, "__init__", side_effect=RuntimeError("timeout")):
        orch = _make_minimal_orchestrator(
            mcp_servers=[{"name": "mcp", "command": "npx", "args": []}]
        )
    # _tool_registry should be the builtin registry, not a CombinedToolRegistry
    assert orch._tool_registry is not None
    assert orch._rag_registry is None


def test_rag_mcp_init_failure_does_not_crash():
    """RAG MCP init failure should also be caught gracefully."""
    from tools import MCPToolRegistry
    with patch.object(MCPToolRegistry, "__init__", side_effect=ConnectionError("rag down")):
        orch = _make_minimal_orchestrator(
            mcp_servers=[{"name": "rag", "command": "npx", "args": []}]
        )
    assert orch._rag_registry is None
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python3 -m pytest tests/test_orchestrator_mcp_init.py -v
```

Expected: tests fail because MCPToolRegistry errors propagate and crash Orchestrator construction.

- [ ] **Step 3: Wrap MCP init in try/except in `orchestrator.py`**

Find lines ~633-643:

```python
# Before:
if mcp_servers:
    mcp_registry = MCPToolRegistry(mcp_servers)
    tool_registry = CombinedToolRegistry(builtin_tools, mcp_registry)
else:
    tool_registry = builtin_tools
self._tool_registry = tool_registry

rag_servers = [s for s in (mcp_servers or []) if s.get("name") == "rag"]
rag_registry = MCPToolRegistry(rag_servers) if rag_servers else None

# After:
if mcp_servers:
    try:
        mcp_registry = MCPToolRegistry(mcp_servers)
        tool_registry = CombinedToolRegistry(builtin_tools, mcp_registry)
    except Exception as exc:
        logger.warning("[orchestrator] MCP init failed: %s — continuing with builtin tools only", exc)
        tool_registry = builtin_tools
else:
    tool_registry = builtin_tools
self._tool_registry = tool_registry

rag_servers = [s for s in (mcp_servers or []) if s.get("name") == "rag"]
try:
    rag_registry = MCPToolRegistry(rag_servers) if rag_servers else None
except Exception as exc:
    logger.warning("[orchestrator] RAG MCP init failed: %s — RAG disabled", exc)
    rag_registry = None
```

Note: `logger` is the module-level logger in orchestrator.py. If it's named differently (e.g. `_log`), use whatever name the file uses — check with `grep -n "^_log\|^logger" orchestrator.py | head -3`.

- [ ] **Step 4: Run tests to confirm they pass**

```bash
python3 -m pytest tests/test_orchestrator_mcp_init.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add orchestrator.py tests/test_orchestrator_mcp_init.py
git commit -m "fix(startup): catch MCP init errors and fall back to builtin tools

Prevents Orchestrator construction from crashing when MCP servers are
unreachable or misconfigured. Logs a warning and continues with
builtin tools / no RAG respectively.

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 3: Thread-safe checkpoint writes

**Files:**
- Modify: `orchestrator.py` (`Orchestrator.__init__`, `_save_checkpoint`, `_clear_checkpoint`)
- Create: `tests/test_checkpoint_thread_safety.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_checkpoint_thread_safety.py
import json
import threading
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


def _make_orchestrator_with_tmpdir(tmp_path):
    from orchestrator import Orchestrator, PipelineResult
    config = {
        "llm": {"backend": "openai", "model": "gpt-4o", "api_key": "test"},
        "github": {"token": "gh_test", "owner": "o", "repo": "r"},
        "checkpoints": {"dir": str(tmp_path)},
    }
    return Orchestrator(config=config)


def test_concurrent_checkpoint_writes_produce_valid_json(tmp_path):
    """10 threads calling _save_checkpoint concurrently must not corrupt the file."""
    from orchestrator import PipelineResult
    orch = _make_orchestrator_with_tmpdir(tmp_path)
    result = PipelineResult(requirement="test-req")

    barrier = threading.Barrier(10)

    def writer():
        barrier.wait()
        orch._save_checkpoint(result)

    threads = [threading.Thread(target=writer) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Find the checkpoint file and verify it's valid JSON
    files = list(tmp_path.glob("*.json"))
    assert len(files) >= 1, "No checkpoint file was written"
    data = json.loads(files[0].read_text())
    assert data["requirement"] == "test-req"


def test_checkpoint_lock_exists_on_orchestrator(tmp_path):
    """Orchestrator must have a _checkpoint_lock threading.Lock attribute."""
    orch = _make_orchestrator_with_tmpdir(tmp_path)
    assert hasattr(orch, "_checkpoint_lock")
    assert isinstance(orch._checkpoint_lock, threading.Lock)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python3 -m pytest tests/test_checkpoint_thread_safety.py -v
```

Expected: `AttributeError: '_checkpoint_lock'` or JSON decode error from corrupted concurrent writes.

- [ ] **Step 3: Add `_checkpoint_lock` to `Orchestrator.__init__`**

Find where other locks/instance variables are initialised in `Orchestrator.__init__` (search for `self._` assignments). Add near the top of `__init__`:

```python
self._checkpoint_lock: threading.Lock = threading.Lock()
```

- [ ] **Step 4: Wrap `_save_checkpoint()` and `_clear_checkpoint()` with the lock**

Find `def _save_checkpoint(self, result)` and `def _clear_checkpoint(self, result)`. Wrap each method body:

```python
def _save_checkpoint(self, result: PipelineResult) -> None:
    with self._checkpoint_lock:
        # ... existing method body unchanged ...

def _clear_checkpoint(self, result: PipelineResult) -> None:
    with self._checkpoint_lock:
        # ... existing method body unchanged ...
```

Just indent the existing body one level — don't change any logic.

- [ ] **Step 5: Run tests to confirm they pass**

```bash
python3 -m pytest tests/test_checkpoint_thread_safety.py -v
```

Expected: both tests PASS.

- [ ] **Step 6: Full suite check**

```bash
python3 -m pytest tests/ -x -q 2>/dev/null | tail -5
```

Expected: no new failures.

- [ ] **Step 7: Commit and push**

```bash
git add orchestrator.py tests/test_checkpoint_thread_safety.py
git commit -m "fix(concurrency): add _checkpoint_lock to Orchestrator for thread-safe writes

Prevents concurrent _save_checkpoint() calls from racing during parallel
stage execution. Also protects _clear_checkpoint().

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
git push origin t4-a-concurrency-safety
```

---

### Task 4: Create PR

```bash
gh pr create \
  --title "fix(concurrency): T4-A — thread-safe PipelineResult, MCP fallback, checkpoint lock" \
  --body "## Summary

Three concurrency and startup safety fixes:

### 1. Thread-safe PipelineResult mutations
- Added \`_lock: threading.Lock\` field to \`PipelineResult\` dataclass
- \`add_error()\` now acquires the lock before appending
- New \`add_completed_stage(key)\` method (thread-safe); replaces all direct \`.completed_stages.append()\` calls (~15 sites)

### 2. MCP init fallback
- Wrapped both \`MCPToolRegistry()\` calls in \`try/except Exception\`
- On failure: logs warning, falls back to builtin tools / no RAG
- Orchestrator no longer crashes on unreachable MCP servers at startup

### 3. Checkpoint write lock
- Added \`_checkpoint_lock: threading.Lock\` to \`Orchestrator.__init__()\`
- \`_save_checkpoint()\` and \`_clear_checkpoint()\` both acquire the lock
- Prevents JSON corruption from concurrent writes during parallel stage execution

## Tests
- \`tests/test_pipeline_result_thread_safety.py\` (new) — 3 tests, 50-thread barrier stress
- \`tests/test_orchestrator_mcp_init.py\` (new) — 3 tests, MCP failure scenarios
- \`tests/test_checkpoint_thread_safety.py\` (new) — 2 tests, concurrent write safety

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>" \
  --base master
```
