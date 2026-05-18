"""Tests for SQLAlchemy ORM models and relationships."""

import pytest
from datetime import datetime, timezone
from sqlalchemy import select

from db.base import Base, TimestampMixin
from db.models import EmailAccount, EmailMessage, SyncState, Attachment


class TestTimestampMixin:
    """Tests for the TimestampMixin."""

    def test_timestamp_mixin_has_created_at(self):
        assert hasattr(TimestampMixin, "created_at")

    def test_timestamp_mixin_has_updated_at(self):
        assert hasattr(TimestampMixin, "updated_at")


class TestEmailAccountModel:
    """Tests for EmailAccount ORM model."""

    def test_email_account_table_name(self):
        assert EmailAccount.__tablename__ == "email_accounts"

    def test_email_account_has_required_columns(self):
        columns = {c.name for c in EmailAccount.__table__.columns}
        expected = {
            "id", "user_id", "email_address", "imap_host", "imap_port",
            "username", "encrypted_password", "is_active", "created_at", "updated_at",
        }
        assert expected.issubset(columns)

    def test_email_account_is_active_defaults_true(self):
        account = EmailAccount(
            user_id="test-user",
            email_address="test@example.com",
            imap_host="imap.example.com",
            imap_port=993,
            username="test@example.com",
            encrypted_password="encrypted",
        )
        assert account.is_active is True

    def test_email_account_has_messages_relationship(self):
        assert hasattr(EmailAccount, "messages")

    def test_email_account_has_sync_states_relationship(self):
        assert hasattr(EmailAccount, "sync_states")

    @pytest.mark.asyncio
    async def test_create_and_query_account(self, async_session):
        account = EmailAccount(
            user_id="test-user",
            email_address="test@example.com",
            imap_host="imap.example.com",
            imap_port=993,
            username="test@example.com",
            encrypted_password="encrypted-pw",
        )
        async_session.add(account)
        await async_session.flush()

        stmt = select(EmailAccount).where(EmailAccount.email_address == "test@example.com")
        result = await async_session.execute(stmt)
        found = result.scalar_one()

        assert found.user_id == "test-user"
        assert found.is_active is True
        assert found.id is not None

    @pytest.mark.asyncio
    async def test_email_account_unique_email_address(self, async_session):
        account1 = EmailAccount(
            user_id="user1",
            email_address="unique@example.com",
            imap_host="imap.example.com",
            imap_port=993,
            username="unique@example.com",
            encrypted_password="encrypted",
        )
        async_session.add(account1)
        await async_session.flush()

        account2 = EmailAccount(
            user_id="user2",
            email_address="unique@example.com",
            imap_host="imap.example.com",
            imap_port=993,
            username="unique@example.com",
            encrypted_password="encrypted2",
        )
        async_session.add(account2)

        with pytest.raises(Exception):
            await async_session.flush()


