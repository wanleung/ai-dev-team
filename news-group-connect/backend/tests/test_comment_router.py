"""Tests for Comment API endpoints."""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient


class TestCreateCommentEndpoint:
    """Tests for POST /api/v1/comments."""

    def _make_mock_comment(self):
        """Create a mock comment that works with the router's _build_comment_response."""
        comment = MagicMock()
        comment.id = 1
        comment.post_id = 1
        comment.author_id = 1
        comment.content = "This is a test comment"
        comment.parent_id = None
        comment.like_count = 0
        comment.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        comment.updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        comment.replies = []
        return comment

    def test_create_comment_success(self, client, mock_db_session):
        """Should create a new comment and return 201."""
        created_comment = self._make_mock_comment()

        async def mock_refresh(obj):
            pass

        mock_db_session.add = MagicMock()
        mock_db_session.commit = AsyncMock()
        mock_db_session.refresh = mock_refresh

        response = client.post(
            "/api/v1/comments",
            json={
                "post_id": 1,
                "content": "Test comment",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["content"] == "This is a test comment"

    def test_create_comment_with_parent(self, client, mock_db_session):
        """Should create a reply when parent_id is valid."""
        parent_comment = MagicMock()
        parent_comment.id = 1
        parent_comment.post_id = 1
        parent_comment.author_id = 1
        parent_comment.content = "Parent"
        parent_comment.parent_id = None
        parent_comment.like_count = 0
        parent_comment.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        parent_comment.updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)

        created_comment = self._make_mock_comment()
        created_comment.parent_id = 1

        mock_parent_result = MagicMock()
        mock_parent_result.scalar_one_or_none = MagicMock(return_value=parent_comment)

        async def mock_execute(*args, **kwargs):
            return mock_parent_result

        async def mock_refresh(obj):
            pass

        mock_db_session.add = MagicMock()
        mock_db_session.commit = AsyncMock()
        mock_db_session.refresh = mock_refresh
        mock_db_session.execute = mock_execute

        response = client.post(
            "/api/v1/comments",
            json={
                "post_id": 1,
                "content": "Test reply",
                "parent_id": 1,
            },
        )

        assert response.status_code == 201

    def test_create_comment_with_invalid_parent_returns_404(self, client, mock_db_session):
        """Should return 404 when parent_id doesn't exist."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        response = client.post(
            "/api/v1/comments",
            json={
                "post_id": 1,
                "content": "Test reply",
                "parent_id": 999,
            },
        )

        assert response.status_code == 404

    def test_create_comment_with_invalid_data_returns_422(self, client):
        """Should return 422 when required fields are missing."""
        response = client.post(
            "/api/v1/comments",
            json={"content": "Test"},
        )

        assert response.status_code == 422

    def test_create_comment_with_empty_content_returns_422(self, client):
        """Should return 422 when content is empty."""
        response = client.post(
            "/api/v1/comments",
            json={
                "post_id": 1,
                "content": "",
            },
        )

        assert response.status_code == 422


class TestListCommentsEndpoint:
    """Tests for GET /api/v1/comments."""

    def test_list_comments_success(self, client, mock_db_session, sample_comment):
        """Should return paginated list of comments for a post."""
        sample_comment.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        sample_comment.updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)

        mock_result = MagicMock()
        mock_result.scalar = MagicMock(return_value=1)
        mock_scalars = MagicMock()
        mock_scalars.all = MagicMock(return_value=[sample_comment])
        mock_result.scalars = MagicMock(return_value=mock_scalars)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        response = client.get("/api/v1/comments?post_id=1")

        assert response.status_code == 200
        data = response.json()
        assert "comments" in data
        assert "total" in data
        assert "page" in data
        assert "limit" in data

    def test_list_comments_with_pagination(self, client, mock_db_session):
        """Should respect pagination parameters."""
        mock_result = MagicMock()
        mock_result.scalar = MagicMock(return_value=0)
        mock_scalars = MagicMock()
        mock_scalars.all = MagicMock(return_value=[])
        mock_result.scalars = MagicMock(return_value=mock_scalars)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        response = client.get("/api/v1/comments?post_id=1&page=2&limit=10")

        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 2
        assert data["limit"] == 10

    def test_list_comments_without_post_id_returns_422(self, client):
        """Should return 422 when post_id is missing."""
        response = client.get("/api/v1/comments")

        assert response.status_code == 422

    def test_list_comments_with_invalid_post_id_returns_422(self, client):
        """Should return 422 when post_id is not positive."""
        response = client.get("/api/v1/comments?post_id=0")

        assert response.status_code == 422


class TestGetCommentEndpoint:
    """Tests for GET /api/v1/comments/{comment_id}."""

    def test_get_comment_success(self, client, mock_db_session, sample_comment):
        """Should return comment by ID."""
        sample_comment.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        sample_comment.updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=sample_comment)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        response = client.get("/api/v1/comments/1")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == 1

    def test_get_comment_not_found_returns_404(self, client, mock_db_session):
        """Should return 404 when comment doesn't exist."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        response = client.get("/api/v1/comments/999")

        assert response.status_code == 404


class TestUpdateCommentEndpoint:
    """Tests for PUT /api/v1/comments/{comment_id}."""

    def test_update_comment_success(self, client, mock_db_session, sample_comment):
        """Should update comment when author matches."""
        sample_comment.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        sample_comment.updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=sample_comment)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        response = client.put(
            "/api/v1/comments/1",
            json={"content": "Updated content"},
        )

        assert response.status_code == 200

    def test_update_comment_not_found_returns_404(self, client, mock_db_session):
        """Should return 404 when comment doesn't exist."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        response = client.put(
            "/api/v1/comments/999",
            json={"content": "Updated"},
        )

        assert response.status_code == 404


class TestDeleteCommentEndpoint:
    """Tests for DELETE /api/v1/comments/{comment_id}."""

    def test_delete_comment_success(self, client, mock_db_session, sample_comment):
        """Should delete comment when author matches."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=sample_comment)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        response = client.delete("/api/v1/comments/1")

        assert response.status_code == 200
        data = response.json()
        assert data["deleted"] is True

    def test_delete_comment_not_found_returns_404(self, client, mock_db_session):
        """Should return 404 when comment doesn't exist."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        response = client.delete("/api/v1/comments/999")

        assert response.status_code == 404


class TestLikeCommentEndpoint:
    """Tests for POST /api/v1/comments/{comment_id}/like."""

    def test_like_comment_success(self, client, mock_db_session, sample_comment):
        """Should increment like count."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=sample_comment)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        response = client.post("/api/v1/comments/1/like")

        assert response.status_code == 200
        data = response.json()
        assert "like_count" in data

    def test_like_comment_not_found_returns_404(self, client, mock_db_session):
        """Should return 404 when comment doesn't exist."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        response = client.post("/api/v1/comments/999/like")

        assert response.status_code == 404
