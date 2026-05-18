"""Tests for account management API endpoints."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import Result

from api.accounts import router as accounts_router


def create_test_app(session_mock):
    """Create a test app with overridden session dependency."""
    app = FastAPI(title="Test Accounts")

    async def override_get_session():
        yield session_mock

    from db.session import get_session
    app.include_router(accounts_router)
    app.dependency_overrides[get_session] = override_get_session
    return app


class TestCreateAccount:
    """Tests for POST /accounts."""

    def test_create_account_success(self, create_test_app, mock_get_encryption_manager):
        app, session_mock = create_test_app()

        created_account = MagicMock()
        created_account.id = 1
        created_account.user_id = "test-user"
        created_account.email_address = "test@example.com"
        created_account.imap_host = "imap.example.com"
        created_account.imap_port = 993
        created_account.username = "test@example.com"
        created_account.is_active = True
        created_account.created_at = datetime(2024, 1, 15, tzinfo=timezone.utc)
        created_account.updated_at = datetime(2024, 1, 15, tzinfo=timezone.utc)

        async def mock_flush():
            pass

        async def mock_refresh(obj):
            obj.id = 1

        session_mock.flush = mock_flush
        session_mock.refresh = mock_refresh

        client = TestClient(app)
        response = client.post("/accounts", json={
            "user_id": "test-user",
            "email_address": "test@example.com",
            "imap_host": "imap.example.com",
            "imap_port": 993,
            "username": "test@example.com",
            "password": "secret",
        })

        assert response.status_code == 201
        data = response.json()
        assert data["email_address"] == "test@example.com"
        assert data["is_active"] is True

    def test_create_account_invalid_email(self, create_test_app, mock_get_encryption_manager):
        app, session_mock = create_test_app()

        client = TestClient(app)
        response = client.post("/accounts", json={
            "user_id": "test-user",
            "email_address": "not-an-email",
            "imap_host": "imap.example.com",
            "username": "user",
            "password": "secret",
        })

        assert response.status_code == 422

    def test_create_account_missing_required_fields(self, create_test_app, mock_get_encryption_manager):
        app, session_mock = create_test_app()

        client = TestClient(app)
        response = client.post("/accounts", json={})

        assert response.status_code == 422


class TestListAccounts:
    """Tests for GET /accounts."""

    def test_list_accounts_empty(self, create_test_app):
        app, session_mock = create_test_app()

        mock_count_result = MagicMock()
        mock_count_result.scalar = MagicMock(return_value=0)

        mock_accounts_result = MagicMock()
        mock_accounts_result.scalars.return_value.all.return_value = []

        async def mock_execute(stmt):
            if "count" in str(stmt).lower() or "func" in str(stmt).lower():
                return mock_count_result
            return mock_accounts_result

        session_mock.execute = mock_execute

        client = TestClient(app)
        response = client.get("/accounts")

        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_list_accounts_with_user_id_filter(self, create_test_app):
        app, session_mock = create_test_app()

        mock_count_result = MagicMock()
        mock_count_result.scalar = MagicMock(return_value=0)

        mock_accounts_result = MagicMock()
        mock_accounts_result.scalars.return_value.all.return_value = []

        async def mock_execute(stmt):
            if "count" in str(stmt).lower() or "func" in str(stmt).lower():
                return mock_count_result
            return mock_accounts_result

        session_mock.execute = mock_execute

        client = TestClient(app)
        response = client.get("/accounts?user_id=test-user")

        assert response.status_code == 200


class TestGetAccount:
    """Tests for GET /accounts/{account_id}."""

    def test_get_account_success(self, create_test_app):
        app, session_mock = create_test_app()

        account = MagicMock()
        account.id = 1
        account.user_id = "test-user"
        account.email_address = "test@example.com"
        account.imap_host = "imap.example.com"
        account.imap_port = 993
        account.username = "test@example.com"
        account.is_active = True
        account.created_at = datetime(2024, 1, 15, tzinfo=timezone.utc)
        account.updated_at = datetime(2024, 1, 15, tzinfo=timezone.utc)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=account)

        async def mock_execute(stmt):
            return mock_result

        session_mock.execute = mock_execute

        client = TestClient(app)
        response = client.get("/accounts/1")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == 1
        assert data["email_address"] == "test@example.com"

    def test_get_account_not_found(self, create_test_app):
        app, session_mock = create_test_app()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)

        async def mock_execute(stmt):
            return mock_result

        session_mock.execute = mock_execute

        client = TestClient(app)
        response = client.get("/accounts/999")

        assert response.status_code == 404


class TestDeleteAccount:
    """Tests for DELETE /accounts/{account_id}."""

    def test_delete_account_success(self, create_test_app):
        app, session_mock = create_test_app()

        account = MagicMock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=account)

        async def mock_execute(stmt):
            return mock_result

        session_mock.execute = mock_execute
        session_mock.delete = MagicMock()

        client = TestClient(app)
        response = client.delete("/accounts/1")

        assert response.status_code == 204
        session_mock.delete.assert_called_once()

    def test_delete_account_not_found(self, create_test_app):
        app, session_mock = create_test_app()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)

        async def mock_execute(stmt):
            return mock_result

        session_mock.execute = mock_execute

        client = TestClient(app)
        response = client.delete("/accounts/999")

        assert response.status_code == 404


class TestTriggerSync:
    """Tests for POST /accounts/{account_id}/sync."""

    def test_trigger_sync_success(self, create_test_app, mock_get_encryption_manager):
        app, session_mock = create_test_app()

        account = MagicMock()
        account.id = 1
        account.imap_host = "imap.example.com"
        account.imap_port = 993
        account.username = "test@example.com"
        account.encrypted_password = "encrypted"
        account.is_active = True

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=account)

        async def mock_execute(stmt):
            return mock_result

        session_mock.execute = mock_execute

        with patch("api.accounts.SyncManager") as MockSyncManager:
            mock_sync = MagicMock()
            mock_sync.sync_account = AsyncMock(return_value=5)
            MockSyncManager.return_value = mock_sync

            client = TestClient(app)
            response = client.post("/accounts/1/sync", json={})

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "completed"
            assert data["messages_synced"] == 5

    def test_trigger_sync_account_not_found(self, create_test_app):
        app, session_mock = create_test_app()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)

        async def mock_execute(stmt):
            return mock_result

        session_mock.execute = mock_execute

        client = TestClient(app)
        response = client.post("/accounts/999/sync", json={})

        assert response.status_code == 404

    def test_trigger_sync_account_inactive(self, create_test_app, mock_get_encryption_manager):
        app, session_mock = create_test_app()

        account = MagicMock()
        account.id = 1
        account.is_active = False
        account.encrypted_password = "encrypted"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=account)

        async def mock_execute(stmt):
            return mock_result

        session_mock.execute = mock_execute

        client = TestClient(app)
        response = client.post("/accounts/1/sync", json={})

        assert response.status_code == 400

    def test_trigger_sync_with_folders(self, create_test_app, mock_get_encryption_manager):
        app, session_mock = create_test_app()

        account = MagicMock()
        account.id = 1
        account.imap_host = "imap.example.com"
        account.imap_port = 993
        account.username = "test@example.com"
        account.encrypted_password = "encrypted"
        account.is_active = True

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=account)

        async def mock_execute(stmt):
            return mock_result

        session_mock.execute = mock_execute

        with patch("api.accounts.SyncManager") as MockSyncManager:
            mock_sync = MagicMock()
            mock_sync.sync_account = AsyncMock(return_value=10)
            MockSyncManager.return_value = mock_sync

            client = TestClient(app)
            response = client.post("/accounts/1/sync", json={
                "folders": ["INBOX", "Sent"]
            })

            assert response.status_code == 200
            mock_sync.sync_account.assert_called_once()

    def test_trigger_sync_handles_error(self, create_test_app, mock_get_encryption_manager):
        app, session_mock = create_test_app()

        account = MagicMock()
        account.id = 1
        account.imap_host = "imap.example.com"
        account.imap_port = 993
        account.username = "test@example.com"
        account.encrypted_password = "encrypted"
        account.is_active = True

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=account)

        async def mock_execute(stmt):
            return mock_result

        session_mock.execute = mock_execute

        with patch("api.accounts.SyncManager") as MockSyncManager:
            mock_sync = MagicMock()
            mock_sync.sync_account = AsyncMock(side_effect=Exception("Connection failed"))
            MockSyncManager.return_value = mock_sync

            client = TestClient(app)
            response = client.post("/accounts/1/sync", json={})

            assert response.status_code == 500
            assert "Sync failed" in response.json()["detail"]
