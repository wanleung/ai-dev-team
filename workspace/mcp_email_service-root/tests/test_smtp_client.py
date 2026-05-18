"""Tests for SMTP client."""

import ssl
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiosmtplib
import pytest

from smtp.client import (
    SMTPClient,
    SMTPConnectionError,
    SMTPAuthenticationError,
    SMTPRetryExhaustedError,
    SMTOPOperationError,
)


class TestSMTPClientInit:
    """Tests for SMTPClient initialization."""

    def test_default_values(self):
        client = SMTPClient(host="smtp.example.com")
        assert client.host == "smtp.example.com"
        assert client.port == 587
        assert client.username == ""
        assert client.password == ""
        assert client.use_tls is True
        assert client.use_ssl is False
        assert client.use_oauth is False
        assert client.timeout == 30.0
        assert client.max_retries == 3
        assert client.backoff_factor == 2.0
        assert client.oauth2_token_callback is None
        assert client._connected is False
        assert client._client is None

    def test_custom_values(self):
        client = SMTPClient(
            host="smtp.gmail.com",
            port=465,
            username="user@gmail.com",
            password="secret",
            use_tls=False,
            use_ssl=True,
            use_oauth=True,
            timeout=60.0,
            max_retries=5,
            backoff_factor=3.0,
        )
        assert client.host == "smtp.gmail.com"
        assert client.port == 465
        assert client.username == "user@gmail.com"
        assert client.password == "secret"
        assert client.use_tls is False
        assert client.use_ssl is True
        assert client.use_oauth is True
        assert client.timeout == 60.0
        assert client.max_retries == 5
        assert client.backoff_factor == 3.0

    def test_ssl_context_created(self):
        client = SMTPClient(host="smtp.example.com")
        assert client.ssl_context is not None
        assert isinstance(client.ssl_context, ssl.SSLContext)

    def test_custom_ssl_context(self):
        custom_ctx = ssl.create_default_context()
        client = SMTPClient(host="smtp.example.com", ssl_context=custom_ctx)
        assert client.ssl_context is custom_ctx


class TestSMTPClientSSLContext:
    """Tests for _create_default_ssl_context."""

    def test_tls_minimum_version(self):
        ctx = SMTPClient._create_default_ssl_context()
        assert ctx.minimum_version == ssl.TLSVersion.TLSv1_2

    def test_cert_verification(self):
        ctx = SMTPClient._create_default_ssl_context()
        assert ctx.verify_mode == ssl.CERT_REQUIRED

    def test_hostname_check(self):
        ctx = SMTPClient._create_default_ssl_context()
        assert ctx.check_hostname is True


class TestSMTPClientConnect:
    """Tests for SMTPClient.connect."""

    @pytest.mark.asyncio
    async def test_connect_success_starttls(self):
        client = SMTPClient(host="smtp.example.com", port=587, use_tls=True, use_ssl=False)

        mock_smtp = AsyncMock()
        mock_smtp.connect = AsyncMock()
        mock_smtp.starttls = AsyncMock()
        mock_smtp.login = AsyncMock()

        with patch("smtp.client.aiosmtplib.SMTP", return_value=mock_smtp):
            await client.connect()

        assert client._connected is True
        mock_smtp.connect.assert_awaited_once()
        mock_smtp.starttls.assert_awaited_once()
        mock_smtp.login.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_success_ssl(self):
        client = SMTPClient(host="smtp.example.com", port=465, use_tls=False, use_ssl=True)

        mock_smtp = AsyncMock()
        mock_smtp.connect = AsyncMock()
        mock_smtp.starttls = AsyncMock()
        mock_smtp.login = AsyncMock()

        with patch("smtp.client.aiosmtplib.SMTP", return_value=mock_smtp):
            await client.connect()

        assert client._connected is True
        mock_smtp.connect.assert_awaited_once()
        mock_smtp.starttls.assert_not_called()

    @pytest.mark.asyncio
    async def test_connect_already_connected(self):
        client = SMTPClient(host="smtp.example.com")
        client._connected = True
        client._client = AsyncMock()

        await client.connect()

        assert client._connected is True

    @pytest.mark.asyncio
    async def test_connect_raises_on_connection_error(self):
        client = SMTPClient(host="smtp.example.com")

        mock_smtp = AsyncMock()
        mock_smtp.connect = AsyncMock(side_effect=ConnectionError("refused"))

        with patch("smtp.client.aiosmtplib.SMTP", return_value=mock_smtp):
            with pytest.raises(SMTPConnectionError, match="Failed to connect"):
                await client.connect()

        assert client._connected is False

    @pytest.mark.asyncio
    async def test_connect_reraises_auth_error(self):
        client = SMTPClient(host="smtp.example.com")

        mock_smtp = AsyncMock()
        mock_smtp.connect = AsyncMock()
        mock_smtp.starttls = AsyncMock()
        mock_smtp.login = AsyncMock(side_effect=SMTPAuthenticationError("bad credentials"))

        with patch("smtp.client.aiosmtplib.SMTP", return_value=mock_smtp):
            with pytest.raises(SMTPAuthenticationError):
                await client.connect()


