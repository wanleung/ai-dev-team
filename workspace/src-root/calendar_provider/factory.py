"""Provider factory for instantiating calendar providers.

Factory function to create the correct calendar provider instance
based on configuration. Supports Google Calendar and Outlook Calendar.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.calendar_provider.base import CalendarProvider
from src.calendar_provider.google_provider import GoogleCalendarProvider
from src.config.settings import settings
from src.models.calendar import ProviderConfig

try:
    from src.calendar_provider.outlook_provider import OutlookCalendarProvider as _OutlookCalendarProvider
    _outlook_available = True
except ImportError:
    _outlook_available = False
    _OutlookCalendarProvider = None  # type: ignore[assignment,misc]

if TYPE_CHECKING:
    from src.calendar_provider.outlook_provider import OutlookCalendarProvider


def create_provider(provider: str | None = None) -> CalendarProvider:
    """Create a calendar provider instance based on the specified or default provider.

    Reads configuration from the application settings and builds a
    `ProviderConfig` object, then instantiates the appropriate provider.

    Args:
        provider: Provider name ("google" or "outlook"). If None, uses
            the default provider configured in settings.

    Returns:
        An instance of `GoogleCalendarProvider` or `OutlookCalendarProvider`.

    Raises:
        ValueError: If the provider name is not recognized or required
            configuration is missing.
        ImportError: If Outlook provider is requested but msgraph-sdk is not installed.
    """
    provider_name = (provider or settings.default_provider).lower()

    if provider_name == "google":
        config = ProviderConfig(
            provider="google",
            client_id=settings.google_client_id or "",
            client_secret=settings.google_client_secret or "",
            redirect_uri=settings.google_redirect_uri,
            scopes=settings.google_scopes,
            access_token=settings.google_access_token,
            refresh_token=settings.google_refresh_token,
        )
        return GoogleCalendarProvider(config)

    if provider_name == "outlook":
        if not _outlook_available:
            raise ImportError(
                "Outlook provider requires 'msgraph-sdk'. "
                "Install with: pip install msgraph-sdk kiota-abstractions kiota-http"
            )
        config = ProviderConfig(
            provider="outlook",
            client_id=settings.outlook_client_id or "",
            client_secret=settings.outlook_client_secret or "",
            redirect_uri=settings.outlook_redirect_uri,
            scopes=settings.outlook_scopes,
            access_token=settings.outlook_access_token,
            refresh_token=settings.outlook_refresh_token,
        )
        return _OutlookCalendarProvider(config)

    raise ValueError(f"Unknown provider: '{provider_name}'. Supported providers: google, outlook")
