"""MCP tool: get_email - Get full details of a cached email including attachments."""

import json
import logging

from sqlalchemy import select

from db.models import Attachment, EmailMessage
from db.session import async_session_factory

logger = logging.getLogger(__name__)


async def get_email(message_id: int) -> str:
    """Get full details of a cached email including attachments.

    Args:
        message_id: The database ID of the email message.

    Returns:
        JSON string with full email data and attachment list.

    Raises:
        ValueError: If the message does not exist.
    """
    async with async_session_factory() as session:
        stmt = select(EmailMessage).where(EmailMessage.id == message_id)
        result = await session.execute(stmt)
        msg = result.scalar_one_or_none()

        if msg is None:
            raise ValueError(f"Message {message_id} not found")

        att_stmt = select(Attachment).where(Attachment.message_id == message_id)
        att_result = await session.execute(att_stmt)
        attachments = att_result.scalars().all()

        data = {
            "id": msg.id,
            "account_id": msg.account_id,
            "uid": msg.uid,
            "message_id": msg.message_id,
            "subject": msg.subject,
            "sender": msg.sender,
            "recipients": msg.recipients,
            "date_received": msg.date_received.isoformat(),
            "body_text": msg.body_text,
            "body_html": msg.body_html,
            "has_attachments": msg.has_attachments,
            "is_read": msg.is_read,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
            "attachments": [
                {
                    "id": att.id,
                    "filename": att.filename,
                    "content_type": att.content_type,
                    "size_bytes": att.size_bytes,
                    "storage_path": att.storage_path,
                }
                for att in attachments
            ],
        }

        return json.dumps(data)
