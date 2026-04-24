from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.database import engine
from app.groups.router import router as groups_router
from app.notifications.router import router as notifications_router
from app.users.router import router as users_router
from models.user import Base


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables on startup and dispose engine on shutdown."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)


@app.get("/health", tags=["health"])
async def health_check():
    """Health check endpoint for deployment verification."""
    return {
        "status": "healthy",
        "app": settings.app_name,
        "version": settings.app_version,
    }


app.include_router(users_router)
app.include_router(groups_router)
app.include_router(notifications_router)
