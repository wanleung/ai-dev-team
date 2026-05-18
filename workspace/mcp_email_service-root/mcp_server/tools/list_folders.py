"""MCP tool: list_folders - List IMAP folders for a given account."""

import json
import logging

from sqlalchemy import select

from db.models import EmailAccount
from db.session import async_session_factory
from imap.connection_pool import IMAPConnectionPool
from mcp_server.tools.base import _require_deps

logger = logging.getLogger(__name__)


async def list_folders(account_id: int) -> str:
    """List IMAP folders for a given email account.

    Connects to the IMAP server and retrieves the folder list.

    Args:
        account_id: The email account ID to query.

    Returns:
        JSON string with list of folder names.

    Raises:
        ValueError: If the account does not exist or is inactive.
        RuntimeError: If the IMAP connection fails.
    """
    async with async_session_factory() as session:
        stmt = select(EmailAccount).where(EmailAccount.id == account_id)
        result = await session.execute(stmt)
        account = result.scalar_one_or_none()

        if account is None:
            raise ValueError(f"Account {account_id} not found")

        if not account.is_active:
            raise ValueError(f"Account {account_id} is inactive")

        connection_pool = _require_deps().connection_pool

        async with connection_pool.connection(account_id) as client:
            folders = await client.list_folders()

    return json.dumps({
        "account_id": account_id,
        "folders": folders,
        "total": len(folders),
    })
