"""FastAPI application entry point for MCP Email Service REST API."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from config.settings import get_settings
from db.session import init_db, close_db
from middleware.auth import user_scoping_middleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup and clean up on shutdown."""
    await init_db()
    yield
    await close_db()


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

app.middleware("http")(user_scoping_middleware)


@app.get("/health", tags=["health"])
async def health_check():
    """Health check endpoint for deployment verification."""
    return {
        "status": "healthy",
        "app": settings.app_name,
        "version": "0.1.0",
    }


from api.router import api_router

app.include_router(api_router, prefix=settings.api_prefix)
