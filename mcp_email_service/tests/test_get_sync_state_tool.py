"""Tests for MCP tool: get_sync_state."""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_server.tools import get_sync_state


class TestGetSyncStateTool:
    """Tests for the get_sync_state MCP tool."""

    @pytest.mark.asyncio
    async def test_get_sync_state_returns_folders(self):
        """Given a synced account, then per-folder sync states are returned."""
        mock_session = AsyncMock()

        with patch("mcp_server.tools.sync_account.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch.object(get_sync_state.__module__.split('.')[0] + ".tools", "_require_deps") as mock_deps:
                pass

        mock_session2 = AsyncMock()

        with patch("mcp_server.tools.get_sync_state.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session2)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("mcp_server.tools.get_sync_state._require_deps") as mock_deps:
                mock_deps.return_value.sync_manager.get_sync_state = AsyncMock(return_value=[
                    {"folder_name": "INBOX", "last_synced_uid": 100, "last_synced_at": datetime.now(timezone.utc), "status": "idle"},
                    {"folder_name": "Sent", "last_synced_uid": 50, "last_synced_at": datetime.now(timezone.utc), "status": "idle"},
                ])

                result = await get_sync_state(account_id=1)

        data = json.loads(result)
        assert data["account_id"] == 1
        assert len(data["folders"]) == 2
        assert data["folders"][0]["folder_name"] == "INBOX"
        assert data["folders"][1]["folder_name"] == "Sent"

    @pytest.mark.asyncio
    async def test_get_sync_state_empty(self):
        """Given an account with no sync history, then empty folders list is returned."""
        mock_session = AsyncMock()

        with patch("mcp_server.tools.get_sync_state.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("mcp_server.tools.get_sync_state._require_deps") as mock_deps:
                mock_deps.return_value.sync_manager.get_sync_state = AsyncMock(return_value=[])

                result = await get_sync_state(account_id=1)

        data = json.loads(result)
        assert data["account_id"] == 1
        assert data["folders"] == []

    @pytest.mark.asyncio
    async def test_get_sync_state_raises_when_deps_not_initialized(self):
        """Given uninitialized dependencies, then a RuntimeError is raised."""
        mock_session = AsyncMock()

        with patch("mcp_server.tools.get_sync_state.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("mcp_server.tools.get_sync_state._require_deps", side_effect=RuntimeError("not initialized")):
                with pytest.raises(RuntimeError, match="not initialized"):
                    await get_sync_state(account_id=1)
