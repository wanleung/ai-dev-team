"""Tests for email query and attachment API endpoints."""

import os
import tempfile
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.emails import router as emails_router


def create_test_app(session_mock):
    """Create a test app with overridden session dependency."""
    app = FastAPI(title="Test Emails")

    async def override_get_session():
        yield session_mock

    from db.session import get_session
    app.include_router(emails_router)
    app.dependency_overrides[get_session] = override_get_session
    return app


class TestListEmails:
    """Tests for GET /emails."""

    def test_list_emails_empty(self, create_test_app):
        app, session_mock = create_test_app()

        mock_count_result = MagicMock()
        mock_count_result.scalar = MagicMock(return_value=0)

        mock_emails_result = MagicMock()
        mock_emails_result.scalars.return_value.all.return_value = []

        async def mock_execute(stmt):
            if "count" in str(stmt).lower() or "func" in str(stmt).lower():
                return mock_count_result
            return mock_emails_result

        session_mock.execute = mock_execute

        client = TestClient(app)
        response = client.get("/emails")

        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_list_emails_with_pagination(self, create_test_app):
        app, session_mock = create_test_app()

        mock_count_result = MagicMock()
        mock_count_result.scalar = MagicMock(return_value=100)

        mock_emails_result = MagicMock()
        mock_emails_result.scalars.return_value.all.return_value = []

        async def mock_execute(stmt):
            if "count" in str(stmt).lower() or "func" in str(stmt).lower():
                return mock_count_result
            return mock_emails_result

        session_mock.execute = mock_execute

        client = TestClient(app)
        response = client.get("/emails?limit=10&offset=20")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 100

    def test_list_emails_with_account_filter(self, create_test_app):
        app, session_mock = create_test_app()

        mock_count_result = MagicMock()
        mock_count_result.scalar = MagicMock(return_value=5)

        mock_emails_result = MagicMock()
        mock_emails_result.scalars.return_value.all.return_value = []

        async def mock_execute(stmt):
            if "count" in str(stmt).lower() or "func" in str(stmt).lower():
                return mock_count_result
            return mock_emails_result

        session_mock.execute = mock_execute

        client = TestClient(app)
        response = client.get("/emails?account_id=1")

        assert response.status_code == 200

    def test_list_emails_with_search(self, create_test_app):
        app, session_mock = create_test_app()

        mock_count_result = MagicMock()
        mock_count_result.scalar = MagicMock(return_value=2)

        mock_emails_result = MagicMock()
        mock_emails_result.scalars.return_value.all.return_value = []

        async def mock_execute(stmt):
            if "count" in str(stmt).lower() or "func" in str(stmt).lower():
                return mock_count_result
            return mock_emails_result

        session_mock.execute = mock_execute

        client = TestClient(app)
        response = client.get("/emails?search=invoice")

        assert response.status_code == 200

    def test_list_emails_with_read_filter(self, create_test_app):
        app, session_mock = create_test_app()

        mock_count_result = MagicMock()
        mock_count_result.scalar = MagicMock(return_value=10)

        mock_emails_result = MagicMock()
        mock_emails_result.scalars.return_value.all.return_value = []

        async def mock_execute(stmt):
            if "count" in str(stmt).lower() or "func" in str(stmt).lower():
                return mock_count_result
            return mock_emails_result

        session_mock.execute = mock_execute

        client = TestClient(app)
        response = client.get("/emails?is_read=true")

        assert response.status_code == 200

    def test_list_emails_with_attachments_filter(self, create_test_app):
        app, session_mock = create_test_app()

        mock_count_result = MagicMock()
        mock_count_result.scalar = MagicMock(return_value=3)

        mock_emails_result = MagicMock()
        mock_emails_result.scalars.return_value.all.return_value = []

        async def mock_execute(stmt):
            if "count" in str(stmt).lower() or "func" in str(stmt).lower():
                return mock_count_result
            return mock_emails_result

        session_mock.execute = mock_execute

        client = TestClient(app)
        response = client.get("/emails?has_attachments=true")

        assert response.status_code == 200

    def test_list_emails_limit_validation(self, create_test_app):
        app, session_mock = create_test_app()

        client = TestClient(app)
        response = client.get("/emails?limit=0")

        assert response.status_code == 422

    def test_list_emails_limit_max_validation(self, create_test_app):
        app, session_mock = create_test_app()

        client = TestClient(app)
        response = client.get("/emails?limit=201")

        assert response.status_code == 422

    def test_list_emails_offset_validation(self, create_test_app):
        app, session_mock = create_test_app()

        client = TestClient(app)
        response = client.get("/emails?offset=-1")

        assert response.status_code == 422


