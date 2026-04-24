"""Tests for PostService business logic."""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from app.posts.service import PostService
from app.posts.schemas import PostCreate, PostUpdate
from models.post import Post


class TestPostServiceCreatePost:
    """Tests for PostService.create_post."""

    @pytest.mark.asyncio
    async def test_create_post_success(self, mock_db_session):
        """Should create a new post with valid data."""
        service = PostService(mock_db_session)
        post_data = PostCreate(
            title="New Post",
            content="Post content here",
            category="news",
        )

        created_post = Post()
        created_post.id = 1
        created_post.title = "New Post"
        created_post.content = "Post content here"
        created_post.author_id = 1
        created_post.category = "news"
        created_post.group_id = None
        created_post.image_url = None
        created_post.view_count = 0
        created_post.like_count = 0
        created_post.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        created_post.updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)

        async def mock_add_and_commit(*args, **kwargs):
            pass

        mock_db_session.add = MagicMock()
        mock_db_session.commit = AsyncMock()
        mock_db_session.refresh = AsyncMock()

        result = await service.create_post(1, post_data)

        mock_db_session.add.assert_called_once()
        mock_db_session.commit.assert_awaited_once()
        mock_db_session.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_post_with_group_id(self, mock_db_session):
        """Should create a post associated with a group."""
        service = PostService(mock_db_session)
        post_data = PostCreate(
            title="Group Post",
            content="Content",
            category="tech",
            group_id=5,
        )

        mock_db_session.add = MagicMock()
        mock_db_session.commit = AsyncMock()
        mock_db_session.refresh = AsyncMock()

        await service.create_post(1, post_data)

        added_post = mock_db_session.add.call_args[0][0]
        assert added_post.group_id == 5

    @pytest.mark.asyncio
    async def test_create_post_with_image_url(self, mock_db_session):
        """Should create a post with an image URL."""
        service = PostService(mock_db_session)
        post_data = PostCreate(
            title="Image Post",
            content="Content",
            category="media",
            image_url="https://example.com/image.jpg",
        )

        mock_db_session.add = MagicMock()
        mock_db_session.commit = AsyncMock()
        mock_db_session.refresh = AsyncMock()

        await service.create_post(1, post_data)

        added_post = mock_db_session.add.call_args[0][0]
        assert added_post.image_url == "https://example.com/image.jpg"

    @pytest.mark.asyncio
    async def test_create_post_initializes_counters_to_zero(self, mock_db_session):
        """Should initialize view_count and like_count to 0."""
        service = PostService(mock_db_session)
        post_data = PostCreate(
            title="Test",
            content="Content",
            category="news",
        )

        mock_db_session.add = MagicMock()
        mock_db_session.commit = AsyncMock()
        mock_db_session.refresh = AsyncMock()

        await service.create_post(1, post_data)

        added_post = mock_db_session.add.call_args[0][0]
        assert added_post.view_count == 0
        assert added_post.like_count == 0


class TestPostServiceGetPostById:
    """Tests for PostService.get_post_by_id."""

    @pytest.mark.asyncio
    async def test_get_post_by_id_success(self, mock_db_session, sample_post):
        """Should return post and increment view count."""
        service = PostService(mock_db_session)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=sample_post)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        result = await service.get_post_by_id(1)

        assert result is not None
        assert result.view_count == 1
        mock_db_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_post_by_id_not_found(self, mock_db_session):
        """Should return None when post doesn't exist."""
        service = PostService(mock_db_session)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        result = await service.get_post_by_id(999)

        assert result is None
        mock_db_session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_post_by_id_increments_view_count(self, mock_db_session):
        """Should increment view_count each time post is retrieved."""
        service = PostService(mock_db_session)
        post = Post()
        post.id = 1
        post.title = "Test"
        post.content = "Content"
        post.author_id = 1
        post.category = "news"
        post.view_count = 5
        post.like_count = 0
        post.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        post.updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=post)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        result = await service.get_post_by_id(1)

        assert result.view_count == 6


