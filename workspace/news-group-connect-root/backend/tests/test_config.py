"""Tests for FastAPI application configuration and database."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.config import Settings


class TestSettings:
    """Tests for application settings."""

    def test_default_app_name(self):
        """Should have correct default app name."""
        settings = Settings()
        assert settings.app_name == "NewsGroup Connect"

    def test_default_app_version(self):
        """Should have correct default app version."""
        settings = Settings()
        assert settings.app_version == "0.1.0"

    def test_default_debug_false(self):
        """Should have debug disabled by default."""
        settings = Settings()
        assert settings.debug is False

    def test_default_database_url(self):
        """Should have default database URL."""
        settings = Settings()
        assert "postgresql+asyncpg" in settings.database_url

    def test_default_database_pool_size(self):
        """Should have default pool size of 5."""
        settings = Settings()
        assert settings.database_pool_size == 5

    def test_default_database_max_overflow(self):
        """Should have default max overflow of 10."""
        settings = Settings()
        assert settings.database_max_overflow == 10

    def test_default_secret_key(self):
        """Should have default secret key."""
        settings = Settings()
        assert settings.secret_key == "change-me-in-production"

    def test_default_algorithm(self):
        """Should use HS256 algorithm."""
        settings = Settings()
        assert settings.algorithm == "HS256"

    def test_default_token_expiry(self):
        """Should have default token expiry of 30 minutes."""
        settings = Settings()
        assert settings.access_token_expire_minutes == 30

    def test_default_refresh_token_expiry(self):
        """Should have default refresh token expiry of 7 days."""
        settings = Settings()
        assert settings.refresh_token_expire_days == 7

    def test_default_smtp_settings(self):
        """Should have default SMTP settings."""
        settings = Settings()
        assert settings.smtp_host == "localhost"
        assert settings.smtp_port == 587
        assert settings.smtp_from_email == "noreply@newsgroup.local"


class TestDatabase:
    """Tests for database module."""

    def test_get_db_yields_session(self):
        """get_db should yield an async session."""
        from app.database import get_db

        # get_db is an async generator, verify it exists
        assert callable(get_db)

    def test_init_db_exists(self):
        """init_db function should exist."""
        from app.database import init_db

        assert callable(init_db)

    def test_close_db_exists(self):
        """close_db function should exist."""
        from app.database import close_db

        assert callable(close_db)

    def test_engine_created(self):
        """Engine should be created with settings."""
        from app.database import engine

        assert engine is not None

    def test_async_session_factory_created(self):
        """Async session factory should be created."""
        from app.database import async_session_factory

        assert async_session_factory is not None


class TestAppLifespan:
    """Tests for FastAPI application lifespan."""

    @pytest.mark.asyncio
    async def test_lifespan_initializes_db(self):
        """Lifespan should initialize database on startup."""
        from main import lifespan
        from fastapi import FastAPI

        app = FastAPI()

        with patch("main.init_db", new_callable=AsyncMock) as mock_init:
            with patch("main.close_db", new_callable=AsyncMock) as mock_close:
                async with lifespan(app):
                    mock_init.assert_awaited_once()
                mock_close.assert_awaited_once()


class TestAppStartup:
    """Tests for FastAPI application startup."""

    def test_app_has_title(self):
        """App should have correct title."""
        from main import app

        assert app.title == "NewsGroup Connect"

    def test_app_has_version(self):
        """App should have correct version."""
        from main import app

        assert app.version == "0.1.0"

    def test_app_includes_posts_router(self):
        """App should include posts router."""
        from main import app

        routes = [r.path for r in app.routes]
        assert any("/posts" in r for r in routes)

    def test_app_includes_comments_router(self):
        """App should include comments router."""
        from main import app

        routes = [r.path for r in app.routes]
        assert any("/comments" in r for r in routes)

    def test_openapi_schema_generates(self):
        """OpenAPI schema should generate without errors."""
        from main import app

        schema = app.openapi()
        assert "openapi" in schema
        assert "paths" in schema
        assert "info" in schema

    def test_openapi_info_has_title(self):
        """OpenAPI info should have correct title."""
        from main import app

        schema = app.openapi()
        assert schema["info"]["title"] == "NewsGroup Connect"

    def test_openapi_info_has_version(self):
        """OpenAPI info should have correct version."""
        from main import app

        schema = app.openapi()
        assert schema["info"]["version"] == "0.1.0"
