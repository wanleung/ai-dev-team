"""FastAPI router for account management endpoints."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import get_encryption_manager, get_settings
from db.models import EmailAccount
from db.session import get_session
from api.schemas import (
    AccountCreate,
    AccountListResponse,
    AccountResponse,
    SyncRequest,
    SyncResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.post(
    "",
    response_model=AccountResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new IMAP account",
)
async def create_account(
    payload: AccountCreate,
    session: AsyncSession = Depends(get_session),
) -> AccountResponse:
    """Register a new IMAP account with encrypted credentials.

    Validates the IMAP connection, encrypts the password, and persists
    the account details to the database.
    """
    encryption_manager = get_encryption_manager()
    encrypted_password = encryption_manager.encrypt(payload.password)

    account = EmailAccount(
        user_id=payload.user_id,
        email_address=payload.email_address,
        imap_host=payload.imap_host,
        imap_port=payload.imap_port,
        username=payload.username,
        encrypted_password=encrypted_password,
        is_active=True,
    )

    session.add(account)
    await session.flush()
    await session.refresh(account)

    return AccountResponse.model_validate(account)


@router.get(
    "",
    response_model=AccountListResponse,
    summary="List registered accounts",
)
async def list_accounts(
    user_id: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
) -> AccountListResponse:
    """List all registered IMAP accounts, optionally filtered by user_id."""
    query = select(EmailAccount)
    if user_id:
        query = query.where(EmailAccount.user_id == user_id)

    count_query = select(func.count()).select_from(EmailAccount)
    if user_id:
        count_query = count_query.where(EmailAccount.user_id == user_id)

    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    result = await session.execute(query.order_by(EmailAccount.created_at.desc()))
    accounts = result.scalars().all()

    return AccountListResponse(
        items=[AccountResponse.model_validate(a) for a in accounts],
        total=total,
    )


@router.get(
    "/{account_id}",
    response_model=AccountResponse,
    summary="Get account details",
)
async def get_account(
    account_id: int,
    session: AsyncSession = Depends(get_session),
) -> AccountResponse:
    """Retrieve details for a specific IMAP account."""
    result = await session.execute(
        select(EmailAccount).where(EmailAccount.id == account_id)
    )
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Account {account_id} not found",
        )

    return AccountResponse.model_validate(account)


@router.delete(
    "/{account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an account",
)
async def delete_account(
    account_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Delete an IMAP account and all associated data."""
    result = await session.execute(
        select(EmailAccount).where(EmailAccount.id == account_id)
    )
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Account {account_id} not found",
        )

    await session.delete(account)


@router.post(
    "/{account_id}/sync",
    response_model=SyncResponse,
    summary="Trigger incremental sync for an account",
)
async def trigger_sync(
    account_id: int,
    payload: SyncRequest,
    session: AsyncSession = Depends(get_session),
) -> SyncResponse:
    """Trigger an incremental IMAP sync for a registered account.

    Fetches new messages since the last sync cursor and persists them
    to the database.
    """
    result = await session.execute(
        select(EmailAccount).where(EmailAccount.id == account_id)
    )
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Account {account_id} not found",
        )

    if not account.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Account {account_id} is not active",
        )

    encryption_manager = get_encryption_manager()
    password = encryption_manager.decrypt(account.encrypted_password)

    from sync.manager import SyncManager

    settings = get_settings()
    sync_manager = SyncManager(
        session=session,
        host=account.imap_host,
        port=account.imap_port,
        username=account.username,
        password=password,
        batch_size=settings.sync_batch_size,
    )

    try:
        messages_synced = await sync_manager.sync_account(
            account_id=account_id,
            folders=payload.folders,
        )
        return SyncResponse(status="completed", messages_synced=messages_synced)
    except Exception as e:
        logger.error(f"Sync failed for account {account_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Sync failed: {str(e)}",
        )
