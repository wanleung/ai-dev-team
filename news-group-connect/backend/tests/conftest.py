"""Shared pytest fixtures for NewsGroup Connect tests."""

import asyncio
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def mock_db_session():
    """Create a mock async database session."""
    session = AsyncMock(spec=AsyncSession)
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.delete = AsyncMock()
    session.refresh = AsyncMock()

    # Configure execute to return a proper mock result
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=None)
    mock_result.scalar = MagicMock(return_value=0)
    mock_scalars = MagicMock()
    mock_scalars.all = MagicMock(return_value=[])
    mock_result.scalars = MagicMock(return_value=mock_scalars)
    session.execute = AsyncMock(return_value=mock_result)

    session.get = AsyncMock()
    return session


@pytest.fixture
def mock_execute_result(mock_scalar_result):
    """Fixture to configure mock_db_session.execute to return mock_scalar_result."""
    return mock_scalar_result


@pytest.fixture
def sample_user():
    """Create a sample User ORM object."""
    from models.user import User

    user = User()
    user.id = 1
    user.email = "test@example.com"
    user.username = "testuser"
    user.password_hash = "hashed_password_123"
    user.full_name = "Test User"
    user.avatar_url = None
    user.is_verified = True
    user.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    user.updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return user


@pytest.fixture
def sample_post(sample_user):
    """Create a sample Post ORM object."""
    from models.post import Post

    post = Post()
    post.id = 1
    post.title = "Test Post"
    post.content = "This is test content"
    post.author_id = 1
    post.group_id = None
    post.category = "news"
    post.image_url = None
    post.view_count = 0
    post.like_count = 0
    post.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    post.updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    post.author = sample_user
    return post


@pytest.fixture
def sample_comment(sample_user, sample_post):
    """Create a sample Comment ORM object."""
    from models.comment import Comment

    comment = Comment()
    comment.id = 1
    comment.post_id = 1
    comment.author_id = 1
    comment.content = "This is a test comment"
    comment.parent_id = None
    comment.like_count = 0
    comment.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    comment.updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    comment.author = sample_user
    comment.post = sample_post
    # Set replies directly in the internal dict to avoid SQLAlchemy relationship events
    state = vars(comment)["_sa_instance_state"]
    state.dict["replies"] = []
    return comment


@pytest.fixture
def sample_reply(sample_user, sample_post, sample_comment):
    """Create a sample reply Comment ORM object."""
    from models.comment import Comment

    reply = Comment()
    reply.id = 2
    reply.post_id = 1
    reply.author_id = 1
    reply.content = "This is a test reply"
    reply.parent_id = 1
    reply.like_count = 0
    reply.created_at = datetime(2024, 1, 2, tzinfo=timezone.utc)
    reply.updated_at = datetime(2024, 1, 2, tzinfo=timezone.utc)
    reply.author = sample_user
    reply.post = sample_post
    return reply


@pytest.fixture
def sample_group(sample_user):
    """Create a sample Group ORM object."""
    from models.group import Group

    group = Group()
    group.id = 1
    group.name = "Test Group"
    group.description = "A test group"
    group.owner_id = 1
    group.is_public = True
    group.member_count = 1
    group.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    group.updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    group.owner = sample_user
    return group


@pytest.fixture
def sample_notification(sample_user):
    """Create a sample Notification ORM object."""
    from models.notification import Notification

    notification = Notification()
    notification.id = 1
    notification.user_id = 1
    notification.type = "post_like"
    notification.title = "New Like"
    notification.message = "Someone liked your post"
    notification.is_read = False
    notification.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    notification.updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    notification.user = sample_user
    return notification


@pytest.fixture
def sample_membership(sample_user, sample_group):
    """Create a sample GroupMembership ORM object."""
    from models.membership import GroupMembership

    membership = GroupMembership()
    membership.id = 1
    membership.group_id = 1
    membership.user_id = 1
    membership.role = "admin"
    membership.is_active = True
    membership.joined_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    membership.group = sample_group
    membership.user = sample_user
    return membership


@pytest.fixture
def mock_scalar_result(sample_post):
    """Create a mock scalar result for database queries."""
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=sample_post)
    result.scalar = MagicMock(return_value=1)
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[sample_post])))
    return result


@pytest.fixture
def mock_empty_scalar_result():
    """Create a mock scalar result returning None."""
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=None)
    result.scalar = MagicMock(return_value=0)
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    return result


@pytest.fixture
def app():
    """Create FastAPI app for testing with SQLite and no lifespan DB init."""
    from fastapi import FastAPI
    from app.comments.router import router as comments_router
    from app.posts.router import router as posts_router

    @asynccontextmanager
    async def test_lifespan(app: FastAPI):
        yield

    test_app = FastAPI(
        title="NewsGroup Connect",
        version="0.1.0",
        lifespan=test_lifespan,
    )
    test_app.include_router(posts_router)
    test_app.include_router(comments_router)

    return test_app


@pytest.fixture
def client(app, mock_db_session):
    """Create test client with mocked database."""
    from app.database import get_db_session

    async def override_get_db():
        yield mock_db_session

    app.dependency_overrides[get_db_session] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
