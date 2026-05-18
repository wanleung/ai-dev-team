"""Configuration settings for Calendar MCP Service."""

from __future__ import annotations

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Server
    server_host: str = Field(default="0.0.0.0", alias="SERVER_HOST")
    server_port: int = Field(default=8000, alias="SERVER_PORT")
    debug: bool = Field(default=False, alias="DEBUG")

    # Google Calendar OAuth2
    google_client_id: str = Field(default="", alias="GOOGLE_CLIENT_ID")
    google_client_secret: str = Field(default="", alias="GOOGLE_CLIENT_SECRET")
    google_redirect_uri: str = Field(
        default="http://localhost:8000/auth/google/callback",
        alias="GOOGLE_REDIRECT_URI",
    )
    google_access_token: str | None = Field(default=None, alias="GOOGLE_ACCESS_TOKEN")
    google_refresh_token: str | None = Field(default=None, alias="GOOGLE_REFRESH_TOKEN")

    # Outlook/Microsoft Graph OAuth2
    outlook_client_id: str = Field(default="", alias="OUTLOOK_CLIENT_ID")
    outlook_client_secret: str = Field(default="", alias="OUTLOOK_CLIENT_SECRET")
    outlook_redirect_uri: str = Field(
        default="http://localhost:8000/auth/outlook/callback",
        alias="OUTLOOK_REDIRECT_URI",
    )
    outlook_access_token: str | None = Field(default=None, alias="OUTLOOK_ACCESS_TOKEN")
    outlook_refresh_token: str | None = Field(default=None, alias="OUTLOOK_REFRESH_TOKEN")
    outlook_tenant_id: str = Field(default="common", alias="OUTLOOK_TENANT_ID")

    # Default provider
    default_provider: str = Field(default="google", alias="DEFAULT_PROVIDER")

    # Rate limiting
    rate_limit_google_capacity: int = Field(default=10000, alias="RATE_LIMIT_GOOGLE_CAPACITY")
    rate_limit_google_refill_rate: float = Field(default=100.0, alias="RATE_LIMIT_GOOGLE_REFILL_RATE")
    rate_limit_outlook_capacity: int = Field(default=10000, alias="RATE_LIMIT_OUTLOOK_CAPACITY")
    rate_limit_outlook_refill_rate: float = Field(default=10000 / 600, alias="RATE_LIMIT_OUTLOOK_REFILL_RATE")
    rate_limit_default_capacity: int = Field(default=1000, alias="RATE_LIMIT_DEFAULT_CAPACITY")
    rate_limit_default_refill_rate: float = Field(default=10.0, alias="RATE_LIMIT_DEFAULT_REFILL_RATE")
    rate_limit_max_retries: int = Field(default=3, alias="RATE_LIMIT_MAX_RETRIES")
    rate_limit_backoff_base: float = Field(default=1.0, alias="RATE_LIMIT_BACKOFF_BASE")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "populate_by_name": True,
    }


settings = Settings()
