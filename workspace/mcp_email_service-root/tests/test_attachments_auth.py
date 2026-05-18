"""Tests for REST API attachment endpoints with auth scoping."""

import os
import tempfile
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.attachments import router as attachments_router


def create_test_app_with_auth(session_mock, user_id="test-user"):
    """Create a test app with auth middleware for attachment endpoints."""
    app = FastAPI(title="Test Attachments Auth")

    async def override_get_session():
        yield session_mock

    from db.session import get_session
    app.include_router(attachments_router)
    app.dependency_overrides[get_session] = override_get_session

    async def mock_middleware(request, call_next):
        from middleware.auth import UserContext
        request.state.user = UserContext(user_id=user_id, is_authenticated=user_id != "default")
        return await call_next(request)

    app.middleware("http")(mock_middleware)

    return app


class TestAttachmentDownloadWithAuth:
    """Tests for GET /accounts/{account_id}/emails/{message_id}/attachments/{attachment_id}."""

    def test_download_attachment_success_with_auth(self):
        """Given authenticated user and valid attachment, then file is streamed."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(b"%PDF-1.4 test content")
            tmp_path = tmp.name

        try:
            from sqlalchemy.ext.asyncio import AsyncSession
            session_mock = AsyncMock(spec=AsyncSession)

            mock_account = MagicMock()
            mock_account.id = 1
            mock_account.user_id = "test-user"

            mock_message = MagicMock()
            mock_message.id = 1
            mock_message.account_id = 1

            mock_attachment = MagicMock()
            mock_attachment.id = 1
            mock_attachment.filename = "report.pdf"
            mock_attachment.content_type = "application/pdf"
            mock_attachment.size_bytes = 21
            mock_attachment.storage_path = tmp_path

            call_count = 0

            async def mock_execute(stmt):
                nonlocal call_count
                call_count += 1
                mock_result = MagicMock()
                if call_count == 1:
                    mock_result.scalar_one_or_none = MagicMock(return_value=mock_account)
                elif call_count == 2:
                    mock_result.scalar_one_or_none = MagicMock(return_value=mock_message)
                else:
                    mock_result.scalar_one_or_none = MagicMock(return_value=mock_attachment)
                return mock_result

            session_mock.execute = mock_execute

            app = create_test_app_with_auth(session_mock, user_id="test-user")
            client = TestClient(app)
            response = client.get("/accounts/1/emails/1/attachments/1")

            assert response.status_code == 200
            assert response.headers["content-type"] == "application/pdf"
            assert "report.pdf" in response.headers["content-disposition"]
        finally:
            os.unlink(tmp_path)

    def test_download_attachment_denies_wrong_user(self):
        """Given a user who doesn't own the account, then 404 is returned."""
        from sqlalchemy.ext.asyncio import AsyncSession
        session_mock = AsyncMock(spec=AsyncSession)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        session_mock.execute.return_value = mock_result

        app = create_test_app_with_auth(session_mock, user_id="wrong-user")
        client = TestClient(app)
        response = client.get("/accounts/1/emails/1/attachments/1")

        assert response.status_code == 404
        assert "access denied" in response.json()["detail"].lower()

    def test_download_attachment_message_not_found(self):
        """Given a non-existent message, then 404 is returned."""
        from sqlalchemy.ext.asyncio import AsyncSession
        session_mock = AsyncMock(spec=AsyncSession)

        mock_account = MagicMock()
        mock_account.id = 1
        mock_account.user_id = "test-user"

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.scalar_one_or_none = MagicMock(return_value=mock_account)
            else:
                mock_result.scalar_one_or_none = MagicMock(return_value=None)
            return mock_result

        session_mock.execute = mock_execute

        app = create_test_app_with_auth(session_mock, user_id="test-user")
        client = TestClient(app)
        response = client.get("/accounts/1/emails/999/attachments/1")

        assert response.status_code == 404

    def test_download_attachment_not_found(self):
        """Given a non-existent attachment, then 404 is returned."""
        from sqlalchemy.ext.asyncio import AsyncSession
        session_mock = AsyncMock(spec=AsyncSession)

        mock_account = MagicMock()
        mock_account.id = 1
        mock_account.user_id = "test-user"

        mock_message = MagicMock()
        mock_message.id = 1

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.scalar_one_or_none = MagicMock(return_value=mock_account)
            elif call_count == 2:
                mock_result.scalar_one_or_none = MagicMock(return_value=mock_message)
            else:
                mock_result.scalar_one_or_none = MagicMock(return_value=None)
            return mock_result

        session_mock.execute = mock_execute

        app = create_test_app_with_auth(session_mock, user_id="test-user")
        client = TestClient(app)
        response = client.get("/accounts/1/emails/1/attachments/999")

        assert response.status_code == 404

    def test_download_attachment_file_missing(self):
        """Given an attachment with missing file, then 404 is returned."""
        from sqlalchemy.ext.asyncio import AsyncSession
        session_mock = AsyncMock(spec=AsyncSession)

        mock_account = MagicMock()
        mock_account.id = 1
        mock_account.user_id = "test-user"

        mock_message = MagicMock()
        mock_message.id = 1

        mock_attachment = MagicMock()
        mock_attachment.id = 1
        mock_attachment.filename = "missing.pdf"
        mock_attachment.content_type = "application/pdf"
        mock_attachment.size_bytes = 100
        mock_attachment.storage_path = "/nonexistent/file.pdf"

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.scalar_one_or_none = MagicMock(return_value=mock_account)
            elif call_count == 2:
                mock_result.scalar_one_or_none = MagicMock(return_value=mock_message)
            else:
                mock_result.scalar_one_or_none = MagicMock(return_value=mock_attachment)
            return mock_result

        session_mock.execute = mock_execute

        app = create_test_app_with_auth(session_mock, user_id="test-user")
        client = TestClient(app)
        response = client.get("/accounts/1/emails/1/attachments/1")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_download_attachment_requires_auth(self):
        """Given unauthenticated request, then 401 is returned."""
        from sqlalchemy.ext.asyncio import AsyncSession
        session_mock = AsyncMock(spec=AsyncSession)

        app = create_test_app_with_auth(session_mock, user_id="default")
        client = TestClient(app)
        response = client.get("/accounts/1/emails/1/attachments/1")

        assert response.status_code == 401
        assert "Authentication required" in response.json()["detail"]
