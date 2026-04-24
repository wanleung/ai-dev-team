"""FastAPI router for email query and attachment endpoints."""

import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Attachment, EmailMessage
from db.session import get_session
from api.schemas import AttachmentResponse, EmailListResponse, EmailResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/emails", tags=["emails"])


@router.get(
    "",
    response_model=EmailListResponse,
    summary="Query cached emails",
)
async def list_emails(
    account_id: Optional[int] = Query(default=None, description="Filter by account ID"),
    limit: int = Query(default=50, ge=1, le=200, description="Results per page"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    search: Optional[str] = Query(default=None, description="Search term for subject/sender"),
    is_read: Optional[bool] = Query(default=None, description="Filter by read status"),
    has_attachments: Optional[bool] = Query(default=None, description="Filter by attachment presence"),
    session: AsyncSession = Depends(get_session),
) -> EmailListResponse:
    """Query cached emails with filtering and pagination."""
    query = select(EmailMessage)
    count_query = select(func.count()).select_from(EmailMessage)

    if account_id is not None:
        query = query.where(EmailMessage.account_id == account_id)
        count_query = count_query.where(EmailMessage.account_id == account_id)

    if search:
        search_pattern = f"%{search}%"
        query = query.where(
            EmailMessage.subject.ilike(search_pattern)
            | EmailMessage.sender.ilike(search_pattern)
        )
        count_query = count_query.where(
            EmailMessage.subject.ilike(search_pattern)
            | EmailMessage.sender.ilike(search_pattern)
        )

    if is_read is not None:
        query = query.where(EmailMessage.is_read == is_read)
        count_query = count_query.where(EmailMessage.is_read == is_read)

    if has_attachments is not None:
        query = query.where(EmailMessage.has_attachments == has_attachments)
        count_query = count_query.where(EmailMessage.has_attachments == has_attachments)

    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    result = await session.execute(
        query.order_by(EmailMessage.date_received.desc())
        .offset(offset)
        .limit(limit)
    )
    emails = result.scalars().all()

    return EmailListResponse(
        items=[EmailResponse.model_validate(e) for e in emails],
        total=total,
    )


@router.get(
    "/{email_id}",
    response_model=EmailResponse,
    summary="Get full email detail with attachments",
)
async def get_email(
    email_id: int,
    session: AsyncSession = Depends(get_session),
) -> EmailResponse:
    """Retrieve a single cached email with all attachment metadata."""
    result = await session.execute(
        select(EmailMessage).where(EmailMessage.id == email_id)
    )
    email = result.scalar_one_or_none()

    if not email:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Email {email_id} not found",
        )

    attachments_result = await session.execute(
        select(Attachment).where(Attachment.message_id == email_id)
    )
    attachments = attachments_result.scalars().all()

    response = EmailResponse.model_validate(email)
    response.attachments = [AttachmentResponse.model_validate(a) for a in attachments]

    return response


@router.get(
    "/{email_id}/attachments/{attachment_id}/download",
    summary="Stream an email attachment",
)
async def download_attachment(
    email_id: int,
    attachment_id: int,
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """Stream an attachment file from local storage."""
    result = await session.execute(
        select(Attachment).where(
            Attachment.id == attachment_id,
            Attachment.message_id == email_id,
        )
    )
    attachment = result.scalar_one_or_none()

    if not attachment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Attachment {attachment_id} not found for email {email_id}",
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


@router.patch(
    "/{email_id}/read",
    response_model=EmailResponse,
    summary="Mark email as read",
)
async def mark_email_read(
    email_id: int,
    session: AsyncSession = Depends(get_session),
) -> EmailResponse:
    """Mark a cached email as read."""
    result = await session.execute(
        select(EmailMessage).where(EmailMessage.id == email_id)
    )
    email = result.scalar_one_or_none()

    if not email:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Email {email_id} not found",
        )

    email.is_read = True
    await session.flush()
    await session.refresh(email)

    return EmailResponse.model_validate(email)
