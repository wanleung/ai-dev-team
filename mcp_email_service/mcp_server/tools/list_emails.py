"""MCP tool: list_emails - List cached emails for a given IMAP account."""

import json
import logging
from typing import Optional

from sqlalchemy import func, select

from db.models import EmailMessage
from db.session import async_session_factory

logger = logging.getLogger(__name__)


async def list_emails(
    account_id: int,
    limit: int = 20,
    offset: int = 0,
    search: Optional[str] = None,
    is_read: Optional[bool] = None,
    folder: Optional[str] = None,
) -> str:
    """List cached emails for a given IMAP account.

    Args:
        account_id: The email account ID to query.
        limit: Maximum number of emails to return.
        offset: Number of emails to skip (for pagination).
        search: Optional free-text search on subject and sender.
        is_read: Optional filter by read status.
        folder: Optional filter by IMAP folder (via sync state join).

    Returns:
        JSON string with items array and total count.
    """
    async with async_session_factory() as session:
        query = select(EmailMessage).where(EmailMessage.account_id == account_id)

        if search:
            search_pattern = f"%{search}%"
            query = query.where(
                (EmailMessage.subject.ilike(search_pattern))
                | (EmailMessage.sender.ilike(search_pattern))
            )

        if is_read is not None:
            query = query.where(EmailMessage.is_read == is_read)

        count_query = select(func.count()).select_from(query.subquery())
        total_result = await session.execute(count_query)
        total = total_result.scalar_one()

        query = query.order_by(EmailMessage.date_received.desc())
        query = query.offset(offset).limit(limit)

        result = await session.execute(query)
        messages = result.scalars().all()

        items = []
        for msg in messages:
            items.append({
                "id": msg.id,
                "account_id": msg.account_id,
                "uid": msg.uid,
                "message_id": msg.message_id,
                "subject": msg.subject,
                "sender": msg.sender,
                "recipients": msg.recipients,
                "date_received": msg.date_received.isoformat(),
                "has_attachments": msg.has_attachments,
                "is_read": msg.is_read,
            })

        return json.dumps({"items": items, "total": total})
