from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class JobStatus(str, Enum):
    """Valid statuses for an import job."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class LogLevel(str, Enum):
    """Valid log levels for import job entries."""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ImportJobCreateRequest(BaseModel):
    """Request body for triggering a new import job.
    
    Credentials are sourced from environment variables, so the request body is intentionally empty.
    """
    pass


class ImportJobCreateResponse(BaseModel):
    """Response returned when an import job is successfully queued."""
    model_config = ConfigDict(from_attributes=True)
    job_id: int
    status: JobStatus
    message: str


class ImportJobStatusResponse(BaseModel):
    """Response containing the current status and progress of an import job."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: JobStatus
    progress_pct: float = Field(ge=0.0, le=100.0, description="Progress percentage (0.0-100.0)")
    total_entities: int = Field(ge=0, description="Total number of entities to import")
    processed_entities: int = Field(ge=0, description="Number of successfully processed entities")
    failed_entities: int = Field(ge=0, description="Number of entities that failed to import")
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class ImportLogEntryResponse(BaseModel):
    """Response schema for a single import entry."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    level: LogLevel
    message: str = Field(min_length=1, max_length=2000, description="Log message")
    entity_type: Optional[str] = Field(default=None, max_length=50, description="Type of entity (e.g., post, category)")
    entity_id: Optional[str] = Field(default=None, max_length=100, description="Identifier of the entity")
    created_at: datetime


class ImportLogsQuery(BaseModel):
    """Query parameters for paginated log retrieval."""
    limit: int = Field(default=50, ge=1, le=100, description="Number of logs to return")
    offset: int = Field(default=0, ge=0, description="Number of logs to skip")


class ImportLogsResponse(BaseModel):
    """Paginated response for import job logs."""
    logs: List[ImportLogEntryResponse]
    total: int = Field(ge=0, description="Total number of log entries matching the query")


class ErrorResponse(BaseModel):
    """Standard error response for API endpoints."""
    error: str
    message: str
