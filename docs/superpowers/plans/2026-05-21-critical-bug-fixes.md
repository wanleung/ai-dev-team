# Critical Bug Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three critical bugs identified in code review: thread-safe log routing in the watcher daemon (C1), a threading lock on `MemoryStore`'s SQLite connection (C2), and catching `BudgetExceededError` in the sequential pipeline path so a checkpoint is saved (I4).

**Architecture:**
- C1: Replace process-global `sys.stdout/stderr` redirect in `watcher.py` with a per-run `logging.FileHandler` added/removed around `_dispatch()` and `_run_pr_revision()`. The `configure_logging` helper in `logging_setup.py` already supports a `log_file` parameter — we reuse it and remove the handler after the run.
- C2: Add `self._lock = threading.Lock()` to `MemoryStore.__init__` and wrap every public method that touches `self._conn` with `with self._lock:`. Also enable `PRAGMA journal_mode=WAL` on init.
- I4: Add a `except BudgetExceededError` clause alongside the existing `except _ShutdownRequested` in `Orchestrator.run()` so budget exhaustion in the sequential path saves a checkpoint and returns gracefully instead of propagating uncaught.

**Tech Stack:** Python 3.13, SQLite (`sqlite3`), `threading`, `logging`, `structlog`, `pytest`

---

## File Map

| File | Change |
|------|--------|
| `watcher.py` | Remove `sys.stdout/stderr` redirect; add/remove `FileHandler` instead |
| `memory_store.py` | Add `threading.Lock`; enable WAL; guard all public methods |
| `orchestrator.py` | Add `except BudgetExceededError` to sequential `run()` path |
| `tests/test_watcher_dispatch.py` | Add test: concurrent `_dispatch` calls write to separate logs |
| `tests/test_memory_store_extended.py` | Add test: concurrent `save`/`recall` does not raise |
| `tests/test_parallel_budget_exceeded.py` | Add test: sequential budget exceeded saves checkpoint |

---

## Task 1: Fix C1 — Thread-safe log routing in `watcher.py`

**Files:**
- Modify: `watcher.py` (function `_dispatch` ~line 820, function `_run_pr_revision` ~line 966)
- Test: `tests/test_watcher_dispatch.py`

### What the problem is

`_dispatch()` and `_run_pr_revision()` both do:
```python
old_stdout, old_stderr = sys.stdout, sys.stderr
sys.stdout = sys.stderr = fh
...
finally:
    sys.stdout, sys.stderr = old_stdout, old_stderr
```
`sys.stdout` is process-global. Two threads running concurrently will overwrite each other's redirect, causing all output to go to whichever log file was assigned last.

### What we replace it with

Add the log file as a `logging.FileHandler` for the duration of the run, then remove it. The existing `configure_logging` in `logging_setup.py` already does this — we call it, capture the handler it added, then remove it in `finally`.

- [ ] **Step 1: Write failing test for C1**

Add to `tests/test_watcher_dispatch.py`:

