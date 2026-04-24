"""Tests for Pydantic schemas."""

import pytest
from pydantic import ValidationError

from app.posts.schemas import PostCreate, PostUpdate, PostResponse, PostListResponse, LikeResponse
from app.comments.schemas import (
    CommentCreate,
    CommentUpdate,
    CommentResponse,
    CommentListResponse,
    CommentReplyResponse,
    LikeResponse as CommentLikeResponse,
)


class TestPostCreateSchema:
    """Tests for PostCreate schema."""

    def test_post_create_valid_data(self):
        """Should accept valid post data."""
        data = PostCreate(
            title="Test Post",
            content="Test content",
            category="news",
        )
        assert data.title == "Test Post"
        assert data.content == "Test content"
        assert data.category == "news"
        assert data.group_id is None
        assert data.image_url is None

    def test_post_create_with_optional_fields(self):
        """Should accept optional group_id and image_url."""
        data = PostCreate(
            title="Test",
            content="Content",
            category="tech",
            group_id=5,
            image_url="https://example.com/img.jpg",
        )
        assert data.group_id == 5
        assert data.image_url == "https://example.com/img.jpg"

    def test_post_create_empty_title_raises(self):
        """Should reject empty title."""
        with pytest.raises(ValidationError):
            PostCreate(title="", content="Content", category="news")

    def test_post_create_empty_content_raises(self):
        """Should reject empty content."""
        with pytest.raises(ValidationError):
            PostCreate(title="Title", content="", category="news")

    def test_post_create_empty_category_raises(self):
        """Should reject empty category."""
        with pytest.raises(ValidationError):
            PostCreate(title="Title", content="Content", category="")

    def test_post_create_title_too_long_raises(self):
        """Should reject title over 200 characters."""
        with pytest.raises(ValidationError):
            PostCreate(title="A" * 201, content="Content", category="news")

    def test_post_create_category_too_long_raises(self):
        """Should reject category over 50 characters."""
        with pytest.raises(ValidationError):
            PostCreate(title="Title", content="Content", category="A" * 51)

    def test_post_create_missing_required_field_raises(self):
        """Should reject missing required fields."""
        with pytest.raises(ValidationError):
            PostCreate(title="Title")


class TestPostUpdateSchema:
    """Tests for PostUpdate schema."""

    def test_post_update_all_fields(self):
        """Should accept all fields."""
        data = PostUpdate(
            title="Updated",
            content="Updated content",
            category="tech",
            image_url="https://example.com/img.jpg",
        )
        assert data.title == "Updated"

    def test_post_update_partial_fields(self):
        """Should accept partial updates."""
        data = PostUpdate(title="Updated")
        assert data.title == "Updated"
        assert data.content is None

    def test_post_update_empty_title_raises(self):
        """Should reject empty title."""
        with pytest.raises(ValidationError):
            PostUpdate(title="")

    def test_post_update_empty_content_raises(self):
        """Should reject empty content."""
        with pytest.raises(ValidationError):
            PostUpdate(content="")


