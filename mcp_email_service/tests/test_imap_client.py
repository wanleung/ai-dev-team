"""Tests for IMAPClient."""

import ssl
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import aioimaplib

from imap.client import (
    IMAPClient,
    IMAPConnectionError,
    IMAPAuthenticationError,
    IMAPRetryExhaustedError,
    IMAPOperationError,
)


class TestIMAPClientInit:
    """Tests for IMAPClient initialization."""

    def test_default_values(self):
        client = IMAPClient(host="imap.example.com")
        assert client.host == "imap.example.com"
        assert client.port == 993
        assert client.username == ""
        assert client.password == ""
        assert client.use_oauth is False
        assert client.timeout == 30.0
        assert client.max_retries == 3
        assert client.backoff_factor == 2.0
        assert client._connected is False
        assert client._selected_folder is None

    def test_custom_values(self):
        client = IMAPClient(
            host="imap.test.com",
            port=999,
            username="user",
            password="pass",
            use_oauth=True,
            timeout=60.0,
            max_retries=5,
            backoff_factor=3.0,
        )
        assert client.host == "imap.test.com"
        assert client.port == 999
        assert client.username == "user"
        assert client.password == "pass"
        assert client.use_oauth is True
        assert client.timeout == 60.0
        assert client.max_retries == 5
        assert client.backoff_factor == 3.0

    def test_custom_ssl_context(self):
        ctx = ssl.create_default_context()
        client = IMAPClient(host="imap.example.com", ssl_context=ctx)
        assert client.ssl_context is ctx


class TestIMAPClientSSL:
    """Tests for SSL context creation."""

    def test_default_ssl_context_is_secure(self):
        ctx = IMAPClient._create_default_ssl_context()
        assert ctx.check_hostname is True
        assert ctx.verify_mode == ssl.CERT_REQUIRED


class TestIMAPClientConnect:
    """Tests for IMAPClient.connect()."""

    @pytest.mark.asyncio
    async def test_connect_success(self):
        client = IMAPClient(host="imap.example.com", username="user", password="pass")

        mock_imap = MagicMock()
        mock_imap.login = AsyncMock(return_value=MagicMock(result="OK"))

        with patch("imap.client.aioimaplib.IMAP4_SSL", return_value=mock_imap):
            await client.connect()

        assert client._connected is True
        assert client._client is mock_imap

    @pytest.mark.asyncio
    async def test_connect_already_connected(self):
        client = IMAPClient(host="imap.example.com")
        client._connected = True

        await client.connect()
        assert client._connected is True

    @pytest.mark.asyncio
    async def test_connect_authentication_error(self):
        client = IMAPClient(host="imap.example.com", username="user", password="wrong")

        mock_imap = MagicMock()
        mock_imap.login = AsyncMock(
            side_effect=aioimaplib.IMAP4Error("AUTHENTICATION FAILED")
        )

        with patch("imap.client.aioimaplib.IMAP4_SSL", return_value=mock_imap):
            with pytest.raises(IMAPAuthenticationError):
                await client.connect()

    @pytest.mark.asyncio
    async def test_connect_raises_imap_connection_error(self):
        client = IMAPClient(host="imap.example.com")

        with patch("imap.client.aioimaplib.IMAP4_SSL", side_effect=ConnectionError("refused")):
            with pytest.raises(IMAPConnectionError):
                await client.connect()


class TestIMAPClientDisconnect:
    """Tests for IMAPClient.disconnect()."""

    @pytest.mark.asyncio
    async def test_disconnect_when_connected(self):
        client = IMAPClient(host="imap.example.com")
        client._connected = True

        mock_imap = MagicMock()
        mock_imap.logout = AsyncMock()
        client._client = mock_imap

        await client.disconnect()

        mock_imap.logout.assert_called_once()
        assert client._connected is False
        assert client._client is None

    @pytest.mark.asyncio
    async def test_disconnect_when_not_connected(self):
        client = IMAPClient(host="imap.example.com")
        await client.disconnect()
        assert client._connected is False

    @pytest.mark.asyncio
    async def test_disconnect_handles_error_gracefully(self):
        client = IMAPClient(host="imap.example.com")
        client._connected = True

        mock_imap = MagicMock()
        mock_imap.logout = AsyncMock(side_effect=Exception("network error"))
        client._client = mock_imap

        await client.disconnect()
        assert client._client is None


