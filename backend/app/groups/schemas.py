from datetime import datetime

from pydantic import BaseModel, Field


class GroupBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=2000)
    is_public: bool = True


class GroupCreate(GroupBase):
    pass


class GroupUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=2000)
    is_public: bool | None = None


class GroupRead(GroupBase):
    id: int
    owner_id: int
    member_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class GroupListResponse(BaseModel):
    groups: list[GroupRead]
    total: int
    page: int
    limit: int
    has_next: bool
    has_prev: bool


class MembershipRead(BaseModel):
    id: int
    group_id: int
    user_id: int
    role: str
    joined_at: datetime
    is_active: bool

    model_config = {"from_attributes": True}


class JoinResponse(BaseModel):
    membership: MembershipRead
    member_count: int


class LeaveResponse(BaseModel):
    left: bool
    member_count: int
