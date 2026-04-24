"""Extended tests for database module and configuration."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock


class TestDatabaseGetDb:
    """Tests for get_db session management."""

    @pytest.mark.asyncio
    async def test_get_db_yields_session_and_commits(self):
        """get_db should yield session and commit on success."""
        from app.database import get_db

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("app.database.async_session_factory", return_value=MagicMock(
            __aenter__=AsyncMock(return_value=mock_session),
            __aexit__=AsyncMock(return_value=None),
        )):
            gen = get_db()
            session = await gen.__anext__()
            assert session is not None

    @pytest.mark.asyncio
    async def test_get_db_rolls_back_on_exception(self):
        """get_db should rollback on exception."""
        from app.database import get_db

        mock_session = AsyncMock()
        mock_session.commit = AsyncMock(side_effect=Exception("DB error"))

        with patch("app.database.async_session_factory", return_value=MagicMock(
            __aenter__=AsyncMock(return_value=mock_session),
            __aexit__=AsyncMock(return_value=None),
        )):
            gen = get_db()
            session = await gen.__anext__()
            with pytest.raises(Exception, match="DB error"):
                await gen.__anext__()


class TestDatabaseInitDb:
    """Tests for init_db function."""

    @pytest.mark.asyncio
    async def test_init_db_creates_tables(self):
        """init_db should create all tables."""
        from app.database import init_db

        mock_conn = AsyncMock()
        mock_conn.run_sync = MagicMock()

        mock_engine = MagicMock()
        mock_engine.begin = MagicMock(
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=mock_conn),
                __aexit__=AsyncMock(return_value=None),
            )
        )

        with patch("app.database.engine", mock_engine):
            await init_db()
            mock_conn.run_sync.assert_called_once()


class TestDatabaseCloseDb:
    """Tests for close_db function."""

    @pytest.mark.asyncio
    async def test_close_db_disposes_engine(self):
        """close_db should dispose the engine."""
        from app.database import close_db

        mock_engine = AsyncMock()

        with patch("app.database.engine", mock_engine):
            await close_db()
            mock_engine.dispose.assert_awaited_once()


class TestDatabaseEngine:
    """Tests for database engine configuration."""

    def test_engine_exists(self):
        """Engine should be created."""
        from app.database import engine
        assert engine is not None

    def test_async_session_factory_exists(self):
        """Async session factory should be created."""
        from app.database import async_session_factory
        assert async_session_factory is not None

    def test_get_db_session_alias_exists(self):
        """get_db_session alias should exist."""
        from app.database import get_db_session
        assert callable(get_db_session)


class TestSettingsExtended:
    """Extended tests for application settings."""

    def test_settings_from_environment(self, monkeypatch):
        """Settings should read from environment variables."""
        monkeypatch.setenv("APP_NAME", "Custom App")
        monkeypatch.setenv("DEBUG", "true")

        from pydantic_settings import BaseSettings
        from app.config import Settings

        settings = Settings()
        assert settings.app_name == "Custom App"
        assert settings.debug is True

    def test_settings_database_url_can_be_overridden(self, monkeypatch):
        """Database URL should be overridable via environment."""
        monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///test.db")

        from app.config import Settings
        settings = Settings()
        assert "sqlite" in settings.database_url

    def test_settings_secret_key_can_be_overridden(self, monkeypatch):
        """Secret key should be overridable via environment."""
        monkeypatch.setenv("SECRET_KEY", "super-secret-key")

        from app.config import Settings
        settings = Settings()
        assert settings.secret_key == "super-secret-key"

    def test_settings_smtp_settings_can_be_overridden(self, monkeypatch):
        """SMTP settings should be overridable via environment."""
        monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("SMTP_PORT", "465")
        monkeypatch.setenv("SMTP_FROM_EMAIL", "test@example.com")

        from app.config import Settings
        settings = Settings()
        assert settings.smtp_host == "smtp.example.com"
        assert settings.smtp_port == 465
        assert settings.smtp_from_email == "test@example.com"


class TestAppOpenApiExtended:
    """Extended tests for OpenAPI schema."""

    def test_openapi_has_paths(self):
        """OpenAPI schema should have paths."""
        from main import app
        schema = app.openapi()
        assert "/api/v1/posts" in schema["paths"]
        assert "/api/v1/comments" in schema["paths"]

    def test_openapi_has_post_endpoints(self):
        """OpenAPI should document all post endpoints."""
        from main import app
        schema = app.openapi()
        paths = schema["paths"]
        assert "post" in paths["/api/v1/posts"]
        assert "get" in paths["/api/v1/posts"]
        assert "get" in paths["/api/v1/posts/{post_id}"]
        assert "put" in paths["/api/v1/posts/{post_id}"]
        assert "delete" in paths["/api/v1/posts/{post_id}"]
        assert "post" in paths["/api/v1/posts/{post_id}/like"]

    def test_openapi_has_comment_endpoints(self):
        """OpenAPI should document all comment endpoints."""
        from main import app
        schema = app.openapi()
        paths = schema["paths"]
        assert "post" in paths["/api/v1/comments"]
        assert "get" in paths["/api/v1/comments"]
        assert "get" in paths["/api/v1/comments/{comment_id}"]
        assert "put" in paths["/api/v1/comments/{comment_id}"]
        assert "delete" in paths["/api/v1/comments/{comment_id}"]
        assert "post" in paths["/api/v1/comments/{comment_id}/like"]

    def test_openapi_has_tags(self):
        """OpenAPI should have tags defined."""
        from main import app
        schema = app.openapi()
        tags = [t["name"] for t in schema.get("tags", [])]
        assert "posts" in tags
        assert "comments" in tags

    def test_openapi_has_schemas(self):
        """OpenAPI should have schema definitions."""
        from main import app
        schema = app.openapi()
        assert "components" in schema
        assert "schemas" in schema["components"]
