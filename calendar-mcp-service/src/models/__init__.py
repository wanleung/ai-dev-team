"""Data models package."""

from src.models.calendar import (
    Calendar,
    Event,
    EventAttendee,
    EventReminder,
    FreeBusySlot,
    ProviderConfig,
    RecurrenceRule,
)
from src.models.mcp import (
    CreateEventRequest,
    CreateEventResponse,
    DeleteEventRequest,
    DeleteEventResponse,
    GetEventsRequest,
    GetEventsResponse,
    GetFreeBusyRequest,
    GetFreeBusyResponse,
    ListCalendarsRequest,
    ListCalendarsResponse,
    UpdateEventRequest,
    UpdateEventResponse,
)

__all__ = [
    # Calendar models
    "Calendar",
    "Event",
    "EventAttendee",
    "EventReminder",
    "FreeBusySlot",
    "ProviderConfig",
    "RecurrenceRule",
    # MCP models
    "ListCalendarsRequest",
    "ListCalendarsResponse",
    "GetEventsRequest",
    "GetEventsResponse",
    "CreateEventRequest",
    "CreateEventResponse",
    "UpdateEventRequest",
    "UpdateEventResponse",
    "DeleteEventRequest",
    "DeleteEventResponse",
    "GetFreeBusyRequest",
    "GetFreeBusyResponse",
]
