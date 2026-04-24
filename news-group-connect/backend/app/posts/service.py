"""Post service business logic for CRUD operations and categorization."""

from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.posts.schemas import PostCreate, PostUpdate
from models.post import Post


class PostService:
    """Service class for managing news posts."""

    def __init__(self, db_session: AsyncSession):
        self.db_session = db_session

    async def create_post(
        self,
        author_id: int,
        post_data: PostCreate,
    ) -> Post:
        """Create a new news post.

        Args:
            author_id: ID of the post author
            post_data: Post creation data

        Returns:
            Created Post instance
        """
        post = Post(
            author_id=author_id,
            title=post_data.title,
            content=post_data.content,
            category=post_data.category,
            group_id=post_data.group_id,
            image_url=post_data.image_url,
            view_count=0,
            like_count=0,
        )
        self.db_session.add(post)
        await self.db_session.commit()
        await self.db_session.refresh(post)
        return post

    async def get_post_by_id(self, post_id: int) -> Optional[Post]:
        """Retrieve a single post by ID, incrementing view count.

        Args:
            post_id: ID of the post to retrieve

        Returns:
            Post instance or None if not found
        """
        result = await self.db_session.execute(
            select(Post).where(Post.id == post_id)
        )
        post = result.scalar_one_or_none()
        if post:
            post.view_count += 1
            await self.db_session.commit()
            await self.db_session.refresh(post)
        return post

    async def list_posts(
        self,
        page: int = 1,
        limit: int = 20,
        category: Optional[str] = None,
        group_id: Optional[int] = None,
        author_id: Optional[int] = None,
    ) -> tuple[list[Post], int]:
        """List posts with pagination and optional filters.

        Args:
            page: Page number (1-indexed)
            limit: Items per page
            category: Filter by category
            group_id: Filter by group
            author_id: Filter by author

        Returns:
            Tuple of (posts list, total count)
        """
        query = select(Post)

        if category:
            query = query.where(Post.category == category)
        if group_id is not None:
            query = query.where(Post.group_id == group_id)
        if author_id is not None:
            query = query.where(Post.author_id == author_id)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db_session.execute(count_query)
        total = total_result.scalar() or 0

        # Get paginated results
        query = query.order_by(Post.created_at.desc())
        query = query.offset((page - 1) * limit).limit(limit)

        result = await self.db_session.execute(query)
        posts = list(result.scalars().all())

        return posts, total

    async def update_post(
        self,
        post_id: int,
        author_id: int,
        post_data: PostUpdate,
    ) -> Optional[Post]:
        """Update an existing post. Only the author can update.

        Args:
            post_id: ID of the post to update
            author_id: ID of the requesting user
            post_data: Post update data

        Returns:
            Updated Post instance or None if not found/unauthorized
        """
        result = await self.db_session.execute(
            select(Post).where(Post.id == post_id)
        )
        post = result.scalar_one_or_none()

        if not post or post.author_id != author_id:
            return None

        update_data = post_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(post, field, value)

        await self.db_session.commit()
        await self.db_session.refresh(post)
        return post

    async def delete_post(self, post_id: int, author_id: int) -> bool:
        """Delete a post. Only the author can delete.

        Args:
            post_id: ID of the post to delete
            author_id: ID of the requesting user

        Returns:
            True if deleted, False if not found/unauthorized
        """
        result = await self.db_session.execute(
            select(Post).where(Post.id == post_id)
        )
        post = result.scalar_one_or_none()

        if not post or post.author_id != author_id:
            return False

        await self.db_session.delete(post)
        await self.db_session.commit()
        return True

    async def like_post(self, post_id: int) -> Optional[Post]:
        """Increment the like count for a post.

        Args:
            post_id: ID of the post to like

        Returns:
            Updated Post instance or None if not found
        """
        result = await self.db_session.execute(
            select(Post).where(Post.id == post_id)
        )
        post = result.scalar_one_or_none()

        if not post:
            return None

        post.like_count += 1
        await self.db_session.commit()
        await self.db_session.refresh(post)
        return post
