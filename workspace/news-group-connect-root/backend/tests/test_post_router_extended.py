"""Extended tests for Post API endpoints - edge cases and additional coverage."""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient


class TestCreatePostEdgeCases:
    """Edge case tests for POST /api/v1/posts."""

    def test_create_post_with_title_at_max_length(self, client, mock_db_session):
        """Should accept title at exactly 200 characters."""
        async def mock_refresh(obj):
            obj.id = 1
            obj.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
            obj.updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)

        mock_db_session.add = MagicMock()
        mock_db_session.commit = AsyncMock()
        mock_db_session.refresh = mock_refresh

        response = client.post(
            "/api/v1/posts",
            json={
                "title": "A" * 200,
                "content": "Content",
                "category": "news",
            },
        )

        assert response.status_code == 201

    def test_create_post_with_title_over_max_length_returns_422(self, client):
        """Should return 422 when title exceeds 200 characters."""
        response = client.post(
            "/api/v1/posts",
            json={
                "title": "A" * 201,
                "content": "Content",
                "category": "news",
            },
        )

        assert response.status_code == 422

    def test_create_post_with_category_over_max_length_returns_422(self, client):
        """Should return 422 when category exceeds 50 characters."""
        response = client.post(
            "/api/v1/posts",
            json={
                "title": "Title",
                "content": "Content",
                "category": "A" * 51,
            },
        )

        assert response.status_code == 422

    def test_create_post_missing_content_returns_422(self, client):
        """Should return 422 when content is missing."""
        response = client.post(
            "/api/v1/posts",
            json={
                "title": "Title",
                "category": "news",
            },
        )

        assert response.status_code == 422

    def test_create_post_missing_category_returns_422(self, client):
        """Should return 422 when category is missing."""
        response = client.post(
            "/api/v1/posts",
            json={
                "title": "Title",
                "content": "Content",
            },
        )

        assert response.status_code == 422

    def test_create_post_with_negative_group_id_validates(self, client, mock_db_session):
        """Should accept negative group_id (no validation constraint)."""
        async def mock_refresh(obj):
            obj.id = 1
            obj.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
            obj.updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)

        mock_db_session.add = MagicMock()
        mock_db_session.commit = AsyncMock()
        mock_db_session.refresh = mock_refresh

        response = client.post(
            "/api/v1/posts",
            json={
                "title": "Title",
                "content": "Content",
                "category": "news",
                "group_id": -1,
            },
        )

        assert response.status_code == 201


class TestListPostsEdgeCases:
    """Edge case tests for GET /api/v1/posts."""

    def test_list_posts_with_group_id_filter(self, client, mock_db_session):
        """Should filter posts by group_id."""
        mock_result = MagicMock()
        mock_result.scalar = MagicMock(return_value=0)
        mock_scalars = MagicMock()
        mock_scalars.all = MagicMock(return_value=[])
        mock_result.scalars = MagicMock(return_value=mock_scalars)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        response = client.get("/api/v1/posts?group_id=5")

        assert response.status_code == 200

    def test_list_posts_with_author_id_filter(self, client, mock_db_session):
        """Should filter posts by author_id."""
        mock_result = MagicMock()
        mock_result.scalar = MagicMock(return_value=0)
        mock_scalars = MagicMock()
        mock_scalars.all = MagicMock(return_value=[])
        mock_result.scalars = MagicMock(return_value=mock_scalars)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        response = client.get("/api/v1/posts?author_id=3")

        assert response.status_code == 200

    def test_list_posts_with_multiple_filters(self, client, mock_db_session):
        """Should apply multiple filters simultaneously."""
        mock_result = MagicMock()
        mock_result.scalar = MagicMock(return_value=0)
        mock_scalars = MagicMock()
        mock_scalars.all = MagicMock(return_value=[])
        mock_result.scalars = MagicMock(return_value=mock_scalars)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        response = client.get("/api/v1/posts?category=tech&group_id=5&author_id=3")

        assert response.status_code == 200

    def test_list_posts_with_max_limit(self, client, mock_db_session):
        """Should accept limit at maximum value of 100."""
        mock_result = MagicMock()
        mock_result.scalar = MagicMock(return_value=0)
        mock_scalars = MagicMock()
        mock_scalars.all = MagicMock(return_value=[])
        mock_result.scalars = MagicMock(return_value=mock_scalars)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        response = client.get("/api/v1/posts?limit=100")

        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 100

    def test_list_posts_has_next_calculation(self, client, mock_db_session, sample_post):
        """Should correctly calculate has_next when more items exist."""
        sample_post.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        sample_post.updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)

        mock_result = MagicMock()
        mock_result.scalar = MagicMock(return_value=50)
        mock_scalars = MagicMock()
        mock_scalars.all = MagicMock(return_value=[sample_post])
        mock_result.scalars = MagicMock(return_value=mock_scalars)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        response = client.get("/api/v1/posts?page=1&limit=10")

        assert response.status_code == 200
        data = response.json()
        assert data["has_next"] is True
        assert data["has_prev"] is False

    def test_list_posts_has_prev_calculation(self, client, mock_db_session):
        """Should correctly calculate has_prev on page 2."""
        mock_result = MagicMock()
        mock_result.scalar = MagicMock(return_value=0)
        mock_scalars = MagicMock()
        mock_scalars.all = MagicMock(return_value=[])
        mock_result.scalars = MagicMock(return_value=mock_scalars)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        response = client.get("/api/v1/posts?page=2&limit=10")

        assert response.status_code == 200
        data = response.json()
        assert data["has_prev"] is True