class TestEmailMessageModel:
    """Tests for EmailMessage ORM model."""

    def test_email_message_table_name(self):
        assert EmailMessage.__tablename__ == "email_messages"

    def test_email_message_has_required_columns(self):
        columns = {c.name for c in EmailMessage.__table__.columns}
        expected = {
            "id", "account_id", "uid", "message_id", "subject", "sender",
            "recipients", "date_received", "body_text", "body_html",
            "has_attachments", "is_read", "created_at", "updated_at",
        }
        assert expected.issubset(columns)

    def test_email_message_has_attachments_defaults_false(self):
        msg = EmailMessage(
            account_id=1,
            uid=100,
            message_id="<msg@example.com>",
            subject="Test",
            sender="sender@example.com",
            recipients="recipient@example.com",
            date_received=datetime(2024, 1, 15, tzinfo=timezone.utc),
        )
        assert msg.has_attachments is False

    def test_email_message_is_read_defaults_false(self):
        msg = EmailMessage(
            account_id=1,
            uid=100,
            message_id="<msg@example.com>",
            subject="Test",
            sender="sender@example.com",
            recipients="recipient@example.com",
            date_received=datetime(2024, 1, 15, tzinfo=timezone.utc),
        )
        assert msg.is_read is False

    def test_email_message_has_account_relationship(self):
        assert hasattr(EmailMessage, "account")

    def test_email_message_has_attachments_relationship(self):
        assert hasattr(EmailMessage, "attachments")

    @pytest.mark.asyncio
    async def test_create_and_query_message(self, async_session):
        account = EmailAccount(
            user_id="test-user",
            email_address="test@example.com",
            imap_host="imap.example.com",
            imap_port=993,
            username="test@example.com",
            encrypted_password="encrypted",
        )
        async_session.add(account)
        await async_session.flush()

        msg = EmailMessage(
            account_id=account.id,
            uid=100,
            message_id="<msg@example.com>",
            subject="Test Subject",
            sender="sender@example.com",
            recipients="recipient@example.com",
            date_received=datetime(2024, 1, 15, tzinfo=timezone.utc),
            body_text="Body text",
        )
        async_session.add(msg)
        await async_session.flush()

        stmt = select(EmailMessage).where(EmailMessage.message_id == "<msg@example.com>")
        result = await async_session.execute(stmt)
        found = result.scalar_one()

        assert found.subject == "Test Subject"
        assert found.account_id == account.id


class TestSyncStateModel:
    """Tests for SyncState ORM model."""

    def test_sync_state_table_name(self):
        assert SyncState.__tablename__ == "sync_states"

    def test_sync_state_has_required_columns(self):
        columns = {c.name for c in SyncState.__table__.columns}
        expected = {
            "id", "account_id", "folder_name", "last_synced_uid",
            "last_synced_at", "status", "created_at", "updated_at",
        }
        assert expected.issubset(columns)

    def test_sync_state_status_defaults_idle(self):
        state = SyncState(
            account_id=1,
            folder_name="INBOX",
        )
        assert state.status == "idle"

    def test_sync_state_last_synced_uid_defaults_zero(self):
        state = SyncState(
            account_id=1,
            folder_name="INBOX",
        )
        assert state.last_synced_uid == 0

    def test_sync_state_has_account_relationship(self):
        assert hasattr(SyncState, "account")

    @pytest.mark.asyncio
    async def test_create_and_query_sync_state(self, async_session):
        account = EmailAccount(
            user_id="test-user",
            email_address="test@example.com",
            imap_host="imap.example.com",
            imap_port=993,
            username="test@example.com",
            encrypted_password="encrypted",
        )
        async_session.add(account)
        await async_session.flush()

        state = SyncState(
            account_id=account.id,
            folder_name="INBOX",
            last_synced_uid=100,
            status="idle",
        )
        async_session.add(state)
        await async_session.flush()

        stmt = select(SyncState).where(
            SyncState.account_id == account.id,
            SyncState.folder_name == "INBOX",
        )
        result = await async_session.execute(stmt)
        found = result.scalar_one()

        assert found.last_synced_uid == 100
        assert found.status == "idle"


class TestAttachmentModel:
    """Tests for Attachment ORM model."""

    def test_attachment_table_name(self):
        assert Attachment.__tablename__ == "attachments"

    def test_attachment_has_required_columns(self):
        columns = {c.name for c in Attachment.__table__.columns}
        expected = {
            "id", "message_id", "filename", "content_type",
            "size_bytes", "storage_path", "created_at", "updated_at",
        }
        assert expected.issubset(columns)

    def test_attachment_has_message_relationship(self):
        assert hasattr(Attachment, "message")

    @pytest.mark.asyncio
    async def test_create_and_query_attachment(self, async_session):
        account = EmailAccount(
            user_id="test-user",
            email_address="test@example.com",
            imap_host="imap.example.com",
            imap_port=993,
            username="test@example.com",
            encrypted_password="encrypted",
        )
        async_session.add(account)
        await async_session.flush()

        msg = EmailMessage(
            account_id=account.id,
            uid=100,
            message_id="<msg@example.com>",
            subject="Test",
            sender="sender@example.com",
            recipients="recipient@example.com",
            date_received=datetime(2024, 1, 15, tzinfo=timezone.utc),
            has_attachments=True,
        )
        async_session.add(msg)
        await async_session.flush()

        att = Attachment(
            message_id=msg.id,
            filename="report.pdf",
            content_type="application/pdf",
            size_bytes=1024,
            storage_path="/tmp/report.pdf",
        )
        async_session.add(att)
        await async_session.flush()

        stmt = select(Attachment).where(Attachment.message_id == msg.id)
        result = await async_session.execute(stmt)
        found = result.scalar_one()

        assert found.filename == "report.pdf"
        assert found.size_bytes == 1024


