"""FastAPI router for post endpoints."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db_session
from app.posts.schemas import (
    LikeResponse,
    PostCreate,
    PostListResponse,
    PostResponse,
    PostUpdate,
)
from app.posts.service import PostService

router = APIRouter(prefix="/api/v1/posts", tags=["posts"])


def get_post_service(db_session: AsyncSession = Depends(get_db_session)) -> PostService:
    """Dependency to get PostService instance."""
    return PostService(db_session)


@router.post(
    "",
    response_model=PostResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new post",
)
async def create_post(
    post_data: PostCreate,
    author_id: int = 1,  # TODO: Replace with actual auth dependency
    service: PostService = Depends(get_post_service),
) -> PostResponse:
    """Create a new news post.

    Args:
        post_data: Post creation data
        author_id: ID of the authenticated user
        service: PostService dependency

    Returns:
        Created post data

    Raises:
        HTTPException: If creation fails
    """
    try:
        post = await service.create_post(author_id, post_data)
        return PostResponse.model_validate(post)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create post: {str(e)}",
        )


@router.get(
    "",
    response_model=PostListResponse,
    summary="List all posts",
)
async def list_posts(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    category: Optional[str] = Query(None, description="Filter by category"),
    group_id: Optional[int] = Query(None, description="Filter by group"),
    author_id: Optional[int] = Query(None, description="Filter by author"),
    service: PostService = Depends(get_post_service),
) -> PostListResponse:
    """List posts with pagination and optional filters.

    Args:
        page: Page number (1-indexed)
        limit: Items per page (max 100)
        category: Filter by category
        group_id: Filter by group
        author_id: Filter by author
        service: PostService dependency

    Returns:
        Paginated list of posts
    """
    posts, total = await service.list_posts(
        page=page,
        limit=limit,
        category=category,
        group_id=group_id,
        author_id=author_id,
    )

    return PostListResponse(
        posts=[PostResponse.model_validate(p) for p in posts],
        total=total,
        page=page,
        limit=limit,
        has_next=(page * limit) < total,
        has_prev=page > 1,
    )


@router.get(
    "/{post_id}",
    response_model=PostResponse,
    summary="Get a single post",
)
async def get_post(
    post_id: int,
    service: PostService = Depends(get_post_service),
) -> PostResponse:
    """Retrieve a single post by ID.

    Args:
        post_id: ID of the post to retrieve
        service: PostService dependency

    Returns:
        Post data

    Raises:
        HTTPException: If post not found
    """
    post = await service.get_post_by_id(post_id)
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found",
        )
    return PostResponse.model_validate(post)


@router.put(
    "/{post_id}",
    response_model=PostResponse,
    summary="Update a post",
)
async def update_post(
    post_id: int,
    post_data: PostUpdate,
    author_id: int = 1,  # TODO: Replace with actual auth dependency
    service: PostService = Depends(get_post_service),
) -> PostResponse:
    """Update an existing post. Only the author can update.

    Args:
        post_id: ID of the post to update
        post_data: Post update data
        author_id: ID of the authenticated user
        service: PostService dependency

    Returns:
        Updated post data

    Raises:
        HTTPException: If post not found or unauthorized
    """
    post = await service.update_post(post_id, author_id, post_data)
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found or you don't have permission to update it",
        )
    return PostResponse.model_validate(post)


@router.delete(
    "/{post_id}",
    summary="Delete a post",
)
async def delete_post(
    post_id: int,
    author_id: int = 1,  # TODO: Replace with actual auth dependency
    service: PostService = Depends(get_post_service),
) -> dict:
    """Delete a post. Only the author can delete.

    Args:
        post_id: ID of the post to delete
        author_id: ID of the authenticated user
        service: PostService dependency

    Returns:
        Deletion confirmation

    Raises:
        HTTPException: If post not found or unauthorized
    """
    deleted = await service.delete_post(post_id, author_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found or you don't have permission to delete it",
        )
    return {"deleted": True}


@router.post(
    "/{post_id}/like",
    response_model=LikeResponse,
    summary="Like a post",
)
async def like_post(
    post_id: int,
    service: PostService = Depends(get_post_service),
) -> LikeResponse:
    """Like a post, incrementing the like count.

    Args:
        post_id: ID of the post to like
        service: PostService dependency

    Returns:
        Updated like count

    Raises:
        HTTPException: If post not found
    """
    post = await service.like_post(post_id)
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found",
        )
    return LikeResponse(like_count=post.like_count)
