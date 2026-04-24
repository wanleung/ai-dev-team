"""Tests for MCP tool: send_email."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_server.tools import send_email
from smtp.client import SMTOPOperationError


class TestSendEmailTool:
    """Tests for the send_email MCP tool."""

    @pytest.mark.asyncio
    async def test_send_email_success(self):
        """Given valid account and recipients, then email is sent."""
        mock_session = AsyncMock()
        mock_account = MagicMock()
        mock_account.id = 1
        mock_account.is_active = True
        mock_account.imap_host = "imap.example.com"
        mock_account.imap_port = 993
        mock_account.username = "sender@example.com"
        mock_account.auth_method = "basic"
        mock_account.encrypted_password = "encrypted-pw"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_account)
        mock_session.execute.return_value = mock_result

        mock_settings = MagicMock()
        mock_em = MagicMock()
        mock_em.decrypt.return_value = "decrypted-password"
        mock_settings.get_encryption_manager.return_value = mock_em

        with patch("mcp_server.tools.send_email.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("mcp_server.tools.send_email.get_settings", return_value=mock_settings):
                with patch("mcp_server.tools.send_email.SMTPClient") as MockSMTPClient:
                    mock_smtp = MagicMock()
                    mock_smtp.send_email = AsyncMock(return_value={
                        "status": "sent",
                        "message_id": "<msg123@example.com>",
                        "recipients": ["recipient@example.com"],
                        "smtp_response": "250 OK",
                    })
                    mock_smtp.__aenter__ = AsyncMock(return_value=mock_smtp)
                    mock_smtp.__aexit__ = AsyncMock(return_value=None)
                    MockSMTPClient.return_value = mock_smtp

                    result = await send_email(
                        account_id=1,
                        to="recipient@example.com",
                        subject="Test Subject",
                        body="Hello World",
                    )

        data = json.loads(result)
        assert data["status"] == "sent"
        assert data["message_id"] == "<msg123@example.com>"
        MockSMTPClient.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_email_raises_for_nonexistent_account(self):
        """Given a non-existent account, then a ValueError is raised."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_session.execute.return_value = mock_result

        with patch("mcp_server.tools.send_email.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(ValueError, match="Account .* not found"):
                await send_email(
                    account_id=999,
                    to="recipient@example.com",
                    subject="Test",
                    body="Hello",
                )

    @pytest.mark.asyncio
    async def test_send_email_raises_for_inactive_account(self):
        """Given an inactive account, then a ValueError is raised."""
        mock_session = AsyncMock()
        mock_account = MagicMock()
        mock_account.id = 1
        mock_account.is_active = False

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_account)
        mock_session.execute.return_value = mock_result

        with patch("mcp_server.tools.send_email.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(ValueError, match="Account .* is inactive"):
                await send_email(
                    account_id=1,
                    to="recipient@example.com",
                    subject="Test",
                    body="Hello",
                )

    @pytest.mark.asyncio
    async def test_send_email_raises_for_no_recipients(self):
        """Given empty recipients, then a ValueError is raised."""
        mock_session = AsyncMock()
        mock_account = MagicMock()
        mock_account.id = 1
        mock_account.is_active = True
        mock_account.imap_host = "imap.example.com"
        mock_account.imap_port = 993
        mock_account.username = "sender@example.com"
        mock_account.auth_method = "basic"
        mock_account.encrypted_password = "encrypted-pw"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_account)
        mock_session.execute.return_value = mock_result

        mock_settings = MagicMock()
        mock_em = MagicMock()
        mock_em.decrypt.return_value = "decrypted-password"
        mock_settings.get_encryption_manager.return_value = mock_em

        with patch("mcp_server.tools.send_email.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("mcp_server.tools.send_email.get_settings", return_value=mock_settings):
                with pytest.raises(ValueError, match="At least one recipient"):
                    await send_email(
                        account_id=1,
                        to="",
                        subject="Test",
                        body="Hello",
                    )

    @pytest.mark.asyncio
    async def test_send_email_with_cc_and_bcc(self):
        """Given CC and BCC recipients, then they are parsed correctly."""
        mock_session = AsyncMock()
        mock_account = MagicMock()
        mock_account.id = 1
        mock_account.is_active = True
        mock_account.imap_host = "imap.example.com"
        mock_account.imap_port = 993
        mock_account.username = "sender@example.com"
        mock_account.auth_method = "basic"
        mock_account.encrypted_password = "encrypted-pw"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_account)
        mock_session.execute.return_value = mock_result

        mock_settings = MagicMock()
        mock_em = MagicMock()
        mock_em.decrypt.return_value = "decrypted-password"
        mock_settings.get_encryption_manager.return_value = mock_em

        with patch("mcp_server.tools.send_email.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("mcp_server.tools.send_email.get_settings", return_value=mock_settings):
                with patch("mcp_server.tools.send_email.SMTPClient") as MockSMTPClient:
                    mock_smtp = MagicMock()
                    mock_smtp.send_email = AsyncMock(return_value={
                        "status": "sent",
                        "message_id": "<msg@example.com>",
                        "recipients": ["to@example.com", "cc@example.com", "bcc@example.com"],
                        "smtp_response": "250 OK",
                    })
                    mock_smtp.__aenter__ = AsyncMock(return_value=mock_smtp)
                    mock_smtp.__aexit__ = AsyncMock(return_value=None)
                    MockSMTPClient.return_value = mock_smtp

                    result = await send_email(
                        account_id=1,
                        to="to@example.com",
                        subject="Test",
                        body="Hello",
                        cc="cc@example.com",
                        bcc="bcc@example.com",
                    )

        data = json.loads(result)
        assert data["status"] == "sent"

    @pytest.mark.asyncio
    async def test_send_email_with_html_body(self):
        """Given an HTML body, then it is passed to SMTP client."""
        mock_session = AsyncMock()
        mock_account = MagicMock()
        mock_account.id = 1
        mock_account.is_active = True
        mock_account.imap_host = "imap.example.com"
        mock_account.imap_port = 993
        mock_account.username = "sender@example.com"
        mock_account.auth_method = "basic"
        mock_account.encrypted_password = "encrypted-pw"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_account)
        mock_session.execute.return_value = mock_result

        mock_settings = MagicMock()
        mock_em = MagicMock()
        mock_em.decrypt.return_value = "decrypted-password"
        mock_settings.get_encryption_manager.return_value = mock_em

        with patch("mcp_server.tools.send_email.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("mcp_server.tools.send_email.get_settings", return_value=mock_settings):
                with patch("mcp_server.tools.send_email.SMTPClient") as MockSMTPClient:
                    mock_smtp = MagicMock()
                    mock_smtp.send_email = AsyncMock(return_value={
                        "status": "sent",
                        "message_id": "<msg@example.com>",
                        "recipients": ["recipient@example.com"],
                        "smtp_response": "250 OK",
                    })
                    mock_smtp.__aenter__ = AsyncMock(return_value=mock_smtp)
                    mock_smtp.__aexit__ = AsyncMock(return_value=None)
                    MockSMTPClient.return_value = mock_smtp

                    await send_email(
                        account_id=1,
                        to="recipient@example.com",
                        subject="Test",
                        body="Plain text",
                        html="<p>HTML body</p>",
                    )

                    _, kwargs = mock_smtp.send_email.call_args
                    assert kwargs["html"] == "<p>HTML body</p>"

    @pytest.mark.asyncio
    async def test_send_email_with_attachments(self):
        """Given attachment paths, then they are passed to SMTP client."""
        mock_session = AsyncMock()
        mock_account = MagicMock()
        mock_account.id = 1
        mock_account.is_active = True
        mock_account.imap_host = "imap.example.com"
        mock_account.imap_port = 993
        mock_account.username = "sender@example.com"
        mock_account.auth_method = "basic"
        mock_account.encrypted_password = "encrypted-pw"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_account)
        mock_session.execute.return_value = mock_result

        mock_settings = MagicMock()
        mock_em = MagicMock()
        mock_em.decrypt.return_value = "decrypted-password"
        mock_settings.get_encryption_manager.return_value = mock_em

        with patch("mcp_server.tools.send_email.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("mcp_server.tools.send_email.get_settings", return_value=mock_settings):
                with patch("mcp_server.tools.send_email.SMTPClient") as MockSMTPClient:
                    mock_smtp = MagicMock()
                    mock_smtp.send_email = AsyncMock(return_value={
                        "status": "sent",
                        "message_id": "<msg@example.com>",
                        "recipients": ["recipient@example.com"],
                        "smtp_response": "250 OK",
                    })
                    mock_smtp.__aenter__ = AsyncMock(return_value=mock_smtp)
                    mock_smtp.__aexit__ = AsyncMock(return_value=None)
                    MockSMTPClient.return_value = mock_smtp

                    await send_email(
                        account_id=1,
                        to="recipient@example.com",
                        subject="Test",
                        body="Hello",
                        attachment_paths="/tmp/file1.pdf,/tmp/file2.docx",
                    )

                    _, kwargs = mock_smtp.send_email.call_args
                    assert kwargs["attachments"] == ["/tmp/file1.pdf", "/tmp/file2.docx"]

    @pytest.mark.asyncio
    async def test_send_email_smtp_error_raises(self):
        """Given SMTP failure, then SMTOPOperationError is raised."""
        mock_session = AsyncMock()
        mock_account = MagicMock()
        mock_account.id = 1
        mock_account.is_active = True
        mock_account.imap_host = "imap.example.com"
        mock_account.imap_port = 993
        mock_account.username = "sender@example.com"
        mock_account.auth_method = "basic"
        mock_account.encrypted_password = "encrypted-pw"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_account)
        mock_session.execute.return_value = mock_result

        mock_settings = MagicMock()
        mock_em = MagicMock()
        mock_em.decrypt.return_value = "decrypted-password"
        mock_settings.get_encryption_manager.return_value = mock_em

        with patch("mcp_server.tools.send_email.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("mcp_server.tools.send_email.get_settings", return_value=mock_settings):
                with patch("mcp_server.tools.send_email.SMTPClient") as MockSMTPClient:
                    mock_smtp = MagicMock()
                    mock_smtp.send_email = AsyncMock(side_effect=SMTOPOperationError("SMTP connection refused"))
                    mock_smtp.__aenter__ = AsyncMock(return_value=mock_smtp)
                    mock_smtp.__aexit__ = AsyncMock(return_value=None)
                    MockSMTPClient.return_value = mock_smtp

                    with pytest.raises(SMTOPOperationError, match="SMTP connection refused"):
                        await send_email(
                            account_id=1,
                            to="recipient@example.com",
                            subject="Test",
                            body="Hello",
                        )

    @pytest.mark.asyncio
    async def test_send_email_multiple_recipients(self):
        """Given comma-separated recipients, then they are parsed as a list."""
        mock_session = AsyncMock()
        mock_account = MagicMock()
        mock_account.id = 1
        mock_account.is_active = True
        mock_account.imap_host = "imap.example.com"
        mock_account.imap_port = 993
        mock_account.username = "sender@example.com"
        mock_account.auth_method = "basic"
        mock_account.encrypted_password = "encrypted-pw"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_account)
        mock_session.execute.return_value = mock_result

        mock_settings = MagicMock()
        mock_em = MagicMock()
        mock_em.decrypt.return_value = "decrypted-password"
        mock_settings.get_encryption_manager.return_value = mock_em

        with patch("mcp_server.tools.send_email.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("mcp_server.tools.send_email.get_settings", return_value=mock_settings):
                with patch("mcp_server.tools.send_email.SMTPClient") as MockSMTPClient:
                    mock_smtp = MagicMock()
                    mock_smtp.send_email = AsyncMock(return_value={
                        "status": "sent",
                        "message_id": "<msg@example.com>",
                        "recipients": ["a@example.com", "b@example.com", "c@example.com"],
                        "smtp_response": "250 OK",
                    })
                    mock_smtp.__aenter__ = AsyncMock(return_value=mock_smtp)
                    mock_smtp.__aexit__ = AsyncMock(return_value=None)
                    MockSMTPClient.return_value = mock_smtp

                    await send_email(
                        account_id=1,
                        to="a@example.com, b@example.com, c@example.com",
                        subject="Test",
                        body="Hello",
                    )

                    _, kwargs = mock_smtp.send_email.call_args
                    assert kwargs["to"] == ["a@example.com", "b@example.com", "c@example.com"]

    @pytest.mark.asyncio
    async def test_send_email_decrypts_password(self):
        """Given an account, then the encrypted password is decrypted before use."""
        mock_session = AsyncMock()
        mock_account = MagicMock()
        mock_account.id = 1
        mock_account.is_active = True
        mock_account.imap_host = "imap.example.com"
        mock_account.imap_port = 993
        mock_account.username = "sender@example.com"
        mock_account.auth_method = "basic"
        mock_account.encrypted_password = "encrypted-pw"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_account)
        mock_session.execute.return_value = mock_result

        mock_settings = MagicMock()
        mock_em = MagicMock()
        mock_em.decrypt.return_value = "decrypted-password"
        mock_settings.get_encryption_manager.return_value = mock_em

        with patch("mcp_server.tools.send_email.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("mcp_server.tools.send_email.get_settings", return_value=mock_settings):
                with patch("mcp_server.tools.send_email.SMTPClient") as MockSMTPClient:
                    mock_smtp = MagicMock()
                    mock_smtp.send_email = AsyncMock(return_value={
                        "status": "sent",
                        "message_id": "<msg@example.com>",
                        "recipients": ["recipient@example.com"],
                        "smtp_response": "250 OK",
                    })
                    mock_smtp.__aenter__ = AsyncMock(return_value=mock_smtp)
                    mock_smtp.__aexit__ = AsyncMock(return_value=None)
                    MockSMTPClient.return_value = mock_smtp

                    await send_email(
                        account_id=1,
                        to="recipient@example.com",
                        subject="Test",
                        body="Hello",
                    )

                    mock_em.decrypt.assert_called_once_with("encrypted-pw")
