"""Router for WordPress import API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.imports.service import ImportService
from app.schemas.import_schemas import (
    ImportJobCreateResponse,
    ImportJobCreateRequest,
    ImportJobStatusResponse,
    ImportLogsResponse,
    JobStatus,
)
from models.import_job import JobStatus as JobStatusEnum

router = APIRouter(prefix="/api/v1/import", tags=["import"])


async def _get_import_service(db: AsyncSession = Depends(get_db)) -> ImportService:
    return ImportService(db)


@router.post("", response_model=ImportJobCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_import_job(
    request: ImportJobCreateRequest,
    service: ImportService = Depends(_get_import_service),
) -> ImportJobCreateResponse:
    """Trigger a new WordPress import job.
    
    The WordPress database URL is sourced from the WP_DATABASE_URL environment variable.
    """
    wp_database_url = settings.wp_database_url if hasattr(settings, 'wp_database_url') else ""
    
    if not wp_database_url:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="WP_DATABASE_URL environment variable is not configured",
        )

    job = await service.create_import_job(wp_database_url)
    
    return ImportJobCreateResponse(
        job_id=job.id,
        status=JobStatus(job.status.value),
        message="Import job queued successfully",
    )


@router.get("/{job_id}", response_model=ImportJobStatusResponse)
async def get_import_job_status(
    job_id: int,
    service: ImportService = Depends(_get_import_service),
) -> ImportJobStatusResponse:
    """Get the current status and progress of an import job."""
    job_status = await service.get_job_status(job_id)
    if not job_status:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Import job not found",
        )
    return job_status


@router.get("/{job_id}/logs", response_model=ImportLogsResponse)
async def get_import_job_logs(
    job_id: int,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    service: ImportService = Depends(_get_import_service),
) -> ImportLogsResponse:
    """Retrieve logs for a specific import job with pagination."""
    logs = await service.get_job_logs(job_id, limit=limit, offset=offset)
    if not logs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Import job not found",
        )
    return logs