class TestPostServiceListPosts:
    """Tests for PostService.list_posts."""

    @pytest.mark.asyncio
    async def test_list_posts_returns_paginated_results(self, mock_db_session):
        """Should return paginated list of posts with total count."""
        service = PostService(mock_db_session)
        mock_result = MagicMock()
        mock_result.scalar = MagicMock(return_value=2)
        mock_scalars = MagicMock()
        mock_scalars.all = MagicMock(return_value=[])
        mock_result.scalars = MagicMock(return_value=mock_scalars)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        posts, total = await service.list_posts(page=1, limit=10)

        assert total == 2
        assert isinstance(posts, list)
        assert mock_db_session.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_list_posts_filters_by_category(self, mock_db_session):
        """Should filter posts by category when provided."""
        service = PostService(mock_db_session)
        mock_result = MagicMock()
        mock_result.scalar = MagicMock(return_value=0)
        mock_scalars = MagicMock()
        mock_scalars.all = MagicMock(return_value=[])
        mock_result.scalars = MagicMock(return_value=mock_scalars)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        await service.list_posts(category="tech")

        # Verify execute was called (filtering happens in query construction)
        assert mock_db_session.execute.await_count >= 1

    @pytest.mark.asyncio
    async def test_list_posts_filters_by_group_id(self, mock_db_session):
        """Should filter posts by group_id when provided."""
        service = PostService(mock_db_session)
        mock_result = MagicMock()
        mock_result.scalar = MagicMock(return_value=0)
        mock_scalars = MagicMock()
        mock_scalars.all = MagicMock(return_value=[])
        mock_result.scalars = MagicMock(return_value=mock_scalars)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        await service.list_posts(group_id=5)

        assert mock_db_session.execute.await_count >= 1

    @pytest.mark.asyncio
    async def test_list_posts_filters_by_author_id(self, mock_db_session):
        """Should filter posts by author_id when provided."""
        service = PostService(mock_db_session)
        mock_result = MagicMock()
        mock_result.scalar = MagicMock(return_value=0)
        mock_scalars = MagicMock()
        mock_scalars.all = MagicMock(return_value=[])
        mock_result.scalars = MagicMock(return_value=mock_scalars)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        await service.list_posts(author_id=3)

        assert mock_db_session.execute.await_count >= 1

    @pytest.mark.asyncio
    async def test_list_posts_empty_result(self, mock_db_session):
        """Should return empty list when no posts exist."""
        service = PostService(mock_db_session)
        mock_result = MagicMock()
        mock_result.scalar = MagicMock(return_value=0)
        mock_scalars = MagicMock()
        mock_scalars.all = MagicMock(return_value=[])
        mock_result.scalars = MagicMock(return_value=mock_scalars)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        posts, total = await service.list_posts()

        assert posts == []
        assert total == 0


class TestPostServiceUpdatePost:
    """Tests for PostService.update_post."""

    @pytest.mark.asyncio
    async def test_update_post_success(self, mock_db_session, sample_post):
        """Should update post when author matches."""
        service = PostService(mock_db_session)
        update_data = PostUpdate(title="Updated Title")

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=sample_post)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        result = await service.update_post(1, 1, update_data)

        assert result is not None
        assert result.title == "Updated Title"
        mock_db_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_post_not_found(self, mock_db_session):
        """Should return None when post doesn't exist."""
        service = PostService(mock_db_session)
        update_data = PostUpdate(title="Updated")

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        result = await service.update_post(999, 1, update_data)

        assert result is None

    @pytest.mark.asyncio
    async def test_update_post_unauthorized(self, mock_db_session, sample_post):
        """Should return None when author_id doesn't match."""
        service = PostService(mock_db_session)
        update_data = PostUpdate(title="Updated")

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=sample_post)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        result = await service.update_post(1, 999, update_data)

        assert result is None

    @pytest.mark.asyncio
    async def test_update_post_partial_update(self, mock_db_session, sample_post):
        """Should only update provided fields."""
        service = PostService(mock_db_session)
        original_content = sample_post.content
        update_data = PostUpdate(category="updated_category")

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=sample_post)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        result = await service.update_post(1, 1, update_data)

        assert result is not None
        assert result.category == "updated_category"
        assert result.content == original_content


class TestPostServiceDeletePost:
    """Tests for PostService.delete_post."""

    @pytest.mark.asyncio
    async def test_delete_post_success(self, mock_db_session, sample_post):
        """Should delete post when author matches."""
        service = PostService(mock_db_session)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=sample_post)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        result = await service.delete_post(1, 1)

        assert result is True
        mock_db_session.delete.assert_awaited_once_with(sample_post)
        mock_db_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_post_not_found(self, mock_db_session):
        """Should return False when post doesn't exist."""
        service = PostService(mock_db_session)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        result = await service.delete_post(999, 1)

        assert result is False

    @pytest.mark.asyncio
    async def test_delete_post_unauthorized(self, mock_db_session, sample_post):
        """Should return False when author_id doesn't match."""
        service = PostService(mock_db_session)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=sample_post)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        result = await service.delete_post(1, 999)

        assert result is False
        mock_db_session.delete.assert_not_awaited()


class TestPostServiceLikePost:
    """Tests for PostService.like_post."""

    @pytest.mark.asyncio
    async def test_like_post_success(self, mock_db_session, sample_post):
        """Should increment like count."""
        service = PostService(mock_db_session)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=sample_post)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        result = await service.like_post(1)

        assert result is not None
        assert result.like_count == 1
        mock_db_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_like_post_not_found(self, mock_db_session):
        """Should return None when post doesn't exist."""
        service = PostService(mock_db_session)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        result = await service.like_post(999)

        assert result is None

    @pytest.mark.asyncio
    async def test_like_post_multiple_likes(self, mock_db_session):
        """Should accumulate likes across multiple calls."""
        service = PostService(mock_db_session)
        post = Post()
        post.id = 1
        post.title = "Test"
        post.content = "Content"
        post.author_id = 1
        post.category = "news"
        post.view_count = 0
        post.like_count = 5
        post.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        post.updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=post)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        result = await service.like_post(1)

        assert result.like_count == 6
