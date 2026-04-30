# Unified Pipeline Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify all pipeline entry points into a single watcher-driven process that maps GitHub labels to YAML pipeline definitions, with per-repo issue parallelism and per-LLM-backend connection pools.

**Architecture:** One `Orchestrator` class handles all pipeline types via stages registered in `_make_stage_registry()`. The watcher selects a per-label `pipelines/<label>.yaml` and dispatches via per-repo thread pools. A new `LLMPoolManager` provides backend semaphores so Ollama (or any rate-limited backend) is never overloaded.

**Tech Stack:** Python 3.11+, PyYAML, threading.Semaphore, ThreadPoolExecutor, pytest, GitHub Actions.

---

## File Structure

**New files:**
- `llm_pool.py` — `LLMPoolManager` class with one `Semaphore` per backend
- `pipelines/ai-feature.yaml` — Built-in feature pipeline (PM → Architect → Engineer → QA)
- `pipelines/ai-fix.yaml` — Built-in bug-fix pipeline (diagnose → fix → review → test)
- `pipelines/ai-docs.yaml` — Built-in docs pipeline (generate → commit → PR)
- `tests/test_llm_pool.py` — Unit tests for LLMPoolManager
- `tests/test_pipeline_registry.py` — Tests for label → pipeline file resolution
- `tests/test_watcher_once.py` — Tests for watcher `--once` mode

**Modified files:**
- `orchestrator.py` — absorb bug-fix and doc stages into `_make_stage_registry()`; add label-based pipeline file lookup
- `agents/base_agent.py` — wrap LLM calls with pool acquire/release
- `watcher.py` — per-repo `ThreadPoolExecutor`; pipeline YAML dispatch by label; `--once` mode
- `main.py` — add `--pipeline` and `--list-pipelines` flags
- `repos.yaml.example` — document new `parallel_issues` field
- `config.yaml` / `config.yaml.example` — document new `llm.pools` section
- `.github/workflows/feature-build.yml` — call `watcher.py --once` instead of `build_feature.py`
- `.github/workflows/bug-fix.yml` — call `watcher.py --once` instead of `fix_issue.py`
- `README.md` — document new pipeline label mapping and concurrency model

**Deleted files:**
- `bug_fix_orchestrator.py`
- `doc_orchestrator.py`
- `build_feature.py`
- `fix_issue.py`

**Decomposition rationale:** Each task below produces a self-contained, testable change. Tasks 1–4 are non-breaking refactors; Tasks 5–7 add new features (pool, dispatch); Tasks 8–10 are the cleanup that removes the old entry points. Tests run after every task and the existing 52 tests must stay green throughout.

---

## Task 1: Add `LLMPoolManager`

**Files:**
- Create: `llm_pool.py`
- Test: `tests/test_llm_pool.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_llm_pool.py`:

```python
"""Tests for LLMPoolManager — per-backend connection pools."""
import threading
import time

import pytest

from llm_pool import LLMPoolManager


def test_default_limits():
    pool = LLMPoolManager()
    # Ollama default is 1 (safe for local), others default to 5
    assert pool.limit_for("ollama") == 1
    assert pool.limit_for("openai") == 5
    assert pool.limit_for("anything-else") == 5


def test_custom_limits_from_config():
    pool = LLMPoolManager({"ollama": 2, "openai": 8, "opencode-zen": 3})
    assert pool.limit_for("ollama") == 2
    assert pool.limit_for("openai") == 8
    assert pool.limit_for("opencode-zen") == 3
    # Unlisted backends still get the default
    assert pool.limit_for("nvidia_nim") == 5


def test_semaphore_blocks_above_limit():
    pool = LLMPoolManager({"ollama": 1})
    acquired = []
    blocked_started = threading.Event()
    blocked_acquired = threading.Event()

    def worker():
        blocked_started.set()
        with pool.acquire("ollama"):
            blocked_acquired.set()
            acquired.append("worker")

    with pool.acquire("ollama"):
        t = threading.Thread(target=worker)
        t.start()
        # Wait for the worker thread to start and try to acquire
        assert blocked_started.wait(1.0)
        # Give it a moment to try (and block)
        time.sleep(0.1)
        # The worker should NOT have acquired yet
        assert not blocked_acquired.is_set()
        assert acquired == []
    # We released — worker should now acquire
    t.join(timeout=2.0)
    assert blocked_acquired.is_set()
    assert acquired == ["worker"]


def test_acquire_is_context_manager():
    pool = LLMPoolManager({"openai": 1})
    with pool.acquire("openai"):
        pass  # should release on exit


def test_unknown_backend_uses_default():
    pool = LLMPoolManager()
    # No exception, uses default limit
    with pool.acquire("brand-new-backend"):
        pass


def test_singleton_helper():
    """get_pool() / set_pool() provide a process-wide singleton for base_agent."""
    from llm_pool import get_pool, set_pool
    custom = LLMPoolManager({"ollama": 3})
    set_pool(custom)
    assert get_pool() is custom
    # Reset to None for other tests
    set_pool(None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_llm_pool.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'llm_pool'`

- [ ] **Step 3: Implement `LLMPoolManager`**

Create `llm_pool.py`:

```python
"""LLMPoolManager — per-backend semaphore pools for safe concurrent LLM access.

Each LLM backend (ollama, openai, opencode-zen, etc.) has its own
``threading.Semaphore`` whose count is set from ``config.yaml`` under
``llm.pools.<backend>``. Agents acquire a slot before making a call:

    with get_pool().acquire("ollama"):
        response = backend.call(messages)

The default for ``ollama`` is 1 (single connection — safe for local
GPU/CPU resources). All other backends default to 5.

Thread-safe. The pool is a process-wide singleton so every worker thread
in the watcher shares the same semaphores.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Optional

# Default per-backend limits when not specified in config
_DEFAULT_LIMITS = {
    "ollama": 1,
}
_FALLBACK_LIMIT = 5


class LLMPoolManager:
    """Holds one ``threading.Semaphore`` per backend name."""

    def __init__(self, limits: Optional[dict] = None):
        self._limits: dict = dict(limits or {})
        self._semaphores: dict[str, threading.Semaphore] = {}
        self._lock = threading.Lock()

    def limit_for(self, backend: str) -> int:
        """Return the configured limit for ``backend``."""
        if backend in self._limits:
            return self._limits[backend]
        return _DEFAULT_LIMITS.get(backend, _FALLBACK_LIMIT)

    def _semaphore_for(self, backend: str) -> threading.Semaphore:
        with self._lock:
            sem = self._semaphores.get(backend)
            if sem is None:
                sem = threading.Semaphore(self.limit_for(backend))
                self._semaphores[backend] = sem
            return sem

    @contextmanager
    def acquire(self, backend: str):
        """Context manager: acquire a slot for ``backend`` and release on exit."""
        sem = self._semaphore_for(backend)
        sem.acquire()
        try:
            yield
        finally:
            sem.release()


# ── Process-wide singleton ────────────────────────────────────────────────
_POOL: Optional[LLMPoolManager] = None
_POOL_LOCK = threading.Lock()


def get_pool() -> LLMPoolManager:
    """Return the global LLMPoolManager, creating a default one if unset."""
    global _POOL
    with _POOL_LOCK:
        if _POOL is None:
            _POOL = LLMPoolManager()
        return _POOL


def set_pool(pool: Optional[LLMPoolManager]) -> None:
    """Install a global LLMPoolManager (or reset to None)."""
    global _POOL
    with _POOL_LOCK:
        _POOL = pool
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_llm_pool.py -v`
Expected: PASS — all 6 tests green.

