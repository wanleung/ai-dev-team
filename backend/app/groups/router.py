from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.groups.schemas import (
    GroupCreate,
    GroupRead,
    GroupUpdate,
    GroupListResponse,
    JoinResponse,
    LeaveResponse,
)
from app.groups.service import GroupService

router = APIRouter(prefix="/api/v1/groups", tags=["groups"])


async def _get_group_service(db: AsyncSession = Depends(get_db)) -> GroupService:
    return GroupService(db)


@router.post("", response_model=GroupRead, status_code=status.HTTP_201_CREATED)
async def create_group(
    data: GroupCreate,
    service: GroupService = Depends(_get_group_service),
) -> GroupRead:
    """Create a new group. The creator becomes the owner and admin."""
    # In production, extract owner_id from JWT token
    owner_id = 1  # Placeholder: replace with get_current_user().id
    return await service.create_group(data, owner_id)


@router.get("", response_model=GroupListResponse)
async def list_groups(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    is_public: bool | None = None,
    service: GroupService = Depends(_get_group_service),
) -> GroupListResponse:
    """List all groups with pagination."""
    groups, total = await service.list_groups(page=page, limit=limit, is_public=is_public)
    return GroupListResponse(
        groups=groups,
        total=total,
        page=page,
        limit=limit,
        has_next=(page * limit) < total,
        has_prev=page > 1,
    )


@router.get("/{group_id}", response_model=GroupRead)
async def get_group(
    group_id: int,
    service: GroupService = Depends(_get_group_service),
) -> GroupRead:
    """Get group details by ID."""
    group = await service.get_group_by_id(group_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    return group


@router.put("/{group_id}", response_model=GroupRead)
async def update_group(
    group_id: int,
    data: GroupUpdate,
    service: GroupService = Depends(_get_group_service),
) -> GroupRead:
    """Update a group. Only the owner can update."""
    group = await service.get_group_by_id(group_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    # In production: check if current user is owner
    return await service.update_group(group, data)


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: int,
    service: GroupService = Depends(_get_group_service),
) -> None:
    """Delete a group. Only the owner can delete."""
    group = await service.get_group_by_id(group_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    # In production: check if current user is owner
    await service.delete_group(group)


@router.post("/{group_id}/join", response_model=JoinResponse)
async def join_group(
    group_id: int,
    service: GroupService = Depends(_get_group_service),
) -> JoinResponse:
    """Join a group. User becomes a member."""
    group = await service.get_group_by_id(group_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")

    # In production, extract user_id from JWT token
    user_id = 2  # Placeholder: replace with get_current_user().id

    existing = await service.get_membership(group_id, user_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Already a member of this group",
        )

    membership = await service.join_group(group, user_id)
    return JoinResponse(membership=membership, member_count=group.member_count)


@router.post("/{group_id}/leave", response_model=LeaveResponse)
async def leave_group(
    group_id: int,
    service: GroupService = Depends(_get_group_service),
) -> LeaveResponse:
    """Leave a group."""
    group = await service.get_group_by_id(group_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")

    # In production, extract user_id from JWT token
    user_id = 2  # Placeholder: replace with get_current_user().id

    membership = await service.get_membership(group_id, user_id)
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Not a member of this group",
        )

    await service.leave_group(group, user_id)
    return LeaveResponse(left=True, member_count=group.member_count)
