from datetime import datetime

from pydantic import BaseModel, Field


class NotificationBase(BaseModel):
    type: str = Field(..., min_length=1, max_length=50)
    title: str = Field(..., min_length=1, max_length=255)
    message: str = Field(..., min_length=1, max_length=2000)


class NotificationCreate(NotificationBase):
    user_id: int


class NotificationRead(NotificationBase):
    id: int
    user_id: int
    is_read: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationListResponse(BaseModel):
    notifications: list[NotificationRead]
    total: int
    page: int
    limit: int
    has_next: bool
    has_prev: bool


class MarkReadResponse(BaseModel):
    id: int
    is_read: bool
