"""MCP tool: list_accounts - List all registered IMAP email accounts."""

import json
import logging

from sqlalchemy import select

from db.models import EmailAccount
from db.session import async_session_factory

logger = logging.getLogger(__name__)


async def list_accounts() -> str:
    """List all registered IMAP email accounts.

    Returns:
        JSON string with account summaries.
    """
    async with async_session_factory() as session:
        stmt = select(EmailAccount).order_by(EmailAccount.id)
        result = await session.execute(stmt)
        accounts = result.scalars().all()

        items = []
        for acc in accounts:
            items.append({
                "id": acc.id,
                "email_address": acc.email_address,
                "imap_host": acc.imap_host,
                "imap_port": acc.imap_port,
                "is_active": acc.is_active,
                "created_at": acc.created_at.isoformat() if acc.created_at else None,
            })

        return json.dumps(items)
