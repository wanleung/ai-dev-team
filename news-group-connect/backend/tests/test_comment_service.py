"""Tests for CommentService business logic."""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from app.comments.service import CommentService
from app.comments.schemas import CommentCreate, CommentUpdate
from models.comment import Comment


class TestCommentServiceCreateComment:
    """Tests for CommentService.create_comment."""

    @pytest.mark.asyncio
    async def test_create_comment_success(self, mock_db_session):
        """Should create a new comment with valid data."""
        service = CommentService(mock_db_session)
        comment_data = CommentCreate(
            post_id=1,
            content="Test comment",
        )

        mock_db_session.add = MagicMock()
        mock_db_session.commit = AsyncMock()
        mock_db_session.refresh = AsyncMock()

        await service.create_comment(1, comment_data)

        mock_db_session.add.assert_called_once()
        mock_db_session.commit.assert_awaited_once()
        mock_db_session.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_comment_with_parent(self, mock_db_session):
        """Should create a reply when parent_id is valid."""
        service = CommentService(mock_db_session)
        comment_data = CommentCreate(
            post_id=1,
            content="Test reply",
            parent_id=5,
        )

        parent_comment = Comment()
        parent_comment.id = 5
        parent_comment.post_id = 1
        parent_comment.author_id = 1
        parent_comment.content = "Parent"
        parent_comment.parent_id = None
        parent_comment.like_count = 0
        parent_comment.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        parent_comment.updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=parent_comment)
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        mock_db_session.add = MagicMock()
        mock_db_session.commit = AsyncMock()
        mock_db_session.refresh = AsyncMock()

        await service.create_comment(1, comment_data)

        added_comment = mock_db_session.add.call_args[0][0]
        assert added_comment.parent_id == 5

    @pytest.mark.asyncio
    async def test_create_comment_with_invalid_parent_raises(self, mock_db_session):
        """Should raise ValueError when parent_id doesn't exist."""
        service = CommentService(mock_db_session)
        comment_data = CommentCreate(
            post_id=1,
            content="Test reply",
            parent_id=999,
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValueError, match="Parent comment not found"):
            await service.create_comment(1, comment_data)

    @pytest.mark.asyncio
    async def test_create_comment_initializes_like_count_to_zero(self, mock_db_session):
        """Should initialize like_count to 0."""
        service = CommentService(mock_db_session)
        comment_data = CommentCreate(
            post_id=1,
            content="Test comment",
        )

        mock_db_session.add = MagicMock()
        mock_db_session.commit = AsyncMock()
        mock_db_session.refresh = AsyncMock()

        await service.create_comment(1, comment_data)

        added_comment = mock_db_session.add.call_args[0][0]
        assert added_comment.like_count == 0


class TestCommentServiceGetCommentsByPost:
    """Tests for CommentService.get_comments_by_post."""

    @pytest.mark.asyncio
    async def test_get_comments_by_post_success(self, mock_db_session):
        """Should return paginated top-level comments with total count."""
        service = CommentService(mock_db_session)

        mock_result = MagicMock()
        mock_result.scalar = MagicMock(return_value=2)
        mock_scalars = MagicMock()
        mock_scalars.all = MagicMock(return_value=[])
        mock_result.scalars = MagicMock(return_value=mock_scalars)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        comments, total = await service.get_comments_by_post(post_id=1, page=1, limit=10)

        assert total == 2
        assert isinstance(comments, list)

    @pytest.mark.asyncio
    async def test_get_comments_by_post_empty_result(self, mock_db_session):
        """Should return empty list when no comments exist."""
        service = CommentService(mock_db_session)

        mock_result = MagicMock()
        mock_result.scalar = MagicMock(return_value=0)
        mock_scalars = MagicMock()
        mock_scalars.all = MagicMock(return_value=[])
        mock_result.scalars = MagicMock(return_value=mock_scalars)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        comments, total = await service.get_comments_by_post(post_id=1)

        assert comments == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_get_comments_by_post_pagination(self, mock_db_session):
        """Should apply pagination correctly."""
        service = CommentService(mock_db_session)

        mock_result = MagicMock()
        mock_result.scalar = MagicMock(return_value=50)
        mock_scalars = MagicMock()
        mock_scalars.all = MagicMock(return_value=[])
        mock_result.scalars = MagicMock(return_value=mock_scalars)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        comments, total = await service.get_comments_by_post(post_id=1, page=2, limit=10)

        assert total == 50