class TestSMTPClientAuthenticate:
    """Tests for SMTPClient._authenticate."""

    @pytest.mark.asyncio
    async def test_authenticate_basic(self):
        client = SMTPClient(host="smtp.example.com", use_oauth=False)
        client._client = AsyncMock()
        client._client.login = AsyncMock()

        await client._authenticate()

        client._client.login.assert_awaited_once_with("smtp.example.com", "")

    @pytest.mark.asyncio
    async def test_authenticate_oauth2(self):
        client = SMTPClient(host="smtp.example.com", use_oauth=True, username="user", password="token")
        client._client = AsyncMock()
        client._client.login = AsyncMock()

        await client._authenticate_oauth2()

        client._client.login.assert_awaited_once_with("user", "token", use_oauth2=True)

    @pytest.mark.asyncio
    async def test_authenticate_raises_if_no_client(self):
        client = SMTPClient(host="smtp.example.com")
        client._client = None

        with pytest.raises(SMTPConnectionError, match="not initialized"):
            await client._authenticate()

    @pytest.mark.asyncio
    async def test_authenticate_handles_smtp_exception(self):
        client = SMTPClient(host="smtp.example.com")
        client._client = AsyncMock()
        client._client.login = AsyncMock(side_effect=aiosmtplib.SMTPException("generic"))

        with pytest.raises(SMTPAuthenticationError, match="SMTP authentication error"):
            await client._authenticate()


class TestSMTPClientOAuth2Refresh:
    """Tests for SMTPClient._refresh_and_retry_oauth2."""

    @pytest.mark.asyncio
    async def test_refresh_and_retry_success(self):
        callback = AsyncMock(return_value="new-token")
        client = SMTPClient(
            host="smtp.example.com",
            use_oauth=True,
            username="user",
            password="old-token",
            oauth2_token_callback=callback,
        )
        client._client = AsyncMock()
        client._client.login = AsyncMock()

        await client._refresh_and_retry_oauth2()

        callback.assert_awaited_once()
        assert client.password == "new-token"
        client._client.login.assert_awaited_once_with("user", "new-token", use_oauth2=True)

    @pytest.mark.asyncio
    async def test_refresh_and_retry_raises_if_callback_fails(self):
        callback = AsyncMock(side_effect=Exception("callback error"))
        client = SMTPClient(
            host="smtp.example.com",
            use_oauth=True,
            username="user",
            password="old-token",
            oauth2_token_callback=callback,
        )
        client._client = AsyncMock()

        with pytest.raises(SMTPAuthenticationError, match="OAuth2 token refresh failed"):
            await client._refresh_and_retry_oauth2()

    @pytest.mark.asyncio
    async def test_refresh_and_retry_raises_if_login_fails_after_refresh(self):
        callback = AsyncMock(return_value="new-token")
        client = SMTPClient(
            host="smtp.example.com",
            use_oauth=True,
            username="user",
            password="old-token",
            oauth2_token_callback=callback,
        )
        client._client = AsyncMock()
        client._client.login = AsyncMock(side_effect=aiosmtplib.SMTPAuthenticationError(401, "bad"))

        with pytest.raises(SMTPAuthenticationError, match="after token refresh"):
            await client._refresh_and_retry_oauth2()

    @pytest.mark.asyncio
    async def test_refresh_and_retry_raises_if_no_client(self):
        client = SMTPClient(host="smtp.example.com", oauth2_token_callback=AsyncMock())
        client._client = None

        with pytest.raises(SMTPConnectionError, match="not initialized"):
            await client._refresh_and_retry_oauth2()


class TestSMTPClientDisconnect:
    """Tests for SMTPClient.disconnect."""

    @pytest.mark.asyncio
    async def test_disconnect_when_connected(self):
        client = SMTPClient(host="smtp.example.com")
        client._connected = True
        client._client = AsyncMock()
        client._client.quit = AsyncMock()

        await client.disconnect()

        client._client.quit.assert_awaited_once()
        assert client._client is None
        assert client._connected is False

    @pytest.mark.asyncio
    async def test_disconnect_when_not_connected(self):
        client = SMTPClient(host="smtp.example.com")
        client._connected = False
        client._client = None

        await client.disconnect()

        assert client._connected is False

    @pytest.mark.asyncio
    async def test_disconnect_handles_error(self):
        client = SMTPClient(host="smtp.example.com")
        client._connected = True
        client._client = AsyncMock()
        client._client.quit = AsyncMock(side_effect=Exception("network error"))

        await client.disconnect()

        assert client._client is None
        assert client._connected is False


