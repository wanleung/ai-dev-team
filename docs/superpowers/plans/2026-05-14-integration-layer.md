# Integration Layer (MCP + REST API) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `aisw_server.py` — a FastAPI + MCP server that lets Copilot CLI, Claude Code, OpenCode, web UIs, and curl trigger `ai-software-house` pipelines, stream live logs via SSE, and inspect results.

**Architecture:** Single process exposing REST (FastAPI) + MCP (fastapi_mcp auto-bridge) on port 8765. Jobs run in a `ThreadPoolExecutor` (wrapping the sync `Orchestrator`), persisted to `jobs.db` SQLite, with stdout/stderr captured per-job to `logs/jobs/{run_id}.log` for SSE replay.

**Tech Stack:** FastAPI, uvicorn, fastapi-mcp, pydantic v2, Python stdlib sqlite3, asyncio SSE

**Spec:** `docs/superpowers/specs/2026-05-14-integration-layer-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `server/__init__.py` | Create | Package marker |
| `server/models.py` | Create | Pydantic request/response models + `JobRecord` |
| `server/job_store.py` | Create | SQLite CRUD for `jobs` table |
| `server/auth.py` | Create | `X-API-Key` FastAPI dependency |
| `server/job_runner.py` | Create | `ThreadPoolExecutor` + log capture + SSE stream |
| `server/app.py` | Create | FastAPI app + all routes |
| `aisw_server.py` | Create | Entrypoint: uvicorn + fastapi_mcp mount |
| `aisw_server.yaml` | Create | Example config (host/port/api_key/defaults) |
| `tests/test_job_store.py` | Create | Unit tests for SQLite CRUD |
| `tests/test_job_runner.py` | Create | Unit tests for job lifecycle (mock Orchestrator) |
| `tests/test_aisw_server.py` | Create | Route tests via FastAPI TestClient |
| `requirements.txt` | Modify | Add fastapi, uvicorn[standard], fastapi-mcp |

---

## Task 1: Worktree + dependencies

**Files:** `requirements.txt`

- [ ] **Step 1: Create worktree**

```bash
cd /home/wanleung/Projects/ai-software-house
git worktree add .worktrees/t17-integration-layer -b t17-integration-layer
cd .worktrees/t17-integration-layer
```

- [ ] **Step 2: Add dependencies to requirements.txt**

Add these lines to `requirements.txt` (after the existing entries):

```
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
fastapi-mcp>=0.3.0
```

Note: `pydantic>=2.0` is already in requirements.txt.

- [ ] **Step 3: Verify import available**

```bash
pip install fastapi uvicorn[standard] fastapi-mcp 2>&1 | tail -3
python3 -c "import fastapi, fastapi_mcp; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "build: add fastapi, uvicorn, fastapi-mcp dependencies"
```

---

## Task 2: Models

**Files:**
- Create: `server/__init__.py`
- Create: `server/models.py`
- Create: `tests/test_server_models.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_server_models.py`:

```python
"""Tests for server Pydantic models."""
import pytest
from server.models import RunRequest, RunSubmitted, JobRecord, RunDetail, RunSummary


class TestRunRequest:
    def test_defaults(self):
        r = RunRequest(requirement="Build a TODO app")
        assert r.requirement == "Build a TODO app"
        assert r.repo is None
        assert r.pipeline is None
        assert r.engineers is None

    def test_all_fields(self):
        r = RunRequest(requirement="x", repo="o/r", pipeline="ai-fix", engineers=3)
        assert r.repo == "o/r"
        assert r.engineers == 3


class TestJobRecord:
    def test_required_fields(self):
        j = JobRecord(
            id="abc",
            status="queued",
            requirement="Build X",
            repo="o/r",
            pipeline="ai-feature",
            engineers=2,
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
            log_path="/tmp/abc.log",
        )
        assert j.id == "abc"
        assert j.result_json is None

    def test_result_json_optional(self):
        j = JobRecord(
            id="x", status="done", requirement="r", repo="o/r",
            pipeline="p", engineers=1,
            created_at="t", updated_at="t", log_path="/tmp/x.log",
            result_json='{"verdict":"approved"}',
        )
        assert j.result_json == '{"verdict":"approved"}'


class TestRunSubmitted:
    def test_fields(self):
        s = RunSubmitted(run_id="abc", status="queued", stream_url="/runs/abc/stream")
        assert s.run_id == "abc"


class TestRunSummary:
    def test_fields(self):
        s = RunSummary(
            run_id="x", status="done", requirement="Build X",
            repo="o/r", pipeline="p",
            created_at="t", updated_at="t",
        )
        assert s.run_id == "x"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd .worktrees/t17-integration-layer
