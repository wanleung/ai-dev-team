"""MCP Server package.

FastAPI application with MCP protocol implementation, SSE transport,
and calendar tool registration.
"""

from src.mcp_server.app import create_app

__all__ = ["create_app"]
