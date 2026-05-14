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
    """Response for DELETE /runs/{id}."""

    run_id: str
    status: str
    message: str


class HealthResponse(BaseModel):
    """Response for GET /health."""

    status: str
    version: str