```python
import threading
import logging
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest


def test_concurrent_dispatch_does_not_redirect_global_stdout(tmp_path):
    """Concurrent _dispatch calls must not clobber sys.stdout/sys.stderr."""
    from watcher import _dispatch

    log1 = tmp_path / "run1.log"
    log2 = tmp_path / "run2.log"

    original_stdout = sys.stdout
    original_stderr = sys.stderr

    # A fake PipelineResult
    fake_result = MagicMock()
    fake_result.errors = []
    fake_result.next_label = None

    def make_orch(*args, **kwargs):
        orch = MagicMock()
        orch.run.return_value = fake_result
        return orch

    errors = []

    def run_dispatch(log_file):
        try:
            with patch("watcher.Orchestrator", make_orch), \
                 patch("watcher.GitHubClient"), \
                 patch("watcher._collect_issue_prior_context", return_value=""), \
                 patch("watcher._load_pipeline_config", return_value={"llm": {}, "pipeline": {}}):
                _dispatch(
                    label="ai-feature",
                    tracker_repo="owner/repo",
                    target_repo="owner/repo",
                    issue_number=1,
                    model="gpt-4.1",
                    num_engineers=1,
                    log_file=log_file,
                )
        except Exception as exc:
            errors.append(str(exc))

    t1 = threading.Thread(target=run_dispatch, args=(log1,))
    t2 = threading.Thread(target=run_dispatch, args=(log2,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # After both threads complete, global stdout/stderr must be unchanged
    assert sys.stdout is original_stdout, "sys.stdout was corrupted by _dispatch"
    assert sys.stderr is original_stderr, "sys.stderr was corrupted by _dispatch"
    assert errors == [], f"Dispatch raised errors: {errors}"
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd /home/wanleung/Projects/ai-software-house
source venv/bin/activate
pytest tests/test_watcher_dispatch.py::test_concurrent_dispatch_does_not_redirect_global_stdout -v 2>&1 | tail -20
```

Expected: FAIL (sys.stdout is corrupted — assertion fails or test hangs).

- [ ] **Step 3: Fix `_dispatch` in `watcher.py`**

Locate `_dispatch` (around line 800). Replace the `sys.stdout/stderr` redirect block:

**Before** (lines ~820–884):
```python
with open(log_file, "w", encoding="utf-8") as fh:
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = fh
    try:
        from orchestrator import Orchestrator
        from github_client import GitHubClient
        ...
        result = orch.run(requirement, ...)
        return result
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr
```

**After** — remove the redirect entirely; use `configure_logging` to add a per-run file handler:
```python
from logging_setup import configure_logging

# Add per-run file handler (thread-local-friendly — logging is thread-safe)
configure_logging(log_file=log_file)
# Retrieve the handler we just added so we can remove it after the run
_run_fh = next(
    (h for h in logging.getLogger().handlers
     if isinstance(h, logging.FileHandler)
     and h.baseFilename == str(Path(log_file).resolve())),
    None,
)
try:
    from orchestrator import Orchestrator
    from github_client import GitHubClient
    ...
    result = orch.run(requirement, ...)
    return result
finally:
    if _run_fh is not None:
        logging.getLogger().removeHandler(_run_fh)
        _run_fh.close()
```

The full replacement for `_dispatch` (only the logging setup lines change — everything else stays identical):

