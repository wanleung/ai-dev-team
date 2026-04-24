"""Calendar provider package.

Provides the abstract `CalendarProvider` interface and concrete
implementations for Google Calendar and Outlook/Microsoft Graph.
"""

from src.calendar_provider.base import CalendarProvider
from src.calendar_provider.factory import create_provider
from src.calendar_provider.google_provider import (
    GoogleCalendarProvider,
    ProviderAPIError,
    AuthenticationError,
    CalendarNotFoundError,
    EventNotFoundError,
    ConflictError,
    ValidationError,
)
from src.calendar_provider.outlook_provider import OutlookCalendarProvider

__all__ = [
    "CalendarProvider",
    "GoogleCalendarProvider",
    "OutlookCalendarProvider",
    "ProviderAPIError",
    "AuthenticationError",
    "CalendarNotFoundError",
    "EventNotFoundError",
    "ConflictError",
    "ValidationError",
    "create_provider",
]