class TestCascadeDeletes:
    """Tests for cascade delete behavior."""

    @pytest.mark.asyncio
    async def test_delete_account_cascades_to_messages(self, async_session):
        account = EmailAccount(
            user_id="test-user",
            email_address="cascade@example.com",
            imap_host="imap.example.com",
            imap_port=993,
            username="cascade@example.com",
            encrypted_password="encrypted",
        )
        async_session.add(account)
        await async_session.flush()

        msg = EmailMessage(
            account_id=account.id,
            uid=100,
            message_id="<cascade-msg@example.com>",
            subject="Test",
            sender="sender@example.com",
            recipients="recipient@example.com",
            date_received=datetime(2024, 1, 15, tzinfo=timezone.utc),
        )
        async_session.add(msg)
        await async_session.flush()

        msg_id = msg.id

        await async_session.delete(account)
        await async_session.flush()

        from sqlalchemy import select as sa_select
        stmt = sa_select(EmailMessage).where(EmailMessage.id == msg_id)
        result = await async_session.execute(stmt)
        found = result.scalar_one_or_none()
        assert found is None

    @pytest.mark.asyncio
    async def test_delete_account_cascades_to_sync_states(self, async_session):
        account = EmailAccount(
            user_id="test-user",
            email_address="cascade2@example.com",
            imap_host="imap.example.com",
            imap_port=993,
            username="cascade2@example.com",
            encrypted_password="encrypted",
        )
        async_session.add(account)
        await async_session.flush()

        state = SyncState(
            account_id=account.id,
            folder_name="INBOX",
        )
        async_session.add(state)
        await async_session.flush()

        state_id = state.id

        await async_session.delete(account)
        await async_session.flush()

        stmt = select(SyncState).where(SyncState.id == state_id)
        result = await async_session.execute(stmt)
        found = result.scalar_one_or_none()
        assert found is None

    @pytest.mark.asyncio
    async def test_delete_message_cascades_to_attachments(self, async_session):
        account = EmailAccount(
            user_id="test-user",
            email_address="cascade3@example.com",
            imap_host="imap.example.com",
            imap_port=993,
            username="cascade3@example.com",
            encrypted_password="encrypted",
        )
        async_session.add(account)
        await async_session.flush()

        msg = EmailMessage(
            account_id=account.id,
            uid=100,
            message_id="<cascade3-msg@example.com>",
            subject="Test",
            sender="sender@example.com",
            recipients="recipient@example.com",
            date_received=datetime(2024, 1, 15, tzinfo=timezone.utc),
            has_attachments=True,
        )
        async_session.add(msg)
        await async_session.flush()

        att = Attachment(
            message_id=msg.id,
            filename="file.pdf",
            content_type="application/pdf",
            size_bytes=512,
            storage_path="/tmp/file.pdf",
        )
        async_session.add(att)
        await async_session.flush()

        att_id = att.id

        await async_session.delete(msg)
        await async_session.flush()

        stmt = select(Attachment).where(Attachment.id == att_id)
        result = await async_session.execute(stmt)
        found = result.scalar_one_or_none()
        assert found is None
