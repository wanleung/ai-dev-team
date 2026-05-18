"""Pydantic models for MCP tool request/response payloads.

Defines structured request and response models for each MCP calendar tool:
list_calendars, get_events, create_event, update_event, delete_event, get_free_busy.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from src.models.calendar import Calendar, Event, EventAttendee, EventReminder, FreeBusySlot, RecurrenceRule


class ListCalendarsRequest(BaseModel):
    """Request model for the list_calendars MCP tool."""

    provider: str | None = Field(default=None, description="Optional provider filter (google/outlook)")


class ListCalendarsResponse(BaseModel):
    """Response model for the list_calendars MCP tool."""

    calendars: list[Calendar]


class GetEventsRequest(BaseModel):
    """Request model for the get_events MCP tool."""

    calendar_id: str | None = Field(default=None, description="Calendar ID; defaults to primary")
    start_time: datetime
    end_time: datetime
    provider: str | None = Field(default=None, description="Optional provider filter")
    max_results: int = Field(default=100, ge=1, le=2500)
    expand_recurring: bool = Field(default=True)


class GetEventsResponse(BaseModel):
    """Response model for the get_events MCP tool."""

    events: list[Event]


class CreateEventRequest(BaseModel):
    """Request model for the create_event MCP tool."""

    calendar_id: str | None = Field(default=None, description="Target calendar; defaults to primary")
    title: str
    description: str | None = None
    location: str | None = None
    start: datetime
    end: datetime
    timezone: str = Field(description="IANA timezone string")
    attendees: list[EventAttendee] = Field(default_factory=list)
    reminders: list[EventReminder] = Field(default_factory=list)
    recurrence: RecurrenceRule | None = None
    provider: str | None = Field(default=None, description="Optional provider filter")


class CreateEventResponse(BaseModel):
    """Response model for the create_event MCP tool."""

    event: Event


class UpdateEventRequest(BaseModel):
    """Request model for the update_event MCP tool."""

    event_id: str
    calendar_id: str | None = Field(default=None, description="Calendar containing the event")
    title: str | None = None
    description: str | None = None
    location: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    timezone: str | None = None
    attendees: list[EventAttendee] | None = None
    reminders: list[EventReminder] | None = None
    recurrence: RecurrenceRule | None = None
    status: str | None = None
    send_notifications: bool = Field(default=True)
    update_series: bool = Field(default=False, description="Update entire recurring series")
    provider: str | None = Field(default=None, description="Optional provider filter")


class UpdateEventResponse(BaseModel):
    """Response model for the update_event MCP tool."""

    event: Event


class DeleteEventRequest(BaseModel):
    """Request model for the delete_event MCP tool."""

    event_id: str
    calendar_id: str | None = Field(default=None, description="Calendar containing the event")
    send_notifications: bool = Field(default=True)
    delete_series: bool = Field(default=False, description="Delete entire recurring series")
    provider: str | None = Field(default=None, description="Optional provider filter")


class DeleteEventResponse(BaseModel):
    """Response model for the delete_event MCP tool."""

    success: bool
    message: str


class GetFreeBusyRequest(BaseModel):
    """Request model for the get_free_busy MCP tool."""

    calendar_ids: list[str] | None = Field(default=None, description="Calendars to check; defaults to all")
    start_time: datetime
    end_time: datetime
    provider: str | None = Field(default=None, description="Optional provider filter")


class GetFreeBusyResponse(BaseModel):
    """Response model for the get_free_busy MCP tool."""

    slots: list[FreeBusySlot]
