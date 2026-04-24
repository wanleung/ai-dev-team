"""MCP tool registration for MCP Email Service.

Registers all MCP tools on the given FastMCP server instance.
Tools are organized into individual modules for maintainability.
"""

import logging
from typing import Optional

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

from mcp_server.tools.list_emails import list_emails as _list_emails
from mcp_server.tools.get_email import get_email as _get_email
from mcp_server.tools.search_emails import search_emails as _search_emails
from mcp_server.tools.mark_read import mark_read as _mark_read
from mcp_server.tools.download_attachments import download_attachments as _download_attachments
from mcp_server.tools.list_folders import list_folders as _list_folders
from mcp_server.tools.sync_account import sync_account as _sync_account
from mcp_server.tools.list_accounts import list_accounts as _list_accounts
from mcp_server.tools.add_account import add_account as _add_account
from mcp_server.tools.get_sync_state import get_sync_state as _get_sync_state
from mcp_server.tools.send_email import send_email as _send_email

logger = logging.getLogger(__name__)


def register_tools(
    mcp: FastMCP,
) -> None:
    """Register all MCP tools on the given FastMCP server instance.

    Tools read dependencies from the module-level _deps variable,
    which is populated by set_dependencies() during server lifespan.

    Args:
        mcp: The FastMCP server to register tools on.
    """

    @mcp.tool()
    async def list_emails(
        account_id: int,
        limit: int = 20,
        offset: int = 0,
        search: Optional[str] = None,
        is_read: Optional[bool] = None,
        folder: Optional[str] = None,
    ) -> str:
        """List cached emails for a given IMAP account."""
        return await _list_emails(account_id, limit, offset, search, is_read, folder)

    @mcp.tool()
    async def get_email(message_id: int) -> str:
        """Get full details of a cached email including attachments."""
        return await _get_email(message_id)

    @mcp.tool()
    async def search_emails(
        account_id: int,
        query: str,
        limit: int = 20,
        offset: int = 0,
    ) -> str:
        """Search cached emails by subject, sender, or body text."""
        return await _search_emails(account_id, query, limit, offset)

    @mcp.tool()
    async def sync_account(
        ctx: Context[ServerSession, None],
        account_id: int,
        folders: Optional[str] = None,
    ) -> str:
        """Trigger an incremental IMAP sync for a registered account."""
        return await _sync_account(ctx, account_id, folders)

    @mcp.tool()
    async def mark_read(message_id: int) -> str:
        """Mark a cached email as read in the database and on the IMAP server."""
        return await _mark_read(message_id)

    @mcp.tool()
    async def list_accounts() -> str:
        """List all registered IMAP email accounts."""
        return await _list_accounts()

    @mcp.tool()
    async def add_account(
        email_address: str,
        imap_host: str,
        imap_port: int = 993,
        username: str = "",
        password: str = "",
        user_id: str = "default",
        auth_method: str = "basic",
    ) -> str:
        """Register a new IMAP email account for syncing."""
        return await _add_account(
            email_address, imap_host, imap_port, username, password, user_id, auth_method
        )

    @mcp.tool()
    async def get_sync_state(account_id: int) -> str:
        """Get the current IMAP sync state for all folders of an account."""
        return await _get_sync_state(account_id)

    @mcp.tool()
    async def send_email(
        account_id: int,
        to: str,
        subject: str,
        body: str,
        cc: Optional[str] = None,
        bcc: Optional[str] = None,
        html: Optional[str] = None,
        attachment_paths: Optional[str] = None,
    ) -> str:
        """Send an email via SMTP using a registered account."""
        return await _send_email(
            account_id, to, subject, body, cc, bcc, html, attachment_paths
        )

    @mcp.tool()
    async def download_attachments(
        message_id: int,
        attachment_id: int,
    ) -> str:
        """Download an attachment file from local storage."""
        return await _download_attachments(message_id, attachment_id)

    @mcp.tool()
    async def list_folders(account_id: int) -> str:
        """List IMAP folders for a given email account."""
        return await _list_folders(account_id)