class TestGetEmail:
    """Tests for GET /emails/{email_id}."""

    def test_get_email_success(self, create_test_app):
        app, session_mock = create_test_app()

        email_msg = MagicMock()
        email_msg.id = 1
        email_msg.account_id = 1
        email_msg.uid = 100
        email_msg.message_id = "<test@example.com>"
        email_msg.subject = "Test Subject"
        email_msg.sender = "sender@example.com"
        email_msg.recipients = "recipient@example.com"
        email_msg.date_received = datetime(2024, 1, 15, tzinfo=timezone.utc)
        email_msg.body_text = "Body text"
        email_msg.body_html = "<p>HTML</p>"
        email_msg.has_attachments = True
        email_msg.is_read = False
        email_msg.created_at = datetime(2024, 1, 15, tzinfo=timezone.utc)

        attachment = MagicMock()
        attachment.id = 1
        attachment.filename = "report.pdf"
        attachment.content_type = "application/pdf"
        attachment.size_bytes = 1024
        attachment.storage_path = "/tmp/report.pdf"

        email_call_count = 0

        async def mock_execute(stmt):
            nonlocal email_call_count
            email_call_count += 1
            mock_result = MagicMock()
            if email_call_count == 1:
                mock_result.scalar_one_or_none = MagicMock(return_value=email_msg)
            else:
                mock_result.scalars.return_value.all.return_value = [attachment]
            return mock_result

        session_mock.execute = mock_execute

        client = TestClient(app)
        response = client.get("/emails/1")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == 1
        assert data["subject"] == "Test Subject"

    def test_get_email_not_found(self, create_test_app):
        app, session_mock = create_test_app()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)

        async def mock_execute(stmt):
            return mock_result

        session_mock.execute = mock_execute

        client = TestClient(app)
        response = client.get("/emails/999")

        assert response.status_code == 404


class TestDownloadAttachment:
    """Tests for GET /emails/{email_id}/attachments/{attachment_id}/download."""

    def test_download_attachment_success(self, create_test_app):
        app, session_mock = create_test_app()

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(b"%PDF-1.4 test content")
            tmp_path = tmp.name

        try:
            attachment = MagicMock()
            attachment.id = 1
            attachment.filename = "report.pdf"
            attachment.content_type = "application/pdf"
            attachment.size_bytes = 21
            attachment.storage_path = tmp_path

            mock_result = MagicMock()
            mock_result.scalar_one_or_none = MagicMock(return_value=attachment)

            async def mock_execute(stmt):
                return mock_result

            session_mock.execute = mock_execute

            client = TestClient(app)
            response = client.get("/emails/1/attachments/1/download")

            assert response.status_code == 200
            assert response.headers["content-type"] == "application/pdf"
        finally:
            os.unlink(tmp_path)

    def test_download_attachment_not_found(self, create_test_app):
        app, session_mock = create_test_app()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)

        async def mock_execute(stmt):
            return mock_result

        session_mock.execute = mock_execute

        client = TestClient(app)
        response = client.get("/emails/1/attachments/999/download")

        assert response.status_code == 404

    def test_download_attachment_file_missing(self, create_test_app):
        app, session_mock = create_test_app()

        attachment = MagicMock()
        attachment.id = 1
        attachment.filename = "missing.pdf"
        attachment.content_type = "application/pdf"
        attachment.size_bytes = 100
        attachment.storage_path = "/nonexistent/path/file.pdf"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=attachment)

        async def mock_execute(stmt):
            return mock_result

        session_mock.execute = mock_execute

        client = TestClient(app)
        response = client.get("/emails/1/attachments/1/download")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


class TestMarkEmailRead:
    """Tests for PATCH /emails/{email_id}/read."""

    def test_mark_email_read_success(self, create_test_app):
        app, session_mock = create_test_app()

        email_msg = MagicMock()
        email_msg.id = 1
        email_msg.account_id = 1
        email_msg.uid = 100
        email_msg.message_id = "<test@example.com>"
        email_msg.subject = "Test Subject"
        email_msg.sender = "sender@example.com"
        email_msg.recipients = "recipient@example.com"
        email_msg.date_received = datetime(2024, 1, 15, tzinfo=timezone.utc)
        email_msg.body_text = "Body"
        email_msg.body_html = ""
        email_msg.has_attachments = False
        email_msg.is_read = False
        email_msg.created_at = datetime(2024, 1, 15, tzinfo=timezone.utc)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=email_msg)

        async def mock_execute(stmt):
            return mock_result

        session_mock.execute = mock_execute

        async def mock_flush():
            pass

        async def mock_refresh(obj):
            obj.is_read = True

        session_mock.flush = mock_flush
        session_mock.refresh = mock_refresh

        client = TestClient(app)
        response = client.patch("/emails/1/read")

        assert response.status_code == 200
        data = response.json()
        assert data["is_read"] is True

    def test_mark_email_read_not_found(self, create_test_app):
        app, session_mock = create_test_app()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)

        async def mock_execute(stmt):
            return mock_result

        session_mock.execute = mock_execute

        client = TestClient(app)
        response = client.patch("/emails/999/read")

        assert response.status_code == 404
