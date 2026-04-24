from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.group import Group
from models.membership import GroupMembership
from app.groups.schemas import GroupCreate, GroupUpdate


class GroupService:
    """Service for group CRUD and membership management."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_group(self, data: GroupCreate, owner_id: int) -> Group:
        """Create a new group and add the owner as an admin member."""
        group = Group(
            name=data.name,
            description=data.description,
            owner_id=owner_id,
            is_public=data.is_public,
        )
        self.db.add(group)
        await self.db.flush()
        await self.db.refresh(group)

        membership = GroupMembership(
            group_id=group.id,
            user_id=owner_id,
            role="admin",
        )
        self.db.add(membership)
        await self.db.flush()

        group.member_count = 1
        await self.db.flush()
        await self.db.refresh(group)
        return group

    async def get_group_by_id(self, group_id: int) -> Group | None:
        """Fetch a group by ID."""
        result = await self.db.execute(select(Group).where(Group.id == group_id))
        return result.scalar_one_or_none()

    async def list_groups(
        self,
        page: int = 1,
        limit: int = 20,
        is_public: bool | None = None,
    ) -> tuple[list[Group], int]:
        """List groups with pagination and optional public filter."""
        query = select(Group)
        count_query = select(func.count(Group.id))

        if is_public is not None:
            query = query.where(Group.is_public == is_public)
            count_query = count_query.where(Group.is_public == is_public)

        query = query.order_by(Group.created_at.desc()).offset((page - 1) * limit).limit(limit)

        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()

        result = await self.db.execute(query)
        groups = list(result.scalars().all())

        return groups, total

    async def update_group(self, group: Group, data: GroupUpdate) -> Group:
        """Update an existing group."""
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(group, field, value)
        await self.db.flush()
        await self.db.refresh(group)
        return group

    async def delete_group(self, group: Group) -> None:
        """Delete a group and all its memberships."""
        await self.db.execute(
            GroupMembership.__table__.delete().where(GroupMembership.group_id == group.id)
        )
        await self.db.delete(group)
        await self.db.flush()

    async def get_membership(self, group_id: int, user_id: int) -> GroupMembership | None:
        """Get a user's membership in a group."""
        result = await self.db.execute(
            select(GroupMembership).where(
                GroupMembership.group_id == group_id,
                GroupMembership.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def join_group(self, group: Group, user_id: int) -> GroupMembership:
        """Add a user to a group as a member."""
        membership = GroupMembership(
            group_id=group.id,
            user_id=user_id,
            role="member",
        )
        self.db.add(membership)
        group.member_count += 1
        await self.db.flush()
        await self.db.refresh(membership)
        await self.db.refresh(group)
        return membership

    async def leave_group(self, group: Group, user_id: int) -> None:
        """Remove a user's membership from a group."""
        membership = await self.get_membership(group.id, user_id)
        if membership:
            await self.db.delete(membership)
            group.member_count = max(0, group.member_count - 1)
            await self.db.flush()