class TestPostResponseSchema:
    """Tests for PostResponse schema."""

    def test_post_response_from_orm(self, sample_post):
        """Should create response from ORM model."""
        response = PostResponse.model_validate(sample_post)
        assert response.id == 1
        assert response.title == "Test Post"
        assert response.content == "This is test content"
        assert response.author_id == 1
        assert response.category == "news"
        assert response.view_count == 0
        assert response.like_count == 0

    def test_post_response_defaults(self):
        """Should have correct defaults."""
        from datetime import datetime, timezone

        data = PostResponse(
            id=1,
            title="Test",
            content="Content",
            author_id=1,
            category="news",
            created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        assert data.view_count == 0
        assert data.like_count == 0
        assert data.group_id is None
        assert data.image_url is None


class TestPostListResponseSchema:
    """Tests for PostListResponse schema."""

    def test_post_list_response(self):
        """Should create paginated response."""
        from datetime import datetime, timezone

        ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        data = PostListResponse(
            posts=[],
            total=0,
            page=1,
            limit=20,
            has_next=False,
            has_prev=False,
        )
        assert data.posts == []
        assert data.total == 0

    def test_post_list_response_with_posts(self, sample_post):
        """Should create response with posts."""
        response = PostResponse.model_validate(sample_post)
        data = PostListResponse(
            posts=[response],
            total=1,
            page=1,
            limit=20,
            has_next=False,
            has_prev=False,
        )
        assert len(data.posts) == 1


class TestPostLikeResponseSchema:
    """Tests for LikeResponse schema."""

    def test_like_response(self):
        """Should create like response."""
        data = LikeResponse(like_count=5)
        assert data.like_count == 5


class TestCommentCreateSchema:
    """Tests for CommentCreate schema."""

    def test_comment_create_valid_data(self):
        """Should accept valid comment data."""
        data = CommentCreate(post_id=1, content="Test comment")
        assert data.post_id == 1
        assert data.content == "Test comment"
        assert data.parent_id is None

    def test_comment_create_with_parent(self):
        """Should accept parent_id for replies."""
        data = CommentCreate(post_id=1, content="Reply", parent_id=5)
        assert data.parent_id == 5

    def test_comment_create_empty_content_raises(self):
        """Should reject empty content."""
        with pytest.raises(ValidationError):
            CommentCreate(post_id=1, content="")

    def test_comment_create_invalid_post_id_raises(self):
        """Should reject non-positive post_id."""
        with pytest.raises(ValidationError):
            CommentCreate(post_id=0, content="Test")

    def test_comment_create_invalid_parent_id_raises(self):
        """Should reject non-positive parent_id."""
        with pytest.raises(ValidationError):
            CommentCreate(post_id=1, content="Test", parent_id=0)

    def test_comment_create_content_too_long_raises(self):
        """Should reject content over 5000 characters."""
        with pytest.raises(ValidationError):
            CommentCreate(post_id=1, content="A" * 5001)


class TestCommentUpdateSchema:
    """Tests for CommentUpdate schema."""

    def test_comment_update_valid(self):
        """Should accept valid update data."""
        data = CommentUpdate(content="Updated content")
        assert data.content == "Updated content"

    def test_comment_update_empty_content_raises(self):
        """Should reject empty content."""
        with pytest.raises(ValidationError):
            CommentUpdate(content="")

    def test_comment_update_content_too_long_raises(self):
        """Should reject content over 5000 characters."""
        with pytest.raises(ValidationError):
            CommentUpdate(content="A" * 5001)


class TestCommentResponseSchema:
    """Tests for CommentResponse schema."""

    def test_comment_response_from_orm(self, sample_comment):
        """Should create response from ORM model."""
        response = CommentResponse.model_validate(sample_comment)
        assert response.id == 1
        assert response.post_id == 1
        assert response.author_id == 1
        assert response.content == "This is a test comment"
        assert response.parent_id is None
        assert response.like_count == 0

    def test_comment_response_with_replies(self, sample_comment, sample_reply):
        """Should include nested replies."""
        state = vars(sample_comment)["_sa_instance_state"]
        state.dict["replies"] = [sample_reply]
        reply_response = CommentReplyResponse.model_validate(sample_reply)
        response = CommentResponse.model_validate(sample_comment)
        assert len(response.replies) == 1


class TestCommentListResponseSchema:
    """Tests for CommentListResponse schema."""

    def test_comment_list_response(self):
        """Should create paginated comment response."""
        data = CommentListResponse(
            comments=[],
            total=0,
            page=1,
            limit=20,
            has_next=False,
            has_prev=False,
        )
        assert data.comments == []


class TestCommentLikeResponseSchema:
    """Tests for CommentLikeResponse schema."""

    def test_comment_like_response(self):
        """Should create like response."""
        data = CommentLikeResponse(like_count=3)
        assert data.like_count == 3