```python
def _dispatch(
    label: str,
    tracker_repo: str,
    target_repo: str,
    issue_number: int,
    model: str,
    num_engineers: int,
    log_file: Path,
    logger: Optional[logging.Logger] = None,
    deploy_cfg: dict | None = None,
    llm_cfg: dict | None = None,
    pipeline_file: str = "",
) -> "PipelineResult":
    """Run the unified Orchestrator with the pipeline file selected by ``label``."""
    token = os.environ.get("GITHUB_TOKEN")

    pipeline_cfg = _load_pipeline_config()
    _llm = llm_cfg if llm_cfg is not None else pipeline_cfg.get("llm", {})
    pipe_cfg = pipeline_cfg.get("pipeline", {})
    cfg_model = _llm.get("model", "") or ""
    effective_model = cfg_model if cfg_model and cfg_model != "gpt-4.1" else model
    model_overrides = _llm.get("overrides", {})
    ollama_url = _llm.get("ollama_url", "http://localhost:11434")
    nvidia_nim_api_key = _llm.get("nvidia_nim_api_key") or os.environ.get("NVIDIA_API_KEY")
    nvidia_nim_base_url = _llm.get("nvidia_nim_base_url") or os.environ.get("NVIDIA_NIM_BASE_URL")
    retry_delay = pipe_cfg.get("retry_delay", 15)
    max_api_retries = pipe_cfg.get("max_api_retries", 5)
    inter_call_delay = pipe_cfg.get("inter_call_delay", 0)

    # ── Per-run file logging (thread-safe: no sys.stdout redirect) ────────────
    from logging_setup import configure_logging as _configure_logging
    _configure_logging(log_file=log_file)
    _run_fh = next(
        (h for h in logging.getLogger().handlers
         if isinstance(h, logging.FileHandler)
         and h.baseFilename == str(Path(log_file).resolve())),
        None,
    )
    try:
        from orchestrator import Orchestrator
        from github_client import GitHubClient

        tracker_gh = GitHubClient(tracker_repo, token)
        issue = tracker_gh.get_issue(issue_number)
        issue_body = issue.get("body") or ""
        requirement = (issue_body or issue.get("title") or "").strip()

        prior_ctx = _collect_issue_prior_context(tracker_gh, issue_number)
        trigger_issue_body = issue_body + prior_ctx if prior_ctx else issue_body

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
            deploy_cfg=deploy_cfg,
            llm_fallbacks=_llm.get("fallbacks") or None,
        )

        if pipeline_file:
            raw = tracker_gh.get_file_content(pipeline_file)
            if raw:
                import yaml as _yaml
                data = _yaml.safe_load(raw)
                if not isinstance(data, dict):
                    _log.warning(
                        "    pipeline_file %r: expected YAML mapping, got %s — falling back to label lookup",
                        pipeline_file, type(data).__name__,
                    )
                    data = {}
                fetched_stages = data.get("stages")
                if fetched_stages is not None:
                    orch._validate_pipeline_stages(pipeline_file, fetched_stages)
                    orch._pipeline_yaml_stages = fetched_stages
                    _log.info("    Using pipeline_file: %s (%d stages)", pipeline_file, len(fetched_stages))
            else:
                _log.warning(
                    "    pipeline_file %r not found in %s — falling back to label lookup",
                    pipeline_file, tracker_repo,
                )

        stages = orch.load_pipeline_for_label(label)
        if stages is not None:
            orch._pipeline_yaml_stages = stages
            _log.info("    Using pipelines/%s.yaml (%d stages)", label, len(stages))
        else:
            _log.info("    Using built-in default pipeline (no pipelines/%s.yaml)", label)

        result = orch.run(requirement, trigger_issue_body=trigger_issue_body, issue_number=issue_number)
        return result
    finally:
        if _run_fh is not None:
            logging.getLogger().removeHandler(_run_fh)
            _run_fh.close()
```

- [ ] **Step 4: Fix `_run_pr_revision` in `watcher.py`**

Locate `_run_pr_revision` (around line 940). Apply the same pattern — remove the `sys.stdout/stderr` redirect and use the logging file handler instead.

**Before** (lines ~965–1021):
```python
try:
    with open(log_file, "w", encoding="utf-8") as fh:
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = fh
        try:
            ...
        except Exception as exc:
            ...
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr
except OSError as exc:
    ...
```

**After**:
```python
try:
    # ── Per-run file logging (thread-safe: no sys.stdout redirect) ────────
    from logging_setup import configure_logging as _configure_logging
    _configure_logging(log_file=log_file)
    _run_fh = next(
        (h for h in logging.getLogger().handlers
         if isinstance(h, logging.FileHandler)
         and h.baseFilename == str(Path(log_file).resolve())),
        None,
    )
    try:
        from orchestrator import Orchestrator

        orch = Orchestrator(
            model=effective_model,
            ...  # unchanged kwargs
        )

        result = orch.run_revision(pr_number)
        status = result.get("status", "ok")

        if status in ("max_revisions_reached", "error"):
            ...  # unchanged
        else:
            ...  # unchanged

    except Exception as exc:
        ...  # unchanged
    finally:
        if _run_fh is not None:
            logging.getLogger().removeHandler(_run_fh)
            _run_fh.close()
except OSError as exc:
    ...  # unchanged
```

- [ ] **Step 5: Run test to confirm it passes**

