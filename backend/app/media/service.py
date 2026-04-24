import uuid
from io import BytesIO

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.media import MediaFile


class MediaService:
    """Service for media file management and S3 upload."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_media_record(
        self,
        filename: str,
        original_filename: str,
        content_type: str,
        file_size: int,
        url: str,
        thumbnail_url: str | None,
        uploaded_by: int,
    ) -> MediaFile:
        """Create a media file record in the database."""
        media = MediaFile(
            filename=filename,
            original_filename=original_filename,
            content_type=content_type,
            file_size=file_size,
            url=url,
            thumbnail_url=thumbnail_url,
            uploaded_by=uploaded_by,
        )
        self.db.add(media)
        await self.db.flush()
        await self.db.refresh(media)
        return media

    async def get_media_by_id(self, media_id: int) -> MediaFile | None:
        """Fetch a media file record by ID."""
        result = await self.db.execute(select(MediaFile).where(MediaFile.id == media_id))
        return result.scalar_one_or_none()

    async def list_media(
        self,
        uploaded_by: int,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[MediaFile], int]:
        """List media files for a user with pagination."""
        query = select(MediaFile).where(MediaFile.uploaded_by == uploaded_by)
        count_query = select(func.count(MediaFile.id)).where(MediaFile.uploaded_by == uploaded_by)

        query = query.order_by(MediaFile.created_at.desc()).offset((page - 1) * limit).limit(limit)

        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()

        result = await self.db.execute(query)
        files = list(result.scalars().all())

        return files, total

    async def delete_media(self, media: MediaFile) -> None:
        """Delete a media file record from the database."""
        await self.db.delete(media)
        await self.db.flush()

    @staticmethod
    def generate_unique_filename(original_filename: str) -> str:
        """Generate a unique filename for storage."""
        ext = original_filename.rsplit(".", 1)[-1] if "." in original_filename else "bin"
        return f"{uuid.uuid4().hex}.{ext}"
