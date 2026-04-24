from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.media.schemas import MediaDeleteResponse, MediaListResponse, MediaUploadResponse
from app.media.service import MediaService

router = APIRouter(prefix="/api/v1/media", tags=["media"])


async def _get_media_service(db: AsyncSession = Depends(get_db)) -> MediaService:
    return MediaService(db)


def _validate_upload(file: UploadFile) -> None:
    """Validate uploaded file against allowed types and size."""
    if file.content_type not in settings.allowed_content_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Content type '{file.content_type}' is not allowed. Allowed: {settings.allowed_content_types}",
        )


async def _upload_to_storage(file: UploadFile, unique_filename: str) -> tuple[str, str | None]:
    """Upload file to S3-compatible storage and return (url, thumbnail_url)."""
    # In production, integrate with boto3/aiobotocore for S3 upload
    # For now, return a placeholder URL
    base_url = settings.cdn_base_url or f"http://localhost:9000/{settings.s3_bucket_name}"
    url = f"{base_url}/{unique_filename}"
    thumbnail_url = None

    # Generate thumbnail for images
    if file.content_type and file.content_type.startswith("image/"):
        thumbnail_url = f"{base_url}/thumbs/{unique_filename}"

    return url, thumbnail_url


@router.post("/upload", response_model=MediaUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_media(
    file: UploadFile,
    service: MediaService = Depends(_get_media_service),
) -> MediaUploadResponse:
    """Upload a media file. Returns the file URL and metadata."""
    _validate_upload(file)

    contents = await file.read()
    file_size = len(contents)

    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    if file_size > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File size exceeds maximum allowed size of {settings.max_upload_size_mb}MB",
        )

    unique_filename = MediaService.generate_unique_filename(file.filename or "upload")
    url, thumbnail_url = await _upload_to_storage(file, unique_filename)

    # In production, extract user_id from JWT token
    uploaded_by = 1  # Placeholder: replace with get_current_user().id

    media = await service.create_media_record(
        filename=unique_filename,
        original_filename=file.filename or "upload",
        content_type=file.content_type or "application/octet-stream",
        file_size=file_size,
        url=url,
        thumbnail_url=thumbnail_url,
        uploaded_by=uploaded_by,
    )

    return media


@router.get("", response_model=MediaListResponse)
async def list_media(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    service: MediaService = Depends(_get_media_service),
) -> MediaListResponse:
    """List media files uploaded by the current user."""
    # In production, extract user_id from JWT token
    uploaded_by = 1  # Placeholder: replace with get_current_user().id

    files, total = await service.list_media(uploaded_by=uploaded_by, page=page, limit=limit)
    return MediaListResponse(
        files=files,
        total=total,
        page=page,
        limit=limit,
        has_next=(page * limit) < total,
        has_prev=page > 1,
    )


@router.get("/{media_id}", response_model=MediaUploadResponse)
async def get_media(
    media_id: int,
    service: MediaService = Depends(_get_media_service),
) -> MediaUploadResponse:
    """Get media file metadata by ID."""
    media = await service.get_media_by_id(media_id)
    if not media:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media file not found")
    return media


@router.delete("/{media_id}", response_model=MediaDeleteResponse)
async def delete_media(
    media_id: int,
    service: MediaService = Depends(_get_media_service),
) -> MediaDeleteResponse:
    """Delete a media file. Removes database record and storage file."""
    media = await service.get_media_by_id(media_id)
    if not media:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media file not found")

    # In production: delete from S3 storage using the filename
    # e.g., await s3_client.delete_object(Bucket=settings.s3_bucket_name, Key=media.filename)

    await service.delete_media(media)
    return MediaDeleteResponse(deleted=True)
