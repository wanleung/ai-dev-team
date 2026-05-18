"""FastAPI router for attachment download endpoints.

Provides streaming file downloads for email attachments with
ownership validation and correct content headers.

Endpoint: GET /accounts/{account_id}/emails/{message_id}/attachments/{attachment_id}
"""

import logging
import os

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Attachment, EmailMessage, EmailAccount
from db.session import get_session
from middleware.auth import get_current_user, require_auth, UserContext

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/accounts/{account_id}/emails/{message_id}/attachments",
    tags=["attachments"],
)


@router.get(
    "/{attachment_id}",
    summary="Download an email attachment",
)
async def download_attachment(
    account_id: int,
    message_id: int,
    attachment_id: int,
    session: AsyncSession = Depends(get_session),
    user: UserContext = Depends(require_auth),
) -> StreamingResponse:
    """Stream an attachment file from local storage.

    Validates that the attachment belongs to the specified message,
    the message belongs to the specified account, and the account
    belongs to the authenticated user. Then streams the file with
    correct Content-Type and Content-Disposition headers.

    Args:
        account_id: The database ID of the email account.
        message_id: The database ID of the email message.
        attachment_id: The database ID of the attachment.
        session: Database session (injected).
        user: Authenticated user context (injected).

    Returns:
        StreamingResponse with the attachment file content.

    Raises:
        HTTPException: 404 if attachment, message, or account not found.
        HTTPException: 403 if the account does not belong to the user.
    """
    account_result = await session.execute(
        select(EmailAccount).where(
            EmailAccount.id == account_id,
            EmailAccount.user_id == user.user_id,
        )
    )
    account = account_result.scalar_one_or_none()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Account {account_id} not found or access denied",
        )

    message_result = await session.execute(
        select(EmailMessage).where(
            EmailMessage.id == message_id,
            EmailMessage.account_id == account_id,
        )
    )
    message = message_result.scalar_one_or_none()

    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Email message {message_id} not found in account {account_id}",
        )

    attachment_result = await session.execute(
        select(Attachment).where(
            Attachment.id == attachment_id,
            Attachment.message_id == message_id,
        )
    )
    attachment = attachment_result.scalar_one_or_none()

    if not attachment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Attachment {attachment_id} not found in message {message_id}",
        )

    storage_path = attachment.storage_path

    if not os.path.exists(storage_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Attachment file not found at {storage_path}",
        )

    def iter_file():
        with open(storage_path, "rb") as f:
            while chunk := f.read(8192):
                yield chunk

    return StreamingResponse(
        iter_file(),
        media_type=attachment.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{attachment.filename}"',
            "Content-Length": str(attachment.size_bytes),
        },
    )
