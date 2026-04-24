from datetime import datetime

from pydantic import BaseModel, Field


class MediaUploadResponse(BaseModel):
    id: int
    filename: str
    original_filename: str
    content_type: str
    file_size: int
    url: str
    thumbnail_url: str | None = None
    uploaded_by: int
    created_at: datetime

    model_config = {"from_attributes": True}


class MediaListResponse(BaseModel):
    files: list[MediaUploadResponse]
    total: int
    page: int
    limit: int
    has_next: bool
    has_prev: bool


class MediaDeleteResponse(BaseModel):
    deleted: bool
