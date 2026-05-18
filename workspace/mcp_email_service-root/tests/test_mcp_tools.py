"""Tests for MCP tool definitions."""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_server.tools import register_tools, set_dependencies, AppDependencies


class TestListEmailsTool:
    """Tests for the list_emails MCP tool."""

    @pytest.mark.asyncio
    async def test_list_emails_returns_json_with_items(self):
        from mcp_server import tools
        from db.models import EmailMessage

        mock_session = AsyncMock()
        mock_msg = MagicMock()
        mock_msg.id = 1
        mock_msg.account_id = 1
        mock_msg.uid = 100
        mock_msg.message_id = "<msg1@example.com>"
        mock_msg.subject = "Test Subject"
        mock_msg.sender = "sender@example.com"
        mock_msg.recipients = "recipient@example.com"
        mock_msg.date_received = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        mock_msg.has_attachments = False
        mock_msg.is_read = False

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_msg]

        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 1

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_count_result
            return mock_result

        mock_session.execute = mock_execute

        with patch("mcp_server.tools.list_emails.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await tools.list_emails(account_id=1, limit=20, offset=0)

        data = json.loads(result)
        assert "items" in data
        assert "total" in data
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["subject"] == "Test Subject"

    @pytest.mark.asyncio
    async def test_list_emails_with_search_filter(self):
        from mcp_server import tools

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 0

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_count_result
            return mock_result

        mock_session.execute = mock_execute

        with patch("mcp_server.tools.list_emails.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await tools.list_emails(account_id=1, search="invoice")

        data = json.loads(result)
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_list_emails_with_read_filter(self):
        from mcp_server import tools

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 0

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_count_result
            return mock_result

        mock_session.execute = mock_execute

        with patch("mcp_server.tools.list_emails.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await tools.list_emails(account_id=1, is_read=True)

        data = json.loads(result)
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_list_emails_empty(self):
        from mcp_server import tools

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 0

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_count_result
            return mock_result

        mock_session.execute = mock_execute

        with patch("mcp_server.tools.list_emails.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await tools.list_emails(account_id=1)

        data = json.loads(result)
        assert data["items"] == []
        assert data["total"] == 0


class TestGetEmailTool:
    """Tests for the get_email MCP tool."""

    @pytest.mark.asyncio
    async def test_get_email_returns_full_details(self):
        from mcp_server import tools

        mock_session = AsyncMock()
        mock_msg = MagicMock()
        mock_msg.id = 1
        mock_msg.account_id = 1
        mock_msg.uid = 100
        mock_msg.message_id = "<msg1@example.com>"
        mock_msg.subject = "Test Subject"
        mock_msg.sender = "sender@example.com"
        mock_msg.recipients = "recipient@example.com"
        mock_msg.date_received = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        mock_msg.body_text = "Body text"
        mock_msg.body_html = "<p>HTML</p>"
        mock_msg.has_attachments = True
        mock_msg.is_read = False
        mock_msg.created_at = datetime(2024, 1, 15, tzinfo=timezone.utc)

        mock_att = MagicMock()
        mock_att.id = 1
        mock_att.filename = "report.pdf"
        mock_att.content_type = "application/pdf"
        mock_att.size_bytes = 1024
        mock_att.storage_path = "/tmp/report.pdf"

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.scalar_one_or_none = MagicMock(return_value=mock_msg)
            else:
                mock_result.scalars.return_value.all.return_value = [mock_att]
            return mock_result

        mock_session.execute = mock_execute

        with patch("mcp_server.tools.get_email.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await tools.get_email(message_id=1)

        data = json.loads(result)
        assert data["id"] == 1
        assert data["subject"] == "Test Subject"
        assert data["body_text"] == "Body text"
        assert data["body_html"] == "<p>HTML</p>"
        assert len(data["attachments"]) == 1
        assert data["attachments"][0]["filename"] == "report.pdf"

    @pytest.mark.asyncio
    async def test_get_email_raises_for_nonexistent(self):
        from mcp_server import tools

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_session.execute.return_value = mock_result

        with patch("mcp_server.tools.get_email.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(ValueError, match="Message .* not found"):
                await tools.get_email(message_id=999)


class TestSearchEmailsTool:
    """Tests for the search_emails MCP tool."""

    @pytest.mark.asyncio
    async def test_search_emails_returns_matches(self):
        from mcp_server import tools

        mock_session = AsyncMock()
        mock_msg = MagicMock()
        mock_msg.id = 1
        mock_msg.subject = "Invoice from Acme"
        mock_msg.sender = "billing@acme.com"
        mock_msg.date_received = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        mock_msg.is_read = False
        mock_msg.has_attachments = True

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_msg]
        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 1

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_count_result
            return mock_result

        mock_session.execute = mock_execute

        with patch("mcp_server.tools.search_emails.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await tools.search_emails(account_id=1, query="invoice")

        data = json.loads(result)
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["subject"] == "Invoice from Acme"

    @pytest.mark.asyncio
    async def test_search_emails_no_matches(self):
        from mcp_server import tools

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 0

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_count_result
            return mock_result

        mock_session.execute = mock_execute

        with patch("mcp_server.tools.search_emails.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await tools.search_emails(account_id=1, query="nonexistent")

        data = json.loads(result)
        assert data["total"] == 0
        assert data["items"] == []


class TestSyncAccountTool:
    """Tests for the sync_account MCP tool."""

    @pytest.mark.asyncio
    async def test_sync_account_success(self, mock_mcp_context):
        from mcp_server import tools

        mock_session = AsyncMock()
        mock_account = MagicMock()
        mock_account.id = 1
        mock_account.is_active = True
        mock_account.imap_host = "imap.example.com"
        mock_account.imap_port = 993
        mock_account.username = "test@example.com"
        mock_account.encrypted_password = "encrypted"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_account)
        mock_session.execute.return_value = mock_result

        with patch("mcp_server.tools.sync_account.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("mcp_server.tools.sync_account._require_deps") as mock_deps:
                mock_sync = MagicMock()
                mock_sync.sync_account = AsyncMock(return_value={"INBOX": 5})
                mock_deps.return_value.sync_manager = mock_sync

                result = await tools.sync_account(mock_mcp_context, account_id=1)

        data = json.loads(result)
        assert data["status"] == "success"
        assert data["account_id"] == 1

    @pytest.mark.asyncio
    async def test_sync_account_raises_for_nonexistent(self, mock_mcp_context):
        from mcp_server import tools

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_session.execute.return_value = mock_result

        with patch("mcp_server.tools.sync_account.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(ValueError, match="Account .* not found"):
                await tools.sync_account(mock_mcp_context, account_id=999)

    @pytest.mark.asyncio
    async def test_sync_account_raises_for_inactive(self, mock_mcp_context):
        from mcp_server import tools

        mock_session = AsyncMock()
        mock_account = MagicMock()
        mock_account.is_active = False

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_account)
        mock_session.execute.return_value = mock_result

        with patch("mcp_server.tools.sync_account.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(ValueError, match="Account .* is inactive"):
                await tools.sync_account(mock_mcp_context, account_id=1)

    @pytest.mark.asyncio
    async def test_sync_account_with_folders(self, mock_mcp_context):
        from mcp_server import tools

        mock_session = AsyncMock()
        mock_account = MagicMock()
        mock_account.id = 1
        mock_account.is_active = True

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_account)
        mock_session.execute.return_value = mock_result

        with patch("mcp_server.tools.sync_account.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("mcp_server.tools.sync_account._require_deps") as mock_deps:
                mock_sync = MagicMock()
                mock_sync.sync_account = AsyncMock(return_value={"INBOX": 3, "Sent": 2})
                mock_deps.return_value.sync_manager = mock_sync

                result = await tools.sync_account(
                    mock_mcp_context, account_id=1, folders="INBOX,Sent"
                )

        data = json.loads(result)
        assert data["status"] == "success"
        mock_mcp_context.info.assert_called()


class TestMarkReadTool:
    """Tests for the mark_read MCP tool."""

    @pytest.mark.asyncio
    async def test_mark_read_success(self):
        from mcp_server import tools

        mock_session = AsyncMock()
        mock_msg = MagicMock()
        mock_msg.id = 1
        mock_msg.account_id = 1

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_msg)
        mock_session.execute.return_value = mock_result

        with patch("mcp_server.tools.mark_read.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("mcp_server.tools.mark_read._require_deps") as mock_deps:
                mock_deps.return_value.sync_manager.mark_read = AsyncMock()

                result = await tools.mark_read(message_id=1)

        data = json.loads(result)
        assert data["status"] == "success"
        assert data["message_id"] == 1
        assert data["account_id"] == 1

    @pytest.mark.asyncio
    async def test_mark_read_raises_for_nonexistent(self):
        from mcp_server import tools

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_session.execute.return_value = mock_result

        with patch("mcp_server.tools.mark_read.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(ValueError, match="Message .* not found"):
                await tools.mark_read(message_id=999)


class TestListAccountsTool:
    """Tests for the list_accounts MCP tool."""

    @pytest.mark.asyncio
    async def test_list_accounts_returns_json_array(self):
        from mcp_server import tools

        mock_session = AsyncMock()
        mock_acc = MagicMock()
        mock_acc.id = 1
        mock_acc.email_address = "test@example.com"
        mock_acc.imap_host = "imap.example.com"
        mock_acc.imap_port = 993
        mock_acc.is_active = True
        mock_acc.created_at = datetime(2024, 1, 15, tzinfo=timezone.utc)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_acc]
        mock_session.execute.return_value = mock_result

        with patch("mcp_server.tools.sync_account.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await tools.list_accounts()

        data = json.loads(result)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["email_address"] == "test@example.com"

    @pytest.mark.asyncio
    async def test_list_accounts_empty(self):
        from mcp_server import tools

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        with patch("mcp_server.tools.sync_account.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await tools.list_accounts()

        data = json.loads(result)
        assert data == []


class TestAddAccountTool:
    """Tests for the add_account MCP tool."""

    @pytest.mark.asyncio
    async def test_add_account_success(self):
        from mcp_server import tools

        mock_session = AsyncMock()
        mock_account = MagicMock()
        mock_account.id = 1
        mock_account.email_address = "new@example.com"

        async def mock_add_side_effect(obj):
            obj.id = 1

        mock_session.add.side_effect = mock_add_side_effect

        mock_settings = MagicMock()
        mock_encryption_manager = MagicMock()
        mock_encryption_manager.encrypt.return_value = "encrypted-pw"
        mock_settings.get_encryption_manager.return_value = mock_encryption_manager

        with patch("mcp_server.tools.add_account.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("mcp_server.tools.add_account.get_settings", return_value=mock_settings):
                result = await tools.add_account(
                    email_address="new@example.com",
                    imap_host="imap.example.com",
                    username="new@example.com",
                    password="secret",
                )

        data = json.loads(result)
        assert data["status"] == "created"
        assert data["email_address"] == "new@example.com"
        mock_encryption_manager.encrypt.assert_called_once_with("secret")

    @pytest.mark.asyncio
    async def test_add_account_with_custom_user_id(self):
        from mcp_server import tools

        mock_session = AsyncMock()
        mock_account = MagicMock()
        mock_account.id = 1
        mock_account.email_address = "new@example.com"

        async def mock_add_side_effect(obj):
            obj.id = 1

        mock_session.add.side_effect = mock_add_side_effect

        mock_settings = MagicMock()
        mock_encryption_manager = MagicMock()
        mock_encryption_manager.encrypt.return_value = "encrypted-pw"
        mock_settings.get_encryption_manager.return_value = mock_encryption_manager

        with patch("mcp_server.tools.add_account.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("mcp_server.tools.add_account.get_settings", return_value=mock_settings):
                result = await tools.add_account(
                    email_address="new@example.com",
                    imap_host="imap.example.com",
                    username="new@example.com",
                    password="secret",
                    user_id="custom-user",
                )

        data = json.loads(result)
        assert data["status"] == "created"


class TestGetSyncStateTool:
    """Tests for the get_sync_state MCP tool."""

    @pytest.mark.asyncio
    async def test_get_sync_state_returns_folders(self):
        from mcp_server import tools

        mock_session = AsyncMock()

        with patch("mcp_server.tools.sync_account.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch.object(tools, "_require_deps") as mock_deps:
                mock_deps.return_value.sync_manager.get_sync_state = AsyncMock(return_value=[
                    {"folder_name": "INBOX", "last_synced_uid": 100, "last_synced_at": datetime.now(timezone.utc), "status": "idle"},
                    {"folder_name": "Sent", "last_synced_uid": 50, "last_synced_at": datetime.now(timezone.utc), "status": "idle"},
                ])

                result = await tools.get_sync_state(account_id=1)

        data = json.loads(result)
        assert data["account_id"] == 1
        assert len(data["folders"]) == 2
        assert data["folders"][0]["folder_name"] == "INBOX"
        assert data["folders"][1]["folder_name"] == "Sent"

    @pytest.mark.asyncio
    async def test_get_sync_state_empty(self):
        from mcp_server import tools

        mock_session = AsyncMock()

        with patch("mcp_server.tools.sync_account.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch.object(tools, "_require_deps") as mock_deps:
                mock_deps.return_value.sync_manager.get_sync_state = AsyncMock(return_value=[])

                result = await tools.get_sync_state(account_id=1)

        data = json.loads(result)
        assert data["account_id"] == 1
        assert data["folders"] == []


class TestRegisterTools:
    """Tests for the register_tools function."""

    def test_register_tools_attaches_tools_to_mcp(self):
        mock_mcp = MagicMock()

        register_tools(mock_mcp)

        assert mock_mcp.tool.call_count >= 9
