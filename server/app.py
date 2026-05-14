"""FastAPI application with all AISW integration routes."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from server.auth import require_api_key
from server.models import (
    CancelResponse, HealthResponse, JobRecord,
    RunDetail, RunRequest, RunSubmitted, RunSummary,
)


def create_app(runner=None) -> FastAPI:
    """Factory so tests can inject a mock runner.

    Args:
        runner: A ``JobRunner`` instance (or mock) that provides
                ``submit``, ``cancel``, ``stream_logs`` and a ``.store``
                attribute exposing the ``JobStore`` interface.

    Returns:
        A configured :class:`fastapi.FastAPI` application instance.
    """
    app = FastAPI(
        title="AI Software House Integration API",
        version="1.0",
        description="Trigger and monitor ai-software-house pipelines via REST or MCP.",
    )

    _runner = runner

    @app.get("/health", response_model=HealthResponse, tags=["meta"])
    def health() -> HealthResponse:
        """Return service health status. No authentication required."""
        return HealthResponse(status="ok", version="1.0")

    @app.post(
        "/runs",
        response_model=RunSubmitted,
        status_code=202,
        tags=["runs"],
        dependencies=[require_api_key()],
    )
    def submit_run(req: RunRequest) -> RunSubmitted:
        """Submit a new pipeline requirement. Returns a run_id for tracking."""
        run_id = _runner.submit(req)
        return RunSubmitted(
            run_id=run_id,
            status="queued",
            stream_url=f"/runs/{run_id}/stream",
        )

    @app.get(
        "/runs",
        response_model=list[RunSummary],
        tags=["runs"],
        dependencies=[require_api_key()],
    )
    def list_runs(limit: int = 50) -> list[RunSummary]:
        """List recent pipeline runs (newest first)."""
        jobs = _runner.store.list_jobs(limit=limit)
        return [
            RunSummary(
                run_id=j.id,
                status=j.status,
                requirement=j.requirement[:120],
                repo=j.repo,
                pipeline=j.pipeline,
                created_at=j.created_at,
                updated_at=j.updated_at,
            )
            for j in jobs
        ]

    @app.get(
        "/runs/{run_id}",
        response_model=RunDetail,
        tags=["runs"],
        dependencies=[require_api_key()],
    )
    def get_run(run_id: str) -> RunDetail:
        """Get full detail for a single run including result and log line count."""
        job: Optional[JobRecord] = _runner.store.get_job(run_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"run_id {run_id!r} not found")
        result = None
        if job.result_json:
            try:
                result = json.loads(job.result_json)
            except json.JSONDecodeError:
                result = {"_parse_error": "result_json is corrupted"}
        log_lines = 0
        try:
            with open(job.log_path, "rb") as _lf:
                for _chunk in iter(lambda: _lf.read(65536), b""):
                    log_lines += _chunk.count(b"\n")
        except OSError:
            pass
        return RunDetail(
            run_id=job.id,
            status=job.status,
            requirement=job.requirement,
            repo=job.repo,
            pipeline=job.pipeline,
            engineers=job.engineers,
            created_at=job.created_at,
            updated_at=job.updated_at,
            result=result,
            log_lines=log_lines,
        )

    @app.delete(
        "/runs/{run_id}",
        response_model=CancelResponse,
        tags=["runs"],
        dependencies=[require_api_key()],
    )
    def cancel_run(run_id: str) -> CancelResponse:
        """Cancel a queued or running job.

        Returns 404 if the run does not exist, 409 if it is already in a
        terminal state.
        """
        job = _runner.store.get_job(run_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"run_id {run_id!r} not found")
        cancelled = _runner.cancel(run_id)
        if not cancelled:
            raise HTTPException(
                status_code=409,
                detail=f"Run {run_id!r} is already in terminal state ({job.status})",
            )
        return CancelResponse(run_id=run_id, status="cancelled", message="Job cancelled.")

    @app.get("/runs/{run_id}/stream", tags=["runs"], dependencies=[require_api_key()])
    async def stream_run(run_id: str) -> StreamingResponse:
        """Stream live log output as Server-Sent Events (text/event-stream)."""
        job = _runner.store.get_job(run_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"run_id {run_id!r} not found")

        async def _generate():
            async for event_type, data in _runner.stream_logs(run_id):
                safe_data = str(data).replace("\n", "\ndata: ")
                yield f"event: {event_type}\ndata: {safe_data}\n\n"

        return StreamingResponse(_generate(), media_type="text/event-stream")

    return app
