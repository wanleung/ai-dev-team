"""Pydantic models for Calendar MCP Service.

Defines unified calendar data models including Calendar, Event, Attendee,
Reminder, RecurrenceRule, FreeBusySlot, and ProviderConfig.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class EventAttendee(BaseModel):
    """Represents an attendee of a calendar event."""

    email: str
    name: str | None = None
    response_status: str | None = Field(
        default=None,
        description="accepted, declined, tentative, needsAction",
    )
    is_organizer: bool = False


class EventReminder(BaseModel):
    """Represents a reminder for a calendar event."""

    method: str = Field(description="email or popup")
    minutes_before: int


class RecurrenceRule(BaseModel):
    """Represents a recurrence rule for recurring events.

    Based on the RRULE standard (RFC 5545).
    """

    frequency: str = Field(
        description="daily, weekly, monthly, yearly",
    )
    interval: int = Field(default=1, ge=1)
    count: int | None = Field(default=None, ge=1)
    until: datetime | None = None
    by_day: list[str] | None = Field(
        default=None,
        description="Day abbreviations: ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU']",
    )
    by_month_day: list[int] | None = None


class Calendar(BaseModel):
    """Represents a calendar that the user can access."""

    id: str
    name: str
    description: str | None = None
    timezone: str = Field(description="IANA timezone string")
    is_primary: bool = False
    access_role: str = Field(
        description="owner, reader, writer, freeBusyReader",
    )
    color: str | None = Field(default=None, description="Hex color code")


class Event(BaseModel):
    """Unified event model representing a calendar event.

    Normalized across providers (Google Calendar, Outlook/Microsoft Graph).
    """

    id: str
    calendar_id: str
    title: str
    description: str | None = None
    location: str | None = None
    start: datetime
    end: datetime
    timezone: str = Field(description="IANA timezone string")
    attendees: list[EventAttendee] = Field(default_factory=list)
    reminders: list[EventReminder] = Field(default_factory=list)
    recurrence: RecurrenceRule | None = None
    status: str = Field(
        default="confirmed",
        description="confirmed, tentative, cancelled",
    )
    created_at: datetime
    updated_at: datetime
    etag: str | None = Field(
        default=None,
        description="ETag for optimistic concurrency control",
    )
    is_recurring_master: bool = False
    recurrence_id: str | None = Field(
        default=None,
        description="ID of the master event for recurring event instances",
    )
    provider_metadata: dict[str, Any] | None = Field(
        default=None,
        description="Provider-specific fields preserved during normalization",
    )


class FreeBusySlot(BaseModel):
    """Represents a free/busy time slot."""

    start: datetime
    end: datetime
    status: str = Field(
        description="free, busy, tentative, outOfOffice",
    )


class ProviderConfig(BaseModel):
    """Configuration for a calendar provider's OAuth2 credentials."""

    provider: str = Field(description="google or outlook")
    client_id: str
    client_secret: str
    redirect_uri: str
    scopes: list[str]
    access_token: str | None = None
    refresh_token: str | None = None
    token_expiry: datetime | None = None