```bash
cd /home/wanleung/Projects/ai-software-house
source venv/bin/activate
pytest tests/test_watcher_dispatch.py::test_concurrent_dispatch_does_not_redirect_global_stdout -v 2>&1 | tail -10
```

Expected: PASS

- [ ] **Step 6: Run existing watcher tests to confirm no regressions**

```bash
cd /home/wanleung/Projects/ai-software-house
source venv/bin/activate
pytest tests/test_watcher_dispatch.py tests/test_watcher.py tests/test_watcher_sanitise.py -v 2>&1 | tail -30
```

Expected: All PASS

- [ ] **Step 7: Commit**

```bash
cd /home/wanleung/Projects/ai-software-house
git add watcher.py tests/test_watcher_dispatch.py
git commit -m "fix(watcher): replace global sys.stdout redirect with per-run logging.FileHandler

Concurrent _dispatch/_run_pr_revision calls were clobbering sys.stdout/stderr
because those attributes are process-global. Under parallel_issues > 1 all
threads wrote to whichever log file was last assigned.

Replace with configure_logging(log_file=...) which adds a FileHandler to the
root logger (logging is thread-safe) and remove it in the finally block.

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 2: Fix C2 — Thread-safe `MemoryStore` SQLite connection

**Files:**
- Modify: `memory_store.py`
- Test: `tests/test_memory_store_extended.py`

### What the problem is

`sqlite3.connect(..., check_same_thread=False)` only disables Python's thread-ownership check on the connection object. The `sqlite3.Connection`'s internal C state (open cursor, active transaction) is not protected. Two threads calling `save()` and `recall()` simultaneously will corrupt it.

### What we add

1. `import threading` at the top of `memory_store.py`
2. `self._lock = threading.Lock()` in `__init__`
3. `with self._lock:` wrapping every method that calls `self._conn`
4. `PRAGMA journal_mode=WAL` in `_init_schema` to reduce write-lock contention

- [ ] **Step 1: Write failing test for C2**

Add to `tests/test_memory_store_extended.py`:

```python
import threading
import pytest
from memory_store import MemoryStore


