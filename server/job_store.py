"""SQLite-backed job store for the AISW integration server."""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Optional

from server.models import JobRecord, JobStatus


def _now() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    """Persistent store for pipeline job records backed by SQLite.

    Args:
        db_path: Path to the SQLite database file. Use ``":memory:"`` for
                 an in-memory database (useful in tests).

    Note:
        When ``db_path`` is ``":memory:"``, a single persistent connection is
        reused for the lifetime of the instance so that the in-memory database
        is not lost between method calls.
    """

    def __init__(self, db_path: str = "jobs.db") -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        # For in-memory databases, keep a single connection alive so the DB
        # is not discarded between calls (each sqlite3.connect(":memory:") call
        # would otherwise return a fresh, empty database).
        self._persistent_conn: Optional[sqlite3.Connection] = None
        if db_path == ":memory:":
            self._persistent_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._persistent_conn.row_factory = sqlite3.Row

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Yield a database connection with ``row_factory`` set to ``sqlite3.Row``.

        For ``:memory:`` databases the shared persistent connection is yielded
        under a mutex so concurrent callers cannot interleave operations.
        For file-based databases a fresh connection is opened, yielded, then
        closed, relying on SQLite's own file-level locking for concurrency.
        """
        if self._persistent_conn is not None:
            with self._lock:
                yield self._persistent_conn
        else:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
            finally:
                conn.close()

    def init_db(self) -> None:
        """Create the jobs table if it does not exist.

        Also marks any jobs whose status is ``"running"`` as
        ``"interrupted"`` — this handles the case where the server was
        restarted while a job was in-flight.
        """
        with self._connect() as conn:
            with conn:
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
                    CREATE INDEX IF NOT EXISTS idx_jobs_created_at
                    ON jobs(created_at DESC)
                """)
                conn.execute("""
                    UPDATE jobs SET status = 'interrupted', updated_at = ?
                    WHERE status = 'running'
                """, (_now(),))

    def insert_job(self, job: JobRecord) -> None:
        """Insert a new job record into the store.

        Args:
            job: The :class:`~server.models.JobRecord` to persist.
        """
        with self._connect() as conn:
            with conn:
                conn.execute("""
                    INSERT INTO jobs
                        (id, status, requirement, repo, pipeline, engineers,
                         created_at, updated_at, log_path, result_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (job.id, job.status, job.requirement, job.repo, job.pipeline,
                      job.engineers, job.created_at, job.updated_at,
                      job.log_path, job.result_json))

    def get_job(self, run_id: str) -> Optional[JobRecord]:
        """Fetch a single job by its ID.

        Args:
            run_id: The job's unique identifier (``JobRecord.id``).

        Returns:
            A :class:`~server.models.JobRecord` instance, or ``None`` if
            no job with that ID exists.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE id = ?", (run_id,)
            ).fetchone()
        if row is None:
            return None
        return JobRecord(**dict(row))

    def update_status(self, run_id: str, status: JobStatus) -> None:
        """Update the status of an existing job.

        Args:
            run_id: The job's unique identifier.
            status: New status value (must be a valid :data:`~server.models.JobStatus`).

        Raises:
            KeyError: If no job with ``run_id`` exists.
        """
        with self._connect() as conn:
            with conn:
                cur = conn.execute(
                    "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?",
                    (status, _now(), run_id),
                )
                if cur.rowcount == 0:
                    raise KeyError(f"No job with id={run_id!r}")

    def set_result(self, run_id: str, status: JobStatus, result_json: str) -> None:
        """Persist a final result alongside a terminal status for a job.

        Args:
            run_id: The job's unique identifier.
            status: Terminal status (e.g. ``"done"`` or ``"failed"``).
            result_json: JSON-encoded result payload string.

        Raises:
            KeyError: If no job with ``run_id`` exists.
        """
        with self._connect() as conn:
            with conn:
                cur = conn.execute(
                    "UPDATE jobs SET status = ?, result_json = ?, updated_at = ? WHERE id = ?",
                    (status, result_json, _now(), run_id),
                )
                if cur.rowcount == 0:
                    raise KeyError(f"No job with id={run_id!r}")

    def list_jobs(self, limit: int = 50) -> list[JobRecord]:
        """Return the most recently created jobs, newest first.

        Args:
            limit: Maximum number of records to return.

        Returns:
            A list of :class:`~server.models.JobRecord` instances ordered by
            ``created_at`` descending.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [JobRecord(**dict(r)) for r in rows]