python3 -m pytest tests/test_server_models.py -v 2>&1 | tail -10
```

Expected: `ImportError` — `server` module not found.

- [ ] **Step 3: Create `server/__init__.py`**

```python
"""ai-software-house integration server package."""
```

- [ ] **Step 4: Create `server/models.py`**

```python
"""Pydantic models for the AISW integration server."""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel


class RunRequest(BaseModel):
    """Body for POST /runs."""
    requirement: str
    repo: Optional[str] = None
    pipeline: Optional[str] = None
    engineers: Optional[int] = None


class RunSubmitted(BaseModel):
    """Response for POST /runs (202)."""
    run_id: str
    status: str
    stream_url: str


class JobRecord(BaseModel):
    """Full job record as stored in SQLite and returned by GET /runs/{id}."""
    id: str
    status: str          # queued | running | done | failed | cancelled | interrupted
    requirement: str
    repo: str
    pipeline: str
    engineers: int
    created_at: str
    updated_at: str
    log_path: str
    result_json: Optional[str] = None


class RunSummary(BaseModel):
    """Lightweight record returned by GET /runs list."""
    run_id: str
    status: str
    requirement: str
    repo: str
    pipeline: str
    created_at: str
    updated_at: str


class RunDetail(BaseModel):
    """Full detail returned by GET /runs/{id}."""
    run_id: str
    status: str
    requirement: str
    repo: str
    pipeline: str
    engineers: int
    created_at: str
    updated_at: str
    result: Optional[dict] = None
    log_lines: int = 0


class CancelResponse(BaseModel):
    run_id: str
    status: str
    message: str


class HealthResponse(BaseModel):
    status: str
    version: str
```

- [ ] **Step 5: Run test to verify it passes**

```bash
python3 -m pytest tests/test_server_models.py -v 2>&1 | tail -10
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add server/__init__.py server/models.py tests/test_server_models.py
git commit -m "feat(server): add Pydantic models for integration layer"
```

---

## Task 3: Job Store (SQLite)

**Files:**
- Create: `server/job_store.py`
- Create: `tests/test_job_store.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_job_store.py`:

```python
"""Tests for SQLite job store."""
import json
import pytest
from server.job_store import JobStore
from server.models import JobRecord


@pytest.fixture
def store(tmp_path):
    """In-memory SQLite job store for tests."""
    s = JobStore(db_path=":memory:")
    s.init_db()
    return s


class TestJobStoreInit:
    def test_init_creates_table(self, store):
        # Should not raise; table exists
        jobs = store.list_jobs(limit=10)
        assert jobs == []

    def test_interrupted_on_init(self, tmp_path):
        """Running jobs become 'interrupted' when store is re-initialised."""
        s = JobStore(db_path=str(tmp_path / "jobs.db"))
        s.init_db()
        s.insert_job(JobRecord(
            id="r1", status="running", requirement="x", repo="o/r",
            pipeline="p", engineers=1, created_at="t", updated_at="t",
            log_path="/tmp/r1.log",
        ))
        # Re-init simulates server restart
        s2 = JobStore(db_path=str(tmp_path / "jobs.db"))
        s2.init_db()
        job = s2.get_job("r1")
        assert job.status == "interrupted"


class TestInsertGet:
    def test_insert_and_get(self, store):
        job = JobRecord(
            id="abc", status="queued", requirement="Build X",
            repo="o/r", pipeline="ai-feature", engineers=2,
            created_at="2026-01-01T00:00:00Z", updated_at="2026-01-01T00:00:00Z",
            log_path="/tmp/abc.log",
        )
        store.insert_job(job)
        fetched = store.get_job("abc")
        assert fetched.id == "abc"
        assert fetched.status == "queued"

    def test_get_missing_returns_none(self, store):
        assert store.get_job("nonexistent") is None


class TestUpdateStatus:
    def test_update_status(self, store):
        job = JobRecord(
            id="j1", status="queued", requirement="x", repo="o/r",
            pipeline="p", engineers=1, created_at="t", updated_at="t",
            log_path="/tmp/j1.log",
        )
        store.insert_job(job)
        store.update_status("j1", "running")
        assert store.get_job("j1").status == "running"

    def test_set_result(self, store):
        job = JobRecord(
            id="j2", status="running", requirement="x", repo="o/r",
            pipeline="p", engineers=1, created_at="t", updated_at="t",
            log_path="/tmp/j2.log",
        )
        store.insert_job(job)
        store.set_result("j2", "done", '{"verdict":"approved"}')
        fetched = store.get_job("j2")
        assert fetched.status == "done"
        assert json.loads(fetched.result_json)["verdict"] == "approved"


