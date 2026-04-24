"""Extended tests for Comment API endpoints - edge cases and additional coverage."""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock


class TestCreateCommentEdgeCases:
    """Edge case tests for POST /api/v1/comments."""

    def test_create_comment_with_content_at_max_length(self, client, mock_db_session):
        """Should accept content at exactly 5000 characters."""
        comment = MagicMock()
        comment.id = 1
        comment.post_id = 1
        comment.author_id = 1
        comment.content = "A" * 5000
        comment.parent_id = None
        comment.like_count = 0
        comment.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        comment.updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        comment.replies = []

        async def mock_refresh(obj):
            pass

        mock_db_session.add = MagicMock()
        mock_db_session.commit = AsyncMock()
        mock_db_session.refresh = mock_refresh

        response = client.post(
            "/api/v1/comments",
            json={
                "post_id": 1,
                "content": "A" * 5000,
            },
        )

        assert response.status_code == 201

    def test_create_comment_with_content_over_max_length_returns_422(self, client):
        """Should return 422 when content exceeds 5000 characters."""
        response = client.post(
            "/api/v1/comments",
            json={
                "post_id": 1,
                "content": "A" * 5001,
            },
        )

        assert response.status_code == 422

    def test_create_comment_with_negative_post_id_returns_422(self, client):
        """Should return 422 when post_id is negative."""
        response = client.post(
            "/api/v1/comments",
            json={
                "post_id": -1,
                "content": "Test",
            },
        )

        assert response.status_code == 422

    def test_create_comment_with_zero_post_id_returns_422(self, client):
        """Should return 422 when post_id is zero."""
        response = client.post(
            "/api/v1/comments",
            json={
                "post_id": 0,
                "content": "Test",
            },
        )

        assert response.status_code == 422

    def test_create_comment_with_negative_parent_id_returns_422(self, client):
        """Should return 422 when parent_id is negative."""
        response = client.post(
            "/api/v1/comments",
            json={
                "post_id": 1,
                "content": "Test",
                "parent_id": -1,
            },
        )

        assert response.status_code == 422

    def test_create_comment_with_zero_parent_id_returns_422(self, client):
        """Should return 422 when parent_id is zero."""
        response = client.post(
            "/api/v1/comments",
            json={
                "post_id": 1,
                "content": "Test",
                "parent_id": 0,
            },
        )

        assert response.status_code == 422

    def test_create_comment_missing_post_id_returns_422(self, client):
        """Should return 422 when post_id is missing."""
        response = client.post(
            "/api/v1/comments",
            json={"content": "Test"},
        )

        assert response.status_code == 422


class TestListCommentsEdgeCases:
    """Edge case tests for GET /api/v1/comments."""

    def test_list_comments_with_max_limit(self, client, mock_db_session):
        """Should accept limit at maximum value of 100."""
        mock_result = MagicMock()
        mock_result.scalar = MagicMock(return_value=0)
        mock_scalars = MagicMock()
        mock_scalars.all = MagicMock(return_value=[])
        mock_result.scalars = MagicMock(return_value=mock_scalars)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        response = client.get("/api/v1/comments?post_id=1&limit=100")

        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 100

    def test_list_comments_has_next_calculation(self, client, mock_db_session, sample_comment):
        """Should correctly calculate has_next when more items exist."""
        sample_comment.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        sample_comment.updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        state = vars(sample_comment)["_sa_instance_state"]; state.dict["replies"] = []

        mock_result = MagicMock()
        mock_result.scalar = MagicMock(return_value=50)
        mock_scalars = MagicMock()
        mock_scalars.all = MagicMock(return_value=[sample_comment])
        mock_result.scalars = MagicMock(return_value=mock_scalars)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        response = client.get("/api/v1/comments?post_id=1&page=1&limit=10")

        assert response.status_code == 200
        data = response.json()
        assert data["has_next"] is True
        assert data["has_prev"] is False

    def test_list_comments_has_prev_calculation(self, client, mock_db_session):
        """Should correctly calculate has_prev on page 2."""
        mock_result = MagicMock()
        mock_result.scalar = MagicMock(return_value=0)
        mock_scalars = MagicMock()
        mock_scalars.all = MagicMock(return_value=[])
        mock_result.scalars = MagicMock(return_value=mock_scalars)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        response = client.get("/api/v1/comments?post_id=1&page=2&limit=10")

        assert response.status_code == 200
        data = response.json()
        assert data["has_prev"] is True

    def test_list_comments_with_invalid_page_returns_422(self, client):
        """Should return 422 for invalid page number."""
        response = client.get("/api/v1/comments?post_id=1&page=0")

        assert response.status_code == 422

    def test_list_comments_with_invalid_limit_returns_422(self, client):
        """Should return 422 for invalid limit."""
        response = client.get("/api/v1/comments?post_id=1&limit=0")

        assert response.status_code == 422

    def test_list_comments_with_limit_over_100_returns_422(self, client):
        """Should return 422 for limit over 100."""
        response = client.get("/api/v1/comments?post_id=1&limit=101")

        assert response.status_code == 422


