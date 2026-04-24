"""Provider factory for instantiating calendar providers.

Factory function to create the correct calendar provider instance
based on configuration. Supports Google Calendar and Outlook Calendar.
"""

from __future__ import annotations

from src.calendar_provider.google_provider import GoogleCalendarProvider
from src.calendar_provider.outlook_provider import OutlookCalendarProvider
from src.config.settings import settings
from src.models.calendar import ProviderConfig


def create_provider(provider: str | None = None) -> GoogleCalendarProvider | OutlookCalendarProvider:
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
        config = ProviderConfig(
            provider="outlook",
            client_id=settings.outlook_client_id or "",
            client_secret=settings.outlook_client_secret or "",
            redirect_uri=settings.outlook_redirect_uri,
            scopes=settings.outlook_scopes,
            access_token=settings.outlook_access_token,
            refresh_token=settings.outlook_refresh_token,
        )
        return OutlookCalendarProvider(config)

    raise ValueError(f"Unknown provider: '{provider_name}'. Supported providers: google, outlook")
