"""Tests for MCP tool: download_attachments."""

import base64
import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_server.tools import download_attachments


class TestDownloadAttachmentsTool:
    """Tests for the download_attachments MCP tool."""

    @pytest.mark.asyncio
    async def test_download_attachment_success(self):
        """Given a valid message and attachment, then base64 content is returned."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(b"%PDF-1.4 test content")
            tmp_path = tmp.name

        try:
            mock_session = AsyncMock()
            mock_msg = MagicMock()
            mock_msg.id = 1

            mock_attachment = MagicMock()
            mock_attachment.id = 1
            mock_attachment.filename = "report.pdf"
            mock_attachment.content_type = "application/pdf"
            mock_attachment.size_bytes = 21
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

                result = await download_attachments(message_id=1, attachment_id=1)

            data = json.loads(result)
            assert data["id"] == 1
            assert data["filename"] == "report.pdf"
            assert data["content_type"] == "application/pdf"
            assert "content_base64" in data
            decoded = base64.b64decode(data["content_base64"])
            assert decoded == b"%PDF-1.4 test content"
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_download_attachment_raises_for_nonexistent_message(self):
        """Given a non-existent message, then a ValueError is raised."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_session.execute.return_value = mock_result

        with patch("mcp_server.tools.download_attachments.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(ValueError, match="Message .* not found"):
                await download_attachments(message_id=999, attachment_id=1)

    @pytest.mark.asyncio
    async def test_download_attachment_raises_for_nonexistent_attachment(self):
        """Given a valid message but non-existent attachment, then a ValueError is raised."""
        mock_session = AsyncMock()
        mock_msg = MagicMock()
        mock_msg.id = 1

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.scalar_one_or_none = MagicMock(return_value=mock_msg)
            else:
                mock_result.scalar_one_or_none = MagicMock(return_value=None)
            return mock_result

        mock_session.execute = mock_execute

        with patch("mcp_server.tools.download_attachments.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(ValueError, match="Attachment .* not found"):
                await download_attachments(message_id=1, attachment_id=999)

    @pytest.mark.asyncio
    async def test_download_attachment_raises_for_missing_file(self):
        """Given an attachment with a non-existent storage path, then a ValueError is raised."""
        mock_session = AsyncMock()
        mock_msg = MagicMock()
        mock_msg.id = 1

        mock_attachment = MagicMock()
        mock_attachment.id = 1
        mock_attachment.storage_path = "/nonexistent/path/file.pdf"

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

            with pytest.raises(ValueError, match="Attachment file not found"):
                await download_attachments(message_id=1, attachment_id=1)

    @pytest.mark.asyncio
    async def test_download_attachment_binary_content(self):
        """Given a binary attachment, then it is correctly base64-encoded."""
        binary_content = bytes(range(256))

        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(binary_content)
            tmp_path = tmp.name

        try:
            mock_session = AsyncMock()
            mock_msg = MagicMock()
            mock_msg.id = 1

            mock_attachment = MagicMock()
            mock_attachment.id = 1
            mock_attachment.filename = "binary.bin"
            mock_attachment.content_type = "application/octet-stream"
            mock_attachment.size_bytes = len(binary_content)
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

                result = await download_attachments(message_id=1, attachment_id=1)

            data = json.loads(result)
            decoded = base64.b64decode(data["content_base64"])
            assert decoded == binary_content
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_download_attachment_empty_file(self):
        """Given an empty attachment file, then empty base64 is returned."""
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

                result = await download_attachments(message_id=1, attachment_id=1)

            data = json.loads(result)
            assert data["content_base64"] == ""
        finally:
            os.unlink(tmp_path)