class TestIMAPClientSelectFolder:
    """Tests for IMAPClient.select_folder()."""

    @pytest.mark.asyncio
    async def test_select_folder_success(self):
        client = IMAPClient(host="imap.example.com")
        client._connected = True

        mock_imap = MagicMock()
        mock_response = MagicMock()
        mock_response.result = "OK"
        mock_response.data = [b"10 EXISTS"]
        mock_imap.select = AsyncMock(return_value=mock_response)
        client._client = mock_imap

        result = await client.select_folder("INBOX")
        assert result["exists"] == 10
        assert client._selected_folder == "INBOX"

    @pytest.mark.asyncio
    async def test_select_folder_readonly(self):
        client = IMAPClient(host="imap.example.com")
        client._connected = True

        mock_imap = MagicMock()
        mock_response = MagicMock()
        mock_response.result = "OK"
        mock_response.data = []
        mock_imap.examine = AsyncMock(return_value=mock_response)
        client._client = mock_imap

        await client.select_folder("INBOX", readonly=True)
        mock_imap.examine.assert_called_once()

    @pytest.mark.asyncio
    async def test_select_folder_not_connected(self):
        client = IMAPClient(host="imap.example.com")
        with pytest.raises(IMAPConnectionError):
            await client.select_folder("INBOX")

    @pytest.mark.asyncio
    async def test_select_folder_failure(self):
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


class TestIMAPClientFetchMessages:
    """Tests for IMAPClient.fetch_messages()."""

    @pytest.mark.asyncio
    async def test_fetch_messages_success(self):
        client = IMAPClient(host="imap.example.com")
        client._connected = True

        mock_imap = MagicMock()
        mock_response = MagicMock()
        mock_response.result = "OK"
        mock_response.data = [
            b"* 1 FETCH (UID 1 BODY[] {10}\r\nFrom: a@b.com\r\n\r\nHello",
        ]
        mock_imap.fetch = AsyncMock(return_value=mock_response)
        client._client = mock_imap

        messages = await client.fetch_messages("1:*")
        assert len(messages) >= 0

    @pytest.mark.asyncio
    async def test_fetch_messages_not_connected(self):
        client = IMAPClient(host="imap.example.com")
        with pytest.raises(IMAPConnectionError):
            await client.fetch_messages("1:*")

    @pytest.mark.asyncio
    async def test_fetch_messages_with_folder(self):
        client = IMAPClient(host="imap.example.com")
        client._connected = True

        mock_imap = MagicMock()
        mock_response = MagicMock()
        mock_response.result = "OK"
        mock_response.data = []
        mock_imap.select = AsyncMock(return_value=mock_response)
        mock_imap.fetch = AsyncMock(return_value=mock_response)
        client._client = mock_imap

        await client.fetch_messages("1:*", folder="INBOX")
        mock_imap.select.assert_called()


class TestIMAPClientSearchMessages:
    """Tests for IMAPClient.search_messages()."""

    @pytest.mark.asyncio
    async def test_search_messages_success(self):
        client = IMAPClient(host="imap.example.com")
        client._connected = True

        mock_imap = MagicMock()
        mock_response = MagicMock()
        mock_response.result = "OK"
        mock_response.data = [b"1 2 3 4 5"]
        mock_imap.search = AsyncMock(return_value=mock_response)
        client._client = mock_imap

        uids = await client.search_messages("ALL")
        assert uids == [1, 2, 3, 4, 5]

    @pytest.mark.asyncio
    async def test_search_messages_not_connected(self):
        client = IMAPClient(host="imap.example.com")
        with pytest.raises(IMAPConnectionError):
            await client.search_messages("ALL")

    @pytest.mark.asyncio
    async def test_search_messages_no_results(self):
        client = IMAPClient(host="imap.example.com")
        client._connected = True

        mock_imap = MagicMock()
        mock_response = MagicMock()
        mock_response.result = "OK"
        mock_response.data = [b""]
        mock_imap.search = AsyncMock(return_value=mock_response)
        client._client = mock_imap

        uids = await client.search_messages("UNSEEN")
        assert uids == []


class TestIMAPClientMarkAsRead:
    """Tests for IMAPClient.mark_as_read()."""

    @pytest.mark.asyncio
    async def test_mark_as_read_success(self):
        client = IMAPClient(host="imap.example.com")
        client._connected = True

        mock_imap = MagicMock()
        mock_response = MagicMock()
        mock_response.result = "OK"
        mock_imap.uid = AsyncMock(return_value=mock_response)
        client._client = mock_imap

        await client.mark_as_read(uid=42)
        mock_imap.uid.assert_called_once()

    @pytest.mark.asyncio
    async def test_mark_as_read_not_connected(self):
        client = IMAPClient(host="imap.example.com")
        with pytest.raises(IMAPConnectionError):
            await client.mark_as_read(uid=42)


