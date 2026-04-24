from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.notifications.schemas import (
    NotificationCreate,
    NotificationRead,
    NotificationListResponse,
    MarkReadResponse,
)
from app.notifications.service import NotificationService

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


async def _get_notification_service(db: AsyncSession = Depends(get_db)) -> NotificationService:
    return NotificationService(db)


@router.post("", response_model=NotificationRead, status_code=status.HTTP_201_CREATED)
async def create_notification(
    data: NotificationCreate,
    service: NotificationService = Depends(_get_notification_service),
) -> NotificationRead:
    """Create a new notification for a user."""
    return await service.create_notification(data)


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    unread_only: bool = False,
    service: NotificationService = Depends(_get_notification_service),
) -> NotificationListResponse:
    """List notifications for the current user with pagination."""
    # In production, extract user_id from JWT token
    user_id = 1  # Placeholder: replace with get_current_user().id

    notifications, total = await service.list_notifications(
        user_id=user_id,
        page=page,
        limit=limit,
        unread_only=unread_only,
    )
    return NotificationListResponse(
        notifications=notifications,
        total=total,
        page=page,
        limit=limit,
        has_next=(page * limit) < total,
        has_prev=page > 1,
    )


@router.post("/{notification_id}/read", response_model=MarkReadResponse)
async def mark_notification_as_read(
    notification_id: int,
    service: NotificationService = Depends(_get_notification_service),
) -> MarkReadResponse:
    """Mark a notification as read."""
    # In production, extract user_id from JWT token
    user_id = 1  # Placeholder: replace with get_current_user().id

    notification = await service.get_notification_by_id(notification_id, user_id)
    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )

    updated = await service.mark_as_read(notification)
    return MarkReadResponse(id=updated.id, is_read=updated.is_read)


@router.post("/read-all", response_model=MarkReadResponse)
async def mark_all_notifications_as_read(
    service: NotificationService = Depends(_get_notification_service),
) -> MarkReadResponse:
    """Mark all notifications for the current user as read."""
    # In production, extract user_id from JWT token
    user_id = 1  # Placeholder: replace with get_current_user().id

    count = await service.mark_all_as_read(user_id)
    return MarkReadResponse(id=0, is_read=True)