def test_concurrent_save_and_recall_does_not_raise(tmp_path):
    """Concurrent save + recall from multiple threads must not raise OperationalError."""
    db = tmp_path / "mem.db"
    store = MemoryStore(db)

    errors = []

    def writer():
        try:
            for i in range(20):
                store.save(repo="owner/repo", summary=f"run {i}", mode="feature")
        except Exception as exc:
            errors.append(f"writer: {exc}")

    def reader():
        try:
            for _ in range(20):
                store.recall(repo="owner/repo")
        except Exception as exc:
            errors.append(f"reader: {exc}")

    threads = [threading.Thread(target=writer) for _ in range(3)]
    threads += [threading.Thread(target=reader) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    store.close()
    assert errors == [], f"Concurrent access raised errors: {errors}"
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd /home/wanleung/Projects/ai-software-house
source venv/bin/activate
pytest tests/test_memory_store_extended.py::test_concurrent_save_and_recall_does_not_raise -v 2>&1 | tail -20
```

Expected: FAIL (OperationalError: database is locked, or ProgrammingError: recursive use of cursor).

- [ ] **Step 3: Fix `memory_store.py`**

Add `import threading` to the imports at the top of `memory_store.py` (after the existing `import json`):

```python
import threading
```

In `MemoryStore.__init__`, add the lock and WAL mode after `self._conn = ...`:

```python
def __init__(self, db_path: str | Path = "./workspace/memory.db"):
    self.db_path = Path(db_path)
    self.db_path.parent.mkdir(parents=True, exist_ok=True)
    self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
    self._lock = threading.Lock()
    self._conn.execute("PRAGMA journal_mode=WAL")
    self._conn.commit()
    self._init_schema()
```

Wrap every public method with `with self._lock:`. The methods to wrap are:
- `_init_schema` (called from `__init__` — already serialised, but wrap for safety)
- `save`
- `needs_consolidation`
- `needs_quarterly`
- `consolidate_monthly`
- `consolidate_quarterly`
- `recall`
- `recall_issues`
- `search`
- `stats`
- `list_repos`
- `close`

Apply the lock to each method by wrapping the method body. Example for `save`:

```python
def save(
    self,
    repo: str,
    summary: str,
    run_id: Optional[str] = None,
    tags: Optional[list[str]] = None,
    mode: str = "feature",
    tier: str = "run",
    period_label: str = "",
) -> int:
    """Persist a summary entry. Returns the row ID."""
    with self._lock:
        cur = self._conn.execute(
            """INSERT INTO runs
               (repo, run_id, created_at, summary, tags, mode, tier, period_label)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                repo,
                run_id or "",
                datetime.now(timezone.utc).isoformat(),
                summary,
                json.dumps(tags or []),
                mode,
                tier,
                period_label or "",
            ),
        )
        self._conn.commit()
        return cur.lastrowid
```

Apply the same `with self._lock:` wrapping pattern to all other public methods. For `consolidate_monthly` and `consolidate_quarterly`, the LLM call (`llm_fn(prompt)`) should happen **outside** the lock to avoid holding the lock during a potentially long LLM round-trip:

```python
def consolidate_monthly(self, repo, llm_fn, period_label=""):
    # Fetch rows under lock
    with self._lock:
        rows = self._conn.execute(
            """SELECT id, created_at, mode, summary
               FROM runs WHERE repo=? AND tier='run' AND consolidated=0
               ORDER BY id ASC""",
            (repo,),
        ).fetchall()
    if not rows:
        return None

    ids = [r[0] for r in rows]
    period_label = period_label or date.today().strftime("%Y-%m")
    entries = "\n\n".join(f"[{r[1][:10]}] ({r[2]})\n{r[3]}" for r in rows)
    prompt = f"""...(unchanged)..."""

    # LLM call outside lock — can be slow
    consolidated_text = llm_fn(prompt)

    # Write results under lock (atomic: INSERT + UPDATE in one transaction)
    with self._lock:
        with self._conn:  # context manager = BEGIN/COMMIT/ROLLBACK
            cur = self._conn.execute(
                """INSERT INTO runs
                   (repo, run_id, created_at, summary, tags, mode, tier, period_label)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (repo, "", datetime.now(timezone.utc).isoformat(),
                 consolidated_text, json.dumps([]), "consolidation", "monthly", period_label),
            )
            new_id = cur.lastrowid
            self._conn.execute(
                f"UPDATE runs SET consolidated=1 WHERE id IN ({','.join('?' * len(ids))})",
                ids,
            )
    return new_id
```

Apply the same split-lock pattern to `consolidate_quarterly`.

**Important:** The `with self._conn:` context manager (SQLite connection as context manager) provides `BEGIN`/`COMMIT`/`ROLLBACK` automatically. This also fixes bug I2 (INSERT + UPDATE are now atomic).

- [ ] **Step 4: Run test to confirm it passes**

```bash
cd /home/wanleung/Projects/ai-software-house
source venv/bin/activate
pytest tests/test_memory_store_extended.py::test_concurrent_save_and_recall_does_not_raise -v 2>&1 | tail -10
```

Expected: PASS

- [ ] **Step 5: Run all memory store tests**

```bash
cd /home/wanleung/Projects/ai-software-house
source venv/bin/activate
pytest tests/test_memory_store_extended.py tests/test_memory_injection.py -v 2>&1 | tail -30
```

Expected: All PASS

- [ ] **Step 6: Commit**

```bash
cd /home/wanleung/Projects/ai-software-house
git add memory_store.py tests/test_memory_store_extended.py
git commit -m "fix(memory_store): add threading.Lock and WAL mode for concurrent safety

sqlite3 connection state is not thread-safe even with check_same_thread=False.
Under parallel pipeline runs all agents share a MemoryStore and call save/recall
concurrently, causing OperationalError or silent corruption.

- Add self._lock = threading.Lock() in __init__
- Wrap every public method with with self._lock:
- LLM calls in consolidate_monthly/quarterly happen outside the lock
- INSERT + UPDATE in consolidations wrapped in with self._conn: for atomicity
  (also fixes I2: duplicate monthly snapshots on crash)
- Enable PRAGMA journal_mode=WAL to reduce write-lock contention

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 3: Fix I4 — Catch `BudgetExceededError` in sequential `run()` path

**Files:**
- Modify: `orchestrator.py` (around line 3165)
- Test: `tests/test_parallel_budget_exceeded.py`

### What the problem is

In `run()`, the sequential stage path (lines 3098–3113) calls `_run_stage()`. `_run_stage` re-raises `BudgetExceededError` at line 4753. This propagates up through `run()` but the outer `try/except` only catches `_ShutdownRequested` (at line 3165). `BudgetExceededError` escapes `run()` entirely without saving a checkpoint, losing all pipeline progress.

The parallel batch path at line 4640 already handles this correctly — we need to mirror that in the sequential path.

- [ ] **Step 1: Write failing test for I4**

Add to `tests/test_parallel_budget_exceeded.py`:

```python
import pytest
from unittest.mock import MagicMock, patch


def test_sequential_budget_exceeded_saves_checkpoint_and_returns(tmp_path):
    """BudgetExceededError in sequential run() must save a checkpoint and return, not propagate."""
    from orchestrator import Orchestrator
    from agents.token_ledger import BudgetExceededError

    orch = Orchestrator(
        model="gpt-4.1",
        use_github=False,
        workspace_dir=str(tmp_path / "workspace"),
    )

    # Simulate a single sequential stage that raises BudgetExceededError
    save_calls = []

    def fake_save(result):
        save_calls.append(True)

    def fake_finish(result, start_time):
        return result

    def budget_busting_stage(result):
        raise BudgetExceededError("budget exceeded in test")

    with patch.object(orch, "_save_checkpoint", side_effect=fake_save), \
         patch.object(orch, "_finish", side_effect=fake_finish), \
         patch.object(orch, "_build_pipeline_stages", return_value=[]), \
         patch.object(orch, "_tracker", MagicMock()):
        # Directly call run() with a mock stage that raises BudgetExceededError
        # We patch _build_pipeline_stages to inject our stage
        from orchestrator import _PipelineStage
        mock_stage = MagicMock()
        mock_stage.checkpoint_key = "test_stage"
        mock_stage.name = "test_stage"
        mock_stage.label = "Test Stage"
        mock_stage.description = "test"
        mock_stage.loop_stages = None
        mock_stage.stop_if = lambda r: False
        mock_stage.stop_message = ""
        mock_stage.required_output_fields = []
        mock_stage.fn = budget_busting_stage
        mock_stage.parallel_group = None

        with patch.object(orch, "_build_pipeline_stages", return_value=[mock_stage]), \
             patch.object(orch, "_load_checkpoint", return_value=None), \
             patch.object(orch, "_clear_checkpoint"):
            result = orch.run("build a test app", resume=False)

    # Must have called _save_checkpoint (not propagated exception)
    assert len(save_calls) >= 1, "Expected _save_checkpoint to be called on BudgetExceededError"
    assert any("budget" in str(e).lower() or "Budget" in str(e) for e in result.errors), \
        f"Expected budget error in result.errors, got: {result.errors}"
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd /home/wanleung/Projects/ai-software-house
source venv/bin/activate
pytest tests/test_parallel_budget_exceeded.py::test_sequential_budget_exceeded_saves_checkpoint_and_returns -v 2>&1 | tail -20
```

Expected: FAIL — either `BudgetExceededError` propagates (no result returned) or `_save_checkpoint` is never called.

- [ ] **Step 3: Fix `orchestrator.py`**

Locate the `except _ShutdownRequested:` block at line ~3165 in `run()`:

```python
        except _ShutdownRequested:
            logging.info("Graceful shutdown: pipeline interrupted before completion")
            result.progress_comment_id = self._tracker.comment_id
            self._save_checkpoint(result)
            return self._finish(result, start_time)
```

Add a `BudgetExceededError` handler immediately after it:

```python
        except _ShutdownRequested:
            logging.info("Graceful shutdown: pipeline interrupted before completion")
            result.progress_comment_id = self._tracker.comment_id
            self._save_checkpoint(result)
            return self._finish(result, start_time)

        except BudgetExceededError:
            logging.warning("Token budget exceeded — saving checkpoint and aborting pipeline")
            result.add_error("Pipeline aborted: token budget exceeded")
            result.progress_comment_id = self._tracker.comment_id
            self._save_checkpoint(result)
            return self._finish(result, start_time)
```

`BudgetExceededError` is already imported at line 63:
```python
from agents.token_ledger import TokenLedger, BudgetExceededError, current_stage, get_ledger, set_ledger
```

No new import needed.

- [ ] **Step 4: Run test to confirm it passes**

```bash
cd /home/wanleung/Projects/ai-software-house
source venv/bin/activate
pytest tests/test_parallel_budget_exceeded.py::test_sequential_budget_exceeded_saves_checkpoint_and_returns -v 2>&1 | tail -10
```

Expected: PASS

- [ ] **Step 5: Run related tests to confirm no regressions**

```bash
cd /home/wanleung/Projects/ai-software-house
source venv/bin/activate
pytest tests/test_parallel_budget_exceeded.py tests/test_token_ledger.py tests/test_token_ledger_thread_safety.py tests/test_checkpoint_save_resume.py -v 2>&1 | tail -30
```

Expected: All PASS

- [ ] **Step 6: Commit**

```bash
cd /home/wanleung/Projects/ai-software-house
git add orchestrator.py tests/test_parallel_budget_exceeded.py
git commit -m "fix(orchestrator): catch BudgetExceededError in sequential run() path

BudgetExceededError raised by _run_stage() in the sequential stage path
was not caught by run()'s outer try/except (which only handled
_ShutdownRequested). The exception escaped run() entirely, losing all
pipeline progress without saving a checkpoint.

Add except BudgetExceededError alongside _ShutdownRequested to save a
checkpoint and return a result gracefully. The parallel batch path at
line 4640 already handled this correctly — this mirrors that behaviour
for sequential runs.

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 4: Final verification

- [ ] **Step 1: Run the full test suite**

```bash
cd /home/wanleung/Projects/ai-software-house
source venv/bin/activate
pytest tests/ -x -q 2>&1 | tail -40
```

Expected: All tests pass (or pre-existing failures only — no new failures introduced).

- [ ] **Step 2: Confirm no sys.stdout redirect exists anywhere in watcher.py**

```bash
grep -n "sys\.stdout\s*=" /home/wanleung/Projects/ai-software-house/watcher.py
```

Expected: No output (the redirect is gone).

- [ ] **Step 3: Confirm threading.Lock is present in memory_store.py**

```bash
grep -n "_lock\|threading\.Lock\|journal_mode=WAL" /home/wanleung/Projects/ai-software-house/memory_store.py
```

Expected: At least 3 lines (the import, the init, and the WAL pragma).

- [ ] **Step 4: Confirm BudgetExceededError is caught in orchestrator.py**

```bash
grep -n -A4 "except BudgetExceededError" /home/wanleung/Projects/ai-software-house/orchestrator.py
```

Expected: At least 2 occurrences — the existing parallel-path one and the new sequential-path one.