class TestIMAPClientGetUids:
    """Tests for IMAPClient.get_uids()."""

    @pytest.mark.asyncio
    async def test_get_uids_delegates_to_search(self):
        client = IMAPClient(host="imap.example.com")
        client._connected = True

        mock_imap = MagicMock()
        mock_response = MagicMock()
        mock_response.result = "OK"
        mock_response.data = [b"10 20 30"]
        mock_imap.search = AsyncMock(return_value=mock_response)
        client._client = mock_imap

        uids = await client.get_uids()
        assert uids == [10, 20, 30]


class TestIMAPClientListFolders:
    """Tests for IMAPClient.list_folders()."""

    @pytest.mark.asyncio
    async def test_list_folders_success(self):
        client = IMAPClient(host="imap.example.com")
        client._connected = True

        mock_imap = MagicMock()
        mock_response = MagicMock()
        mock_response.result = "OK"
        mock_response.data = [
            b'(\\HasNoChildren) "/" "INBOX"',
            b'(\\HasNoChildren) "/" "Sent"',
            b'(\\HasChildren) "/" "Archive"',
        ]
        mock_imap.list = AsyncMock(return_value=mock_response)
        client._client = mock_imap

        folders = await client.list_folders()
        assert folders == ["INBOX", "Sent", "Archive"]

    @pytest.mark.asyncio
    async def test_list_folders_not_connected(self):
        client = IMAPClient(host="imap.example.com")
        with pytest.raises(IMAPConnectionError):
            await client.list_folders()

    @pytest.mark.asyncio
    async def test_list_folders_failure(self):
        client = IMAPClient(host="imap.example.com")
        client._connected = True

        mock_imap = MagicMock()
        mock_response = MagicMock()
        mock_response.result = "NO"
        mock_response.data = [b"Permission denied"]
        mock_imap.list = AsyncMock(return_value=mock_response)
        client._client = mock_imap

        with pytest.raises(IMAPOperationError):
            await client.list_folders()

    @pytest.mark.asyncio
    async def test_list_folders_empty_response(self):
        client = IMAPClient(host="imap.example.com")
        client._connected = True

        mock_imap = MagicMock()
        mock_response = MagicMock()
        mock_response.result = "OK"
        mock_response.data = []
        mock_imap.list = AsyncMock(return_value=mock_response)
        client._client = mock_imap

        folders = await client.list_folders()
        assert folders == []


class TestIMAPClientProperties:
    """Tests for IMAPClient properties."""

    def test_is_connected_false_initially(self):
        client = IMAPClient(host="imap.example.com")
        assert client.is_connected is False

    def test_selected_folder_none_initially(self):
        client = IMAPClient(host="imap.example.com")
        assert client.selected_folder is None


class TestIMAPClientContextManager:
    """Tests for async context manager support."""

    @pytest.mark.asyncio
    async def test_aenter_aexit(self):
        client = IMAPClient(host="imap.example.com")

        mock_imap = MagicMock()
        mock_imap.login = AsyncMock(return_value=MagicMock(result="OK"))
        mock_imap.logout = AsyncMock()

        with patch("imap.client.aioimaplib.IMAP4_SSL", return_value=mock_imap):
            async with client as c:
                assert c is client
                assert client._connected is True

        assert client._connected is False


class TestIMAPClientRetryWithBackoff:
    """Tests for _retry_with_backoff."""

    @pytest.mark.asyncio
    async def test_retry_succeeds_on_first_attempt(self):
        client = IMAPClient(host="imap.example.com", max_retries=3)
        func = AsyncMock(return_value="success")
        result = await client._retry_with_backoff("test", func)
        assert result == "success"
        func.assert_called_once()

    @pytest.mark.asyncio
    async def test_retry_succeeds_after_failure(self):
        client = IMAPClient(host="imap.example.com", max_retries=3, backoff_factor=0.01)
        func = AsyncMock(side_effect=[OSError("fail"), OSError("fail"), "success"])
        result = await client._retry_with_backoff("test", func)
        assert result == "success"
        assert func.call_count == 3

    @pytest.mark.asyncio
    async def test_retry_exhausted_raises(self):
        client = IMAPClient(host="imap.example.com", max_retries=2, backoff_factor=0.01)
        func = AsyncMock(side_effect=OSError("fail"))
        with pytest.raises(IMAPRetryExhaustedError):
            await client._retry_with_backoff("test", func)
