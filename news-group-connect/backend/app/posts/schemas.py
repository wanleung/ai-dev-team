"""Pydantic schemas for post service request/response validation."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class PostCreate(BaseModel):
    """Schema for creating a new post."""

    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1)
    category: str = Field(..., min_length=1, max_length=50)
    group_id: Optional[int] = None
    image_url: Optional[str] = None


class PostUpdate(BaseModel):
    """Schema for updating an existing post."""

    title: Optional[str] = Field(None, min_length=1, max_length=200)
    content: Optional[str] = Field(None, min_length=1)
    category: Optional[str] = Field(None, min_length=1, max_length=50)
    image_url: Optional[str] = None


class PostResponse(BaseModel):
    """Schema for post response data."""

    id: int
    title: str
    content: str
    author_id: int
    group_id: Optional[int] = None
    category: str
    image_url: Optional[str] = None
    view_count: int = 0
    like_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PostListResponse(BaseModel):
    """Schema for paginated list of posts."""

    posts: list[PostResponse]
    total: int
    page: int
    limit: int
    has_next: bool
    has_prev: bool


class LikeResponse(BaseModel):
    """Schema for like operation response."""

    like_count: int
