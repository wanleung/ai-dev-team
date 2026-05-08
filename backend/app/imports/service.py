"""Service layer for WordPress import operations."""

import hashlib
from typing import List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.import_schemas import ImportLogEntryResponse, ImportJobStatusResponse, ImportLogsResponse, LogLevel
from models.import_job import ImportJob, JobStatus
from models.import_log import ImportLogEntry


class ImportService:
    """Handles WordPress import job creation, status tracking, and log retrieval."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_import_job(self, wp_database_url: str) -> ImportJob:
        """Create a new import job and queue it for processing."""
        wp_db_url_hash = hashlib.sha256(wp_database_url.encode()).hexdigest()
        
        job = ImportJob(
            status=JobStatus.PENDING,
            wp_db_url_hash=wp_db_url_hash,
            progress_pct=0.0,
            total_entities=0,
            processed_entities=0,
            failed_entities=0,
        )
        self.db.add(job)
        await self.db.commit()
        await self.db.refresh(job)
        return job

    async def get_job_by_id(self, job_id: int) -> Optional[ImportJob]:
        """Retrieve an import job by its ID."""
        result = await self.db.execute(select(ImportJob).where(ImportJob.id == job_id))
        return result.scalar_one_or_none()

    async def get_job_status(self, job_id: int) -> Optional[ImportJobStatusResponse]:
        """Get the current status of an import job."""
        job = await self.get_job_by_id(job_id)
        if not job:
            return None
        
        return ImportJobStatusResponse(
            id=job.id,
            status=JobStatus(job.status.value),
            progress_pct=job.progress_pct,
            total_entities=job.total_entities,
            processed_entities=job.processed_entities,
            failed_entities=job.failed_entities,
            started_at=job.started_at,
            completed_at=job.completed_at,
        )

    async def get_job_logs(self, job_id: int, limit: int = 50, offset: int = 0) -> Optional[ImportLogsResponse]:
        """Retrieve logs for a specific import job with pagination."""
        job = await self.get_job_by_id(job_id)
        if not job:
            return None

        total_result = await self.db.execute(
            select(func.count()).select_from(ImportLogEntry).where(ImportLogEntry.job_id == job_id)
        )
        total = total_result.scalar_one()

        logs_result = await self.db.execute(
            select(ImportLogEntry)
            .where(ImportLogEntry.job_id == job_id)
            .order_by(ImportLogEntry.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        log_entries = logs_result.scalars().all()

        logs = [
            ImportLogEntryResponse(
                id=entry.id,
                level=LogLevel(entry.level),
                message=entry.message,
                entity_type=entry.entity_type,
                entity_id=entry.entity_id,
                created_at=entry.created_at,
            )
            for entry in log_entries
        ]

        return ImportLogsResponse(logs=logs, total=total)
