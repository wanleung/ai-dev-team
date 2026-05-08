"""SQLAlchemy model for the ImportLogEntry table."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from models.import_job import Base


class ImportLogEntry(Base):
    """Represents a single log entry for a WordPress import job.
    
    Stores structured logs generated during the WP database import process,
    including severity level, associated entity details, and timestamps.
    """
    __tablename__ = "import_log_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(Integer, ForeignKey("import_jobs.id"), nullable=False)
    level: Mapped[str] = mapped_column(String(10), nullable=False)
    message: Mapped[str] = mapped_column(String(2000), nullable=False)
    entity_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    entity_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        nullable=False, 
        default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self) -> str:
        return f"<ImportLogEntry(id={self.id}, job_id={self.job_id}, level='{self.level}')>"
