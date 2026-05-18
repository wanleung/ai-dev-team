"""Tests for SyncManager."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sync.manager import SyncManager
from db.models import EmailAccount, EmailMessage, SyncState


class TestSyncManagerInit:
    """Tests for SyncManager initialization."""

    def test_default_values(self, mock_connection_pool):
        manager = SyncManager(connection_pool=mock_connection_pool)
        assert manager.connection_pool is mock_connection_pool
        assert manager.sync_interval == 300
        assert manager.batch_size == 100

    def test_custom_values(self, mock_connection_pool):
        manager = SyncManager(
            connection_pool=mock_connection_pool,
            sync_interval=600,
            batch_size=50,
        )
        assert manager.sync_interval == 600
        assert manager.batch_size == 50


class TestSyncManagerSyncAccount:
    """Tests for sync_account."""

    @pytest.mark.asyncio
    async def test_sync_account_raises_for_nonexistent(self, mock_connection_pool):
        manager = SyncManager(connection_pool=mock_connection_pool)

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_session.execute.return_value = mock_result

        with pytest.raises(ValueError, match="Account .* not found"):
            await manager.sync_account(999, mock_session)

    @pytest.mark.asyncio
    async def test_sync_account_skips_inactive(self, mock_connection_pool):
        manager = SyncManager(connection_pool=mock_connection_pool)

        mock_account = MagicMock()
        mock_account.is_active = False

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_account)
        mock_session.execute.return_value = mock_result

        result = await manager.sync_account(1, mock_session)
        assert result == {}


class TestSyncManagerGetSyncState:
    """Tests for get_sync_state."""

    @pytest.mark.asyncio
    async def test_get_sync_state_returns_list(self, mock_connection_pool):
        manager = SyncManager(connection_pool=mock_connection_pool)

        mock_state = MagicMock()
        mock_state.folder_name = "INBOX"
        mock_state.last_synced_uid = 100
        mock_state.last_synced_at = datetime.now(timezone.utc)
        mock_state.status = "idle"

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_state]
        mock_session.execute.return_value = mock_result

        states = await manager.get_sync_state(mock_session, 1)
        assert len(states) == 1
        assert states[0]["folder_name"] == "INBOX"
        assert states[0]["last_synced_uid"] == 100


class TestSyncManagerMarkRead:
    """Tests for mark_read."""

    @pytest.mark.asyncio
    async def test_mark_read_raises_for_nonexistent(self, mock_connection_pool):
        manager = SyncManager(connection_pool=mock_connection_pool)

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_session.execute.return_value = mock_result

        with pytest.raises(ValueError, match="Message .* not found"):
            await manager.mark_read(mock_session, 999)

    @pytest.mark.asyncio
    async def test_mark_read_updates_database(self, mock_connection_pool):
        manager = SyncManager(connection_pool=mock_connection_pool)

        mock_msg = MagicMock()
        mock_msg.id = 1
        mock_msg.uid = 100
        mock_msg.is_read = False

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_msg)
        mock_session.execute.return_value = mock_result

        await manager.mark_read(mock_session, 1)
        assert mock_msg.is_read is True

    @pytest.mark.asyncio
    async def test_mark_read_calls_imap_when_client_provided(self, mock_connection_pool, mock_imap_client):
        manager = SyncManager(connection_pool=mock_connection_pool)

        mock_msg = MagicMock()
        mock_msg.id = 1
        mock_msg.uid = 100
        mock_msg.is_read = False

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_msg)
        mock_session.execute.return_value = mock_result

        mock_imap_client.is_connected = True

        await manager.mark_read(mock_session, 1, client=mock_imap_client)
        mock_imap_client.mark_as_read.assert_called_once_with(uid=100)

    @pytest.mark.asyncio
    async def test_mark_read_handles_imap_error_gracefully(self, mock_connection_pool, mock_imap_client):
        manager = SyncManager(connection_pool=mock_connection_pool)

        mock_msg = MagicMock()
        mock_msg.id = 1
        mock_msg.uid = 100
        mock_msg.is_read = False

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_msg)
        mock_session.execute.return_value = mock_result

        mock_imap_client.is_connected = True
        mock_imap_client.mark_as_read = AsyncMock(side_effect=Exception("IMAP error"))

        await manager.mark_read(mock_session, 1, client=mock_imap_client)
        assert mock_msg.is_read is True


class TestSyncManagerBackgroundSync:
    """Tests for background sync lifecycle."""

    @pytest.mark.asyncio
    async def test_start_background_sync(self, mock_connection_pool):
        manager = SyncManager(connection_pool=mock_connection_pool, sync_interval=1)
        manager.start_background_sync()
        assert manager._running is True
        assert manager._background_task is not None
        await manager.stop_background_sync()

    @pytest.mark.asyncio
    async def test_stop_background_sync(self, mock_connection_pool):
        manager = SyncManager(connection_pool=mock_connection_pool)
        manager.start_background_sync()
        await manager.stop_background_sync()
        assert manager._running is False
        assert manager._background_task is None

    @pytest.mark.asyncio
    async def test_start_background_sync_twice_warns(self, mock_connection_pool, caplog):
        manager = SyncManager(connection_pool=mock_connection_pool)
        manager.start_background_sync()
        manager.start_background_sync()
        await manager.stop_background_sync()


class TestSyncManagerSyncFolder:
    """Tests for _sync_folder."""

    @pytest.mark.asyncio
    async def test_sync_folder_no_new_messages(self, mock_connection_pool, mock_imap_client):
        manager = SyncManager(connection_pool=mock_connection_pool, batch_size=100)

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()

        existing_state = MagicMock()
        existing_state.last_synced_uid = 100

        def execute_side_effect(stmt):
            mock_result = MagicMock()
            if "SyncState" in str(stmt):
                mock_result.scalar_one_or_none = MagicMock(return_value=existing_state)
            else:
                mock_result.scalar_one_or_none = MagicMock(return_value=None)
            return mock_result

        mock_session.execute.side_effect = execute_side_effect
        mock_session.flush = AsyncMock()
        mock_session.add = MagicMock()

        mock_imap_client.get_uids = AsyncMock(return_value=[50, 60, 70])

        result = await manager._sync_folder(
            mock_imap_client, 1, "INBOX", mock_session
        )
        assert result == 0


class TestSyncManagerPersistEmail:
    """Tests for _persist_email."""

    @pytest.mark.asyncio
    async def test_persist_email(self, mock_connection_pool):
        from parser.email_parser import ParsedEmail

        manager = SyncManager(connection_pool=mock_connection_pool)

        parsed = ParsedEmail(
            message_id="<test@example.com>",
            subject="Test",
            sender="sender@example.com",
            sender_email="sender@example.com",
            recipients=["recipient@example.com"],
            recipients_raw="recipient@example.com",
            date_received=datetime.now(timezone.utc),
            body_text="Body",
            body_html="",
            has_attachments=False,
        )

        mock_session = AsyncMock()
        mock_session.flush = AsyncMock()

        msg = await manager._persist_email(mock_session, 1, 100, parsed)

        mock_session.add.assert_called()
        assert msg.subject == "Test"
        assert msg.sender == "sender@example.com"


class TestSyncManagerMessageExists:
    """Tests for _message_exists."""

    @pytest.mark.asyncio
    async def test_message_exists_true(self, mock_connection_pool):
        manager = SyncManager(connection_pool=mock_connection_pool)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=MagicMock())
        mock_session.execute.return_value = mock_result

        exists = await manager._message_exists(mock_session, 1, "<msg@example.com>")
        assert exists is True

    @pytest.mark.asyncio
    async def test_message_exists_false(self, mock_connection_pool):
        manager = SyncManager(connection_pool=mock_connection_pool)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_session.execute.return_value = mock_result

        exists = await manager._message_exists(mock_session, 1, "<msg@example.com>")
        assert exists is False

    @pytest.mark.asyncio
    async def test_message_exists_empty_message_id(self, mock_connection_pool):
        manager = SyncManager(connection_pool=mock_connection_pool)
        mock_session = AsyncMock()

        exists = await manager._message_exists(mock_session, 1, "")
        assert exists is False


class TestSyncManagerExtractUid:
    """Tests for _extract_uid_from_message."""

    def test_extract_uid_from_header(self):
        from email.message import Message
        msg = Message()
        msg["X-UID"] = "42"
        uid = SyncManager._extract_uid_from_message(msg)
        assert uid == 42

    def test_extract_uid_no_header(self):
        from email.message import Message
        msg = Message()
        uid = SyncManager._extract_uid_from_message(msg)
        assert uid is None

    def test_extract_uid_invalid_value(self):
        from email.message import Message
        msg = Message()
        msg["X-UID"] = "not-a-number"
        uid = SyncManager._extract_uid_from_message(msg)
        assert uid is None


class TestSyncManagerGetOrCreateSyncState:
    """Tests for _get_or_create_sync_state."""

    @pytest.mark.asyncio
    async def test_get_existing_sync_state(self, mock_connection_pool):
        manager = SyncManager(connection_pool=mock_connection_pool)

        mock_state = MagicMock()
        mock_state.folder_name = "INBOX"
        mock_state.last_synced_uid = 50

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_state)
        mock_session.execute.return_value = mock_result

        state = await manager._get_or_create_sync_state(mock_session, 1, "INBOX")
        assert state is mock_state

    @pytest.mark.asyncio
    async def test_create_new_sync_state(self, mock_connection_pool):
        manager = SyncManager(connection_pool=mock_connection_pool)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_session.execute.return_value = mock_result
        mock_session.flush = AsyncMock()
        mock_session.add = MagicMock()

        state = await manager._get_or_create_sync_state(mock_session, 1, "INBOX")
        mock_session.add.assert_called()
