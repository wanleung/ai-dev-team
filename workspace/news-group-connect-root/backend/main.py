"""FastAPI application entry point for NewsGroup Connect."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.database import close_db, init_db
from app.comments.router import router as comments_router
from app.posts.router import router as posts_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database tables on startup and dispose engine on shutdown."""
    await init_db()
    yield
    await close_db()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)

# Include routers for all services
app.include_router(posts_router)
app.include_router(comments_router)
