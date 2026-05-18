"""Pydantic models for MCP tool request/response payloads.

Defines the schemas for MCP message exchange between clients and the calendar service.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from src.models.calendar import (
    Calendar,
    Event,
    EventAttendee,
    EventReminder,
    FreeBusySlot,
    RecurrenceRule,
)


class ListCalendarsRequest(BaseModel):
    """Request model for list_calendars tool."""
    
    provider: Optional[str] = Field(default=None, description="Optional provider filter")


class ListCalendarsResponse(BaseModel):
    """Response model for list_calendars tool."""
    
    calendars: list[Calendar]


class GetEventsRequest(BaseModel):
    """Request model for get_events tool."""
    
    calendar_id: Optional[str] = Field(default=None)
    start_time: datetime
    end_time: datetime
    provider: Optional[str] = Field(default=None)
    max_results: int = Field(default=100)
    expand_recurring: bool = Field(default=True)


class GetEventsResponse(BaseModel):
    """Response model for get_events tool."""
    
    events: list[Event]


class CreateEventRequest(BaseModel):
    """Request model for create_event tool."""
    
    calendar_id: Optional[str] = Field(default=None, description="Uses primary if None")
    title: str
    description: Optional[str] = None
    location: Optional[str] = None
    start: datetime
    end: datetime
    timezone: str
    attendees: list[EventAttendee] = Field(default_factory=list)
    reminders: list[EventReminder] = Field(default_factory=list)
    recurrence: Optional[RecurrenceRule] = None
    provider: Optional[str] = Field(default=None)


class CreateEventResponse(BaseModel):
    """Response model for create_event tool."""
    
    event: Event


class UpdateEventRequest(BaseModel):
    """Request model for update_event tool."""
    
    event_id: str
    calendar_id: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    timezone: Optional[str] = None
    attendees: Optional[list[EventAttendee]] = None
    reminders: Optional[list[EventReminder]] = None
    recurrence: Optional[RecurrenceRule] = None
    status: Optional[str] = None
    send_notifications: bool = Field(default=True)
    update_series: bool = Field(default=False, description="For recurring events")
    provider: Optional[str] = None


class UpdateEventResponse(BaseModel):
    """Response model for update_event tool."""
    
    event: Event


class DeleteEventRequest(BaseModel):
    """Request model for delete_event tool."""
    
    event_id: str
    calendar_id: Optional[str] = None
    send_notifications: bool = Field(default=True)
    delete_series: bool = Field(default=False, description="For recurring events")
    provider: Optional[str] = None


class DeleteEventResponse(BaseModel):
    """Response model for delete_event tool."""
    
    success: bool
    message: str


class GetFreeBusyRequest(BaseModel):
    """Request model for get_free_busy tool."""
    
    calendar_ids: Optional[list[str]] = Field(default=None, description="None = all accessible")
    start_time: datetime
    end_time: datetime
    provider: Optional[str] = Field(default=None)


class GetFreeBusyResponse(BaseModel):
    """Response model for get_free_busy tool."""
    
    slots: list[FreeBusySlot]
