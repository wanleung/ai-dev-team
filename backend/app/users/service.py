from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from app.users.schemas import UserCreate, UserUpdate


class UserService:
    """Service for user profile CRUD and email verification."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, user_id: int) -> User | None:
        """Fetch a user by ID."""
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        """Fetch a user by email."""
        result = await self.db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> User | None:
        """Fetch a user by username."""
        result = await self.db.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()

    async def create(self, data: UserCreate, password_hash: str) -> User:
        """Create a new user."""
        user = User(
            email=data.email,
            username=data.username,
            full_name=data.full_name,
            password_hash=password_hash,
        )
        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def update(self, user: User, data: UserUpdate) -> User:
        """Update an existing user profile."""
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(user, field, value)
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def verify_email(self, user: User) -> User:
        """Mark a user as email-verified."""
        user.is_verified = True
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def delete(self, user: User) -> None:
        """Delete a user."""
        await self.db.delete(user)
        await self.db.flush()
