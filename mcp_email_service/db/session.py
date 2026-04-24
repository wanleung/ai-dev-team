"""Async database session management with connection pooling."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config.settings import get_settings

_settings = get_settings()

connect_args = {}
if _settings.is_sqlite:
    connect_args = {"check_same_thread": False}

engine = create_async_engine(
    _settings.database_url,
    echo=_settings.db_echo,
    pool_size=None if _settings.is_sqlite else _settings.db_pool_size,
    max_overflow=None if _settings.is_sqlite else _settings.db_max_overflow,
    connect_args=connect_args,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session, handling cleanup automatically."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Initialise the async engine and verify connectivity."""
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: None)


async def close_db() -> None:
    """Dispose of the async engine and release all pooled connections."""
    await engine.dispose()
