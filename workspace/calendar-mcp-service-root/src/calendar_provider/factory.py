"""Provider factory for Calendar MCP Service.

Factory function to instantiate the correct calendar provider based on
configuration and provider name.
"""

import logging
from typing import Optional

from src.calendar_provider.base import CalendarProvider
from src.calendar_provider.google_provider import GoogleCalendarProvider
from src.calendar_provider.outlook_provider import OutlookCalendarProvider
from src.config.settings import settings

logger = logging.getLogger(__name__)


def create_provider(
    provider_name: Optional[str] = None,
    oauth_manager=None,
    error_handler=None,
) -> CalendarProvider:
    """Create a calendar provider instance.
    
    Args:
        provider_name: Provider name ('google' or 'outlook'). Uses default if None.
        oauth_manager: OAuth2 token manager instance.
        error_handler: Error handler instance.
        
    Returns:
        CalendarProvider instance for the specified provider.
        
    Raises:
        ValueError: If provider name is not supported.
    """
    target_provider = provider_name or settings.default_provider
    
    if target_provider == "google":
        return GoogleCalendarProvider(
            oauth_manager=oauth_manager,
            error_handler=error_handler,
        )
    elif target_provider == "outlook":
        return OutlookCalendarProvider(
            oauth_manager=oauth_manager,
            error_handler=error_handler,
        )
    else:
        raise ValueError(f"Unsupported provider: {target_provider}")
