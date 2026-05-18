"""Tests for MCP tool: list_folders."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_server.tools import list_folders


class TestListFoldersTool:
    """Tests for the list_folders MCP tool."""

    @pytest.mark.asyncio
    async def test_list_folders_success(self):
        """Given a valid account, when list_folders is called, then folders are returned."""
        mock_session = AsyncMock()
        mock_account = MagicMock()
        mock_account.id = 1
        mock_account.is_active = True

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_account)
        mock_session.execute.return_value = mock_result

        mock_pool = MagicMock()
        mock_client = MagicMock()
        mock_client.list_folders = AsyncMock(return_value=["INBOX", "Sent", "Drafts"])

        mock_pool.connection.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_pool.connection.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch("mcp_server.tools.list_folders.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("mcp_server.tools.list_folders._require_deps") as mock_deps:
                mock_deps.return_value.connection_pool = mock_pool

                result = await list_folders(account_id=1)

        data = json.loads(result)
        assert data["account_id"] == 1
        assert data["total"] == 3
        assert "INBOX" in data["folders"]
        assert "Sent" in data["folders"]
        assert "Drafts" in data["folders"]

    @pytest.mark.asyncio
    async def test_list_folders_empty(self):
        """Given an account with no folders, then an empty list is returned."""
        mock_session = AsyncMock()
        mock_account = MagicMock()
        mock_account.id = 1
        mock_account.is_active = True

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_account)
        mock_session.execute.return_value = mock_result

        mock_pool = MagicMock()
        mock_client = MagicMock()
        mock_client.list_folders = AsyncMock(return_value=[])

        mock_pool.connection.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_pool.connection.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch("mcp_server.tools.list_folders.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("mcp_server.tools.list_folders._require_deps") as mock_deps:
                mock_deps.return_value.connection_pool = mock_pool

                result = await list_folders(account_id=1)

        data = json.loads(result)
        assert data["folders"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_list_folders_raises_for_nonexistent_account(self):
        """Given a non-existent account, then a ValueError is raised."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_session.execute.return_value = mock_result

        with patch("mcp_server.tools.list_folders.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(ValueError, match="Account .* not found"):
                await list_folders(account_id=999)

    @pytest.mark.asyncio
    async def test_list_folders_raises_for_inactive_account(self):
        """Given an inactive account, then a ValueError is raised."""
        mock_session = AsyncMock()
        mock_account = MagicMock()
        mock_account.id = 1
        mock_account.is_active = False

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_account)
        mock_session.execute.return_value = mock_result

        with patch("mcp_server.tools.list_folders.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(ValueError, match="Account .* is inactive"):
                await list_folders(account_id=1)

    @pytest.mark.asyncio
    async def test_list_folders_with_gmail_labels(self):
        """Given a Gmail account, then labels are returned as folders."""
        mock_session = AsyncMock()
        mock_account = MagicMock()
        mock_account.id = 1
        mock_account.is_active = True

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_account)
        mock_session.execute.return_value = mock_result

        mock_pool = MagicMock()
        mock_client = MagicMock()
        mock_client.list_folders = AsyncMock(return_value=[
            "INBOX", "[Gmail]/Sent Mail", "[Gmail]/Drafts", "[Gmail]/Trash", "Custom Label"
        ])

        mock_pool.connection.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_pool.connection.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch("mcp_server.tools.list_folders.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("mcp_server.tools.list_folders._require_deps") as mock_deps:
                mock_deps.return_value.connection_pool = mock_pool

                result = await list_folders(account_id=1)

        data = json.loads(result)
        assert data["total"] == 5
        assert "[Gmail]/Sent Mail" in data["folders"]
        assert "Custom Label" in data["folders"]

    @pytest.mark.asyncio
    async def test_list_folders_raises_when_deps_not_initialized(self):
        """Given uninitialized dependencies, then a RuntimeError is raised."""
        mock_session = AsyncMock()
        mock_account = MagicMock()
        mock_account.id = 1
        mock_account.is_active = True

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_account)
        mock_session.execute.return_value = mock_result

        with patch("mcp_server.tools.list_folders.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("mcp_server.tools.list_folders._require_deps", side_effect=RuntimeError("not initialized")):
                with pytest.raises(RuntimeError, match="not initialized"):
                    await list_folders(account_id=1)
