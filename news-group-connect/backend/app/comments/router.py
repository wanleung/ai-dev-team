"""FastAPI router for comment endpoints."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.comments.schemas import (
    CommentCreate,
    CommentListResponse,
    CommentResponse,
    CommentReplyResponse,
    CommentUpdate,
    LikeResponse,
)
from app.comments.service import CommentService
from app.database import get_db_session

router = APIRouter(prefix="/api/v1/comments", tags=["comments"])


def get_comment_service(
    db_session: AsyncSession = Depends(get_db_session),
) -> CommentService:
    """Dependency to get CommentService instance."""
    return CommentService(db_session)


def _build_comment_response(comment) -> CommentResponse:
    """Build CommentResponse from ORM model including nested replies."""
    replies = [
        CommentReplyResponse(
            id=r.id,
            author_id=r.author_id,
            content=r.content,
            like_count=r.like_count,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in comment.replies
    ]
    return CommentResponse(
        id=comment.id,
        post_id=comment.post_id,
        author_id=comment.author_id,
        content=comment.content,
        parent_id=comment.parent_id,
        like_count=comment.like_count,
        created_at=comment.created_at,
        updated_at=comment.updated_at,
        replies=replies,
    )


@router.post(
    "",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a comment",
)
async def create_comment(
    comment_data: CommentCreate,
    author_id: int = 1,  # TODO: Replace with actual auth dependency
    service: CommentService = Depends(get_comment_service),
) -> CommentResponse:
    """Create a new comment or reply on a post.

    Args:
        comment_data: Comment creation data
        author_id: ID of the authenticated user
        service: CommentService dependency

    Returns:
        Created comment data

    Raises:
        HTTPException: If creation fails or parent comment not found
    """
    try:
        comment = await service.create_comment(author_id, comment_data)
        return _build_comment_response(comment)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create comment: {str(e)}",
        )


@router.get(
    "",
    response_model=CommentListResponse,
    summary="List comments for a post",
)
async def list_comments(
    post_id: int = Query(..., gt=0, description="Post ID to fetch comments for"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    service: CommentService = Depends(get_comment_service),
) -> CommentListResponse:
    """List comments for a post with pagination.

    Args:
        post_id: ID of the post
        page: Page number (1-indexed)
        limit: Items per page (max 100)
        service: CommentService dependency

    Returns:
        Paginated list of comments with nested replies
    """
    comments, total = await service.get_comments_by_post(
        post_id=post_id,
        page=page,
        limit=limit,
    )

    return CommentListResponse(
        comments=[_build_comment_response(c) for c in comments],
        total=total,
        page=page,
        limit=limit,
        has_next=(page * limit) < total,
        has_prev=page > 1,
    )


@router.get(
    "/{comment_id}",
    response_model=CommentResponse,
    summary="Get a single comment",
)
async def get_comment(
    comment_id: int,
    service: CommentService = Depends(get_comment_service),
) -> CommentResponse:
    """Retrieve a single comment by ID.

    Args:
        comment_id: ID of the comment
        service: CommentService dependency

    Returns:
        Comment data with nested replies

    Raises:
        HTTPException: If comment not found
    """
    comment = await service.get_comment_by_id(comment_id)
    if not comment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Comment not found",
        )
    return _build_comment_response(comment)


@router.put(
    "/{comment_id}",
    response_model=CommentResponse,
    summary="Update a comment",
)
async def update_comment(
    comment_id: int,
    comment_data: CommentUpdate,
    author_id: int = 1,  # TODO: Replace with actual auth dependency
    service: CommentService = Depends(get_comment_service),
) -> CommentResponse:
    """Update an existing comment. Only the author can update.

    Args:
        comment_id: ID of the comment to update
        comment_data: Comment update data
        author_id: ID of the authenticated user
        service: CommentService dependency

    Returns:
        Updated comment data

    Raises:
        HTTPException: If comment not found or unauthorized
    """
    comment = await service.update_comment(comment_id, author_id, comment_data)
    if not comment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Comment not found or you don't have permission to update it",
        )
    return _build_comment_response(comment)


@router.delete(
    "/{comment_id}",
    summary="Delete a comment",
)
async def delete_comment(
    comment_id: int,
    author_id: int = 1,  # TODO: Replace with actual auth dependency
    service: CommentService = Depends(get_comment_service),
) -> dict:
    """Delete a comment. Only the author can delete.

    Args:
        comment_id: ID of the comment to delete
        author_id: ID of the authenticated user
        service: CommentService dependency

    Returns:
        Deletion confirmation

    Raises:
        HTTPException: If comment not found or unauthorized
    """
    deleted = await service.delete_comment(comment_id, author_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Comment not found or you don't have permission to delete it",
        )
    return {"deleted": True}


@router.post(
    "/{comment_id}/like",
    response_model=LikeResponse,
    summary="Like a comment",
)
async def like_comment(
    comment_id: int,
    service: CommentService = Depends(get_comment_service),
) -> LikeResponse:
    """Like a comment, incrementing the like count.

    Args:
        comment_id: ID of the comment to like
        service: CommentService dependency

    Returns:
        Updated like count

    Raises:
        HTTPException: If comment not found
    """
    comment = await service.like_comment(comment_id)
    if not comment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Comment not found",
        )
    return LikeResponse(like_count=comment.like_count)