class TestSMTPClientSendEmail:
    """Tests for SMTPClient.send_email."""

    @pytest.mark.asyncio
    async def test_send_email_success(self):
        client = SMTPClient(host="smtp.example.com")
        client._connected = True
        client._client = AsyncMock()
        client._client.send_message = AsyncMock(return_value="250 OK")

        result = await client.send_email(
            to="recipient@example.com",
            subject="Test",
            body="Hello",
        )

        assert result["status"] == "sent"
        assert "message_id" in result
        assert "recipient@example.com" in result["recipients"]

    @pytest.mark.asyncio
    async def test_send_email_with_multiple_recipients(self):
        client = SMTPClient(host="smtp.example.com")
        client._connected = True
        client._client = AsyncMock()
        client._client.send_message = AsyncMock(return_value="250 OK")

        result = await client.send_email(
            to=["a@example.com", "b@example.com"],
            subject="Test",
            body="Hello",
        )

        assert "a@example.com" in result["recipients"]
        assert "b@example.com" in result["recipients"]

    @pytest.mark.asyncio
    async def test_send_email_with_cc_and_bcc(self):
        client = SMTPClient(host="smtp.example.com")
        client._connected = True
        client._client = AsyncMock()
        client._client.send_message = AsyncMock(return_value="250 OK")

        result = await client.send_email(
            to="to@example.com",
            subject="Test",
            body="Hello",
            cc="cc@example.com",
            bcc="bcc@example.com",
        )

        assert "cc@example.com" in result["recipients"]
        assert "bcc@example.com" in result["recipients"]

    @pytest.mark.asyncio
    async def test_send_email_raises_if_not_connected(self):
        client = SMTPClient(host="smtp.example.com")
        client._connected = False

        with pytest.raises(SMTPConnectionError, match="Not connected"):
            await client.send_email(to="a@b.com", subject="Test", body="Hello")

    @pytest.mark.asyncio
    async def test_send_email_raises_if_client_is_none(self):
        client = SMTPClient(host="smtp.example.com")
        client._connected = True
        client._client = None

        with pytest.raises(SMTPConnectionError, match="Not connected"):
            await client.send_email(to="a@b.com", subject="Test", body="Hello")

    @pytest.mark.asyncio
    async def test_send_email_with_html_body(self):
        client = SMTPClient(host="smtp.example.com")
        client._connected = True
        client._client = AsyncMock()
        client._client.send_message = AsyncMock(return_value="250 OK")

        result = await client.send_email(
            to="recipient@example.com",
            subject="Test",
            body="Plain text",
            html="<p>HTML body</p>",
        )

        assert result["status"] == "sent"

    @pytest.mark.asyncio
    async def test_send_email_with_reply_to(self):
        client = SMTPClient(host="smtp.example.com")
        client._connected = True
        client._client = AsyncMock()
        client._client.send_message = AsyncMock(return_value="250 OK")

        result = await client.send_email(
            to="recipient@example.com",
            subject="Test",
            body="Hello",
            reply_to="reply@example.com",
        )

        assert result["status"] == "sent"

    @pytest.mark.asyncio
    async def test_send_email_retries_on_failure(self):
        client = SMTPClient(
            host="smtp.example.com",
            max_retries=2,
            backoff_factor=0.01,
        )
        client._connected = True
        client._client = AsyncMock()
        client._client.send_message = AsyncMock(
            side_effect=[aiosmtplib.SMTPException("temp fail"), "250 OK"]
        )

        result = await client.send_email(
            to="recipient@example.com",
            subject="Test",
            body="Hello",
        )

        assert result["status"] == "sent"
        assert client._client.send_message.call_count == 2

    @pytest.mark.asyncio
    async def test_send_email_raises_after_max_retries(self):
        client = SMTPClient(
            host="smtp.example.com",
            max_retries=2,
            backoff_factor=0.01,
        )
        client._connected = True
        client._client = AsyncMock()
        client._client.send_message = AsyncMock(side_effect=aiosmtplib.SMTPException("fail"))

        with pytest.raises(SMTOPOperationError, match="Failed to send email"):
            await client.send_email(to="a@b.com", subject="Test", body="Hello")


