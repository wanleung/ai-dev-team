"""MCP Server module for Calendar MCP Service.

Implements MCP protocol over HTTP/SSE transport with tool registration
for calendar operations.
"""

from .app import create_app
from .sse import SSETransport
from .tools import register_calendar_tools
from .handlers import MCPMessageHandler

__all__ = [
    "create_app",
    "SSETransport",
    "register_calendar_tools",
    "MCPMessageHandler",
]