class TestGetCommentEdgeCases:
    """Edge case tests for GET /api/v1/comments/{comment_id}."""

    def test_get_comment_with_non_numeric_id_returns_422(self, client):
        """Should return 422 when comment_id is not an integer."""
        response = client.get("/api/v1/comments/abc")

        assert response.status_code == 422

    def test_get_comment_with_negative_id_returns_404(self, client):
        """Should return 404 when comment_id is negative (path param not validated)."""
        response = client.get("/api/v1/comments/-1")

        assert response.status_code == 404


class TestUpdateCommentEdgeCases:
    """Edge case tests for PUT /api/v1/comments/{comment_id}."""

    def test_update_comment_with_empty_content_returns_422(self, client):
        """Should return 422 when content is empty string."""
        response = client.put(
            "/api/v1/comments/1",
            json={"content": ""},
        )

        assert response.status_code == 422

    def test_update_comment_with_content_over_max_length_returns_422(self, client):
        """Should return 422 when content exceeds 5000 characters."""
        response = client.put(
            "/api/v1/comments/1",
            json={"content": "A" * 5001},
        )

        assert response.status_code == 422

    def test_update_comment_with_non_numeric_id_returns_422(self, client):
        """Should return 422 when comment_id is not an integer."""
        response = client.put(
            "/api/v1/comments/abc",
            json={"content": "Updated"},
        )

        assert response.status_code == 422

    def test_update_comment_missing_content_returns_422(self, client):
        """Should return 422 when content field is missing."""
        response = client.put(
            "/api/v1/comments/1",
            json={},
        )

        assert response.status_code == 422


class TestDeleteCommentEdgeCases:
    """Edge case tests for DELETE /api/v1/comments/{comment_id}."""

    def test_delete_comment_with_non_numeric_id_returns_422(self, client):
        """Should return 422 when comment_id is not an integer."""
        response = client.delete("/api/v1/comments/abc")

        assert response.status_code == 422

    def test_delete_comment_response_format(self, client, mock_db_session, sample_comment):
        """Should return correct deletion confirmation format."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=sample_comment)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        response = client.delete("/api/v1/comments/1")

        assert response.status_code == 200
        data = response.json()
        assert data == {"deleted": True}


class TestLikeCommentEdgeCases:
    """Edge case tests for POST /api/v1/comments/{comment_id}/like."""

    def test_like_comment_with_non_numeric_id_returns_422(self, client):
        """Should return 422 when comment_id is not an integer."""
        response = client.post("/api/v1/comments/abc/like")

        assert response.status_code == 422

    def test_like_comment_response_format(self, client, mock_db_session, sample_comment):
        """Should return correct like response format."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=sample_comment)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        response = client.post("/api/v1/comments/1/like")

        assert response.status_code == 200
        data = response.json()
        assert "like_count" in data
        assert isinstance(data["like_count"], int)
