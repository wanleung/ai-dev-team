"""MCP Tool Definitions for MCP Email Service.

Registers AI-facing tools (list_emails, get_email, search_emails, sync_account,
mark_read, list_accounts, add_account, get_sync_state, send_email, download_attachments,
list_folders) via the MCP Python SDK. All dependencies are injected via lifespan,
not instantiated at module level.

This package re-exports from submodules for backward compatibility.
"""

from mcp_server.tools.base import (
    AppDependencies,
    set_dependencies,
    _require_deps,
)
from mcp_server.tools.register import register_tools
from mcp_server.tools.list_emails import list_emails
from mcp_server.tools.get_email import get_email
from mcp_server.tools.search_emails import search_emails
from mcp_server.tools.mark_read import mark_read
from mcp_server.tools.download_attachments import download_attachments
from mcp_server.tools.list_folders import list_folders
from mcp_server.tools.sync_account import sync_account
from mcp_server.tools.list_accounts import list_accounts
from mcp_server.tools.add_account import add_account
from mcp_server.tools.get_sync_state import get_sync_state
from mcp_server.tools.send_email import send_email

__all__ = [
    "AppDependencies",
    "set_dependencies",
    "_require_deps",
    "register_tools",
    "list_emails",
    "get_email",
    "search_emails",
    "mark_read",
    "download_attachments",
    "list_folders",
    "sync_account",
    "list_accounts",
    "add_account",
    "get_sync_state",
    "send_email",
]
