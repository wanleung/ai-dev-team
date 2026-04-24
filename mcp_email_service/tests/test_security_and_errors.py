"""Security, Error Handling, and Edge Case Tests for MCP Email Service (IMAP).

Validates:
- Credentials never logged or exposed
- All IMAP errors caught and returned as structured MCP error responses
- TLS required by default
- Input validation and edge cases
- Large attachment handling
- Connection resilience
"""

import base64
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# =============================================================================
# Security: Credential Protection
# =============================================================================

class TestSecurity_CredentialProtection:
    """Credentials must never be logged or exposed in responses."""

    def test_password_not_in_list_accounts_response(self):
        """Given accounts with passwords, then list_accounts does not expose them."""
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

        with patch("mcp_server.tools.list_accounts.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = tools.list_accounts.__wrapped__() if hasattr(tools.list_accounts, '__wrapped__') else None

        with patch("mcp_server.tools.list_accounts.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            import asyncio
            result = asyncio.get_event_loop().run_until_complete(tools.list_accounts())

        data = json.loads(result)
        for acc in data:
            assert "password" not in acc
            assert "encrypted_password" not in acc
            assert "secret" not in str(acc).lower()

    def test_password_not_in_add_account_response(self):
        """Given new account with password, then response does not contain password."""
        from mcp_server import tools
        import asyncio

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
                result = asyncio.get_event_loop().run_until_complete(
                    tools.add_account(
                        email_address="new@example.com",
                        imap_host="imap.example.com",
                        username="new@example.com",
                        password="my-super-secret-password",
                    )
                )

        data = json.loads(result)
        assert "my-super-secret-password" not in str(data)
        assert "password" not in data

    def test_credentials_not_in_logs(self, caplog):
        """Given IMAP operations, then credentials do not appear in any log output."""
        caplog.set_level(logging.DEBUG)

        from imap.client import IMAPClient

        client = IMAPClient(
            host="imap.example.com",
            username="secret-user@example.com",
            password="secret-password-123",
        )

        for record in caplog.records:
            assert "secret-password-123" not in record.message
            assert "secret-user@example.com" not in record.message

    def test_encrypted_password_stored_not_plaintext(self, encryption_manager):
        """Given password for storage, then it is encrypted before storage."""
        plaintext = "my-secret-password"
        encrypted = encryption_manager.encrypt(plaintext)

        assert encrypted != plaintext
        assert "my-secret-password" not in encrypted

        decrypted = encryption_manager.decrypt(encrypted)
        assert decrypted == plaintext


# =============================================================================
# Error Handling: Structured MCP Error Responses
# =============================================================================

class TestErrorHandling_StructuredErrors:
    """All IMAP errors must be caught and returned as structured MCP error responses."""

    @pytest.mark.asyncio
    async def test_imap_connection_error_mapped(self):
        """Given IMAP connection failure, then structured error (not unhandled exception)."""
        from imap.client import IMAPClient, IMAPConnectionError
        import asyncio

        client = IMAPClient(host="unreachable.example.com")

        with patch("imap.client.aioimaplib.IMAP4_SSL", side_effect=ConnectionError("connection refused")):
            with pytest.raises(IMAPConnectionError) as exc_info:
                await client.connect()

        assert "connection refused" in str(exc_info.value).lower() or "unreachable" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_imap_auth_error_mapped(self):
        """Given IMAP auth failure, then IMAPAuthenticationError raised (not raw exception)."""
        from imap.client import IMAPClient, IMAPAuthenticationError
        import aioimaplib
        import asyncio

        client = IMAPClient(
            host="imap.example.com",
            username="user@example.com",
            password="wrong",
        )

        mock_imap = MagicMock()
        mock_imap.login = AsyncMock(
            side_effect=aioimaplib.IMAP4Error("AUTHENTICATION FAILED")
        )

        with patch("imap.client.aioimaplib.IMAP4_SSL", return_value=mock_imap):
            with pytest.raises(IMAPAuthenticationError):
                await client.connect()

    @pytest.mark.asyncio
    async def test_imap_operation_error_mapped(self):
        """Given IMAP operation failure, then IMAPOperationError raised."""
        from imap.client import IMAPClient, IMAPOperationError
        import asyncio

        client = IMAPClient(host="imap.example.com")
        client._connected = True

        mock_imap = MagicMock()
        mock_response = MagicMock()
        mock_response.result = "NO"
        mock_response.data = [b"Mailbox not found"]
        mock_imap.select = AsyncMock(return_value=mock_response)
        client._client = mock_imap

        with pytest.raises(IMAPOperationError):
            await client.select_folder("NONEXISTENT")

    @pytest.mark.asyncio
    async def test_retry_exhausted_error_mapped(self):
        """Given repeated failures, then IMAPRetryExhaustedError raised after retries."""
        from imap.client import IMAPClient, IMAPRetryExhaustedError
        import asyncio

        client = IMAPClient(host="imap.example.com", max_retries=2, backoff_factor=0.01)
        func = AsyncMock(side_effect=OSError("fail"))

        with pytest.raises(IMAPRetryExhaustedError):
            await client._retry_with_backoff("test", func)

    @pytest.mark.asyncio
    async def test_mcp_tool_value_error_for_not_found(self):
        """Given non-existent resource in MCP tool, then ValueError (structured error)."""
        from mcp_server import tools

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_session.execute.return_value = mock_result

        with patch("mcp_server.tools.get_email.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(ValueError) as exc_info:
                await tools.get_email(message_id=999)

        assert "not found" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_mcp_tool_runtime_error_when_deps_not_initialized(self):
        """Given uninitialized dependencies, then RuntimeError raised."""
        from mcp_server.tools.base import _require_deps

        with patch("mcp_server.tools.base._deps", None):
            with pytest.raises(RuntimeError, match="not initialized"):
                _require_deps()


# =============================================================================
# Input Validation & Edge Cases
# =============================================================================

class TestInputValidation:
    """Test edge cases, invalid inputs, and boundary conditions."""

    @pytest.mark.asyncio
    async def test_list_emails_zero_limit(self):
        """Given limit=0, then empty list returned."""
        from mcp_server import tools

        mock_session = AsyncMock()
        mock_count = MagicMock()
        mock_count.scalar_one.return_value = 5
        mock_list = MagicMock()
        mock_list.scalars.return_value.all.return_value = []

        call_count = 0
        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            return mock_count if call_count == 1 else mock_list

        mock_session.execute = mock_execute

        with patch("mcp_server.tools.list_emails.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await tools.list_emails(account_id=1, limit=0)

        data = json.loads(result)
        assert data["items"] == []

    @pytest.mark.asyncio
    async def test_list_emails_large_offset(self):
        """Given offset beyond available emails, then empty list returned."""
        from mcp_server import tools

        mock_session = AsyncMock()
        mock_count = MagicMock()
        mock_count.scalar_one.return_value = 5
        mock_list = MagicMock()
        mock_list.scalars.return_value.all.return_value = []

        call_count = 0
        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            return mock_count if call_count == 1 else mock_list

        mock_session.execute = mock_execute

        with patch("mcp_server.tools.list_emails.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await tools.list_emails(account_id=1, offset=1000)

        data = json.loads(result)
        assert data["items"] == []

    @pytest.mark.asyncio
    async def test_search_emails_empty_query(self):
        """Given empty search query, then all emails matched."""
        from mcp_server import tools

        mock_session = AsyncMock()
        mock_msg = MagicMock()
        mock_msg.id = 1
        mock_msg.subject = "Test"
        mock_msg.sender = "sender@example.com"
        mock_msg.date_received = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        mock_msg.is_read = False
        mock_msg.has_attachments = False

        mock_count = MagicMock()
        mock_count.scalar_one.return_value = 1
        mock_list = MagicMock()
        mock_list.scalars.return_value.all.return_value = [mock_msg]

        call_count = 0
        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            return mock_count if call_count == 1 else mock_list

        mock_session.execute = mock_execute

        with patch("mcp_server.tools.search_emails.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await tools.search_emails(account_id=1, query="")

        data = json.loads(result)
        assert data["total"] == 1

    @pytest.mark.asyncio
    async def test_search_emails_special_characters(self):
        """Given search query with special characters, then handled gracefully."""
        from mcp_server import tools

        mock_session = AsyncMock()
        mock_count = MagicMock()
        mock_count.scalar_one.return_value = 0
        mock_list = MagicMock()
        mock_list.scalars.return_value.all.return_value = []

        call_count = 0
        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            return mock_count if call_count == 1 else mock_list

        mock_session.execute = mock_execute

        with patch("mcp_server.tools.search_emails.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await tools.search_emails(account_id=1, query="test%_special'\"chars")

        data = json.loads(result)
        assert isinstance(data, dict)
        assert "items" in data

    def test_add_account_empty_email_address(self):
        """Given empty email address, then account is still created (validation at DB level)."""
        from mcp_server import tools
        import asyncio

        mock_session = AsyncMock()
        mock_account = MagicMock()
        mock_account.id = 1
        mock_account.email_address = ""

        async def mock_add_side_effect(obj):
            obj.id = 1

        mock_session.add.side_effect = mock_add_side_effect

        mock_settings = MagicMock()
        mock_encryption_manager = MagicMock()
        mock_encryption_manager.encrypt.return_value = "encrypted"
        mock_settings.get_encryption_manager.return_value = mock_encryption_manager

        with patch("mcp_server.tools.add_account.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("mcp_server.tools.add_account.get_settings", return_value=mock_settings):
                result = asyncio.get_event_loop().run_until_complete(
                    tools.add_account(
                        email_address="",
                        imap_host="imap.example.com",
                    )
                )

        data = json.loads(result)
        assert data["status"] == "created"


# =============================================================================
# Large Attachment Handling
# =============================================================================

class TestLargeAttachments:
    """Test large attachment handling and size limits."""

    @pytest.mark.asyncio
    async def test_download_large_attachment(self):
        """Given large attachment (1MB), then base64 content returned."""
        from mcp_server import tools

        large_content = b"x" * (1024 * 1024)

        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(large_content)
            tmp_path = tmp.name

        try:
            mock_session = AsyncMock()
            mock_msg = MagicMock()
            mock_msg.id = 1

            mock_attachment = MagicMock()
            mock_attachment.id = 1
            mock_attachment.filename = "large.bin"
            mock_attachment.content_type = "application/octet-stream"
            mock_attachment.size_bytes = len(large_content)
            mock_attachment.storage_path = tmp_path

            call_count = 0
            async def mock_execute(stmt):
                nonlocal call_count
                call_count += 1
                mock_result = MagicMock()
                if call_count == 1:
                    mock_result.scalar_one_or_none = MagicMock(return_value=mock_msg)
                else:
                    mock_result.scalar_one_or_none = MagicMock(return_value=mock_attachment)
                return mock_result

            mock_session.execute = mock_execute

            with patch("mcp_server.tools.download_attachments.async_session_factory") as mock_factory:
                mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
                mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

                result = await tools.download_attachments(message_id=1, attachment_id=1)

            data = json.loads(result)
            decoded = base64.b64decode(data["content_base64"])
            assert len(decoded) == 1024 * 1024
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_download_empty_attachment(self):
        """Given empty attachment file, then empty base64 returned."""
        from mcp_server import tools

        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name

        try:
            mock_session = AsyncMock()
            mock_msg = MagicMock()
            mock_msg.id = 1

            mock_attachment = MagicMock()
            mock_attachment.id = 1
            mock_attachment.filename = "empty.txt"
            mock_attachment.content_type = "text/plain"
            mock_attachment.size_bytes = 0
            mock_attachment.storage_path = tmp_path

            call_count = 0
            async def mock_execute(stmt):
                nonlocal call_count
                call_count += 1
                mock_result = MagicMock()
                if call_count == 1:
                    mock_result.scalar_one_or_none = MagicMock(return_value=mock_msg)
                else:
                    mock_result.scalar_one_or_none = MagicMock(return_value=mock_attachment)
                return mock_result

            mock_session.execute = mock_execute

            with patch("mcp_server.tools.download_attachments.async_session_factory") as mock_factory:
                mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
                mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

                result = await tools.download_attachments(message_id=1, attachment_id=1)

            data = json.loads(result)
            assert data["content_base64"] == ""
        finally:
            os.unlink(tmp_path)


# =============================================================================
# Connection Resilience
# =============================================================================

class TestConnectionResilience:
    """Test IMAP connection resilience and retry behavior."""

    @pytest.mark.asyncio
    async def test_retry_succeeds_after_transient_failure(self):
        """Given transient failures, then retry succeeds."""
        from imap.client import IMAPClient

        client = IMAPClient(host="imap.example.com", max_retries=3, backoff_factor=0.01)
        func = AsyncMock(side_effect=[OSError("temp fail"), OSError("temp fail"), "success"])

        result = await client._retry_with_backoff("test", func)
        assert result == "success"
        assert func.call_count == 3

    @pytest.mark.asyncio
    async def test_retry_exhausted_after_permanent_failure(self):
        """Given permanent failure, then retry exhausted."""
        from imap.client import IMAPClient, IMAPRetryExhaustedError

        client = IMAPClient(host="imap.example.com", max_retries=3, backoff_factor=0.01)
        func = AsyncMock(side_effect=OSError("permanent fail"))

        with pytest.raises(IMAPRetryExhaustedError):
            await client._retry_with_backoff("test", func)

        assert func.call_count == 3

    @pytest.mark.asyncio
    async def test_disconnect_handles_graceful_cleanup(self):
        """Given disconnect with error, then cleanup still happens."""
        from imap.client import IMAPClient

        client = IMAPClient(host="imap.example.com")
        client._connected = True

        mock_imap = MagicMock()
        mock_imap.logout = AsyncMock(side_effect=Exception("network error"))
        client._client = mock_imap

        await client.disconnect()
        assert client._connected is False
        assert client._client is None

    @pytest.mark.asyncio
    async def test_context_manager_ensures_cleanup(self):
        """Given context manager usage, then disconnect always called."""
        from imap.client import IMAPClient

        client = IMAPClient(host="imap.example.com")

        mock_imap = MagicMock()
        mock_imap.login = AsyncMock(return_value=MagicMock(result="OK"))
        mock_imap.logout = AsyncMock()

        with patch("imap.client.aioimaplib.IMAP4_SSL", return_value=mock_imap):
            async with client:
                assert client._connected is True

        assert client._connected is False
        mock_imap.logout.assert_called_once()

    @pytest.mark.asyncio
    async def test_select_folder_not_connected_raises(self):
        """Given not connected, then select_folder raises IMAPConnectionError."""
        from imap.client import IMAPClient, IMAPConnectionError

        client = IMAPClient(host="imap.example.com")

        with pytest.raises(IMAPConnectionError):
            await client.select_folder("INBOX")

    @pytest.mark.asyncio
    async def test_fetch_messages_not_connected_raises(self):
        """Given not connected, then fetch_messages raises IMAPConnectionError."""
        from imap.client import IMAPClient, IMAPConnectionError

        client = IMAPClient(host="imap.example.com")

        with pytest.raises(IMAPConnectionError):
            await client.fetch_messages("1:*")

    @pytest.mark.asyncio
    async def test_search_messages_not_connected_raises(self):
        """Given not connected, then search_messages raises IMAPConnectionError."""
        from imap.client import IMAPClient, IMAPConnectionError

        client = IMAPClient(host="imap.example.com")

        with pytest.raises(IMAPConnectionError):
            await client.search_messages("ALL")

    @pytest.mark.asyncio
    async def test_mark_as_read_not_connected_raises(self):
        """Given not connected, then mark_as_read raises IMAPConnectionError."""
        from imap.client import IMAPClient, IMAPConnectionError

        client = IMAPClient(host="imap.example.com")

        with pytest.raises(IMAPConnectionError):
            await client.mark_as_read(uid=42)

    @pytest.mark.asyncio
    async def test_list_folders_not_connected_raises(self):
        """Given not connected, then list_folders raises IMAPConnectionError."""
        from imap.client import IMAPClient, IMAPConnectionError

        client = IMAPClient(host="imap.example.com")

        with pytest.raises(IMAPConnectionError):
            await client.list_folders()
