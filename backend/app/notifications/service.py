from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.notification import Notification
from app.notifications.schemas import NotificationCreate


class NotificationService:
    """Service for notification management."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_notification(self, data: NotificationCreate) -> Notification:
        """Create a new notification for a user."""
        notification = Notification(
            user_id=data.user_id,
            type=data.type,
            title=data.title,
            message=data.message,
        )
        self.db.add(notification)
        await self.db.flush()
        await self.db.refresh(notification)
        return notification

    async def get_notification_by_id(
        self, notification_id: int, user_id: int
    ) -> Notification | None:
        """Fetch a notification by ID, scoped to a user."""
        result = await self.db.execute(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_notifications(
        self,
        user_id: int,
        page: int = 1,
        limit: int = 20,
        unread_only: bool = False,
    ) -> tuple[list[Notification], int]:
        """List notifications for a user with pagination."""
        query = select(Notification).where(Notification.user_id == user_id)
        count_query = select(func.count(Notification.id)).where(Notification.user_id == user_id)

        if unread_only:
            query = query.where(Notification.is_read == False)
            count_query = count_query.where(Notification.is_read == False)

        query = query.order_by(Notification.created_at.desc()).offset((page - 1) * limit).limit(limit)

        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()

        result = await self.db.execute(query)
        notifications = list(result.scalars().all())

        return notifications, total

    async def mark_as_read(self, notification: Notification) -> Notification:
        """Mark a notification as read."""
        notification.is_read = True
        await self.db.flush()
        await self.db.refresh(notification)
        return notification

    async def mark_all_as_read(self, user_id: int) -> int:
        """Mark all notifications for a user as read. Returns count of updated records."""
        result = await self.db.execute(
            Notification.__table__.update()
            .where(Notification.user_id == user_id)
            .where(Notification.is_read == False)
            .values(is_read=True)
        )
        await self.db.flush()
        return result.rowcount
