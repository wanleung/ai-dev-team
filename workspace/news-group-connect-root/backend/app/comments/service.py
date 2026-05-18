"""Comment service business logic for CRUD operations and nested comments."""

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.comments.schemas import CommentCreate, CommentUpdate
from models.comment import Comment


class CommentService:
    """Service class for managing comments on posts."""

    def __init__(self, db_session: AsyncSession):
        self.db_session = db_session

    async def create_comment(
        self,
        author_id: int,
        comment_data: CommentCreate,
    ) -> Comment:
        """Create a new comment or reply.

        Args:
            author_id: ID of the comment author
            comment_data: Comment creation data

        Returns:
            Created Comment instance

        Raises:
            ValueError: If parent_id is provided but doesn't exist
        """
        if comment_data.parent_id is not None:
            parent_result = await self.db_session.execute(
                select(Comment).where(Comment.id == comment_data.parent_id)
            )
            parent = parent_result.scalar_one_or_none()
            if not parent:
                raise ValueError("Parent comment not found")

        comment = Comment(
            post_id=comment_data.post_id,
            author_id=author_id,
            content=comment_data.content,
            parent_id=comment_data.parent_id,
            like_count=0,
        )
        self.db_session.add(comment)
        await self.db_session.commit()
        await self.db_session.refresh(comment)
        return comment

    async def get_comments_by_post(
        self,
        post_id: int,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[Comment], int]:
        """List comments for a post with pagination.

        Only returns top-level comments (parent_id is None).
        Replies are loaded via relationship.

        Args:
            post_id: ID of the post
            page: Page number (1-indexed)
            limit: Items per page

        Returns:
            Tuple of (comments list, total count)
        """
        # Count top-level comments
        count_query = select(func.count()).select_from(Comment).where(
            Comment.post_id == post_id,
            Comment.parent_id.is_(None),
        )
        total_result = await self.db_session.execute(count_query)
        total = total_result.scalar() or 0

        # Get paginated top-level comments with replies
        query = (
            select(Comment)
            .where(Comment.post_id == post_id, Comment.parent_id.is_(None))
            .order_by(Comment.created_at.asc())
            .offset((page - 1) * limit)
            .limit(limit)
        )

        result = await self.db_session.execute(query)
        comments = list(result.scalars().all())

        return comments, total

    async def get_comment_by_id(self, comment_id: int) -> Optional[Comment]:
        """Retrieve a single comment by ID.

        Args:
            comment_id: ID of the comment

        Returns:
            Comment instance or None if not found
        """
        result = await self.db_session.execute(
            select(Comment).where(Comment.id == comment_id)
        )
        return result.scalar_one_or_none()

    async def update_comment(
        self,
        comment_id: int,
        author_id: int,
        comment_data: CommentUpdate,
    ) -> Optional[Comment]:
        """Update an existing comment. Only the author can update.

        Args:
            comment_id: ID of the comment to update
            author_id: ID of the requesting user
            comment_data: Comment update data

        Returns:
            Updated Comment instance or None if not found/unauthorized
        """
        result = await self.db_session.execute(
            select(Comment).where(Comment.id == comment_id)
        )
        comment = result.scalar_one_or_none()

        if not comment or comment.author_id != author_id:
            return None

        comment.content = comment_data.content
        await self.db_session.commit()
        await self.db_session.refresh(comment)
        return comment

    async def delete_comment(self, comment_id: int, author_id: int) -> bool:
        """Delete a comment. Only the author can delete.

        Args:
            comment_id: ID of the comment to delete
            author_id: ID of the requesting user

        Returns:
            True if deleted, False if not found/unauthorized
        """
        result = await self.db_session.execute(
            select(Comment).where(Comment.id == comment_id)
        )
        comment = result.scalar_one_or_none()

        if not comment or comment.author_id != author_id:
            return False

        await self.db_session.delete(comment)
        await self.db_session.commit()
        return True

    async def like_comment(self, comment_id: int) -> Optional[Comment]:
        """Increment the like count for a comment.

        Args:
            comment_id: ID of the comment to like

        Returns:
            Updated Comment instance or None if not found
        """
        result = await self.db_session.execute(
            select(Comment).where(Comment.id == comment_id)
        )
        comment = result.scalar_one_or_none()

        if not comment:
            return None

        comment.like_count += 1
        await self.db_session.commit()
        await self.db_session.refresh(comment)
        return comment