class TestSMTPClientBuildMessage:
    """Tests for SMTPClient._build_message."""

    def test_build_plain_text_message(self):
        client = SMTPClient(host="smtp.example.com", username="sender@example.com")

        msg = client._build_message(
            to=["recipient@example.com"],
            subject="Test Subject",
            body="Plain text body",
        )

        assert msg["Subject"] == "Test Subject"
        assert msg["To"] == "recipient@example.com"
        assert "From" in msg
        assert "Date" in msg
        assert "Message-ID" in msg

    def test_build_message_with_html_and_plain(self):
        client = SMTPClient(host="smtp.example.com", username="sender@example.com")

        msg = client._build_message(
            to=["recipient@example.com"],
            subject="Test",
            body="Plain",
            html="<p>HTML</p>",
        )

        assert msg["Subject"] == "Test"

    def test_build_message_with_cc(self):
        client = SMTPClient(host="smtp.example.com", username="sender@example.com")

        msg = client._build_message(
            to=["to@example.com"],
            subject="Test",
            body="Body",
            cc=["cc1@example.com", "cc2@example.com"],
        )

        assert "cc1@example.com" in msg["Cc"]
        assert "cc2@example.com" in msg["Cc"]

    def test_build_message_with_reply_to(self):
        client = SMTPClient(host="smtp.example.com", username="sender@example.com")

        msg = client._build_message(
            to=["to@example.com"],
            subject="Test",
            body="Body",
            reply_to="reply@example.com",
        )

        assert msg["Reply-To"] == "reply@example.com"

    def test_build_message_with_from_name(self):
        client = SMTPClient(host="smtp.example.com", username="sender@example.com")

        msg = client._build_message(
            to=["to@example.com"],
            subject="Test",
            body="Body",
            from_name="John Doe",
        )

        assert "John Doe" in msg["From"]


class TestSMTPClientCreateAttachment:
    """Tests for SMTPClient._create_attachment."""

    def test_create_attachment_from_existing_file(self, tmp_path):
        client = SMTPClient(host="smtp.example.com")

        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello World")

        attachment = client._create_attachment(str(test_file))

        assert attachment["Content-Disposition"].startswith("attachment")
        assert "test.txt" in attachment["Content-Disposition"]

    def test_create_attachment_raises_for_nonexistent_file(self):
        client = SMTPClient(host="smtp.example.com")

        with pytest.raises(FileNotFoundError, match="not found"):
            client._create_attachment("/nonexistent/file.txt")

    def test_create_attachment_raises_for_directory(self, tmp_path):
        client = SMTPClient(host="smtp.example.com")

        with pytest.raises(ValueError, match="not a file"):
            client._create_attachment(str(tmp_path))

    def test_create_attachment_detects_content_type(self, tmp_path):
        client = SMTPClient(host="smtp.example.com")

        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"%PDF-1.4")

        attachment = client._create_attachment(str(test_file))

        assert "application/pdf" in attachment.get_content_type()


class TestSMTPClientValidateAddresses:
    """Tests for SMTPClient._validate_addresses."""

    def test_valid_addresses(self):
        SMTPClient._validate_addresses(["a@b.com", "c@d.com"], "to")

    def test_empty_address_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            SMTPClient._validate_addresses([""], "to")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            SMTPClient._validate_addresses(["   "], "to")

    def test_missing_at_raises(self):
        with pytest.raises(ValueError, match="Invalid"):
            SMTPClient._validate_addresses(["invalid"], "to")

    def test_label_in_error_message(self):
        with pytest.raises(ValueError, match="cc address cannot be empty"):
            SMTPClient._validate_addresses([""], "cc")


class TestSMTPClientContextManager:
    """Tests for SMTPClient async context manager."""

    @pytest.mark.asyncio
    async def test_aenter_connects(self):
        client = SMTPClient(host="smtp.example.com")

        mock_smtp = AsyncMock()
        mock_smtp.connect = AsyncMock()
        mock_smtp.starttls = AsyncMock()
        mock_smtp.login = AsyncMock()

        with patch("smtp.client.aiosmtplib.SMTP", return_value=mock_smtp):
            async with client as c:
                assert c is client
                assert client._connected is True

    @pytest.mark.asyncio
    async def test_aexit_disconnectes(self):
        client = SMTPClient(host="smtp.example.com")

        mock_smtp = AsyncMock()
        mock_smtp.connect = AsyncMock()
        mock_smtp.starttls = AsyncMock()
        mock_smtp.login = AsyncMock()
        mock_smtp.quit = AsyncMock()

        with patch("smtp.client.aiosmtplib.SMTP", return_value=mock_smtp):
            async with client:
                pass

        assert client._connected is False

    @pytest.mark.asyncio
    async def test_is_connected_property(self):
        client = SMTPClient(host="smtp.example.com")
        assert client.is_connected is False

        client._connected = True
        assert client.is_connected is True
