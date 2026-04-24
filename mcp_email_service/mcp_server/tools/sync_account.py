"""MCP tool: sync_account - Trigger an incremental IMAP sync for a registered account."""

import json
import logging
from typing import Optional

from mcp.server.fastmcp import Context
from mcp.server.session import ServerSession
from sqlalchemy import select

from db.models import EmailAccount
from db.session import async_session_factory
from mcp_server.tools.base import _require_deps

logger = logging.getLogger(__name__)


async def sync_account(
    ctx: Context[ServerSession, None],
    account_id: int,
    folders: Optional[str] = None,
) -> str:
    """Trigger an incremental IMAP sync for a registered account.

    Args:
        ctx: MCP context for progress reporting.
        account_id: The email account ID to sync.
        folders: Optional comma-separated list of folders to sync.

    Returns:
        JSON string with sync status and per-folder message counts.

    Raises:
        ValueError: If the account does not exist or is inactive.
    """
    await ctx.info(f"Starting sync for account {account_id}")

    folder_list = [f.strip() for f in folders.split(",")] if folders else None

    async with async_session_factory() as session:
        stmt = select(EmailAccount).where(EmailAccount.id == account_id)
        result = await session.execute(stmt)
        account = result.scalar_one_or_none()

        if account is None:
            raise ValueError(f"Account {account_id} not found")

        if not account.is_active:
            raise ValueError(f"Account {account_id} is inactive")

        results = await _require_deps().sync_manager.sync_account(
            account_id, session, folders=folder_list
        )

    await ctx.info(f"Sync complete for account {account_id}: {results}")

    return json.dumps({
        "status": "success",
        "account_id": account_id,
        "messages_synced": results,
    })
