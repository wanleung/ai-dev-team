"""Abstract base class for calendar providers.

Defines the `CalendarProvider` interface that all concrete provider
implementations (Google Calendar, Outlook/Microsoft Graph) must follow.
This abstraction allows the MCP service to interact with multiple
calendar backends through a unified API.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from src.models.calendar import (
    Calendar,
    Event,
    FreeBusySlot,
    ProviderConfig,
    RecurrenceRule,
    EventAttendee,
    EventReminder,
)


class CalendarProvider(ABC):
    """Abstract base class defining the calendar provider interface.

    All concrete calendar provider implementations must inherit from
    this class and implement every abstract method. The interface
    covers the full set of calendar operations needed by the MCP tools:

    - Listing calendars
    - Retrieving events within a time range
    - Creating, updating, and deleting events
    - Checking free/busy availability

    Provider implementations are responsible for:
    - Translating unified models to/from provider-specific formats
    - Handling OAuth2 authentication (via the injected config)
    - Managing provider-specific error handling and retries
    """

    def __init__(self, config: ProviderConfig) -> None:
        """Initialize the provider with its configuration.

        Args:
            config: Provider-specific configuration containing OAuth2
                credentials, scopes, and token information.
        """
        self.config = config

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the canonical name of this provider.

        Returns:
            A string identifier for the provider (e.g. "google", "outlook").
        """
        ...

    @abstractmethod
    async def authenticate(self) -> bool:
        """Validate and refresh authentication credentials.

        Checks whether the current access token is valid. If the token
        is expired but a refresh token is available, performs a token
        refresh automatically.

        Returns:
            True if authentication is valid after this call, False otherwise.

        Raises:
            AuthenticationError: If credentials are invalid and cannot
                be refreshed.
        """
        ...

    # ------------------------------------------------------------------ #
    # Calendar operations
    # ------------------------------------------------------------------ #

    @abstractmethod
    async def list_calendars(self) -> list[Calendar]:
        """List all calendars accessible to the authenticated user.

        Returns:
            A list of `Calendar` objects representing each calendar the
            user can access (owned, shared, or subscribed).

        Raises:
            AuthenticationError: If the user is not authenticated.
            ProviderAPIError: If the provider API returns an error.
        """
        ...

    # ------------------------------------------------------------------ #
    # Event operations
    # ------------------------------------------------------------------ #

    @abstractmethod
    async def get_events(
        self,
        calendar_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        max_results: int = 100,
        expand_recurring: bool = True,
    ) -> list[Event]:
        """Retrieve events within a specified time range.

        Args:
            calendar_id: ID of the calendar to query. If None, uses the
                user's primary calendar.
            start_time: Start of the time window (inclusive). If None,
                defaults to the current time.
            end_time: End of the time window (exclusive). If None,
                defaults to 24 hours after start_time.
            max_results: Maximum number of events to return.
            expand_recurring: If True, recurring events are expanded
                into their individual occurrences within the time range.
                If False, only the master recurring event is returned.

        Returns:
            A list of `Event` objects matching the query criteria.

        Raises:
            AuthenticationError: If the user is not authenticated.
            ProviderAPIError: If the provider API returns an error.
            CalendarNotFoundError: If the specified calendar_id does not
                exist or is not accessible.
        """
        ...

    @abstractmethod
    async def create_event(
        self,
        title: str,
        start: datetime,
        end: datetime,
        timezone: str,
        calendar_id: str | None = None,
        description: str | None = None,
        location: str | None = None,
        attendees: list[EventAttendee] | None = None,
        reminders: list[EventReminder] | None = None,
        recurrence: RecurrenceRule | None = None,
        send_notifications: bool = True,
    ) -> Event:
        """Create a new calendar event.

        Args:
            title: Title/summary of the event.
            start: Start time of the event (timezone-aware).
            end: End time of the event (timezone-aware).
            timezone: IANA timezone string for the event.
            calendar_id: Target calendar ID. If None, uses the primary
                calendar.
            description: Detailed description of the event.
            location: Physical or virtual location of the event.
            attendees: List of attendees to invite.
            reminders: List of reminders to attach to the event.
            recurrence: Recurrence rule for recurring events.
            send_notifications: Whether to send email notifications to
                attendees.

        Returns:
            The created `Event` object with provider-assigned ID and
            timestamps populated.

        Raises:
            AuthenticationError: If the user is not authenticated.
            ProviderAPIError: If the provider API returns an error.
            CalendarNotFoundError: If the specified calendar_id does not
                exist or is not accessible.
            ValidationError: If the event data is invalid (e.g., end
                before start).
        """
        ...

    @abstractmethod
    async def update_event(
        self,
        event_id: str,
        calendar_id: str | None = None,
        title: str | None = None,
        description: str | None = None,
        location: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        timezone: str | None = None,
        attendees: list[EventAttendee] | None = None,
        reminders: list[EventReminder] | None = None,
        recurrence: RecurrenceRule | None = None,
        status: str | None = None,
        send_notifications: bool = True,
        update_series: bool = False,
        etag: str | None = None,
    ) -> Event:
        """Update an existing calendar event.

        Only the fields that are provided (non-None) will be updated.
        Unspecified fields retain their current values.

        Args:
            event_id: ID of the event to update.
            calendar_id: Calendar containing the event. If None, uses
                the primary calendar.
            title: New title for the event.
            description: New description for the event.
            location: New location for the event.
            start: New start time.
            end: New end time.
            timezone: New timezone for the event.
            attendees: New attendee list (replaces existing).
            reminders: New reminder list (replaces existing).
            recurrence: New recurrence rule (replaces existing).
            status: New status (confirmed, tentative, cancelled).
            send_notifications: Whether to send notifications about
                the changes to attendees.
            update_series: For recurring events, if True updates the
                entire series; if False updates only this instance.
            etag: Expected ETag for optimistic concurrency control.
                If provided and the server's ETag differs, the update
                is rejected with a conflict error.

        Returns:
            The updated `Event` object.

        Raises:
            AuthenticationError: If the user is not authenticated.
            ProviderAPIError: If the provider API returns an error.
            EventNotFoundError: If the event does not exist.
            ConflictError: If the etag does not match the current
                server version (optimistic concurrency failure).
            ValidationError: If the updated event data is invalid.
        """
        ...

    @abstractmethod
    async def delete_event(
        self,
        event_id: str,
        calendar_id: str | None = None,
        send_notifications: bool = True,
        delete_series: bool = False,
    ) -> bool:
        """Delete a calendar event.

        Args:
            event_id: ID of the event to delete.
            calendar_id: Calendar containing the event. If None, uses
                the primary calendar.
            send_notifications: Whether to send cancellation
                notifications to attendees.
            delete_series: For recurring events, if True deletes the
                entire series; if False deletes only this instance.

        Returns:
            True if the event was successfully deleted.

        Raises:
            AuthenticationError: If the user is not authenticated.
            ProviderAPIError: If the provider API returns an error.
            EventNotFoundError: If the event does not exist.
        """
        ...

    # ------------------------------------------------------------------ #
    # Free/Busy operations
    # ------------------------------------------------------------------ #

    @abstractmethod
    async def get_free_busy(
        self,
        start_time: datetime,
        end_time: datetime,
        calendar_ids: list[str] | None = None,
    ) -> list[FreeBusySlot]:
        """Retrieve free/busy information for a time range.

        Returns a list of time slots indicating the user's availability.
        This is typically used to find open time slots for scheduling.

        Args:
            start_time: Start of the query window (timezone-aware).
            end_time: End of the query window (timezone-aware).
            calendar_ids: List of calendar IDs to check. If None,
                checks all accessible calendars.

        Returns:
            A list of `FreeBusySlot` objects covering the requested
            time range. Slots with status "free" indicate available
            time; other statuses indicate various forms of busy.

        Raises:
            AuthenticationError: If the user is not authenticated.
            ProviderAPIError: If the provider API returns an error.
        """
        ...

    # ------------------------------------------------------------------ #
    # Utility / lifecycle
    # ------------------------------------------------------------------ #

    async def close(self) -> None:
        """Release any resources held by the provider.

        Default implementation is a no-op. Override in subclasses
        to close HTTP clients, connection pools, or other resources.
        """
        pass