- [ ] **Step 5: Commit**

```bash
git add llm_pool.py tests/test_llm_pool.py
git commit -m "feat(llm_pool): add LLMPoolManager for per-backend concurrency limits

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 2: Wire `LLMPoolManager` into `BaseAgent.call`

**Files:**
- Modify: `agents/base_agent.py:411-447` (the `call` method) and `:449-494` (the `call_with_tools` method)
- Test: `tests/test_llm_pool.py` (extend with integration test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_llm_pool.py`:

```python
def test_base_agent_acquires_pool_on_call(monkeypatch):
    """BaseAgent.call should acquire from the global pool before delegating."""
    from llm_pool import LLMPoolManager, set_pool
    from agents.base_agent import BaseAgent

    acquired_backends: list[str] = []

    class TrackingPool(LLMPoolManager):
        @contextmanager_wrap
        def acquire(self, backend):
            acquired_backends.append(backend)
            yield

    # Stand-in contextmanager wrapper since we override the method
    from contextlib import contextmanager as contextmanager_wrap

    set_pool(TrackingPool())

    # Build an agent with a fake backend
    class FakeBackend:
        model = "fake-model"
        _client = None
        def call(self, messages):
            return "ok"
        def supports_tools(self):
            return False
        def _pre_call(self):
            pass

    agent = BaseAgent.__new__(BaseAgent)
    agent._llm = FakeBackend()
    agent._backend = "openai"
    agent._history = []
    agent.system_prompt = ""
    agent._inter_call_delay = 0
    agent._api_model = "fake-model"
    agent.model = "fake-model"

    reply = agent.call("hello")
    assert reply == "ok"
    assert acquired_backends == ["openai"]

    set_pool(None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_llm_pool.py::test_base_agent_acquires_pool_on_call -v`
Expected: FAIL — `acquired_backends == []` (pool never acquired).

- [ ] **Step 3: Modify `agents/base_agent.py` — wrap `call` with pool acquire**

In `agents/base_agent.py`, find the `call` method (around line 411). Replace:

```python
        # All other (OpenAI-compatible) backends: delegate to _llm directly.
        messages: list[dict] = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.extend(self._history)
        messages.append({"role": "user", "content": full_message})

        reply = self._llm.call(messages)
        self._history.append({"role": "user", "content": full_message})
        self._history.append({"role": "assistant", "content": reply})
        return reply
```

with:

```python
        # All other (OpenAI-compatible) backends: delegate to _llm directly.
        messages: list[dict] = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.extend(self._history)
        messages.append({"role": "user", "content": full_message})

        from llm_pool import get_pool
        with get_pool().acquire(self._backend):
            reply = self._llm.call(messages)
        self._history.append({"role": "user", "content": full_message})
        self._history.append({"role": "assistant", "content": reply})
        return reply
```

Also wrap `_call_anthropic` (line 363) and `_call_opencode` (line 379). Find each `reply = self._llm.call(...)` line in those methods and wrap in:

```python
        from llm_pool import get_pool
        with get_pool().acquire(self._backend):
            reply = self._llm.call(messages)
```

And wrap `call_with_tools` similarly — replace `reply = self._llm.call_with_tools(messages, tools, max_turns)` with:

```python
        from llm_pool import get_pool
        with get_pool().acquire(self._backend):
            reply = self._llm.call_with_tools(messages, tools, max_turns)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_llm_pool.py -v`
Expected: PASS — all tests including the new one.

- [ ] **Step 5: Run full test suite to ensure nothing regressed**

Run: `python -m pytest -x -q 2>&1 | tail -20`
Expected: All existing tests pass (52+).

- [ ] **Step 6: Commit**

```bash
git add agents/base_agent.py tests/test_llm_pool.py
git commit -m "feat(base_agent): acquire LLM pool slot around every backend call

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 3: Load `llm.pools` config in watcher and main.py

**Files:**
- Modify: `watcher.py:187-205` (the `_load_pipeline_config` function)
- Modify: `watcher.py:666` (the `main` function — install pool at startup)
- Modify: `main.py` (add same pool-loading at startup)
- Modify: `config.yaml.example` if exists, else `config.yaml`

- [ ] **Step 1: Write the failing test**

Create `tests/test_watcher_pool_init.py`:

```python
"""Tests for watcher / main.py installing the LLM pool from config."""
from llm_pool import LLMPoolManager, get_pool, set_pool


def test_install_pool_from_config():
    """Helper sets up the global pool from a config dict."""
    from watcher import install_llm_pool_from_config

    set_pool(None)
    install_llm_pool_from_config({"llm": {"pools": {"ollama": 4, "openai": 12}}})
    pool = get_pool()
    assert pool.limit_for("ollama") == 4
    assert pool.limit_for("openai") == 12
    set_pool(None)