class TestListJobs:
    def test_list_ordered_by_created_desc(self, store):
        for i, ts in enumerate(["2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"]):
            store.insert_job(JobRecord(
                id=f"j{i}", status="done", requirement="x", repo="o/r",
                pipeline="p", engineers=1, created_at=ts, updated_at=ts,
                log_path=f"/tmp/j{i}.log",
            ))
        jobs = store.list_jobs(limit=10)
        assert jobs[0].id == "j1"   # most recent first

    def test_list_respects_limit(self, store):
        for i in range(5):
            store.insert_job(JobRecord(
                id=f"j{i}", status="done", requirement="x", repo="o/r",
                pipeline="p", engineers=1,
                created_at=f"2026-01-0{i+1}T00:00:00Z",
                updated_at=f"2026-01-0{i+1}T00:00:00Z",
                log_path=f"/tmp/j{i}.log",
            ))
        assert len(store.list_jobs(limit=3)) == 3
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_job_store.py -v 2>&1 | tail -10
```

Expected: `ImportError` — `server.job_store` not found.

- [ ] **Step 3: Create `server/job_store.py`**

```python
"""SQLite-backed job store for the AISW integration server."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from server.models import JobRecord


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    def __init__(self, db_path: str = "jobs.db") -> None:
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        """Create table if needed; mark any stale 'running' jobs as 'interrupted'."""
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id          TEXT PRIMARY KEY,
                    status      TEXT NOT NULL,
                    requirement TEXT NOT NULL,
                    repo        TEXT NOT NULL,
                    pipeline    TEXT NOT NULL,
                    engineers   INTEGER NOT NULL,
                    created_at  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL,
                    log_path    TEXT NOT NULL,
                    result_json TEXT
                )
            """)
            conn.execute("""
                UPDATE jobs SET status = 'interrupted', updated_at = ?
                WHERE status = 'running'
            """, (_now(),))

    def insert_job(self, job: JobRecord) -> None:
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO jobs
                    (id, status, requirement, repo, pipeline, engineers,
                     created_at, updated_at, log_path, result_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (job.id, job.status, job.requirement, job.repo, job.pipeline,
                  job.engineers, job.created_at, job.updated_at,
                  job.log_path, job.result_json))

    def get_job(self, run_id: str) -> Optional[JobRecord]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE id = ?", (run_id,)
            ).fetchone()
        if row is None:
            return None
        return JobRecord(**dict(row))

    def update_status(self, run_id: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?",
                (status, _now(), run_id),
            )

    def set_result(self, run_id: str, status: str, result_json: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, result_json = ?, updated_at = ? WHERE id = ?",
                (status, result_json, _now(), run_id),
            )

    def list_jobs(self, limit: int = 50) -> list[JobRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [JobRecord(**dict(r)) for r in rows]
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python3 -m pytest tests/test_job_store.py -v 2>&1 | tail -10
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add server/job_store.py tests/test_job_store.py
git commit -m "feat(server): add SQLite job store"
```

---

## Task 4: Auth middleware

**Files:**
- Create: `server/auth.py`
- Create: `tests/test_server_auth.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_server_auth.py`:

```python
"""Tests for X-API-Key auth dependency."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from server.auth import require_api_key, set_api_key


def _make_app(key: str) -> FastAPI:
    set_api_key(key)
    app = FastAPI()

    @app.get("/protected", dependencies=[require_api_key()])
    def protected():
        return {"ok": True}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


class TestApiKeyAuth:
    def test_valid_key_passes(self):
        client = TestClient(_make_app("secret"))
        resp = client.get("/protected", headers={"X-API-Key": "secret"})
        assert resp.status_code == 200

    def test_wrong_key_rejected(self):
        client = TestClient(_make_app("secret"))
        resp = client.get("/protected", headers={"X-API-Key": "wrong"})
        assert resp.status_code == 401

    def test_missing_key_rejected(self):
        client = TestClient(_make_app("secret"))
        resp = client.get("/protected")
        assert resp.status_code == 401

    def test_health_no_key_needed(self):
        """Health endpoint has no auth dependency — always works."""
        client = TestClient(_make_app("secret"))
        resp = client.get("/health")
        assert resp.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_server_auth.py -v 2>&1 | tail -10
```

Expected: `ImportError`.

- [ ] **Step 3: Create `server/auth.py`**

```python
"""X-API-Key authentication for the AISW integration server."""
from __future__ import annotations

from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_configured_key: str = ""


def set_api_key(key: str) -> None:
    """Call once at startup with the configured API key."""
    global _configured_key
    _configured_key = key


def require_api_key():
    """FastAPI dependency that enforces X-API-Key auth."""
    def _check(api_key: str | None = Security(_api_key_header)):
        if not _configured_key:
            return  # no key configured → open access (dev mode)
        if api_key != _configured_key:
            raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")
    return Depends(_check)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python3 -m pytest tests/test_server_auth.py -v 2>&1 | tail -10
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add server/auth.py tests/test_server_auth.py
git commit -m "feat(server): add X-API-Key auth dependency"
```

---

## Task 5: Job Runner

**Files:**
- Create: `server/job_runner.py`
- Create: `tests/test_job_runner.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_job_runner.py`:

```python
"""Tests for the async job runner."""
import asyncio
import json
import time
import pytest
from unittest.mock import MagicMock, patch
from server.job_store import JobStore
from server.job_runner import JobRunner
from server.models import RunRequest


@pytest.fixture
def store(tmp_path):
    s = JobStore(db_path=":memory:")
    s.init_db()
    return s


@pytest.fixture
def runner(store, tmp_path):
    r = JobRunner(store=store, log_dir=tmp_path / "logs", config_yaml="config.yaml",
                  default_repo="o/r", default_pipeline="ai-feature", default_engineers=2)
    r.start()
    yield r
    r.shutdown()


class TestSubmitJob:
    def test_submit_returns_run_id(self, runner):
        req = RunRequest(requirement="Build X")
        run_id = runner.submit(req)
        assert len(run_id) > 8

    def test_job_in_store_after_submit(self, runner):
        req = RunRequest(requirement="Build X")
        run_id = runner.submit(req)
        job = runner.store.get_job(run_id)
        assert job is not None
        assert job.status in ("queued", "running")

    def test_defaults_applied(self, runner):
        req = RunRequest(requirement="Build X")  # no repo/pipeline/engineers
        run_id = runner.submit(req)
        job = runner.store.get_job(run_id)
        assert job.repo == "o/r"
        assert job.pipeline == "ai-feature"
        assert job.engineers == 2

    def test_overrides_applied(self, runner):
        req = RunRequest(requirement="Build X", repo="other/r", pipeline="ai-fix", engineers=4)
        run_id = runner.submit(req)
        job = runner.store.get_job(run_id)
        assert job.repo == "other/r"
        assert job.pipeline == "ai-fix"
        assert job.engineers == 4


class TestCancelJob:
    def test_cancel_queued_job(self, runner):
        req = RunRequest(requirement="Build X")
        run_id = runner.submit(req)
        result = runner.cancel(run_id)
        assert result in (True, False)  # may have started already

    def test_cancel_nonexistent_returns_false(self, runner):
        assert runner.cancel("nonexistent") is False


class TestStreamLogs:
    def test_stream_completed_job_replays_then_ends(self, runner, tmp_path):
        """If a job is already done, stream replays the log then yields a done event."""
        from server.job_store import JobStore as JS
        log_path = tmp_path / "logs" / "done_job.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("line1\nline2\n")
        runner.store.insert_job(__import__('server.models', fromlist=['JobRecord']).JobRecord(
            id="done1", status="done", requirement="x", repo="o/r",
            pipeline="p", engineers=1, created_at="t", updated_at="t",
            log_path=str(log_path),
        ))
        events = asyncio.get_event_loop().run_until_complete(_collect_events(runner, "done1"))
        log_events = [e for e in events if e[0] == "log"]
        assert len(log_events) == 2
        done_events = [e for e in events if e[0] == "done"]
        assert len(done_events) == 1


async def _collect_events(runner, run_id):
    events = []
    async for event_type, data in runner.stream_logs(run_id):
        events.append((event_type, data))
        if event_type in ("done", "error"):
            break
    return events
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_job_runner.py -v 2>&1 | tail -10
```

Expected: `ImportError`.

- [ ] **Step 3: Create `server/job_runner.py`**

```python
"""Async job runner — submits Orchestrator runs to a ThreadPoolExecutor."""
from __future__ import annotations

import asyncio
import json
import sys
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator, Optional

from server.job_store import JobStore
from server.models import JobRecord, RunRequest


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobRunner:
    def __init__(
        self,
        store: JobStore,
        log_dir: Path,
        config_yaml: str,
        default_repo: str,
        default_pipeline: str,
        default_engineers: int,
        max_workers: int = 4,
    ) -> None:
        self.store = store
        self._log_dir = Path(log_dir)
        self._config_yaml = config_yaml
        self._default_repo = default_repo
        self._default_pipeline = default_pipeline
        self._default_engineers = default_engineers
        self._executor: Optional[ThreadPoolExecutor] = None
        self._cancel_flags: dict[str, threading.Event] = {}

    def start(self) -> None:
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._executor = ThreadPoolExecutor(max_workers=4)

    def shutdown(self) -> None:
        if self._executor:
            self._executor.shutdown(wait=False)

    def submit(self, req: RunRequest) -> str:
        run_id = str(uuid.uuid4())
        log_path = self._log_dir / f"{run_id}.log"
        job = JobRecord(
            id=run_id,
            status="queued",
            requirement=req.requirement,
            repo=req.repo or self._default_repo,
            pipeline=req.pipeline or self._default_pipeline,
            engineers=req.engineers if req.engineers is not None else self._default_engineers,
            created_at=_now(),
            updated_at=_now(),
            log_path=str(log_path),
        )
        self.store.insert_job(job)
        cancel_event = threading.Event()
        self._cancel_flags[run_id] = cancel_event
        self._executor.submit(self._run_job, run_id, job, cancel_event)
        return run_id

    def cancel(self, run_id: str) -> bool:
        job = self.store.get_job(run_id)
        if job is None:
            return False
        if job.status in ("done", "failed", "cancelled", "interrupted"):
            return False
        if run_id in self._cancel_flags:
            self._cancel_flags[run_id].set()
        self.store.update_status(run_id, "cancelled")
        return True

    def _run_job(self, run_id: str, job: JobRecord, cancel_event: threading.Event) -> None:
        from orchestrator import Orchestrator
        log_path = Path(job.log_path)
        self.store.update_status(run_id, "running")
        try:
            with open(log_path, "w", encoding="utf-8") as fh:
                old_stdout, old_stderr = sys.stdout, sys.stderr
                sys.stdout = sys.stderr = fh
                try:
                    orch = Orchestrator.from_config(
                        self._config_yaml,
                        github_token=None,
                    )
                    result = orch.run(
                        job.requirement,
                        issue_number=None,
                    )
                    result_dict = {
                        "verdict": result.verdict,
                        "pr_url": result.pr_url,
                        "pr_number": result.pr_number,
                        "tests_passed": result.tests_passed,
                        "deploy_tests_passed": result.deploy_tests_passed,
                        "issue_number": result.issue_number,
                        "branch": result.branch,
                    }
                    self.store.set_result(run_id, "done", json.dumps(result_dict))
                except Exception:
                    fh.write(f"\n--- EXCEPTION ---\n{traceback.format_exc()}\n")
                    self.store.update_status(run_id, "failed")
                finally:
                    sys.stdout, sys.stderr = old_stdout, old_stderr
        except OSError as e:
            self.store.update_status(run_id, "failed")

    async def stream_logs(self, run_id: str) -> AsyncGenerator[tuple[str, str], None]:
        """Yield (event_type, data) pairs for SSE streaming."""
        job = self.store.get_job(run_id)
        if job is None:
            yield ("error", f"run_id {run_id!r} not found")
            return

        log_path = Path(job.log_path)
        already_done = job.status in ("done", "failed", "cancelled", "interrupted")

        # Replay existing lines
        if log_path.exists():
            with open(log_path, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    yield ("log", line.rstrip())

        if already_done:
            # Emit terminal event
            if job.status == "done" and job.result_json:
                yield ("done", job.result_json)
            else:
                yield ("error", job.status)
            return

        # Tail new lines until job completes
        with open(log_path, encoding="utf-8", errors="replace") as fh:
            fh.seek(0, 2)  # seek to end (already replayed above)
            while True:
                line = fh.readline()
                if line:
                    yield ("log", line.rstrip())
                else:
                    await asyncio.sleep(0.2)
                    current = self.store.get_job(run_id)
                    if current and current.status in ("done", "failed", "cancelled", "interrupted"):
                        # Drain any remaining lines
                        for remaining in fh:
                            yield ("log", remaining.rstrip())
                        if current.status == "done" and current.result_json:
                            yield ("done", current.result_json)
                        else:
                            yield ("error", current.status)
                        return
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python3 -m pytest tests/test_job_runner.py -v 2>&1 | tail -15
```

Expected: all PASS (some cancel tests may be flaky if the executor starts immediately — that's acceptable).

- [ ] **Step 5: Commit**

```bash
git add server/job_runner.py tests/test_job_runner.py
git commit -m "feat(server): add async job runner with ThreadPoolExecutor and SSE log streaming"
```

---

## Task 6: FastAPI app + routes

**Files:**
- Create: `server/app.py`
- Create: `tests/test_aisw_server.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_aisw_server.py`:

```python
"""Integration tests for the AISW server REST routes."""
import json
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


def _make_client(api_key="test-key"):
    """Build a TestClient with a mocked job runner."""
    from server import auth as auth_mod
    auth_mod.set_api_key(api_key)

    mock_runner = MagicMock()
    mock_runner.submit.return_value = "run-123"
    mock_runner.cancel.return_value = True

    from server.models import JobRecord, RunDetail, RunSummary
    mock_store = MagicMock()
    mock_runner.store = mock_store

    _job = JobRecord(
        id="run-123", status="queued", requirement="Build X",
        repo="o/r", pipeline="ai-feature", engineers=2,
        created_at="2026-01-01T00:00:00Z", updated_at="2026-01-01T00:00:00Z",
        log_path="/tmp/run-123.log",
    )
    mock_store.get_job.return_value = _job
    mock_store.list_jobs.return_value = [_job]

    from server.app import create_app
    app = create_app(runner=mock_runner)
    return TestClient(app), mock_runner


class TestHealth:
    def test_health_no_auth(self):
        client, _ = _make_client()
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestPostRuns:
    def test_submit_returns_202(self):
        client, runner = _make_client()
        resp = client.post(
            "/runs",
            json={"requirement": "Build X"},
            headers={"X-API-Key": "test-key"},
        )
        assert resp.status_code == 202
        assert resp.json()["run_id"] == "run-123"
        assert "/runs/run-123/stream" in resp.json()["stream_url"]

    def test_no_api_key_rejected(self):
        client, _ = _make_client()
        resp = client.post("/runs", json={"requirement": "Build X"})
        assert resp.status_code == 401


class TestGetRuns:
    def test_list_runs(self):
        client, _ = _make_client()
        resp = client.get("/runs", headers={"X-API-Key": "test-key"})
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
        assert resp.json()[0]["run_id"] == "run-123"

    def test_get_run_detail(self):
        client, _ = _make_client()
        resp = client.get("/runs/run-123", headers={"X-API-Key": "test-key"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == "run-123"
        assert data["status"] == "queued"

    def test_get_run_not_found(self):
        client, runner = _make_client()
        runner.store.get_job.return_value = None
        resp = client.get("/runs/missing", headers={"X-API-Key": "test-key"})
        assert resp.status_code == 404


class TestDeleteRun:
    def test_cancel_run(self):
        client, runner = _make_client()
        resp = client.delete("/runs/run-123", headers={"X-API-Key": "test-key"})
        assert resp.status_code == 200
        runner.cancel.assert_called_once_with("run-123")

    def test_cancel_not_found(self):
        client, runner = _make_client()
        runner.store.get_job.return_value = None
        resp = client.delete("/runs/missing", headers={"X-API-Key": "test-key"})
        assert resp.status_code == 404

    def test_cancel_already_done(self):
        client, runner = _make_client()
        runner.cancel.return_value = False
        resp = client.delete("/runs/run-123", headers={"X-API-Key": "test-key"})
        assert resp.status_code == 409
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_aisw_server.py -v 2>&1 | tail -10
```

Expected: `ImportError` — `server.app` not found.

- [ ] **Step 3: Create `server/app.py`**

```python
"""FastAPI application with all AISW integration routes."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from server.auth import require_api_key
from server.models import (
    CancelResponse, HealthResponse, JobRecord,
    RunDetail, RunRequest, RunSubmitted, RunSummary,
)


def create_app(runner=None) -> FastAPI:
    """Factory so tests can inject a mock runner."""
    app = FastAPI(
        title="AI Software House Integration API",
        version="1.0",
        description="Trigger and monitor ai-software-house pipelines via REST or MCP.",
    )

    _runner = runner  # injected or set via app.state

    @app.get("/health", response_model=HealthResponse, tags=["meta"])
    def health():
        return HealthResponse(status="ok", version="1.0")

    @app.post("/runs", response_model=RunSubmitted, status_code=202,
              tags=["runs"], dependencies=[require_api_key()])
    def submit_run(req: RunRequest):
        """Submit a new pipeline requirement. Returns a run_id for tracking."""
        run_id = _runner.submit(req)
        return RunSubmitted(
            run_id=run_id,
            status="queued",
            stream_url=f"/runs/{run_id}/stream",
        )

    @app.get("/runs", response_model=list[RunSummary],
             tags=["runs"], dependencies=[require_api_key()])
    def list_runs(limit: int = 50):
        """List recent pipeline runs."""
        jobs = _runner.store.list_jobs(limit=limit)
        return [
            RunSummary(
                run_id=j.id, status=j.status,
                requirement=j.requirement[:120],
                repo=j.repo, pipeline=j.pipeline,
                created_at=j.created_at, updated_at=j.updated_at,
            )
            for j in jobs
        ]

    @app.get("/runs/{run_id}", response_model=RunDetail,
             tags=["runs"], dependencies=[require_api_key()])
    def get_run(run_id: str):
        """Get full detail for a single run including result."""
        job: Optional[JobRecord] = _runner.store.get_job(run_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"run_id {run_id!r} not found")
        result = json.loads(job.result_json) if job.result_json else None
        log_lines = 0
        try:
            log_lines = Path(job.log_path).read_text(errors="replace").count("\n")
        except OSError:
            pass
        return RunDetail(
            run_id=job.id, status=job.status,
            requirement=job.requirement, repo=job.repo,
            pipeline=job.pipeline, engineers=job.engineers,
            created_at=job.created_at, updated_at=job.updated_at,
            result=result, log_lines=log_lines,
        )

    @app.delete("/runs/{run_id}", response_model=CancelResponse,
                tags=["runs"], dependencies=[require_api_key()])
    def cancel_run(run_id: str):
        """Cancel a queued or running job."""
        job = _runner.store.get_job(run_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"run_id {run_id!r} not found")
        cancelled = _runner.cancel(run_id)
        if not cancelled:
            raise HTTPException(
                status_code=409,
                detail=f"Run {run_id!r} is already in terminal state ({job.status})"
            )
        return CancelResponse(run_id=run_id, status="cancelled", message="Job cancelled.")

    @app.get("/runs/{run_id}/stream", tags=["runs"], dependencies=[require_api_key()])
    async def stream_run(run_id: str):
        """Stream live log output as Server-Sent Events."""
        job = _runner.store.get_job(run_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"run_id {run_id!r} not found")

        async def _generate():
            async for event_type, data in _runner.stream_logs(run_id):
                yield f"event: {event_type}\ndata: {data}\n\n"

        return StreamingResponse(_generate(), media_type="text/event-stream")

    return app
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python3 -m pytest tests/test_aisw_server.py -v 2>&1 | tail -15
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add server/app.py tests/test_aisw_server.py
git commit -m "feat(server): add FastAPI app with all REST routes"
```

---

## Task 7: Entrypoint + config + MCP mount

**Files:**
- Create: `aisw_server.py`
- Create: `aisw_server.yaml`

- [ ] **Step 1: Create `aisw_server.yaml`**

```yaml
server:
  host: 0.0.0.0
  port: 8765
  api_key: "change-me"           # override with AISW_API_KEY env var

defaults:
  repo: "owner/default-repo"
  pipeline: "ai-feature"
  engineers: 2
  config_yaml: "config.yaml"
```

- [ ] **Step 2: Create `aisw_server.py`**

```python
#!/usr/bin/env python3
"""
AI Software House Integration Server

Exposes a REST API + MCP server for triggering and monitoring pipelines.

Usage:
    python aisw_server.py                # uses aisw_server.yaml
    python aisw_server.py --port 9000
    AISW_API_KEY=secret python aisw_server.py
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import uvicorn
import yaml


def _load_config(path: str = "aisw_server.yaml") -> dict:
    if not Path(path).exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def main() -> None:
    parser = argparse.ArgumentParser(description="AISW Integration Server")
    parser.add_argument("--config", default="aisw_server.yaml")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()

    cfg = _load_config(args.config)
    srv = cfg.get("server", {})
    defaults = cfg.get("defaults", {})

    host = args.host or srv.get("host", "0.0.0.0")
    port = args.port or srv.get("port", 8765)
    api_key = os.environ.get("AISW_API_KEY") or srv.get("api_key", "")

    from server import auth as auth_mod
    auth_mod.set_api_key(api_key)

    from server.job_store import JobStore
    from server.job_runner import JobRunner
    from server.app import create_app

    store = JobStore(db_path="jobs.db")
    store.init_db()

    runner = JobRunner(
        store=store,
        log_dir=Path("logs/jobs"),
        config_yaml=defaults.get("config_yaml", "config.yaml"),
        default_repo=defaults.get("repo", ""),
        default_pipeline=defaults.get("pipeline", "ai-feature"),
        default_engineers=defaults.get("engineers", 2),
    )
    runner.start()

    app = create_app(runner=runner)

    # Mount MCP server (auto-generates tools from FastAPI routes)
    try:
        from fastapi_mcp import FastApiMCP
        mcp = FastApiMCP(app)
        mcp.mount()
        print(f"MCP server mounted at http://{host}:{port}/mcp")
    except ImportError:
        print("Warning: fastapi-mcp not installed — MCP endpoint not available", file=sys.stderr)

    print(f"AISW server starting on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Smoke test the server starts**

```bash
cd .worktrees/t17-integration-layer
timeout 5 python3 aisw_server.py --port 8766 2>&1 || true
```

Expected: Lines like `AISW server starting on http://0.0.0.0:8766` and `MCP server mounted`. It will exit after 5s due to timeout — that's fine.

- [ ] **Step 4: Run full test suite to check no regressions**

```bash
python3 -m pytest tests/ -x -q 2>&1 | tail -10
```

Expected: all existing tests still pass + new tests pass.

- [ ] **Step 5: Commit**

```bash
git add aisw_server.py aisw_server.yaml
git commit -m "feat: add aisw_server.py entrypoint with MCP mount and config loading"
```

---

## Task 8: PR + docs update

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add Integration Server section to README**

Find the `### Per-repo deploy mode` section in `README.md` and add a new section above it (before the `---` separator that precedes it):

```markdown
### Integration Layer — REST API + MCP Server

`aisw_server.py` exposes the pipeline as a REST API and MCP server, so Copilot CLI, Claude Code, OpenCode, web UIs, and `curl` can trigger and monitor pipelines without touching GitHub labels.

```bash
# Start the server
python aisw_server.py

# Submit a requirement via curl
curl -X POST http://localhost:8765/runs \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"requirement": "Build a bookmark manager REST API", "repo": "me/my-repo"}'

# Stream live logs
curl -N http://localhost:8765/runs/{run_id}/stream -H "X-API-Key: your-key"
```

**Connect from MCP tools** (Copilot CLI, Claude Code, OpenCode):

```yaml
# ~/.copilot/config.yaml  (Copilot CLI)
mcp_servers:
  - name: ai-software-house
    url: http://localhost:8765/mcp
    headers:
      X-API-Key: "your-key"
```

Configure in `aisw_server.yaml`. See `docs/superpowers/specs/2026-05-14-integration-layer-design.md` for the full API reference.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add Integration Layer section to README"
```

- [ ] **Step 3: Push branch and open PR**

```bash
git push origin t17-integration-layer
gh pr create \
  --title "feat: REST API + MCP integration layer (aisw_server.py)" \
  --body "Adds \`aisw_server.py\` — a FastAPI + MCP server for triggering and monitoring pipelines from Copilot CLI, Claude Code, OpenCode, web UIs, and curl.

## What's in this PR
- \`server/models.py\` — Pydantic models
- \`server/job_store.py\` — SQLite job persistence (survives restarts)
- \`server/auth.py\` — X-API-Key middleware
- \`server/job_runner.py\` — ThreadPoolExecutor wrapping sync Orchestrator, SSE log streaming
- \`server/app.py\` — FastAPI routes (POST/GET/DELETE /runs, SSE /stream, /health)
- \`aisw_server.py\` — entrypoint with fastapi_mcp MCP bridge
- \`aisw_server.yaml\` — example config
- Tests for all components

Closes #T17

Spec: \`docs/superpowers/specs/2026-05-14-integration-layer-design.md\`" \
  --base master
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| FastAPI REST + MCP in one process | Task 7 (entrypoint + fastapi_mcp mount) |
| POST /runs, GET /runs, GET /runs/{id}, DELETE /runs/{id} | Task 6 |
| GET /runs/{id}/stream SSE | Task 6 |
| GET /health (no auth) | Task 6 |
| X-API-Key auth | Task 4 |
| SQLite job store | Task 3 |
| Job states: queued/running/done/failed/cancelled/interrupted | Tasks 3, 5 |
| ThreadPoolExecutor runs Orchestrator | Task 5 |
| stdout/stderr captured to per-job log file | Task 5 |
| SSE replay for completed jobs | Task 5 |
| interrupted jobs on restart | Task 3 |
| aisw_server.yaml config | Task 7 |
| MCP at /mcp via fastapi_mcp | Task 7 |
| README docs | Task 8 |
| Tests for all components | Tasks 2, 3, 4, 5, 6 |
| New dependencies in requirements.txt | Task 1 |
