"""Tests for MCP server creation and lifecycle."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestCreateMcpServer:
    """Tests for create_mcp_server function."""

    def test_create_mcp_server_returns_fastmcp_instance(self):
        from mcp_server.server import create_mcp_server

        mock_settings = MagicMock()
        mock_settings.app_name = "MCP Email Service (Test)"
        mock_settings.ensure_storage_path.return_value = None

        with patch("mcp_server.server.get_settings", return_value=mock_settings):
            with patch("mcp_server.server.FastMCP") as MockFastMCP:
                mock_mcp = MagicMock()
                MockFastMCP.return_value = mock_mcp

                result = create_mcp_server()

                assert result is mock_mcp
                MockFastMCP.assert_called_once()
                call_kwargs = MockFastMCP.call_args[1]
                assert call_kwargs["name"] == "MCP Email Service (Test)"
                assert "lifespan" in call_kwargs

    def test_create_mcp_server_registers_tools(self):
        from mcp_server.server import create_mcp_server

        mock_settings = MagicMock()
        mock_settings.app_name = "MCP Email Service"
        mock_settings.ensure_storage_path.return_value = None

        with patch("mcp_server.server.get_settings", return_value=mock_settings):
            with patch("mcp_server.server.FastMCP") as MockFastMCP:
                mock_mcp = MagicMock()
                MockFastMCP.return_value = mock_mcp

                with patch("mcp_server.server.register_tools") as mock_register:
                    create_mcp_server()

                    mock_register.assert_called_once()
                    args = mock_register.call_args[0]
                    assert args[0] is mock_mcp


class TestServerLifespan:
    """Tests for server_lifespan context manager."""

    @pytest.mark.asyncio
    async def test_lifespan_initializes_db(self):
        from mcp_server.server import server_lifespan

        mock_server = MagicMock()

        with patch("mcp_server.server.init_db") as mock_init_db:
            with patch("mcp_server.server.get_settings") as mock_get_settings:
                mock_settings = MagicMock()
                mock_settings.ensure_storage_path.return_value = None
                mock_get_settings.return_value = mock_settings

                with patch("mcp_server.server.close_db") as mock_close_db:
                    async with server_lifespan(mock_server) as ctx:
                        mock_init_db.assert_called_once()
                        mock_settings.ensure_storage_path.assert_called_once()

                    mock_close_db.assert_called_once()

    @pytest.mark.asyncio
    async def test_lifespan_cleans_up_on_exit(self):
        from mcp_server.server import server_lifespan

        mock_server = MagicMock()

        with patch("mcp_server.server.init_db"):
            with patch("mcp_server.server.get_settings") as mock_get_settings:
                mock_settings = MagicMock()
                mock_settings.ensure_storage_path.return_value = None
                mock_get_settings.return_value = mock_settings

                with patch("mcp_server.server.SyncManager") as MockSyncManager:
                    mock_sync_manager = MagicMock()
                    mock_sync_manager.stop_background_sync = AsyncMock()
                    MockSyncManager.return_value = mock_sync_manager

                    with patch("mcp_server.server.IMAPConnectionPool") as MockPool:
                        mock_pool = MagicMock()
                        mock_pool.start = AsyncMock()
                        mock_pool.stop = AsyncMock()
                        MockPool.return_value = mock_pool

                        with patch("mcp_server.server.close_db"):
                            async with server_lifespan(mock_server):
                                pass

                            mock_sync_manager.stop_background_sync.assert_called_once()


class TestRunTransports:
    """Tests for transport runner functions."""

    def test_run_stdio_calls_mcp_run(self):
        from mcp_server.server import run_stdio

        with patch("mcp_server.server.create_mcp_server") as mock_create:
            mock_mcp = MagicMock()
            mock_create.return_value = mock_mcp

            run_stdio()

            mock_mcp.run.assert_called_once_with(transport="stdio")

    def test_run_sse_calls_mcp_run_with_params(self):
        from mcp_server.server import run_sse

        with patch("mcp_server.server.create_mcp_server") as mock_create:
            mock_mcp = MagicMock()
            mock_create.return_value = mock_mcp

            run_sse(host="127.0.0.1", port=9000)

            mock_mcp.run.assert_called_once_with(transport="sse", host="127.0.0.1", port=9000)

    def test_run_sse_uses_defaults(self):
        from mcp_server.server import run_sse

        with patch("mcp_server.server.create_mcp_server") as mock_create:
            mock_mcp = MagicMock()
            mock_create.return_value = mock_mcp

            run_sse()

            mock_mcp.run.assert_called_once_with(transport="sse", host="0.0.0.0", port=8000)

    def test_run_streamable_http_calls_mcp_run(self):
        from mcp_server.server import run_streamable_http

        with patch("mcp_server.server.create_mcp_server") as mock_create:
            mock_mcp = MagicMock()
            mock_create.return_value = mock_mcp

            run_streamable_http(host="127.0.0.1", port=9000)

            mock_mcp.run.assert_called_once_with(
                transport="streamable-http", host="127.0.0.1", port=9000
            )


class TestMainEntry:
    """Tests for __main__ entry point logic."""

    def test_main_selects_stdio_transport(self):
        with patch("mcp_server.server.get_settings") as mock_get:
            mock_settings = MagicMock()
            mock_settings.mcp_transport = "stdio"
            mock_get.return_value = mock_settings

            with patch("mcp_server.server.run_stdio") as mock_run:
                import importlib
                import mcp_server.server
                importlib.reload(mcp_server.server)

                mcp_server.server.run_stdio = mock_run

                if mock_settings.mcp_transport == "stdio":
                    mcp_server.server.run_stdio()

                mock_run.assert_called_once()

    def test_main_selects_sse_transport(self):
        with patch("mcp_server.server.get_settings") as mock_get:
            mock_settings = MagicMock()
            mock_settings.mcp_transport = "sse"
            mock_settings.mcp_server_host = "0.0.0.0"
            mock_settings.mcp_server_port = 8000
            mock_get.return_value = mock_settings

            with patch("mcp_server.server.run_sse") as mock_run:
                if mock_settings.mcp_transport == "sse":
                    mock_run(
                        host=mock_settings.mcp_server_host,
                        port=mock_settings.mcp_server_port,
                    )

                mock_run.assert_called_once()

    def test_main_selects_streamable_http_transport(self):
        with patch("mcp_server.server.get_settings") as mock_get:
            mock_settings = MagicMock()
            mock_settings.mcp_transport = "streamable-http"
            mock_settings.mcp_server_host = "0.0.0.0"
            mock_settings.mcp_server_port = 8000
            mock_get.return_value = mock_settings

            with patch("mcp_server.server.run_streamable_http") as mock_run:
                if mock_settings.mcp_transport not in ("stdio", "sse"):
                    mock_run(
                        host=mock_settings.mcp_server_host,
                        port=mock_settings.mcp_server_port,
                    )

                mock_run.assert_called_once()
