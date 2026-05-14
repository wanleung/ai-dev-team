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
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


class JobRunner:
    """Manages asynchronous execution of Orchestrator pipeline jobs.

    Jobs are submitted to a :class:`~concurrent.futures.ThreadPoolExecutor`
    and their output is captured to per-job log files. Clients can stream
    log lines via :meth:`stream_logs`.

    Args:
        store: The :class:`~server.job_store.JobStore` used to persist job state.
        log_dir: Directory where per-job ``.log`` files are written.
        config_yaml: Path to the Orchestrator YAML config file.
        default_repo: Default GitHub repo (``owner/name``) if not specified per request.
        default_pipeline: Default pipeline name if not specified per request.
        default_engineers: Default engineer count if not specified per request.
        max_workers: Maximum number of concurrent Orchestrator jobs.
    """

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
        self._max_workers = max_workers
        self._executor: Optional[ThreadPoolExecutor] = None
        self._cancel_flags: dict[str, threading.Event] = {}

    def start(self) -> None:
        """Initialise the log directory and thread-pool executor.

        Must be called before :meth:`submit`.
        """
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._executor = ThreadPoolExecutor(max_workers=self._max_workers)

    def shutdown(self) -> None:
        """Shut down the thread-pool executor without waiting for running jobs."""
        if self._executor:
            self._executor.shutdown(wait=False)

    def submit(self, req: RunRequest) -> str:
        """Submit a new pipeline job and return its run ID.

        The job is immediately inserted into the store with status ``"queued"``
        and dispatched to the executor.

        Args:
            req: A :class:`~server.models.RunRequest` describing the job.

        Returns:
            The unique ``run_id`` (UUID4 string) assigned to this job.
        """
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
        """Request cancellation of a queued or running job.

        Sets the associated cancel flag and marks the job as ``"cancelled"``
        in the store. If the job is already in a terminal state or does not
        exist, returns ``False``.

        Args:
            run_id: The job's unique identifier.

        Returns:
            ``True`` if the cancellation request was accepted, ``False``
            if the job was not found or is already in a terminal state.
        """
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
        """Execute an Orchestrator run in the current thread.

        Redirects stdout/stderr to the job's log file for the duration of
        execution. Updates the job store with final status and result on
        completion.

        Args:
            run_id: The job's unique identifier (used for store updates).
            job: The :class:`~server.models.JobRecord` describing the job.
            cancel_event: A :class:`threading.Event` that is set when
                          cancellation is requested.
        """
        # Lazy import to avoid import-time side effects in tests
        from orchestrator import Orchestrator  # noqa: PLC0415

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
        except OSError:
            self.store.update_status(run_id, "failed")

    async def stream_logs(self, run_id: str) -> AsyncGenerator[tuple[str, str], None]:
        """Yield ``(event_type, data)`` pairs for SSE streaming of a job's output.

        Behaviour:
        - If the job does not exist, yields a single ``("error", ...)`` event.
        - Replays all existing log lines as ``("log", line)`` events.
        - If the job is already in a terminal state after replay, emits a
          final ``("done", result_json)`` or ``("error", status)`` event and
          returns.
        - Otherwise, tails the log file with 200 ms polling until the job
          reaches a terminal state, then drains any remaining lines and emits
          the terminal event.

        Args:
            run_id: The job's unique identifier.

        Yields:
            Tuples of ``(event_type, data)`` where *event_type* is one of
            ``"log"``, ``"done"``, or ``"error"``.
        """
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
            if job.status == "done":
                yield ("done", job.result_json or "{}")
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
                        if current.status == "done":
                            yield ("done", current.result_json or "{}")
                        else:
                            yield ("error", current.status)
                        return
