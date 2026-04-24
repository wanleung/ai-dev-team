"""MCP tool: get_sync_state - Get the current IMAP sync state for all folders of an account."""

import json
import logging

from db.session import async_session_factory
from mcp_server.tools.base import _require_deps

logger = logging.getLogger(__name__)


async def get_sync_state(account_id: int) -> str:
    """Get the current IMAP sync state for all folders of an account.

    Args:
        account_id: The email account ID to query.

    Returns:
        JSON string with per-folder sync states including last synced UID.
    """
    async with async_session_factory() as session:
        states = await _require_deps().sync_manager.get_sync_state(session, account_id)

    return json.dumps({
        "account_id": account_id,
        "folders": states,
    })