class TestGetPostEdgeCases:
    """Edge case tests for GET /api/v1/posts/{post_id}."""

    def test_get_post_with_non_numeric_id_returns_422(self, client):
        """Should return 422 when post_id is not an integer."""
        response = client.get("/api/v1/posts/abc")

        assert response.status_code == 422

    def test_get_post_with_negative_id_returns_404(self, client, mock_db_session):
        """Should return 404 when post_id is negative (valid int, not found)."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        response = client.get("/api/v1/posts/-1")

        assert response.status_code == 404


class TestUpdatePostEdgeCases:
    """Edge case tests for PUT /api/v1/posts/{post_id}."""

    def test_update_post_with_empty_title_returns_422(self, client):
        """Should return 422 when title is empty string."""
        response = client.put(
            "/api/v1/posts/1",
            json={"title": ""},
        )

        assert response.status_code == 422

    def test_update_post_with_empty_content_returns_422(self, client):
        """Should return 422 when content is empty string."""
        response = client.put(
            "/api/v1/posts/1",
            json={"content": ""},
        )

        assert response.status_code == 422

    def test_update_post_with_title_over_max_length_returns_422(self, client):
        """Should return 422 when title exceeds 200 characters."""
        response = client.put(
            "/api/v1/posts/1",
            json={"title": "A" * 201},
        )

        assert response.status_code == 422

    def test_update_post_with_category_over_max_length_returns_422(self, client):
        """Should return 422 when category exceeds 50 characters."""
        response = client.put(
            "/api/v1/posts/1",
            json={"category": "A" * 51},
        )

        assert response.status_code == 422

    def test_update_post_partial_update_only_title(self, client, mock_db_session, sample_post):
        """Should allow partial update with only title."""
        sample_post.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        sample_post.updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=sample_post)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        response = client.put(
            "/api/v1/posts/1",
            json={"title": "New Title"},
        )

        assert response.status_code == 200

    def test_update_post_partial_update_only_category(self, client, mock_db_session, sample_post):
        """Should allow partial update with only category."""
        sample_post.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        sample_post.updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=sample_post)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        response = client.put(
            "/api/v1/posts/1",
            json={"category": "tech"},
        )

        assert response.status_code == 200

    def test_update_post_with_non_numeric_id_returns_422(self, client):
        """Should return 422 when post_id is not an integer."""
        response = client.put(
            "/api/v1/posts/abc",
            json={"title": "Updated"},
        )

        assert response.status_code == 422


class TestDeletePostEdgeCases:
    """Edge case tests for DELETE /api/v1/posts/{post_id}."""

    def test_delete_post_with_non_numeric_id_returns_422(self, client):
        """Should return 422 when post_id is not an integer."""
        response = client.delete("/api/v1/posts/abc")

        assert response.status_code == 422

    def test_delete_post_response_format(self, client, mock_db_session, sample_post):
        """Should return correct deletion confirmation format."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=sample_post)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        response = client.delete("/api/v1/posts/1")

        assert response.status_code == 200
        data = response.json()
        assert data == {"deleted": True}


class TestLikePostEdgeCases:
    """Edge case tests for POST /api/v1/posts/{post_id}/like."""

    def test_like_post_with_non_numeric_id_returns_422(self, client):
        """Should return 422 when post_id is not an integer."""
        response = client.post("/api/v1/posts/abc/like")

        assert response.status_code == 422

    def test_like_post_response_format(self, client, mock_db_session, sample_post):
        """Should return correct like response format."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=sample_post)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        response = client.post("/api/v1/posts/1/like")

        assert response.status_code == 200
        data = response.json()
        assert "like_count" in data
        assert isinstance(data["like_count"], int)
