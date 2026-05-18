"""MCP tool: download_attachments - Download attachment content from local storage."""

import json
import logging
import os

from sqlalchemy import select

from db.models import Attachment, EmailMessage
from db.session import async_session_factory

logger = logging.getLogger(__name__)


async def download_attachments(message_id: int, attachment_id: int) -> str:
    """Download an attachment file from local storage.

    Returns the file content as base64-encoded string along with metadata,
    suitable for MCP text response.

    Args:
        message_id: The database ID of the email message.
        attachment_id: The database ID of the attachment.

    Returns:
        JSON string with attachment metadata and base64-encoded content.

    Raises:
        ValueError: If the message or attachment does not exist, or file is missing.
    """
    import base64

    async with async_session_factory() as session:
        msg_stmt = select(EmailMessage).where(EmailMessage.id == message_id)
        msg_result = await session.execute(msg_stmt)
        msg = msg_result.scalar_one_or_none()

        if msg is None:
            raise ValueError(f"Message {message_id} not found")

        att_stmt = select(Attachment).where(
            Attachment.id == attachment_id,
            Attachment.message_id == message_id,
        )
        att_result = await session.execute(att_stmt)
        attachment = att_result.scalar_one_or_none()

        if attachment is None:
            raise ValueError(
                f"Attachment {attachment_id} not found in message {message_id}"
            )

        storage_path = attachment.storage_path

        if not os.path.exists(storage_path):
            raise ValueError(
                f"Attachment file not found at {storage_path}"
            )

        with open(storage_path, "rb") as f:
            content = f.read()

        content_b64 = base64.b64encode(content).decode("utf-8")

        return json.dumps({
            "id": attachment.id,
            "filename": attachment.filename,
            "content_type": attachment.content_type,
            "size_bytes": attachment.size_bytes,
            "content_base64": content_b64,
        })
