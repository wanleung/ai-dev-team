from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

connect_args = {}
poolclass_args = {}
if settings.is_sqlite:
    connect_args = {"check_same_thread": False}
else:
    poolclass_args = {
        "pool_size": settings.database_pool_size,
        "max_overflow": settings.database_max_overflow,
    }

engine = create_async_engine(
    settings.database_url,
    connect_args=connect_args,
    **poolclass_args,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
