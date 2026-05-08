"""SQLAlchemy model for tracking WordPress import jobs."""

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, Enum as SAEnum, Float, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models in this module."""
    pass


class JobStatus(str, enum.Enum):
    """Enumeration of possible import job statuses."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ImportJob(Base):
    """Represents a WordPress database import job and tracks its execution progress.
    
    Stores audit-safe hashes of the source connection string, progress metrics,
    and lifecycle timestamps. Status transitions are managed by the job tracker service.
    """
    __tablename__ = "import_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    status: Mapped[JobStatus] = mapped_column(
        SAEnum(JobStatus), 
        nullable=False, 
        default=JobStatus.PENDING
    )
    wp_db_url_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    progress_pct: Mapped[float] = mapped_column(
        Float, 
        nullable=False, 
        default=0.0
    )
    total_entities: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_entities: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_entities: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        nullable=False, 
        server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        nullable=False, 
        server_default=func.now(), 
        onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("progress_pct >= 0.0 AND progress_pct <= 100.0", name="ck_progress_pct_range"),
        CheckConstraint("total_entities >= 0", name="ck_total_entities_non_neg"),
        CheckConstraint("processed_entities >= 0", name="ck_processed_entities_non_neg"),
        CheckConstraint("failed_entities >= 0", name="ck_failed_entities_non_neg"),
    )

    def __repr__(self) -> str:
        return f"<ImportJob(id={self.id}, status={self.status.value}, progress={self.progress_pct}%)>"
