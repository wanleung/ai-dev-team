"""MCP Server Gateway for MCP Email Service.

Exposes AI-facing tools (list_emails, get_email, search_emails, sync_account, mark_read)
via stdio/SSE transport using the official MCP Python SDK.
"""

from mcp_server.tools import register_tools
from mcp_server.server import create_mcp_server

__all__ = ["register_tools", "create_mcp_server"]
