"""Calendar provider package.

Provides the abstract `CalendarProvider` interface and concrete
implementations for Google Calendar and Outlook/Microsoft Graph.
"""

from src.calendar_provider.base import CalendarProvider
from src.calendar_provider.google_provider import (
    GoogleCalendarProvider,
    ProviderAPIError,
    AuthenticationError,
    CalendarNotFoundError,
    EventNotFoundError,
    ConflictError,
    ValidationError,
)
from src.calendar_provider.factory import create_provider

try:
    from src.calendar_provider.outlook_provider import OutlookCalendarProvider
    _outlook_available = True
except ImportError:
    _outlook_available = False
    OutlookCalendarProvider = None  # type: ignore[assignment,misc]

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
