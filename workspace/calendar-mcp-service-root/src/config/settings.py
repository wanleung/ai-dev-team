"""Pydantic-settings based configuration management.

Provides type-safe environment variable management for the Calendar MCP Service.
"""

from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Application
    app_name: str = Field(default="Calendar MCP Service", alias="APP_NAME")
    debug: bool = Field(default=False, alias="DEBUG")
    allowed_origins: list[str] = Field(default=["*"], alias="ALLOWED_ORIGINS")
    
    # Google Calendar
    google_client_id: Optional[str] = Field(default=None, alias="GOOGLE_CLIENT_ID")
    google_client_secret: Optional[str] = Field(default=None, alias="GOOGLE_CLIENT_SECRET")
    google_redirect_uri: str = Field(default="http://localhost:8000/auth/google/callback", alias="GOOGLE_REDIRECT_URI")
    google_scopes: list[str] = Field(
        default=["https://www.googleapis.com/auth/calendar"],
        alias="GOOGLE_SCOPES",
    )
    google_access_token: Optional[str] = Field(default=None, alias="GOOGLE_ACCESS_TOKEN")
    google_refresh_token: Optional[str] = Field(default=None, alias="GOOGLE_REFRESH_TOKEN")
    
    # Outlook/Microsoft Graph
    outlook_client_id: Optional[str] = Field(default=None, alias="OUTLOOK_CLIENT_ID")
    outlook_client_secret: Optional[str] = Field(default=None, alias="OUTLOOK_CLIENT_SECRET")
    outlook_redirect_uri: str = Field(default="http://localhost:8000/auth/outlook/callback", alias="OUTLOOK_REDIRECT_URI")
    outlook_tenant_id: str = Field(default="common", alias="OUTLOOK_TENANT_ID")
    outlook_scopes: list[str] = Field(
        default=["https://graph.microsoft.com/Calendars.ReadWrite"],
        alias="OUTLOOK_SCOPES",
    )
    outlook_access_token: Optional[str] = Field(default=None, alias="OUTLOOK_ACCESS_TOKEN")
    outlook_refresh_token: Optional[str] = Field(default=None, alias="OUTLOOK_REFRESH_TOKEN")
    
    # Rate Limiting
    rate_limit_google_requests: int = Field(default=10000, alias="RATE_LIMIT_GOOGLE_REQUESTS")
    rate_limit_google_window: int = Field(default=100, alias="RATE_LIMIT_GOOGLE_WINDOW")
    rate_limit_outlook_requests: int = Field(default=10000, alias="RATE_LIMIT_OUTLOOK_REQUESTS")
    rate_limit_outlook_window: int = Field(default=600, alias="RATE_LIMIT_OUTLOOK_WINDOW")
    
    # Default Provider
    default_provider: str = Field(default="google", alias="DEFAULT_PROVIDER")
    
    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "populate_by_name": True,
    }


settings = Settings()
