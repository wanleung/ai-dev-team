"""MCP Server Initialization and Transport Configuration.

Creates the FastMCP server instance, registers tools, and provides
entry points for stdio and SSE/Streamable HTTP transports.
"""

import logging
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.fastmcp import FastMCP

from config.settings import get_settings
from db.session import close_db, init_db
from imap.connection_pool import IMAPConnectionPool
from imap.oauth2_manager import OAuth2Manager
from mcp_server.tools import AppDependencies, register_tools, set_dependencies
from parser.email_parser import EmailParser
from sync.manager import SyncManager

logger = logging.getLogger(__name__)

_container: dict[str, Any] = {"deps": None}


@asynccontextmanager
async def server_lifespan(server: FastMCP) -> dict[str, Any]:
    """Manage MCP server lifecycle: initialize DB, connection pool, and sync manager."""
    logger.info("MCP Email Service starting up...")

    await init_db()

    settings = get_settings()
    settings.ensure_storage_path()

    connection_pool = IMAPConnectionPool()
    oauth2_manager = OAuth2Manager()
    connection_pool.oauth2_manager = oauth2_manager

    await connection_pool.start()

    sync_manager = SyncManager(
        connection_pool=connection_pool,
        parser=EmailParser(),
        sync_interval=settings.sync_interval_seconds,
        batch_size=settings.sync_batch_size,
    )

    _container["deps"] = AppDependencies(
        sync_manager=sync_manager,
        connection_pool=connection_pool,
        oauth2_manager=oauth2_manager,
    )

    set_dependencies(_container["deps"])

    sync_manager.start_background_sync()

    logger.info("Database initialized, connection pool and sync manager started")

    try:
        yield {}
    finally:
        logger.info("MCP Email Service shutting down...")
        await sync_manager.stop_background_sync()
        await connection_pool.stop()
        await close_db()
        _container["deps"] = None


def create_mcp_server() -> FastMCP:
    """Create and configure the MCP Email Service server.

    Returns:
        Configured FastMCP server instance with all tools registered.
    """
    settings = get_settings()

    mcp = FastMCP(
        name=settings.app_name,
        instructions="MCP Email Service - manage IMAP email accounts, sync emails, and query cached messages.",
        lifespan=server_lifespan,
    )

    register_tools(mcp)

    logger.info("MCP tools registered: list_emails, get_email, search_emails, "
                "sync_account, mark_read, list_accounts, add_account, get_sync_state, send_email")

    return mcp


def run_stdio() -> None:
    """Run the MCP server using stdio transport.

    Suitable for use with Claude Desktop or other stdio-based MCP clients.
    """
    mcp = create_mcp_server()
    mcp.run(transport="stdio")


def run_sse(host: str = "0.0.0.0", port: int = 8000) -> None:
    """Run the MCP server using SSE transport.

    Suitable for browser-based or network-accessible MCP clients.

    Args:
        host: Host address to bind the SSE server to.
        port: Port number to bind the SSE server to.
    """
    mcp = create_mcp_server()
    mcp.run(transport="sse", host=host, port=port)


def run_streamable_http(host: str = "0.0.0.0", port: int = 8000) -> None:
    """Run the MCP server using Streamable HTTP transport.

    Args:
        host: Host address to bind the server to.
        port: Port number to bind the server to.
    """
    mcp = create_mcp_server()
    mcp.run(transport="streamable-http", host=host, port=port)


if __name__ == "__main__":
    settings = get_settings()
    transport = settings.mcp_transport

    logging.basicConfig(level=logging.INFO)

    if transport == "stdio":
        run_stdio()
    elif transport == "sse":
        run_sse(host=settings.mcp_server_host, port=settings.mcp_server_port)
    else:
        run_streamable_http(host=settings.mcp_server_host, port=settings.mcp_server_port)
