"""MCP tool: search_emails - Search cached emails by subject, sender, or body text."""

import json
import logging

from sqlalchemy import func, select

from db.models import EmailMessage
from db.session import async_session_factory

logger = logging.getLogger(__name__)


async def search_emails(
    account_id: int,
    query: str,
    limit: int = 20,
    offset: int = 0,
) -> str:
    """Search cached emails by subject, sender, or body text.

    Args:
        account_id: The email account ID to search within.
        query: The search term to match against subject, sender, and body.
        limit: Maximum number of results to return.
        offset: Number of results to skip.

    Returns:
        JSON string with matching email items and total count.
    """
    pattern = f"%{query}%"

    async with async_session_factory() as session:
        base_query = select(EmailMessage).where(
            EmailMessage.account_id == account_id,
            (
                EmailMessage.subject.ilike(pattern)
                | EmailMessage.sender.ilike(pattern)
                | EmailMessage.body_text.ilike(pattern)
            ),
        )

        count_query = select(func.count()).select_from(base_query.subquery())
        total_result = await session.execute(count_query)
        total = total_result.scalar_one()

        results_query = (
            base_query.order_by(EmailMessage.date_received.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await session.execute(results_query)
        messages = result.scalars().all()

        items = []
        for msg in messages:
            items.append({
                "id": msg.id,
                "subject": msg.subject,
                "sender": msg.sender,
                "date_received": msg.date_received.isoformat(),
                "is_read": msg.is_read,
                "has_attachments": msg.has_attachments,
            })

        return json.dumps({"items": items, "total": total})
