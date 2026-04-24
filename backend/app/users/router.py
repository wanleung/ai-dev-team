from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.users.schemas import UserCreate, UserRead, UserUpdate, EmailVerificationRequest
from app.users.service import UserService

router = APIRouter(prefix="/api/v1/users", tags=["users"])


async def _get_user_service(db: AsyncSession = Depends(get_db)) -> UserService:
    return UserService(db)


@router.get("/{user_id}", response_model=UserRead)
async def get_user(
    user_id: int,
    service: UserService = Depends(_get_user_service),
) -> UserRead:
    """Retrieve a user profile by ID."""
    user = await service.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.put("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: int,
    data: UserUpdate,
    service: UserService = Depends(_get_user_service),
) -> UserRead:
    """Update a user profile."""
    user = await service.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return await service.update(user, data)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    service: UserService = Depends(_get_user_service),
) -> None:
    """Delete a user profile."""
    user = await service.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    await service.delete(user)


@router.post("/verify-email", response_model=UserRead)
async def verify_email(
    data: EmailVerificationRequest,
    service: UserService = Depends(_get_user_service),
) -> UserRead:
    """Verify a user's email address using a token."""
    # In production, decode the token to find the user.
    # For now, assume token contains the user ID.
    try:
        user_id = int(data.token)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification token",
        )

    user = await service.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    return await service.verify_email(user)
