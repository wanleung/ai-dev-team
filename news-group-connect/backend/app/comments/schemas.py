"""Pydantic schemas for comment service request/response validation."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CommentCreate(BaseModel):
    """Schema for creating a new comment."""

    post_id: int = Field(..., gt=0)
    content: str = Field(..., min_length=1, max_length=5000)
    parent_id: Optional[int] = Field(None, gt=0)


class CommentUpdate(BaseModel):
    """Schema for updating an existing comment."""

    content: str = Field(..., min_length=1, max_length=5000)


class CommentReplyResponse(BaseModel):
    """Schema for nested comment replies."""

    id: int
    author_id: int
    content: str
    like_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CommentResponse(BaseModel):
    """Schema for comment response data."""

    id: int
    post_id: int
    author_id: int
    content: str
    parent_id: Optional[int] = None
    like_count: int = 0
    created_at: datetime
    updated_at: datetime
    replies: list[CommentReplyResponse] = []

    model_config = {"from_attributes": True}


class CommentListResponse(BaseModel):
    """Schema for paginated list of comments."""

    comments: list[CommentResponse]
    total: int
    page: int
    limit: int
    has_next: bool
    has_prev: bool


class LikeResponse(BaseModel):
    """Schema for like operation response."""

    like_count: int