class TestCommentServiceGetCommentById:
    """Tests for CommentService.get_comment_by_id."""

    @pytest.mark.asyncio
    async def test_get_comment_by_id_success(self, mock_db_session, sample_comment):
        """Should return comment when found."""
        service = CommentService(mock_db_session)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=sample_comment)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        result = await service.get_comment_by_id(1)

        assert result is not None
        assert result.id == 1

    @pytest.mark.asyncio
    async def test_get_comment_by_id_not_found(self, mock_db_session):
        """Should return None when comment doesn't exist."""
        service = CommentService(mock_db_session)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        result = await service.get_comment_by_id(999)

        assert result is None


class TestCommentServiceUpdateComment:
    """Tests for CommentService.update_comment."""

    @pytest.mark.asyncio
    async def test_update_comment_success(self, mock_db_session, sample_comment):
        """Should update comment when author matches."""
        service = CommentService(mock_db_session)
        update_data = CommentUpdate(content="Updated content")

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=sample_comment)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        result = await service.update_comment(1, 1, update_data)

        assert result is not None
        assert result.content == "Updated content"

    @pytest.mark.asyncio
    async def test_update_comment_not_found(self, mock_db_session):
        """Should return None when comment doesn't exist."""
        service = CommentService(mock_db_session)
        update_data = CommentUpdate(content="Updated")

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        result = await service.update_comment(999, 1, update_data)

        assert result is None

    @pytest.mark.asyncio
    async def test_update_comment_unauthorized(self, mock_db_session, sample_comment):
        """Should return None when author_id doesn't match."""
        service = CommentService(mock_db_session)
        update_data = CommentUpdate(content="Updated")

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=sample_comment)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        result = await service.update_comment(1, 999, update_data)

        assert result is None


class TestCommentServiceDeleteComment:
    """Tests for CommentService.delete_comment."""

    @pytest.mark.asyncio
    async def test_delete_comment_success(self, mock_db_session, sample_comment):
        """Should delete comment when author matches."""
        service = CommentService(mock_db_session)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=sample_comment)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        result = await service.delete_comment(1, 1)

        assert result is True

    @pytest.mark.asyncio
    async def test_delete_comment_not_found(self, mock_db_session):
        """Should return False when comment doesn't exist."""
        service = CommentService(mock_db_session)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        result = await service.delete_comment(999, 1)

        assert result is False

    @pytest.mark.asyncio
    async def test_delete_comment_unauthorized(self, mock_db_session, sample_comment):
        """Should return False when author_id doesn't match."""
        service = CommentService(mock_db_session)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=sample_comment)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        result = await service.delete_comment(1, 999)

        assert result is False


class TestCommentServiceLikeComment:
    """Tests for CommentService.like_comment."""

    @pytest.mark.asyncio
    async def test_like_comment_success(self, mock_db_session, sample_comment):
        """Should increment like count."""
        service = CommentService(mock_db_session)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=sample_comment)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        result = await service.like_comment(1)

        assert result is not None
        assert result.like_count == 1

    @pytest.mark.asyncio
    async def test_like_comment_not_found(self, mock_db_session):
        """Should return None when comment doesn't exist."""
        service = CommentService(mock_db_session)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        result = await service.like_comment(999)

        assert result is None

    @pytest.mark.asyncio
    async def test_like_comment_accumulates(self, mock_db_session):
        """Should accumulate likes across multiple calls."""
        service = CommentService(mock_db_session)
        comment = Comment()
        comment.id = 1
        comment.post_id = 1
        comment.author_id = 1
        comment.content = "Test"
        comment.parent_id = None
        comment.like_count = 10
        comment.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        comment.updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=comment)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        result = await service.like_comment(1)

        assert result.like_count == 11
