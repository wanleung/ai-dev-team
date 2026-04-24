"""Pydantic models for Calendar MCP Service.

Defines unified calendar data models including Calendar, Event, Attendee,
Reminder, RecurrenceRule, and FreeBusySlot.
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class Calendar(BaseModel):
    """Unified calendar model."""
    
    id: str
    name: str
    description: Optional[str] = None
    timezone: str = Field(default="UTC", description="IANA timezone")
    is_primary: bool = Field(default=False)
    access_role: str = Field(
        default="reader",
        description="owner, reader, writer, freeBusyReader",
    )
    color: Optional[str] = Field(default=None, description="Hex color code")


class EventAttendee(BaseModel):
    """Event attendee model."""
    
    email: str
    name: Optional[str] = None
    response_status: Optional[str] = Field(
        default=None,
        description="accepted, declined, tentative, needsAction",
    )
    is_organizer: bool = Field(default=False)


class EventReminder(BaseModel):
    """Event reminder model."""
    
    method: str = Field(description="email, popup")
    minutes_before: int


class RecurrenceRule(BaseModel):
    """Recurrence rule model based on RRULE standard."""
    
    frequency: str = Field(description="daily, weekly, monthly, yearly")
    interval: int = Field(default=1)
    count: Optional[int] = None
    until: Optional[datetime] = None
    by_day: Optional[list[str]] = Field(default=None, description="['MO', 'TU', etc.]")
    by_month_day: Optional[list[int]] = None


class Event(BaseModel):
    """Unified event model."""
    
    id: str
    calendar_id: str
    title: str
    description: Optional[str] = None
    location: Optional[str] = None
    start: datetime
    end: datetime
    timezone: str = Field(default="UTC", description="IANA timezone")
    attendees: list[EventAttendee] = Field(default_factory=list)
    reminders: list[EventReminder] = Field(default_factory=list)
    recurrence: Optional[RecurrenceRule] = None
    status: str = Field(default="confirmed", description="confirmed, tentative, cancelled")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    etag: Optional[str] = Field(default=None, description="For optimistic concurrency")
    is_recurring_master: bool = Field(default=False)
    recurrence_id: Optional[str] = Field(default=None, description="For instances of recurring events")
    provider_metadata: Optional[dict[str, Any]] = Field(default=None, description="Provider-specific fields")


class FreeBusySlot(BaseModel):
    """Free/busy time slot model."""
    
    start: datetime
    end: datetime
    status: str = Field(description="free, busy, tentative, outOfOffice")
