"""FastAPI application setup for the Calendar MCP Service.

Creates and configures the FastAPI application with MCP protocol endpoints,
SSE transport, and calendar tool registration.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from src.mcp_server.handlers import register_handlers
from src.mcp_server.sse import sse_endpoint
from src.mcp_server.tools import register_tools

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown hooks."""
    logger.info("Calendar MCP Service starting up")
    yield
    logger.info("Calendar MCP Service shutting down")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        A configured FastAPI instance with MCP endpoints and SSE transport.
    """
    app = FastAPI(
        title="Calendar MCP Service",
        description="MCP-compliant service for Google Calendar and Outlook Calendar operations",
        version="1.0.0",
        lifespan=lifespan,
    )

    register_tools(app)
    register_handlers(app)

    app.add_api_route("/sse", sse_endpoint, methods=["GET"])

    return app