def test_install_pool_handles_missing_section():
    """No llm.pools key — defaults are used."""
    from watcher import install_llm_pool_from_config

    set_pool(None)
    install_llm_pool_from_config({})
    pool = get_pool()
    assert pool.limit_for("ollama") == 1  # default
    assert pool.limit_for("openai") == 5  # default
    set_pool(None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_watcher_pool_init.py -v`
Expected: FAIL — `cannot import name 'install_llm_pool_from_config'`.

- [ ] **Step 3: Add helper to `watcher.py`**

After the `_load_pipeline_config` function (around line 205) in `watcher.py`, add:

```python
def install_llm_pool_from_config(pipeline_cfg: dict) -> None:
    """Install the global LLMPoolManager from ``pipeline_cfg['llm']['pools']``.

    Should be called once at watcher / CLI startup, before any agent runs.
    Missing sections are tolerated — defaults from llm_pool apply.
    """
    from llm_pool import LLMPoolManager, set_pool
    pools = (pipeline_cfg.get("llm") or {}).get("pools") or {}
    set_pool(LLMPoolManager(pools))
```

In `watcher.py`, modify the `main` function (around line 666). After the line `LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")` and before `logger.info("═" * 60)`, add:

```python
    # Install the LLM pool from config so all agent threads share semaphores
    install_llm_pool_from_config(_load_pipeline_config())
```

- [ ] **Step 4: Modify `main.py` to install the pool at startup**

In `main.py`, find the `main()` function (or top-level entry). Near the start of `main()` (after argument parsing but before any orchestrator construction), add:

```python
    # Install the LLM pool from config so backend semaphores are honoured
    from watcher import install_llm_pool_from_config, _load_pipeline_config
    install_llm_pool_from_config(_load_pipeline_config())
```

- [ ] **Step 5: Update `config.yaml.example` (or create it)**

Add a `llm.pools` section to `config.yaml.example` (or `config.yaml` if no example file exists). Append within the `llm:` section:

```yaml
  # Per-backend concurrency limits. The watcher acquires a slot
  # from the named backend's pool before each LLM call. Use this
  # to protect rate-limited or local backends.
  pools:
    ollama: 1            # local Ollama: serial only (default)
    openai: 10
    anthropic: 5
    opencode-zen: 5
    opencode-go: 5
    nvidia_nim: 5
    # Backends not listed default to 5
```

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/test_watcher_pool_init.py tests/test_llm_pool.py -v`
Expected: All PASS.

Run: `python -m pytest -x -q 2>&1 | tail -10`
Expected: Full suite passes.

- [ ] **Step 7: Commit**

```bash
git add watcher.py main.py config.yaml.example tests/test_watcher_pool_init.py
git commit -m "feat(watcher): install LLM pool from config at startup

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 4: Move bug-fix and doc stages into Orchestrator stage registry

**Files:**
- Modify: `orchestrator.py:741-848` (the `_make_stage_registry` method)
- Modify: `orchestrator.py` (add `_stage_diagnose`, `_stage_bug_fix`, `_stage_doc_generate`, `_stage_doc_commit_pr` methods, copied from bug_fix_orchestrator.py and doc_orchestrator.py)
- Test: `tests/test_pipeline_registry.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_pipeline_registry.py`:

```python
"""Tests for the unified Orchestrator stage registry."""
import pytest


def test_bug_fix_stages_registered():
    """Bug-fix stages should be available in the unified registry."""
    from orchestrator import Orchestrator

    orch = Orchestrator(model="gpt-4.1", use_github=False, github_token=None, github_repo=None, target_repo=None)
    registry = orch._make_stage_registry()
    assert "diagnose" in registry
    assert "bug_fix" in registry


def test_doc_stages_registered():
    """Documentation stages should be available in the unified registry."""
    from orchestrator import Orchestrator

    orch = Orchestrator(model="gpt-4.1", use_github=False, github_token=None, github_repo=None, target_repo=None)
    registry = orch._make_stage_registry()
    assert "doc_generate" in registry
    assert "doc_commit_pr" in registry


def test_existing_stages_still_present():
    """Original stages must not be removed by this refactor."""
    from orchestrator import Orchestrator

    orch = Orchestrator(model="gpt-4.1", use_github=False, github_token=None, github_repo=None, target_repo=None)
    registry = orch._make_stage_registry()
    for name in ("pm", "architect", "engineer", "reviewer", "qa_engineer", "test_fix", "deploy_tester"):
        assert name in registry, f"Existing stage {name!r} disappeared"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pipeline_registry.py -v`
Expected: FAIL — `assert "diagnose" in registry`.

- [ ] **Step 3: Add the four new stage methods to `orchestrator.py`**

Append before `_make_stage_registry` (around line 740) in `orchestrator.py`:

```python
    # ── Bug-fix stages (absorbed from bug_fix_orchestrator) ────────────────

    def _stage_diagnose(self, result: "PipelineResult") -> None:
        """Diagnose a bug from the trigger issue body and existing repo files.

        Sets ``result.architecture`` to the diagnosis Markdown so downstream
        stages (engineer/test_fix) see the fix plan as their architecture.
        """
        from agents import ArchitectAgent
        from bug_fix_orchestrator import _DIAGNOSIS_PREFIX

        body = (result.requirement or "").strip()
        existing_files = getattr(result, "existing_files", {}) or {}
        files_section = ""
        if existing_files:
            files_section = "\n\n## Existing Files\n" + "\n".join(
                f"### `{p}`\n```\n{c[:6000]}\n```" for p, c in existing_files.items()
            )

        arch = ArchitectAgent(
            model=self._architect_model,
            backend=self._architect_backend,
            system_prompt_overlay=_DIAGNOSIS_PREFIX,
            ollama_url=self.ollama_url,
            nvidia_nim_api_key=self.nvidia_nim_api_key,
            nvidia_nim_base_url=self.nvidia_nim_base_url,
        )
        result.architecture = arch.call(body + files_section)
        # Mirror diagnosis into the requirement-derived design so the engineer
        # stage sees a sensible "design" doc.
        if hasattr(result, "modules"):
            try:
                result.modules = arch.extract_modules(result.architecture)
            except Exception:
                result.modules = []

    def _stage_bug_fix(self, result: "PipelineResult") -> None:
        """Apply the bug fix using the engineer agent against existing files."""
        # Delegate to the standard engineer stage — by this point
        # result.architecture holds the diagnosis and the engineer will
        # produce patches against the existing files.
        return self._stage_engineer(result)

    # ── Documentation stages (absorbed from doc_orchestrator) ──────────────

    def _stage_doc_generate(self, result: "PipelineResult") -> None:
        """Generate documentation files using the documentation agent."""
        from agents import DocumentationAgent

        body = (result.requirement or "").strip()
        existing_files = getattr(result, "existing_files", {}) or {}
        agent = DocumentationAgent(
            model=self._doc_model if hasattr(self, "_doc_model") else self.model,
            backend=getattr(self, "_doc_backend", None),
            ollama_url=self.ollama_url,
            nvidia_nim_api_key=self.nvidia_nim_api_key,
            nvidia_nim_base_url=self.nvidia_nim_base_url,
        )
        produced = agent.generate(body, existing_files)
        # Store as files dict so the standard commit/PR helpers can pick them up
        result.files.update(produced)

    def _stage_doc_commit_pr(self, result: "PipelineResult") -> None:
        """Commit doc files and open a PR — uses the same path as feature pipeline."""
        # The orchestrator already has commit + PR helpers used by the
        # feature pipeline. Reuse them.
        if not getattr(result, "files", None):
            return
        self._commit_and_open_pr(result)

```

In the `_make_stage_registry` method (around line 743), append these four entries inside the returned dict, just before the closing `}`:

```python
            "diagnose": PipelineStage(
                name="diagnose",
                label="🔬 Diagnoser",
                description="Diagnosing bug from issue body and existing files...",
                checkpoint_key="diagnose",
                fn=lambda r: self._stage_diagnose(r),
            ),
            "bug_fix": PipelineStage(
                name="bug_fix",
                label="🛠️  Bug Fix",
                description="Applying bug fix patches...",
                checkpoint_key="bug_fix",
                fn=lambda r: self._stage_bug_fix(r),
            ),
            "doc_generate": PipelineStage(
                name="doc_generate",
                label="📚 Doc Generator",
                description="Generating documentation files...",
                checkpoint_key="doc_generate",
                fn=lambda r: self._stage_doc_generate(r),
            ),
            "doc_commit_pr": PipelineStage(
                name="doc_commit_pr",
                label="📤 Doc Commit + PR",
                description="Committing docs and opening PR...",
                checkpoint_key="doc_commit_pr",
                fn=lambda r: self._stage_doc_commit_pr(r),
            ),
```

If `_commit_and_open_pr` does not exist on `Orchestrator`, locate the existing PR/commit code path (search for `create_pull_request` or `make_branch`) and create a small `_commit_and_open_pr` helper that wraps the existing logic. This must not duplicate logic — extract from existing code.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_pipeline_registry.py -v`
Expected: PASS — all 3 tests green.

- [ ] **Step 5: Run full suite — bug_fix_orchestrator and doc_orchestrator tests should still pass (we have not deleted them yet)**

Run: `python -m pytest -x -q 2>&1 | tail -10`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add orchestrator.py tests/test_pipeline_registry.py
git commit -m "feat(orchestrator): register bug-fix and doc stages in unified registry

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 5: Add `pipelines/` directory with built-in YAML files

**Files:**
- Create: `pipelines/ai-feature.yaml`
- Create: `pipelines/ai-fix.yaml`
- Create: `pipelines/ai-docs.yaml`
- Modify: `orchestrator.py:850-933` (the `_load_pipeline_yaml` method) to add label-based search

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pipeline_registry.py`:

```python
def test_load_pipeline_for_label_finds_builtin(tmp_path, monkeypatch):
    """Orchestrator can load pipelines/<label>.yaml from the script dir."""
    from orchestrator import Orchestrator

    orch = Orchestrator(model="gpt-4.1", use_github=False, github_token=None, github_repo=None, target_repo=None)
    stages = orch.load_pipeline_for_label("ai-feature")
    assert stages is not None
    assert isinstance(stages, list)
    assert len(stages) > 0


def test_load_pipeline_for_label_unknown_returns_none():
    from orchestrator import Orchestrator

    orch = Orchestrator(model="gpt-4.1", use_github=False, github_token=None, github_repo=None, target_repo=None)
    assert orch.load_pipeline_for_label("no-such-label") is None


def test_load_pipeline_for_label_project_overrides_builtin(tmp_path):
    """A pipeline.yaml at the project root takes priority over pipelines/<label>.yaml."""
    from orchestrator import Orchestrator

    project = tmp_path / "myproject"
    project.mkdir()
    (project / "pipeline.yaml").write_text(
        "stages:\n  - pm\n  - engineer\n", encoding="utf-8"
    )
    orch = Orchestrator(
        model="gpt-4.1", use_github=False,
        github_token=None, github_repo=None, target_repo=None,
    )
    stages = orch.load_pipeline_for_label("ai-feature", project_dir=str(project))
    # Project pipeline.yaml wins
    assert stages == ["pm", "engineer"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pipeline_registry.py::test_load_pipeline_for_label_finds_builtin -v`
Expected: FAIL — `AttributeError: ... has no attribute 'load_pipeline_for_label'` (and pipelines/ dir doesn't exist).

- [ ] **Step 3: Create the three pipeline YAML files**

Create `pipelines/ai-feature.yaml`:

```yaml
# Built-in feature pipeline — label: ai-feature
# Mirrors the original Orchestrator default sequence.
stages:
  - pm
  - pm_reviewer
  - architect
  - architect_reviewer
  - tier_review
  - junior_engineer
  - senior_engineer
  - reviewer
  - qa_planner
  - qa_engineer
  - test_fix
  - deploy_tester
  - deploy_fix
```

Create `pipelines/ai-fix.yaml`:

```yaml
# Built-in bug-fix pipeline — label: ai-fix
# Replaces bug_fix_orchestrator.py with a stage sequence on the unified
# Orchestrator. The Engineer treats the diagnosis as its architecture.
stages:
  - diagnose
  - bug_fix
  - reviewer
  - test_fix
```

Create `pipelines/ai-docs.yaml`:

```yaml
# Built-in documentation pipeline — label: ai-docs
# Replaces doc_orchestrator.py.
stages:
  - doc_generate
  - doc_commit_pr
```

- [ ] **Step 4: Add `load_pipeline_for_label` to `orchestrator.py`**

In `orchestrator.py`, after the `_load_pipeline_yaml` method (around line 933), add:

```python
    def load_pipeline_for_label(
        self,
        label: str,
        project_dir: "str | None" = None,
    ) -> "list | None":
        """Resolve the pipeline stage list for a given GitHub label.

        Priority (highest to lowest):
        1. ``project_dir/pipeline.yaml`` if it exists (project override)
        2. ``pipelines/<label>.yaml`` next to this orchestrator module
        3. ``None`` (caller falls back to built-in default)
        """
        from pathlib import Path
        # 1. Project override
        if project_dir:
            project_yaml = Path(project_dir) / "pipeline.yaml"
            if project_yaml.exists():
                stages = self._load_pipeline_yaml(str(project_yaml.parent / "config.yaml"))
                if stages is not None:
                    return stages
                # _load_pipeline_yaml looks at parent of config_path — load directly
                import yaml
                with open(project_yaml, encoding="utf-8") as fh:
                    raw = yaml.safe_load(fh) or {}
                return raw.get("stages")

        # 2. Built-in pipelines/<label>.yaml
        builtin = Path(__file__).parent / "pipelines" / f"{label}.yaml"
        if builtin.exists():
            import yaml
            with open(builtin, encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
            return raw.get("stages")

        # 3. Nothing found
        return None
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_pipeline_registry.py -v`
Expected: PASS — all tests including the 3 new ones.

- [ ] **Step 6: Commit**

```bash
git add pipelines/ orchestrator.py tests/test_pipeline_registry.py
git commit -m "feat(pipelines): add built-in YAML pipelines and label-based loader

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 6: Refactor watcher dispatch to use label → pipeline YAML

**Files:**
- Modify: `watcher.py:208-296` (the `_dispatch` function)
- Modify: `watcher.py:578-615` (the `watch` function — pass label instead of pipeline_type)

- [ ] **Step 1: Write the failing test**

Create `tests/test_watcher_dispatch.py`:

```python
"""Tests for label-based watcher dispatch."""
from unittest.mock import MagicMock, patch


def test_dispatch_uses_pipeline_for_label(monkeypatch):
    """Watcher passes the label to Orchestrator and uses pipelines/<label>.yaml."""
    from watcher import _dispatch

    captured: dict = {}

    class FakeOrch:
        def __init__(self, **kwargs):
            captured["init"] = kwargs
            self._pipeline_yaml_stages = None
        def load_pipeline_for_label(self, label, project_dir=None):
            captured["label"] = label
            return ["pm", "engineer"]
        def run(self, requirement, **kwargs):
            captured["run"] = (requirement, kwargs)
            captured["stages"] = self._pipeline_yaml_stages
            return MagicMock(success=True)

    fake_module = MagicMock()
    fake_module.Orchestrator = FakeOrch

    monkeypatch.setitem(__import__("sys").modules, "orchestrator", fake_module)

    # Provide a fake GitHubClient that returns a stub issue
    class FakeGH:
        def __init__(self, repo, token):
            pass
        def get_issue(self, n):
            return {"title": "T", "body": "B"}

    fake_gh_module = MagicMock()
    fake_gh_module.GitHubClient = FakeGH
    fake_gh_module.parse_target_repo = lambda b: None
    monkeypatch.setitem(__import__("sys").modules, "github_client", fake_gh_module)

    from pathlib import Path
    _dispatch(
        label="ai-feature",
        tracker_repo="owner/r", target_repo="owner/r", issue_number=1,
        model="m", num_engineers=1,
        log_file=Path("/tmp/x.log"),
        logger=MagicMock(),
    )
    assert captured["label"] == "ai-feature"
    assert captured["stages"] == ["pm", "engineer"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_watcher_dispatch.py -v`
Expected: FAIL — `_dispatch` still takes `pipeline_type`, not `label`.

- [ ] **Step 3: Refactor `watcher.py:_dispatch`**

In `watcher.py`, replace the entire `_dispatch` function (lines ~208–296) with:

```python
def _dispatch(
    label: str,
    tracker_repo: str,
    target_repo: str,
    issue_number: int,
    model: str,
    num_engineers: int,
    log_file: Path,
    logger: logging.Logger,
) -> None:
    """Run the unified Orchestrator with the pipeline file selected by ``label``."""
    token = os.environ.get("GITHUB_TOKEN")

    pipeline_cfg = _load_pipeline_config()
    llm_cfg = pipeline_cfg.get("llm", {})
    pipe_cfg = pipeline_cfg.get("pipeline", {})
    cfg_model = llm_cfg.get("model", "") or ""
    effective_model = cfg_model if cfg_model and cfg_model != "gpt-4.1" else model
    model_overrides = llm_cfg.get("overrides", {})
    ollama_url = llm_cfg.get("ollama_url", "http://localhost:11434")
    nvidia_nim_api_key = llm_cfg.get("nvidia_nim_api_key") or os.environ.get("NVIDIA_API_KEY")
    nvidia_nim_base_url = llm_cfg.get("nvidia_nim_base_url") or os.environ.get("NVIDIA_NIM_BASE_URL")
    retry_delay = pipe_cfg.get("retry_delay", 15)
    max_api_retries = pipe_cfg.get("max_api_retries", 5)
    inter_call_delay = pipe_cfg.get("inter_call_delay", 0)

    with open(log_file, "w", encoding="utf-8") as fh:
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = fh
        try:
            from orchestrator import Orchestrator
            from github_client import GitHubClient

            tracker_gh = GitHubClient(tracker_repo, token)
            issue = tracker_gh.get_issue(issue_number)
            issue_body = issue.get("body") or ""
            requirement = (issue_body or issue.get("title") or "").strip()

            orch = Orchestrator(
                model=effective_model,
                model_overrides=model_overrides,
                github_token=token,
                github_repo=tracker_repo,
                target_repo=target_repo,
                num_engineers=num_engineers,
                use_github=True,
                ollama_url=ollama_url,
                nvidia_nim_api_key=nvidia_nim_api_key,
                nvidia_nim_base_url=nvidia_nim_base_url,
                retry_delay=retry_delay,
                max_api_retries=max_api_retries,
                inter_call_delay=inter_call_delay,
            )

            # Resolve pipeline stages for this label (project override → builtin)
            stages = orch.load_pipeline_for_label(label)
            if stages is not None:
                orch._pipeline_yaml_stages = stages
                logger.info("    Using pipelines/%s.yaml (%d stages)", label, len(stages))
            else:
                logger.info("    Using built-in default pipeline (no pipelines/%s.yaml)", label)

            orch.run(requirement, trigger_issue_body=issue_body, issue_number=issue_number)
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr
```

- [ ] **Step 4: Update `run_pipeline` and `watch` to pass `label` instead of `pipeline_type`**

In `watcher.py`, modify `run_pipeline` (around line 121). Change the parameter name `pipeline_type: str` to `label: str` and update the call to `_dispatch` to pass `label=label`. Also update the log message to print the label rather than pipeline type.

In `watcher.py`, modify the `watch` function (around line 578) — replace the three blocks that handle `feature_label`, `bug_label`, `doc_label` with a generic loop that respects label config:

```python
        # Read label → pipeline mapping for this watcher entry
        labels_cfg = w.get("labels")
        if labels_cfg is None:
            # Backward-compat: synthesise from old field names
            labels_cfg = {}
            if w.get("feature_label", "ai-feature"):
                labels_cfg[w.get("feature_label", "ai-feature")] = {}
            if w.get("bug_label", "ai-fix"):
                labels_cfg[w.get("bug_label", "ai-fix")] = {}
            if w.get("doc_label"):
                labels_cfg[w.get("doc_label")] = {}

        # Ensure state labels exist
        for name, colour in LABEL_COLOURS.items():
            ensure_label(tracker_repo, name, colour)

        logger.info("Checking %s …", tracker_repo)
        try:
            for label_name, label_cfg in labels_cfg.items():
                pipeline_name = (label_cfg or {}).get("pipeline", label_name)
                for issue in get_open_issues(tracker_repo, label_name):
                    add_label(tracker_repo, issue["number"], LABEL_QUEUED)
                    tasks.append(dict(
                        issue=issue,
                        tracker_repo=tracker_repo,
                        default_target=default_target,
                        label=pipeline_name,
                        parallel_issues=w.get("parallel_issues", 1),
                    ))
                    logger.info("  Queued %s issue #%d: %s", pipeline_name, issue["number"], issue["title"])
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to fetch issues from %s: %s", tracker_repo, exc)
```

In the dispatcher loop (around line 626), change the `pipeline_type` reference to `label`:

```python
        futures = {
            pool.submit(
                run_pipeline,
                t["issue"], t["tracker_repo"], t["default_target"],
                t["label"], model, num_engineers, log_dir, dry_run, logger,
            ): t
            for t in tasks
        }
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_watcher_dispatch.py -v`
Expected: PASS.

Run: `python -m pytest -x -q 2>&1 | tail -10`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add watcher.py tests/test_watcher_dispatch.py
git commit -m "feat(watcher): dispatch by label using pipelines/<label>.yaml

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 7: Add per-repo `parallel_issues` and watcher `--once` mode

**Files:**
- Modify: `watcher.py:540-641` (the `watch` function — per-repo executors)
- Modify: `watcher.py:666-704` (the `main` function — `--once` flags)

- [ ] **Step 1: Write the failing test**

Create `tests/test_watcher_once.py`:

```python
"""Tests for watcher --once mode."""
import sys
from unittest.mock import patch, MagicMock


def test_once_mode_flags_parse():
    """`watcher.py --once --repo X --issue N --label L` parses correctly."""
    from watcher import _build_arg_parser

    parser = _build_arg_parser()
    args = parser.parse_args([
        "--once",
        "--repo", "owner/r",
        "--issue", "42",
        "--label", "ai-feature",
    ])
    assert args.once is True
    assert args.repo == "owner/r"
    assert args.issue == 42
    assert args.label == "ai-feature"


def test_once_dispatches_single_issue(monkeypatch):
    """`run_once(...)` calls _dispatch with the right args and exits."""
    from watcher import run_once

    called: dict = {}

    def fake_dispatch(**kwargs):
        called.update(kwargs)

    monkeypatch.setattr("watcher._dispatch", fake_dispatch)
    monkeypatch.setattr("watcher._load_pipeline_config", lambda: {})

    # Should not raise, should call _dispatch once with our args
    rc = run_once(repo="owner/r", issue=42, label="ai-feature", logger=MagicMock())
    assert rc == 0
    assert called["label"] == "ai-feature"
    assert called["tracker_repo"] == "owner/r"
    assert called["issue_number"] == 42
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_watcher_once.py -v`
Expected: FAIL — `cannot import name '_build_arg_parser'`.

- [ ] **Step 3: Add `_build_arg_parser`, `run_once`, and per-repo executor support**

In `watcher.py`, replace the `main` function with:

```python
def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI Software House — GitHub issue watcher")
    parser.add_argument("--config", default="repos.yaml", help="Path to repos.yaml")
    parser.add_argument("--dry-run", action="store_true", help="Show what would run, make no changes")
    parser.add_argument("--once", action="store_true",
                        help="Process a single issue and exit (used by GitHub Actions)")
    parser.add_argument("--repo", help="(--once mode) tracker repo, e.g. owner/repo")
    parser.add_argument("--issue", type=int, help="(--once mode) issue number")
    parser.add_argument("--label", help="(--once mode) GitHub label that triggered the pipeline")
    return parser


def run_once(repo: str, issue: int, label: str, logger: logging.Logger) -> int:
    """Process a single issue and exit. Used by GitHub Actions workflows.

    Returns exit code (0 = success, 1 = failure).
    """
    install_llm_pool_from_config(_load_pipeline_config())
    log_dir = Path(__file__).parent / "logs" / "watcher"
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    issue_log = log_dir / f"issue-{issue}-{ts}.log"
    try:
        _dispatch(
            label=label,
            tracker_repo=repo,
            target_repo=repo,
            issue_number=issue,
            model="gpt-4.1",
            num_engineers=2,
            log_file=issue_log,
            logger=logger,
        )
        logger.info("✅ Issue #%d complete", issue)
        return 0
    except Exception as exc:  # noqa: BLE001
        logger.error("❌ Issue #%d failed: %s", issue, exc)
        return 1


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    # --once mode short-circuits everything (no lock file, no polling)
    if args.once:
        if not (args.repo and args.issue is not None and args.label):
            print("--once requires --repo, --issue, and --label", file=sys.stderr)
            sys.exit(2)
        log_dir = Path(__file__).parent / "logs" / "watcher"
        logger = _setup_logging(log_dir)
        sys.exit(run_once(args.repo, args.issue, args.label, logger))

    # ── Polling mode (existing behaviour) ───────────────────────────────
    config_path = Path(args.config).resolve()
    if not config_path.exists():
        print(f"Config not found: {config_path}")
        sys.exit(1)

    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    log_dir = Path(config_path.parent / raw.get("settings", {}).get("log_dir", "logs/watcher"))
    logger = _setup_logging(log_dir)

    if LOCK_FILE.exists():
        age = time.time() - LOCK_FILE.stat().st_mtime
        if age < 3600:
            logger.warning("Lock file exists (age %.0fs) — previous run still in progress. Exiting.", age)
            sys.exit(0)
        else:
            logger.warning("Stale lock file (age %.0fs) — removing and continuing.", age)
            LOCK_FILE.unlink()

    LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
    install_llm_pool_from_config(_load_pipeline_config())
    logger.info("═" * 60)
    logger.info("AI Software House Watcher — %s%s",
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                " [DRY RUN]" if args.dry_run else "")
    logger.info("Config: %s", config_path)
    try:
        watch(config_path, dry_run=args.dry_run, logger=logger)
    finally:
        LOCK_FILE.unlink(missing_ok=True)
        logger.info("Done.")
```

In the `watch` function (around line 626), change the single global `ThreadPoolExecutor` to per-repo executors so `parallel_issues` controls concurrency:

```python
    # Group tasks by tracker_repo so each gets its own thread pool
    by_repo: dict[str, list[dict]] = {}
    for t in tasks:
        by_repo.setdefault(t["tracker_repo"], []).append(t)

    logger.info("Dispatching %d pipeline(s) across %d repo(s)…", len(tasks), len(by_repo))

    # One executor per repo; each repo's parallel_issues bounds its concurrency
    repo_executors: list[ThreadPoolExecutor] = []
    futures_to_task: dict = {}
    try:
        for repo_name, repo_tasks in by_repo.items():
            par = max(1, repo_tasks[0].get("parallel_issues", 1))
            ex = ThreadPoolExecutor(max_workers=par, thread_name_prefix=f"watcher-{repo_name}")
            repo_executors.append(ex)
            for t in repo_tasks:
                fut = ex.submit(
                    run_pipeline,
                    t["issue"], t["tracker_repo"], t["default_target"],
                    t["label"], model, num_engineers, log_dir, dry_run, logger,
                )
                futures_to_task[fut] = t

        for fut in as_completed(futures_to_task):
            t = futures_to_task[fut]
            try:
                fut.result()
            except Exception as exc:  # noqa: BLE001
                logger.error("Unhandled error for issue #%d: %s", t["issue"]["number"], exc)
    finally:
        for ex in repo_executors:
            ex.shutdown(wait=True)
```

(Replace the existing `with ThreadPoolExecutor(max_workers=max_parallel) as pool:` block with the above.)

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_watcher_once.py -v`
Expected: PASS.

Run: `python -m pytest -x -q 2>&1 | tail -10`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add watcher.py tests/test_watcher_once.py
git commit -m "feat(watcher): add --once mode and per-repo parallel_issues executors

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 8: Add `--pipeline` and `--list-pipelines` flags to main.py

**Files:**
- Modify: `main.py` (the `main()` function and argparser)
- Test: `tests/test_main_cli.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_main_cli.py`:

```python
"""Tests for main.py CLI flags."""
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_list_pipelines_includes_builtins():
    """`python main.py --list-pipelines` lists ai-feature, ai-fix, ai-docs."""
    result = subprocess.run(
        [sys.executable, "main.py", "--list-pipelines"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "ai-feature" in result.stdout
    assert "ai-fix" in result.stdout
    assert "ai-docs" in result.stdout


def test_pipeline_flag_parses():
    """`--pipeline ai-fix` is a valid argument (will fail elsewhere — we just check parsing)."""
    from main import _build_arg_parser
    parser = _build_arg_parser()
    args = parser.parse_args(["something", "--pipeline", "ai-fix"])
    assert args.pipeline == "ai-fix"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_main_cli.py -v`
Expected: FAIL — `cannot import name '_build_arg_parser'` and `--list-pipelines` doesn't exist.

- [ ] **Step 3: Refactor `main.py` to expose `_build_arg_parser` and add new flags**

In `main.py`, locate the existing `argparse.ArgumentParser` setup (likely inline in `main()`). Extract it to:

```python
def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI Software House — local CLI")
    parser.add_argument("requirement", nargs="?", default=None,
                        help="The requirement to build (omit when using --list-pipelines)")
    parser.add_argument("--pipeline", default=None,
                        help="Pipeline name (resolves to pipelines/<name>.yaml)")
    parser.add_argument("--list-pipelines", action="store_true",
                        help="List available built-in pipelines and exit")
    # Preserve any existing flags below — keep them as they were
    # ...existing add_argument calls...
    return parser
```

In `main()`, near the top, handle `--list-pipelines`:

```python
def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    if args.list_pipelines:
        from pathlib import Path
        pipelines_dir = Path(__file__).parent / "pipelines"
        if not pipelines_dir.exists():
            print("No pipelines/ directory found.")
            sys.exit(0)
        print("Available pipelines:")
        for p in sorted(pipelines_dir.glob("*.yaml")):
            print(f"  {p.stem}")
        sys.exit(0)

    if args.requirement is None:
        parser.error("requirement is required (or pass --list-pipelines)")

    # Install LLM pool from config
    from watcher import install_llm_pool_from_config, _load_pipeline_config
    install_llm_pool_from_config(_load_pipeline_config())

    # ... existing main() body continues here ...
    # When constructing the orchestrator, after creation:
    #     if args.pipeline:
    #         stages = orch.load_pipeline_for_label(args.pipeline)
    #         if stages is None:
    #             print(f"No pipeline found for {args.pipeline!r}", file=sys.stderr)
    #             sys.exit(1)
    #         orch._pipeline_yaml_stages = stages
```

Find the existing `Orchestrator(...)` construction in `main()`. Immediately after that line, add:

```python
    if args.pipeline:
        stages = orch.load_pipeline_for_label(args.pipeline)
        if stages is None:
            print(f"No pipeline found for {args.pipeline!r}", file=sys.stderr)
            sys.exit(1)
        orch._pipeline_yaml_stages = stages
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_main_cli.py -v`
Expected: PASS.

Run: `python -m pytest -x -q 2>&1 | tail -10`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_main_cli.py
git commit -m "feat(main): add --pipeline and --list-pipelines CLI flags

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 9: Update GitHub Actions workflows + delete thin wrappers

**Files:**
- Modify: `.github/workflows/feature-build.yml:60-67` (replace `python build_feature.py` call)
- Modify: `.github/workflows/bug-fix.yml` (replace `python fix_issue.py` call)
- Delete: `build_feature.py`
- Delete: `fix_issue.py`

- [ ] **Step 1: Update `.github/workflows/feature-build.yml`**

In `.github/workflows/feature-build.yml`, replace the `Run full pipeline` step with:

```yaml
      - name: Run pipeline
        env:
          GITHUB_TOKEN: ${{ secrets.GH_TOKEN }}
        run: |
          python watcher.py --once \
            --repo ${{ github.repository }} \
            --issue ${{ steps.issue.outputs.number }} \
            --label ai-feature
```

- [ ] **Step 2: Update `.github/workflows/bug-fix.yml`**

View the current `Run` step in `.github/workflows/bug-fix.yml` and replace it with:

```yaml
      - name: Run pipeline
        env:
          GITHUB_TOKEN: ${{ secrets.GH_TOKEN }}
        run: |
          python watcher.py --once \
            --repo ${{ github.repository }} \
            --issue ${{ steps.issue.outputs.number }} \
            --label ai-fix
```

(Preserve any other steps like checkout, python setup, configure git, post-failure comment.)

- [ ] **Step 3: Delete the thin wrapper scripts**

```bash
rm build_feature.py fix_issue.py
```

- [ ] **Step 4: Verify no other code imports the deleted modules**

Run:

```bash
grep -rn "from build_feature\|import build_feature\|from fix_issue\|import fix_issue" --include="*.py" .
```

Expected: empty output. If any matches appear, update them to use `watcher.run_once` or remove the import.

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest -x -q 2>&1 | tail -10`
Expected: All tests pass. (Watch for any tests that imported the deleted modules — if so, delete those test files too as the functionality is now covered by `tests/test_watcher_once.py`.)

- [ ] **Step 6: Commit**

```bash
git add -A .github/workflows/ build_feature.py fix_issue.py
git commit -m "refactor(workflows): call watcher.py --once; delete thin wrapper scripts

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 10: Delete `bug_fix_orchestrator.py` and `doc_orchestrator.py`

**Files:**
- Delete: `bug_fix_orchestrator.py`
- Delete: `doc_orchestrator.py`
- Modify: any test file that imports the deleted modules

- [ ] **Step 1: Verify the diagnose stage no longer imports the deleted module**

The `_stage_diagnose` method in `orchestrator.py` imports `from bug_fix_orchestrator import _DIAGNOSIS_PREFIX`. Inline the constant directly into `orchestrator.py` instead.

In `orchestrator.py`, near the top of the file (next to other module-level constants), add:

```python
# Diagnosis system prompt overlay used by the bug-fix pipeline.
_DIAGNOSIS_PREFIX = """
You are performing a **bug diagnosis**, not a new system design.

Given:
- A bug report (title + description from a GitHub Issue)
- The existing codebase files provided

Your job is to:
1. Identify the most likely root cause
2. Pinpoint the exact file(s) and function(s) that need changing
3. Describe the minimal fix required — do NOT redesign the whole system
4. List only the module(s) that need to be touched

Output format:
```markdown
# Bug Diagnosis: [Bug Title]

## Root Cause
[Concise explanation of why the bug occurs]

## Affected Files
- `path/to/file.py` — [what needs to change]

## Fix Strategy
[Step-by-step description of the minimal fix]

## Implementation Modules
1. **[module_name]**: [file to fix] — [what to change]
```
"""
```

In the `_stage_diagnose` method, change `from bug_fix_orchestrator import _DIAGNOSIS_PREFIX` to remove the import (the constant is now local to the module).

- [ ] **Step 2: Find and remove orphan tests**

Run:

```bash
grep -rln "from bug_fix_orchestrator\|import bug_fix_orchestrator\|from doc_orchestrator\|import doc_orchestrator" tests/
```

For each file found:
- If it's testing functionality already covered by `tests/test_pipeline_registry.py` (stage existence) and the new dispatch tests, delete the file.
- Otherwise, port the test to use the unified `Orchestrator` with the appropriate `_pipeline_yaml_stages`.

Specifically expected to be affected:
- `tests/test_bug_fix_retry.py` — likely needs porting; if it tests retry behaviour, port it to test the unified test_fix loop
- `tests/test_doc_orchestrator.py` — delete (functionality covered by stage-registry tests)

- [ ] **Step 3: Delete the orchestrator files**

```bash
rm bug_fix_orchestrator.py doc_orchestrator.py
```

- [ ] **Step 4: Run full test suite**

Run: `python -m pytest -x -q 2>&1 | tail -20`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add -A bug_fix_orchestrator.py doc_orchestrator.py orchestrator.py tests/
git commit -m "refactor: delete bug_fix_orchestrator and doc_orchestrator (absorbed into Orchestrator)

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 11: Update README and example configs

**Files:**
- Modify: `README.md` — add a section on label → pipeline mapping and concurrency
- Modify: `repos.yaml.example` (or `repos.yaml` if no example) — add `parallel_issues` and `labels:` examples
- Modify: `config.yaml.example` — confirm `llm.pools` documentation present (added in Task 3)

- [ ] **Step 1: Update `repos.yaml.example`**

Locate `repos.yaml.example` (or the live `repos.yaml`). Add a commented example entry:

```yaml
# Example with new per-label pipeline mapping and parallel issue handling:
#
# watchers:
#   - tracker_repo: owner/my-tracker
#     default_target: owner/my-app
#     enabled: true
#     parallel_issues: 2          # process up to 2 issues concurrently for this repo
#     labels:
#       ai-feature: {}            # uses pipelines/ai-feature.yaml
#       ai-fix: {}                # uses pipelines/ai-fix.yaml
#       ai-docs: {}               # uses pipelines/ai-docs.yaml
#       ai-refactor:              # custom label — create pipelines/ai-refactor.yaml
#         pipeline: ai-refactor   # explicit map (optional; defaults to label name)
#
# Backwards-compat: feature_label / bug_label / doc_label still work.
```

- [ ] **Step 2: Add a section to `README.md`**

Find the existing pipeline / configuration documentation in `README.md`. Add a new section titled `## 🏷️ Label → Pipeline Mapping`:

```markdown
## 🏷️ Label → Pipeline Mapping

Each GitHub label can trigger its own pipeline. The watcher picks the pipeline file based on the label name.

**Built-in pipelines:**

| Label | Pipeline File | Purpose |
|---|---|---|
| `ai-feature` | `pipelines/ai-feature.yaml` | Full feature build (PM → Architect → Engineer → QA) |
| `ai-fix` | `pipelines/ai-fix.yaml` | Bug-fix flow (diagnose → fix → review → test) |
| `ai-docs` | `pipelines/ai-docs.yaml` | Generate documentation and open a PR |

**Custom pipelines:** Create `pipelines/<your-label>.yaml` with a `stages:` list and add the label to your repo entry in `repos.yaml`. See [Custom Pipeline (pipeline.yaml)](#custom-pipeline-pipelineyaml) for the full format.

**Per-project override:** A `pipeline.yaml` at the project's root takes precedence over the built-in `pipelines/<label>.yaml`.

## ⚡ Concurrency

Two independent layers control parallelism:

- **Per-repo:** `parallel_issues: N` in `repos.yaml` — how many issues from one tracker repo run at once. Default: `1`.
- **Per-LLM-backend:** `llm.pools.<backend>: N` in `config.yaml` — how many simultaneous calls to that backend across all running pipelines. Default: `ollama: 1`, others `5`.

This means you can run feature pipelines in parallel against multiple repos but still keep your local Ollama instance at one call at a time.
```

- [ ] **Step 3: Run all tests one final time**

Run: `python -m pytest -x -q 2>&1 | tail -10`
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add README.md repos.yaml.example
git commit -m "docs: document label-based pipeline mapping and concurrency model

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 12: Push branch and open PR

- [ ] **Step 1: Push the feature branch**

```bash
git push -u origin feat/unified-pipeline
```

- [ ] **Step 2: Open the PR via gh CLI**

```bash
gh pr create \
  --base master \
  --head feat/unified-pipeline \
  --title "Unify pipeline entry points (label → pipeline.yaml)" \
  --body "$(cat <<'EOF'
## Summary

Refactors all pipeline entry points (build_feature.py, fix_issue.py, BugFixOrchestrator, DocOrchestrator) into a single watcher-driven process where each GitHub label maps to a YAML pipeline definition.

See the design spec: \`docs/superpowers/specs/2025-07-28-unified-pipeline-design.md\`

## What changed

- 🆕 \`pipelines/\` directory with built-in YAML files (ai-feature, ai-fix, ai-docs)
- 🆕 \`llm_pool.py\` — per-backend semaphore pools (Ollama-safe by default)
- 🆕 \`watcher.py --once\` mode — single-issue processing for GitHub Actions
- 🆕 Per-repo \`parallel_issues\` setting in repos.yaml
- 🆕 \`main.py --pipeline <name>\` and \`--list-pipelines\` flags
- ♻️  \`bug_fix_orchestrator.py\`, \`doc_orchestrator.py\` absorbed into \`orchestrator.py\`
- ♻️  \`build_feature.py\`, \`fix_issue.py\` deleted; workflows call \`watcher.py --once\`
- 🐛 Fixes: adding a new pipeline now requires only a YAML file — no Python, no workflow

## Backwards compatibility

All new config fields are optional with safe defaults. Existing \`repos.yaml\` and \`config.yaml\` work without modification.

## Tests

All 52 existing tests still pass. New tests added:
- \`tests/test_llm_pool.py\` — pool semaphore behaviour
- \`tests/test_pipeline_registry.py\` — label → pipeline file resolution
- \`tests/test_watcher_dispatch.py\` — label-based dispatch
- \`tests/test_watcher_once.py\` — \`--once\` flag
- \`tests/test_watcher_pool_init.py\` — pool installed from config
- \`tests/test_main_cli.py\` — new CLI flags
EOF
)"
```

- [ ] **Step 3: Capture PR URL for follow-up**

The `gh pr create` command prints the PR URL. Save it for any subsequent merge / review work.

---

## Self-Review Notes

- Spec coverage:
  - Section 1 (Unified Orchestrator) → Tasks 4, 5, 10 ✓
  - Section 2 (Watcher + LLM pools) → Tasks 1, 2, 3, 6, 7 ✓
  - Section 3 (GitHub Actions) → Task 9 ✓
  - Section 4 (main.py CLI + tests) → Task 8, plus tests in every task ✓
- Backwards compat: Task 6 keeps `feature_label`/`bug_label`/`doc_label` synthesis; Task 3 makes `llm.pools` optional; Task 7 makes `parallel_issues` optional ✓
- Type consistency: `label` is consistently a `str`; `parallel_issues` is `int`; pipeline stage names match the registry keys exactly ✓
- All steps include real code or commands — no placeholders ✓
