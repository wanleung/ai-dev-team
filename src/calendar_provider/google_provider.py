"""Google Calendar provider implementation.

Concrete implementation of the `CalendarProvider` interface using the
`google-api-python-client` library to interact with Google Calendar API v3.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from src.calendar_provider.base import CalendarProvider
from src.models.calendar import (
    Calendar,
    Event,
    EventAttendee,
    EventReminder,
    FreeBusySlot,
    ProviderConfig,
    RecurrenceRule,
)


class GoogleCalendarProvider(CalendarProvider):
    """Google Calendar API v3 provider.

    Implements the `CalendarProvider` interface using the official
    `google-api-python-client` library. Handles OAuth2 authentication,
    calendar listing, event CRUD, and free/busy queries.
    """

    SCOPES = [
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/calendar.events",
    ]

    def __init__(self, config: ProviderConfig) -> None:
        """Initialize the Google Calendar provider.

        Args:
            config: Provider configuration with OAuth2 credentials.
        """
        super().__init__(config)
        self._service: Any = None
        self._credentials: Credentials | None = None

    @property
    def provider_name(self) -> str:
        """Return the canonical provider name.

        Returns:
            "google"
        """
        return "google"

    def _build_credentials(self) -> Credentials:
        """Build Google OAuth2 credentials from the provider config.

        Returns:
            A `Credentials` object ready for API calls.

        Raises:
            ValueError: If required tokens are missing from config.
        """
        if not self.config.access_token:
            raise ValueError("access_token is required for Google Calendar authentication")

        token_expiry = None
        if self.config.token_expiry:
            if self.config.token_expiry.tzinfo is None:
                token_expiry = self.config.token_expiry.replace(tzinfo=timezone.utc)
            else:
                token_expiry = self.config.token_expiry

        return Credentials(
            token=self.config.access_token,
            refresh_token=self.config.refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self.config.client_id,
            client_secret=self.config.client_secret,
            scopes=self.config.scopes or self.SCOPES,
            expiry=token_expiry,
        )

    def _get_service(self) -> Any:
        """Get or create the Google Calendar API service client.

        Returns:
            A `Calendar` service resource from `googleapiclient`.
        """
        if self._service is None:
            self._credentials = self._build_credentials()
            self._service = build("calendar", "v3", credentials=self._credentials)
        return self._service

    async def authenticate(self) -> bool:
        """Validate and refresh Google OAuth2 credentials.

        Checks whether the current access token is valid. If expired
        but a refresh token is available, performs an automatic refresh.

        Returns:
            True if authentication is valid after this call, False otherwise.
        """
        try:
            credentials = self._build_credentials()
            if credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
                self.config.access_token = credentials.token
                self.config.token_expiry = credentials.expiry
                self.config.refresh_token = credentials.refresh_token
                self._credentials = credentials
                self._service = build("calendar", "v3", credentials=credentials)
            return credentials.valid
        except Exception:
            return False

    async def list_calendars(self) -> list[Calendar]:
        """List all calendars accessible to the authenticated user.

        Returns:
            A list of `Calendar` models for each accessible calendar.

        Raises:
            AuthenticationError: If not authenticated.
            ProviderAPIError: If the Google Calendar API returns an error.
        """
        try:
            service = self._get_service()
            calendars_result = service.calendarList().list().execute()
            calendars: list[Calendar] = []

            for cal in calendars_result.get("items", []):
                calendars.append(
                    Calendar(
                        id=cal["id"],
                        name=cal.get("summary", ""),
                        description=cal.get("description"),
                        timezone=cal.get("timeZone", "UTC"),
                        is_primary=cal.get("primary", False),
                        access_role=cal.get("accessRole", "reader"),
                        color=cal.get("backgroundColor"),
                    )
                )
            return calendars
        except HttpError as e:
            raise ProviderAPIError(
                f"Google Calendar API error listing calendars: {e.reason}",
                status_code=e.resp.status,
            ) from e

    async def get_events(
        self,
        calendar_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        max_results: int = 100,
        expand_recurring: bool = True,
    ) -> list[Event]:
        """Retrieve events within a specified time range from Google Calendar.

        Args:
            calendar_id: Calendar ID to query. Defaults to "primary".
            start_time: Start of the time window. Defaults to now.
            end_time: End of the time window. Defaults to 24h after start.
            max_results: Maximum events to return.
            expand_recurring: If True, expands recurring events.

        Returns:
            A list of `Event` models.

        Raises:
            AuthenticationError: If not authenticated.
            ProviderAPIError: If the API returns an error.
            CalendarNotFoundError: If the calendar does not exist.
        """
        target_calendar = calendar_id or "primary"
        if start_time is None:
            start_time = datetime.now(timezone.utc)
        if end_time is None:
            end_time = start_time.replace(hour=start_time.hour + 24) if start_time else datetime.now(timezone.utc)

        time_min = self._format_datetime(start_time)
        time_max = self._format_datetime(end_time)

        try:
            service = self._get_service()
            events_result = service.events().list(
                calendarId=target_calendar,
                timeMin=time_min,
                timeMax=time_max,
                maxResults=max_results,
                singleEvents=expand_recurring,
                orderBy="startTime" if expand_recurring else None,
            ).execute()

            events: list[Event] = []
            for item in events_result.get("items", []):
                events.append(self._parse_event(item, target_calendar))
            return events
        except HttpError as e:
            if e.resp.status == 404:
                raise CalendarNotFoundError(
                    f"Calendar '{target_calendar}' not found",
                    status_code=404,
                ) from e
            raise ProviderAPIError(
                f"Google Calendar API error getting events: {e.reason}",
                status_code=e.resp.status,
            ) from e

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
        """Create a new event in Google Calendar.

        Args:
            title: Event title.
            start: Event start time.
            end: Event end time.
            timezone: IANA timezone for the event.
            calendar_id: Target calendar. Defaults to "primary".
            description: Event description.
            location: Event location.
            attendees: List of attendees.
            reminders: List of reminders.
            recurrence: Recurrence rule.
            send_notifications: Whether to notify attendees.

        Returns:
            The created `Event` model.

        Raises:
            AuthenticationError: If not authenticated.
            ProviderAPIError: If the API returns an error.
            ValidationError: If event data is invalid.
        """
        if end <= start:
            raise ValidationError("Event end time must be after start time")

        target_calendar = calendar_id or "primary"

        body = self._build_event_body(
            title=title,
            start=start,
            end=end,
            timezone=timezone,
            description=description,
            location=location,
            attendees=attendees,
            reminders=reminders,
            recurrence=recurrence,
        )

        try:
            service = self._get_service()
            created = service.events().insert(
                calendarId=target_calendar,
                body=body,
                sendNotifications=send_notifications,
            ).execute()
            return self._parse_event(created, target_calendar)
        except HttpError as e:
            if e.resp.status == 404:
                raise CalendarNotFoundError(
                    f"Calendar '{target_calendar}' not found",
                    status_code=404,
                ) from e
            raise ProviderAPIError(
                f"Google Calendar API error creating event: {e.reason}",
                status_code=e.resp.status,
            ) from e

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
        """Update an existing event in Google Calendar.

        Only provided (non-None) fields are updated.

        Args:
            event_id: Event ID to update.
            calendar_id: Calendar containing the event. Defaults to "primary".
            title: New title.
            description: New description.
            location: New location.
            start: New start time.
            end: New end time.
            timezone: New timezone.
            attendees: New attendee list.
            reminders: New reminders.
            recurrence: New recurrence rule.
            status: New status.
            send_notifications: Whether to notify attendees.
            update_series: If True, updates entire recurring series.
            etag: ETag for optimistic concurrency.

        Returns:
            The updated `Event` model.

        Raises:
            AuthenticationError: If not authenticated.
            ProviderAPIError: If the API returns an error.
            EventNotFoundError: If the event does not exist.
            ConflictError: If etag mismatch.
            ValidationError: If updated data is invalid.
        """
        target_calendar = calendar_id or "primary"

        try:
            service = self._get_service()
            existing = service.events().get(
                calendarId=target_calendar,
                eventId=event_id,
            ).execute()
        except HttpError as e:
            if e.resp.status == 404:
                raise EventNotFoundError(
                    f"Event '{event_id}' not found in calendar '{target_calendar}'",
                    status_code=404,
                ) from e
            raise ProviderAPIError(
                f"Google Calendar API error fetching event: {e.reason}",
                status_code=e.resp.status,
            ) from e

        if etag and existing.get("etag") != etag:
            raise ConflictError(
                f"Event '{event_id}' has been modified since last read",
                status_code=409,
            )

        updated_body = self._merge_event_body(existing, title, description, location,
                                                start, end, timezone, attendees,
                                                reminders, recurrence, status)

        if start and end and end <= start:
            raise ValidationError("Event end time must be after start time")

        try:
            service = self._get_service()
            headers = {}
            if etag:
                headers["If-Match"] = etag

            updated = service.events().update(
                calendarId=target_calendar,
                eventId=event_id,
                body=updated_body,
                sendNotifications=send_notifications,
            ).execute()
            return self._parse_event(updated, target_calendar)
        except HttpError as e:
            if e.resp.status == 404:
                raise EventNotFoundError(
                    f"Event '{event_id}' not found in calendar '{target_calendar}'",
                    status_code=404,
                ) from e
            if e.resp.status == 412:
                raise ConflictError(
                    f"Event '{event_id}' has been modified since last read",
                    status_code=409,
                ) from e
            raise ProviderAPIError(
                f"Google Calendar API error updating event: {e.reason}",
                status_code=e.resp.status,
            ) from e

    async def delete_event(
        self,
        event_id: str,
        calendar_id: str | None = None,
        send_notifications: bool = True,
        delete_series: bool = False,
    ) -> bool:
        """Delete an event from Google Calendar.

        Args:
            event_id: Event ID to delete.
            calendar_id: Calendar containing the event. Defaults to "primary".
            send_notifications: Whether to send cancellation notifications.
            delete_series: If True, deletes entire recurring series.

        Returns:
            True if successfully deleted.

        Raises:
            AuthenticationError: If not authenticated.
            ProviderAPIError: If the API returns an error.
            EventNotFoundError: If the event does not exist.
        """
        target_calendar = calendar_id or "primary"

        try:
            service = self._get_service()
            service.events().delete(
                calendarId=target_calendar,
                eventId=event_id,
                sendNotifications=send_notifications,
            ).execute()
            return True
        except HttpError as e:
            if e.resp.status == 404:
                raise EventNotFoundError(
                    f"Event '{event_id}' not found in calendar '{target_calendar}'",
                    status_code=404,
                ) from e
            raise ProviderAPIError(
                f"Google Calendar API error deleting event: {e.reason}",
                status_code=e.resp.status,
            ) from e

    async def get_free_busy(
        self,
        start_time: datetime,
        end_time: datetime,
        calendar_ids: list[str] | None = None,
    ) -> list[FreeBusySlot]:
        """Retrieve free/busy information from Google Calendar.

        Args:
            start_time: Start of the query window.
            end_time: End of the query window.
            calendar_ids: Calendar IDs to check. Defaults to all accessible.

        Returns:
            A list of `FreeBusySlot` models.

        Raises:
            AuthenticationError: If not authenticated.
            ProviderAPIError: If the API returns an error.
        """
        time_min = self._format_datetime(start_time)
        time_max = self._format_datetime(end_time)

        if calendar_ids is None:
            calendars = await self.list_calendars()
            calendar_ids = [c.id for c in calendars]

        body = {
            "timeMin": time_min,
            "timeMax": time_max,
            "items": [{"id": cid} for cid in calendar_ids],
        }

        try:
            service = self._get_service()
            result = service.freebusy().query(body=body).execute()
            slots: list[FreeBusySlot] = []

            for cal_id, cal_data in result.get("calendars", {}).items():
                for busy_period in cal_data.get("busy", []):
                    slots.append(
                        FreeBusySlot(
                            start=self._parse_datetime(busy_period["start"]),
                            end=self._parse_datetime(busy_period["end"]),
                            status="busy",
                        )
                    )
            return slots
        except HttpError as e:
            raise ProviderAPIError(
                f"Google Calendar API error querying free/busy: {e.reason}",
                status_code=e.resp.status,
            ) from e

    async def close(self) -> None:
        """Release resources held by the provider."""
        self._service = None
        self._credentials = None

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _format_datetime(dt: datetime) -> str:
        """Format a datetime as an ISO 8601 string for the Google API.

        Args:
            dt: Datetime to format.

        Returns:
            ISO 8601 string with timezone offset.
        """
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()

    @staticmethod
    def _parse_datetime(value: str) -> datetime:
        """Parse an ISO 8601 datetime string from the Google API.

        Args:
            value: ISO 8601 string.

        Returns:
            Timezone-aware datetime.
        """
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    def _parse_event(self, raw: dict[str, Any], calendar_id: str) -> Event:
        """Convert a raw Google Calendar event dict to a unified `Event`.

        Args:
            raw: Raw event dict from the Google Calendar API.
            calendar_id: Calendar ID the event belongs to.

        Returns:
            A unified `Event` model.
        """
        start_raw = raw.get("start", {})
        end_raw = raw.get("end", {})

        if "dateTime" in start_raw:
            start = self._parse_datetime(start_raw["dateTime"])
            end = self._parse_datetime(end_raw.get("dateTime", ""))
            tz = start_raw.get("timeZone", "UTC")
        else:
            start = self._parse_datetime(start_raw.get("date", ""))
            end = self._parse_datetime(end_raw.get("date", ""))
            tz = "UTC"

        attendees: list[EventAttendee] = []
        for att in raw.get("attendees", []):
            attendees.append(
                EventAttendee(
                    email=att.get("email", ""),
                    name=att.get("displayName"),
                    response_status=att.get("responseStatus"),
                    is_organizer=att.get("organizer", False),
                )
            )

        reminders_list: list[EventReminder] = []
        reminders_override = raw.get("reminders", {})
        if reminders_override.get("useDefault", False):
            pass
        for override in reminders_override.get("overrides", []):
            reminders_list.append(
                EventReminder(
                    method=override.get("method", "popup"),
                    minutes_before=override.get("minutes", 0),
                )
            )

        recurrence_rule: RecurrenceRule | None = None
        rrules = raw.get("recurrence")
        if rrules:
            recurrence_rule = self._parse_recurrence(rrules)

        created_at = self._parse_datetime(raw["created"]) if "created" in raw else datetime.now(timezone.utc)
        updated_at = self._parse_datetime(raw["updated"]) if "updated" in raw else datetime.now(timezone.utc)

        recurrence_id = raw.get("recurringEventId")
        is_recurring_master = bool(raw.get("recurrence")) and not recurrence_id

        return Event(
            id=raw["id"],
            calendar_id=calendar_id,
            title=raw.get("summary", ""),
            description=raw.get("description"),
            location=raw.get("location"),
            start=start,
            end=end,
            timezone=tz,
            attendees=attendees,
            reminders=reminders_list,
            recurrence=recurrence_rule,
            status=raw.get("status", "confirmed"),
            created_at=created_at,
            updated_at=updated_at,
            etag=raw.get("etag"),
            is_recurring_master=is_recurring_master,
            recurrence_id=recurrence_id,
            provider_metadata=raw,
        )

    def _parse_recurrence(self, rrules: list[str]) -> RecurrenceRule | None:
        """Parse a Google Calendar recurrence list into a `RecurrenceRule`.

        Args:
            rrules: List of RRULE strings from Google Calendar.

        Returns:
            A `RecurrenceRule` model, or None if parsing fails.
        """
        if not rrules:
            return None

        rrule_str = rrules[0]
        if not rrule_str.startswith("RRULE:"):
            return None

        parts = rrule_str[6:].split(";")
        kwargs: dict[str, Any] = {}

        for part in parts:
            key, _, value = part.partition("=")
            if key == "FREQ":
                kwargs["frequency"] = value.lower()
            elif key == "INTERVAL":
                kwargs["interval"] = int(value)
            elif key == "COUNT":
                kwargs["count"] = int(value)
            elif key == "UNTIL":
                kwargs["until"] = datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            elif key == "BYDAY":
                kwargs["by_day"] = value.split(",")
            elif key == "BYMONTHDAY":
                kwargs["by_month_day"] = [int(d) for d in value.split(",")]

        if "frequency" not in kwargs:
            return None

        return RecurrenceRule(**kwargs)

    def _build_event_body(
        self,
        title: str,
        start: datetime,
        end: datetime,
        timezone: str,
        description: str | None = None,
        location: str | None = None,
        attendees: list[EventAttendee] | None = None,
        reminders: list[EventReminder] | None = None,
        recurrence: RecurrenceRule | None = None,
    ) -> dict[str, Any]:
        """Build a Google Calendar API request body from unified parameters.

        Args:
            title: Event title.
            start: Event start time.
            end: Event end time.
            timezone: IANA timezone.
            description: Event description.
            location: Event location.
            attendees: Attendee list.
            reminders: Reminder list.
            recurrence: Recurrence rule.

        Returns:
            A dict suitable for the Google Calendar API.
        """
        body: dict[str, Any] = {
            "summary": title,
            "start": {
                "dateTime": self._format_datetime(start),
                "timeZone": timezone,
            },
            "end": {
                "dateTime": self._format_datetime(end),
                "timeZone": timezone,
            },
        }

        if description:
            body["description"] = description
        if location:
            body["location"] = location
        if attendees:
            body["attendees"] = [
                {"email": a.email, "displayName": a.name}
                for a in attendees
            ]
        if reminders:
            body["reminders"] = {
                "useDefault": False,
                "overrides": [
                    {"method": r.method, "minutes": r.minutes_before}
                    for r in reminders
                ],
            }
        if recurrence:
            body["recurrence"] = [self._build_rrule(recurrence)]

        return body

    def _merge_event_body(
        self,
        existing: dict[str, Any],
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
    ) -> dict[str, Any]:
        """Merge updated fields into an existing Google Calendar event body.

        Only non-None fields overwrite existing values.

        Args:
            existing: The raw existing event dict from Google Calendar.
            title: New title.
            description: New description.
            location: New location.
            start: New start time.
            end: New end time.
            timezone: New timezone.
            attendees: New attendees.
            reminders: New reminders.
            recurrence: New recurrence.
            status: New status.

        Returns:
            The merged event body dict.
        """
        body = dict(existing)

        if title is not None:
            body["summary"] = title
        if description is not None:
            body["description"] = description
        if location is not None:
            body["location"] = location
        if status is not None:
            body["status"] = status

        tz = timezone or body.get("start", {}).get("timeZone", "UTC")
        if start is not None or end is not None:
            current_start = body.get("start", {})
            current_end = body.get("end", {})
            body["start"] = {
                "dateTime": self._format_datetime(start) if start else current_start.get("dateTime", ""),
                "timeZone": tz,
            }
            body["end"] = {
                "dateTime": self._format_datetime(end) if end else current_end.get("dateTime", ""),
                "timeZone": tz,
            }

        if attendees is not None:
            body["attendees"] = [
                {"email": a.email, "displayName": a.name}
                for a in attendees
            ]

        if reminders is not None:
            body["reminders"] = {
                "useDefault": False,
                "overrides": [
                    {"method": r.method, "minutes": r.minutes_before}
                    for r in reminders
                ],
            }

        if recurrence is not None:
            body["recurrence"] = [self._build_rrule(recurrence)]

        return body

    @staticmethod
    def _build_rrule(rule: RecurrenceRule) -> str:
        """Build an RRULE string from a `RecurrenceRule` model.

        Args:
            rule: The recurrence rule model.

        Returns:
            An RRULE string compatible with Google Calendar.
        """
        parts = [f"FREQ={rule.frequency.upper()}"]

        if rule.interval != 1:
            parts.append(f"INTERVAL={rule.interval}")
        if rule.count is not None:
            parts.append(f"COUNT={rule.count}")
        if rule.until is not None:
            until_str = rule.until.strftime("%Y%m%dT%H%M%SZ")
            parts.append(f"UNTIL={until_str}")
        if rule.by_day:
            parts.append(f"BYDAY={','.join(rule.by_day)}")
        if rule.by_month_day:
            parts.append(f"BYMONTHDAY={','.join(str(d) for d in rule.by_month_day)}")

        return "RRULE:" + ";".join(parts)


class ProviderAPIError(Exception):
    """Raised when a calendar provider API returns an error response."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class AuthenticationError(ProviderAPIError):
    """Raised when authentication fails."""

    pass


class CalendarNotFoundError(ProviderAPIError):
    """Raised when a requested calendar is not found."""

    pass


class EventNotFoundError(ProviderAPIError):
    """Raised when a requested event is not found."""

    pass


class ConflictError(ProviderAPIError):
    """Raised when a concurrent modification conflict is detected."""

    pass


class ValidationError(ProviderAPIError):
    """Raised when event data fails validation."""

    pass
