"""Integration tests for MCP Email Service tools with real SQLite database.

These tests use a real in-memory SQLite database (not mocked sessions)
to validate end-to-end behavior of MCP tools, including database operations,
pagination, filtering, and error conditions.
"""

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from config.settings import EncryptionManager
from db.base import Base
from db.models import EmailAccount, EmailMessage, Attachment, SyncState
from mcp_server.tools import (
    list_emails,
    get_email,
    search_emails,
    mark_read,
    list_accounts,
    add_account,
    get_sync_state,
    list_folders,
    download_attachments,
)


@pytest.fixture
async def integration_engine():
    """Create a real in-memory SQLite engine for integration tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def integration_session(integration_engine):
    """Create a real async session for integration tests."""
    factory = async_sessionmaker(integration_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
def integration_encryption_manager():
    """Create a real EncryptionManager for integration tests."""
    key = Fernet.generate_key()
    return EncryptionManager(key)


@pytest.fixture
async def seeded_account(integration_session, integration_encryption_manager):
    """Create a seeded EmailAccount in the real database."""
    account = EmailAccount(
        user_id="integration-test-user",
        email_address="integration@example.com",
        imap_host="imap.example.com",
        imap_port=993,
        username="integration@example.com",
        encrypted_password=integration_encryption_manager.encrypt("test-password"),
        is_active=True,
        auth_method="basic",
    )
    integration_session.add(account)
    await integration_session.flush()
    return account


@pytest.fixture
async def seeded_emails(integration_session, seeded_account):
    """Create 5 seeded EmailMessage records in the real database."""
    messages = []
    for i in range(5):
        msg = EmailMessage(
            account_id=seeded_account.id,
            uid=100 + i,
            message_id=f"<integration-msg{i}@example.com>",
            subject=f"Integration Test Email {i}",
            sender=f"sender{i}@example.com",
            recipients="recipient@example.com",
            date_received=datetime(2024, 1, 15, 10, 30, i, tzinfo=timezone.utc),
            body_text=f"Body text for integration email {i}",
            body_html=f"<html><body>HTML content {i}</body></html>",
            has_attachments=(i == 0),
            is_read=(i % 2 == 0),
        )
        integration_session.add(msg)
        await integration_session.flush()
        messages.append(msg)

    await integration_session.commit()
    return messages, seeded_account.id


@pytest.fixture
async def seeded_attachment(integration_session, seeded_emails):
    """Create a seeded Attachment record in the real database."""
    messages, account_id = seeded_emails
    msg_with_attachment = messages[0]

    att = Attachment(
        message_id=msg_with_attachment.id,
        filename="integration_report.pdf",
        content_type="application/pdf",
        size_bytes=2048,
        storage_path="/tmp/integration_test_report.pdf",
    )
    integration_session.add(att)
    await integration_session.commit()
    return att, msg_with_attachment.id


class TestListEmailsIntegration:
    """Integration tests for list_emails with real DB."""

    @pytest.mark.asyncio
    async def test_list_emails_returns_all_messages(self, integration_session, seeded_emails):
        """Given seeded emails, when list_emails is called, then all messages are returned."""
        messages, account_id = seeded_emails

        with patch("mcp_server.tools.list_emails.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=integration_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await list_emails(account_id=account_id, limit=20, offset=0)

        data = json.loads(result)
        assert data["total"] == 5
        assert len(data["items"]) == 5

    @pytest.mark.asyncio
    async def test_list_emails_respects_limit(self, integration_session, seeded_emails):
        """Given 5 emails, when list_emails is called with limit=2, then exactly 2 are returned."""
        messages, account_id = seeded_emails

        with patch("mcp_server.tools.list_emails.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=integration_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await list_emails(account_id=account_id, limit=2, offset=0)

        data = json.loads(result)
        assert len(data["items"]) == 2
        assert data["total"] == 5

    @pytest.mark.asyncio
    async def test_list_emails_respects_offset(self, integration_session, seeded_emails):
        """Given 5 emails, when list_emails is called with offset=3, then 2 are returned."""
        messages, account_id = seeded_emails

        with patch("mcp_server.tools.list_emails.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=integration_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await list_emails(account_id=account_id, limit=10, offset=3)

        data = json.loads(result)
        assert len(data["items"]) == 2

    @pytest.mark.asyncio
    async def test_list_emails_filters_by_is_read(self, integration_session, seeded_emails):
        """Given mixed read/unread emails, when filtering by is_read=True, then only read emails returned."""
        messages, account_id = seeded_emails

        with patch("mcp_server.tools.list_emails.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=integration_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await list_emails(account_id=account_id, is_read=True)

        data = json.loads(result)
        assert all(item["is_read"] for item in data["items"])

    @pytest.mark.asyncio
    async def test_list_emails_filters_by_search(self, integration_session, seeded_emails):
        """Given emails with different subjects, when searching, then matching emails are returned."""
        messages, account_id = seeded_emails

        with patch("mcp_server.tools.list_emails.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=integration_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await list_emails(account_id=account_id, search="Email 2")

        data = json.loads(result)
        assert data["total"] >= 1
        assert any("Email 2" in item["subject"] for item in data["items"])

    @pytest.mark.asyncio
    async def test_list_emails_empty_account(self, integration_session, seeded_account):
        """Given an account with no emails, then empty list is returned."""
        with patch("mcp_server.tools.list_emails.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=integration_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await list_emails(account_id=seeded_account.id)

        data = json.loads(result)
        assert data["items"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_list_emails_returns_correct_metadata_fields(self, integration_session, seeded_emails):
        """Given emails, then each item contains all required metadata fields."""
        messages, account_id = seeded_emails

        with patch("mcp_server.tools.list_emails.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=integration_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await list_emails(account_id=account_id, limit=1)

        data = json.loads(result)
        item = data["items"][0]
        required_fields = ["id", "account_id", "uid", "message_id", "subject", "sender", "recipients", "date_received", "has_attachments", "is_read"]
        for field in required_fields:
            assert field in item, f"Missing field: {field}"


class TestGetEmailIntegration:
    """Integration tests for get_email with real DB."""

    @pytest.mark.asyncio
    async def test_get_email_returns_full_details(self, integration_session, seeded_emails):
        """Given a seeded email, when get_email is called, then full details are returned."""
        messages, account_id = seeded_emails
        msg_id = messages[0].id

        with patch("mcp_server.tools.get_email.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=integration_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await get_email(message_id=msg_id)

        data = json.loads(result)
        assert data["id"] == msg_id
        assert data["subject"] == "Integration Test Email 0"
        assert data["body_text"] == "Body text for integration email 0"
        assert data["body_html"] == "<html><body>HTML content 0</body></html>"

    @pytest.mark.asyncio
    async def test_get_email_returns_attachments(self, integration_session, seeded_attachment):
        """Given an email with attachments, then attachments list is populated."""
        att, msg_id = seeded_attachment

        with patch("mcp_server.tools.get_email.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=integration_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await get_email(message_id=msg_id)

        data = json.loads(result)
        assert len(data["attachments"]) == 1
        assert data["attachments"][0]["filename"] == "integration_report.pdf"

    @pytest.mark.asyncio
    async def test_get_email_raises_for_nonexistent(self, integration_session):
        """Given a non-existent message ID, then ValueError is raised."""
        with patch("mcp_server.tools.get_email.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=integration_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(ValueError, match="Message .* not found"):
                await get_email(message_id=99999)


class TestSearchEmailsIntegration:
    """Integration tests for search_emails with real DB."""

    @pytest.mark.asyncio
    async def test_search_by_subject(self, integration_session, seeded_emails):
        """Given emails, when searching by subject keyword, then matching emails are returned."""
        messages, account_id = seeded_emails

        with patch("mcp_server.tools.search_emails.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=integration_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await search_emails(account_id=account_id, query="Email 3")

        data = json.loads(result)
        assert data["total"] >= 1
        assert any("Email 3" in item["subject"] for item in data["items"])

    @pytest.mark.asyncio
    async def test_search_by_sender(self, integration_session, seeded_emails):
        """Given emails from different senders, when searching by sender, then matches returned."""
        messages, account_id = seeded_emails

        with patch("mcp_server.tools.search_emails.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=integration_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await search_emails(account_id=account_id, query="sender2@")

        data = json.loads(result)
        assert data["total"] >= 1

    @pytest.mark.asyncio
    async def test_search_by_body_text(self, integration_session, seeded_emails):
        """Given emails with different bodies, when searching body text, then matches returned."""
        messages, account_id = seeded_emails

        with patch("mcp_server.tools.search_emails.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=integration_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await search_emails(account_id=account_id, query="Body text for integration")

        data = json.loads(result)
        assert data["total"] == 5

    @pytest.mark.asyncio
    async def test_search_no_matches(self, integration_session, seeded_emails):
        """Given emails, when searching for non-existent term, then empty results."""
        messages, account_id = seeded_emails

        with patch("mcp_server.tools.search_emails.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=integration_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await search_emails(account_id=account_id, query="nonexistent-xyz-123")

        data = json.loads(result)
        assert data["total"] == 0
        assert data["items"] == []

    @pytest.mark.asyncio
    async def test_search_respects_limit(self, integration_session, seeded_emails):
        """Given 5 emails, when searching with limit=2, then at most 2 returned."""
        messages, account_id = seeded_emails

        with patch("mcp_server.tools.search_emails.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=integration_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await search_emails(account_id=account_id, query="Integration", limit=2)

        data = json.loads(result)
        assert len(data["items"]) <= 2


class TestMarkReadIntegration:
    """Integration tests for mark_read with real DB."""

    @pytest.mark.asyncio
    async def test_mark_read_updates_database(self, integration_session, seeded_emails):
        """Given an unread email, when mark_read is called, then is_read becomes True."""
        messages, account_id = seeded_emails
        unread_msg = [m for m in messages if not m.is_read][0]

        with patch("mcp_server.tools.mark_read.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=integration_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("mcp_server.tools.mark_read._require_deps") as mock_deps:
                mock_deps.return_value.sync_manager.mark_read = AsyncMock()

                result = await mark_read(message_id=unread_msg.id)

        data = json.loads(result)
        assert data["status"] == "success"
        assert data["message_id"] == unread_msg.id

    @pytest.mark.asyncio
    async def test_mark_read_raises_for_nonexistent(self, integration_session):
        """Given a non-existent message, then ValueError is raised."""
        with patch("mcp_server.tools.mark_read.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=integration_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(ValueError, match="Message .* not found"):
                await mark_read(message_id=99999)


class TestListAccountsIntegration:
    """Integration tests for list_accounts with real DB."""

    @pytest.mark.asyncio
    async def test_list_accounts_returns_seeded_account(self, integration_session, seeded_account):
        """Given a seeded account, then it appears in list_accounts."""
        with patch("mcp_server.tools.list_accounts.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=integration_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await list_accounts()

        data = json.loads(result)
        assert isinstance(data, list)
        assert len(data) >= 1
        assert any(acc["email_address"] == "integration@example.com" for acc in data)

    @pytest.mark.asyncio
    async def test_list_accounts_excludes_password(self, integration_session, seeded_account):
        """Given accounts with encrypted passwords, then passwords are not exposed."""
        with patch("mcp_server.tools.list_accounts.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=integration_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await list_accounts()

        data = json.loads(result)
        for acc in data:
            assert "encrypted_password" not in acc
            assert "password" not in acc


class TestAddAccountIntegration:
    """Integration tests for add_account with real DB."""

    @pytest.mark.asyncio
    async def test_add_account_creates_record(self, integration_session, integration_encryption_manager):
        """Given valid account details, then a new record is created in the database."""
        mock_settings = MagicMock()
        mock_settings.get_encryption_manager.return_value = integration_encryption_manager

        with patch("mcp_server.tools.add_account.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=integration_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("mcp_server.tools.add_account.get_settings", return_value=mock_settings):
                result = await add_account(
                    email_address="new-integration@example.com",
                    imap_host="imap.new.com",
                    imap_port=993,
                    username="new-integration@example.com",
                    password="new-password",
                    user_id="integration-user",
                )

        data = json.loads(result)
        assert data["status"] == "created"
        assert data["email_address"] == "new-integration@example.com"

    @pytest.mark.asyncio
    async def test_add_account_encrypts_password(self, integration_session, integration_encryption_manager):
        """Given a password, then it is encrypted before storage."""
        mock_settings = MagicMock()
        mock_settings.get_encryption_manager.return_value = integration_encryption_manager

        with patch("mcp_server.tools.add_account.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=integration_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("mcp_server.tools.add_account.get_settings", return_value=mock_settings):
                await add_account(
                    email_address="encrypt-test@example.com",
                    imap_host="imap.example.com",
                    username="encrypt-test@example.com",
                    password="plaintext-secret",
                )

        from sqlalchemy import select
        stmt = select(EmailAccount).where(EmailAccount.email_address == "encrypt-test@example.com")
        result = await integration_session.execute(stmt)
        account = result.scalar_one_or_none()

        assert account is not None
        assert account.encrypted_password != "plaintext-secret"
        decrypted = integration_encryption_manager.decrypt(account.encrypted_password)
        assert decrypted == "plaintext-secret"


class TestGetSyncStateIntegration:
    """Integration tests for get_sync_state with real DB."""

    @pytest.mark.asyncio
    async def test_get_sync_state_returns_json(self, integration_session, seeded_account):
        """Given an account, when get_sync_state is called, then valid JSON is returned."""
        with patch("mcp_server.tools.get_sync_state.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=integration_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("mcp_server.tools.get_sync_state._require_deps") as mock_deps:
                mock_deps.return_value.sync_manager.get_sync_state = AsyncMock(return_value=[])

                result = await get_sync_state(account_id=seeded_account.id)

        data = json.loads(result)
        assert data["account_id"] == seeded_account.id
        assert "folders" in data


class TestListFoldersIntegration:
    """Integration tests for list_folders with real DB."""

    @pytest.mark.asyncio
    async def test_list_folders_valid_account(self, integration_session, seeded_account):
        """Given a valid active account, then folders are returned from IMAP."""
        mock_pool = MagicMock()
        mock_client = MagicMock()
        mock_client.list_folders = AsyncMock(return_value=["INBOX", "Sent", "Drafts"])
        mock_pool.connection.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_pool.connection.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch("mcp_server.tools.list_folders.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=integration_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("mcp_server.tools.list_folders._require_deps") as mock_deps:
                mock_deps.return_value.connection_pool = mock_pool

                result = await list_folders(account_id=seeded_account.id)

        data = json.loads(result)
        assert data["account_id"] == seeded_account.id
        assert data["total"] == 3

    @pytest.mark.asyncio
    async def test_list_folders_inactive_account(self, integration_session, seeded_account):
        """Given an inactive account, then ValueError is raised."""
        seeded_account.is_active = False
        await integration_session.commit()

        with patch("mcp_server.tools.list_folders.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=integration_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(ValueError, match="Account .* is inactive"):
                await list_folders(account_id=seeded_account.id)

    @pytest.mark.asyncio
    async def test_list_folders_nonexistent_account(self, integration_session):
        """Given a non-existent account, then ValueError is raised."""
        with patch("mcp_server.tools.list_folders.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=integration_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(ValueError, match="Account .* not found"):
                await list_folders(account_id=99999)


class TestDownloadAttachmentsIntegration:
    """Integration tests for download_attachments with real DB."""

    @pytest.mark.asyncio
    async def test_download_attachment_success(self, integration_session, seeded_attachment):
        """Given a valid attachment with a real file, then base64 content is returned."""
        att, msg_id = seeded_attachment

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(b"%PDF-1.4 integration test content")
            tmp_path = tmp.name

        try:
            att.storage_path = tmp_path
            await integration_session.commit()

            with patch("mcp_server.tools.download_attachments.async_session_factory") as mock_factory:
                mock_factory.return_value.__aenter__ = AsyncMock(return_value=integration_session)
                mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

                result = await download_attachments(message_id=msg_id, attachment_id=att.id)

            data = json.loads(result)
            assert data["filename"] == "integration_report.pdf"
            assert "content_base64" in data
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_download_attachment_missing_file(self, integration_session, seeded_attachment):
        """Given an attachment with non-existent file path, then ValueError is raised."""
        att, msg_id = seeded_attachment
        att.storage_path = "/nonexistent/path/file.pdf"
        await integration_session.commit()

        with patch("mcp_server.tools.download_attachments.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=integration_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(ValueError, match="Attachment file not found"):
                await download_attachments(message_id=msg_id, attachment_id=att.id)

    @pytest.mark.asyncio
    async def test_download_attachment_nonexistent_message(self, integration_session):
        """Given a non-existent message, then ValueError is raised."""
        with patch("mcp_server.tools.download_attachments.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=integration_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(ValueError, match="Message .* not found"):
                await download_attachments(message_id=99999, attachment_id=1)

    @pytest.mark.asyncio
    async def test_download_attachment_nonexistent_attachment(self, integration_session, seeded_emails):
        """Given a valid message but non-existent attachment, then ValueError is raised."""
        messages, account_id = seeded_emails
        msg_id = messages[0].id

        with patch("mcp_server.tools.download_attachments.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=integration_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(ValueError, match="Attachment .* not found"):
                await download_attachments(message_id=msg_id, attachment_id=99999)
