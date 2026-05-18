"""MCP tool: mark_read - Mark a cached email as read in the database and on the IMAP server."""

import json
import logging

from sqlalchemy import select

from db.models import EmailMessage
from db.session import async_session_factory
from mcp_server.tools.base import _require_deps

logger = logging.getLogger(__name__)


async def mark_read(message_id: int) -> str:
    """Mark a cached email as read in the database and on the IMAP server.

    Args:
        message_id: The database ID of the email message.

    Returns:
        JSON string confirming the mark-read operation.

    Raises:
        ValueError: If the message does not exist.
    """
    async with async_session_factory() as session:
        stmt = select(EmailMessage).where(EmailMessage.id == message_id)
        result = await session.execute(stmt)
        msg = result.scalar_one_or_none()

        if msg is None:
            raise ValueError(f"Message {message_id} not found")

        account_id = msg.account_id
        await _require_deps().sync_manager.mark_read(session, message_id)

    return json.dumps({
        "status": "success",
        "message_id": message_id,
        "account_id": account_id,
    })
