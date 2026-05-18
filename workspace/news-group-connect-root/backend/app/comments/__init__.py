"""Comment service module for NewsGroup Connect."""

from app.comments.router import router
from app.comments.schemas import (
    CommentCreate,
    CommentListResponse,
    CommentResponse,
    CommentUpdate,
)
from app.comments.service import CommentService

__all__ = [
    "CommentService",
    "CommentCreate",
    "CommentUpdate",
    "CommentResponse",
    "CommentListResponse",
    "router",
]
