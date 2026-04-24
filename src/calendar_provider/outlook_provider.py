"""Outlook Calendar provider implementation.

Concrete implementation of the `CalendarProvider` interface using the
`msgraph-sdk` library to interact with Microsoft Graph Calendar API.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from kiota_abstractions.api_error import APIError
from kiota_abstractions.authentication import AnonymousAuthenticationProvider
from kiota_http.httpx_request_adapter import HttpxRequestAdapter
from msgraph import GraphServiceClient
from msgraph.generated.calendars.calendars_request_builder import CalendarsRequestBuilder
from msgraph.generated.me.me_request_builder import MeRequestBuilder
from msgraph.generated.models.attendee import Attendee
from msgraph.generated.models.attendee_type import AttendeeType
from msgraph.generated.models.body_type import BodyType
from msgraph.generated.models.date_time_time_zone import DateTimeTimeZone
from msgraph.generated.models.email_address import EmailAddress
from msgraph.generated.models.event import Event as GraphEvent
from msgraph.generated.models.location import Location
from msgraph.generated.models.patterned_recurrence import PatternedRecurrence
from msgraph.generated.models.recurrence_pattern import RecurrencePattern
from msgraph.generated.models.recurrence_range import RecurrenceRange
from msgraph.generated.models.response_status import ResponseStatus
from msgraph.generated.models.response_type import ResponseType
from msgraph.generated.models.schedule_item import ScheduleItem
from msgraph.generated.users.item.calendar_view.calendar_view_request_builder import CalendarViewRequestBuilder
from msgraph.generated.users.item.calendars.item.events.events_request_builder import EventsRequestBuilder

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


class OutlookCalendarProvider(CalendarProvider):
    """Outlook/Microsoft Graph Calendar API provider.

    Implements the `CalendarProvider` interface using the official
    `msgraph-sdk` library. Handles OAuth2 authentication, calendar
    listing, event CRUD, and free/busy queries.
    """

    SCOPES = [
        "Calendars.Read",
        "Calendars.ReadWrite",
        "User.Read",
    ]

    def __init__(self, config: ProviderConfig) -> None:
        """Initialize the Outlook Calendar provider.

        Args:
            config: Provider configuration with OAuth2 credentials.
        """
        super().__init__(config)
        self._client: GraphServiceClient | None = None
        self._http_client: httpx.AsyncClient | None = None

    @property
    def provider_name(self) -> str:
        """Return the canonical provider name.

        Returns:
            "outlook"
        """
        return "outlook"

    def _build_graph_client(self) -> GraphServiceClient:
        """Build a Microsoft Graph service client from the provider config.

        Returns:
            A configured `GraphServiceClient` ready for API calls.

        Raises:
            ValueError: If required tokens are missing from config.
        """
        if not self.config.access_token:
            raise ValueError("access_token is required for Outlook Calendar authentication")

        async def auth_callback(request, additional_scopes=None):
            request.headers["Authorization"] = f"Bearer {self.config.access_token}"

        httpx_client = httpx.AsyncClient()
        auth_provider = AnonymousAuthenticationProvider()
        request_adapter = HttpxRequestAdapter(
            authentication_provider=auth_provider,
            http_client=httpx_client,
        )
        client = GraphServiceClient(request_adapter=request_adapter, scopes=self.config.scopes or self.SCOPES)
        return client

    def _get_client(self) -> GraphServiceClient:
        """Get or create the Microsoft Graph service client.

        Returns:
            A `GraphServiceClient` instance.
        """
        if self._client is None:
            self._client = self._build_graph_client()
        return self._client

    async def authenticate(self) -> bool:
        """Validate and refresh Microsoft OAuth2 credentials.

        Checks whether the current access token is valid. If expired
        but a refresh token is available, performs an automatic refresh
        via the Microsoft identity platform token endpoint.

        Returns:
            True if authentication is valid after this call, False otherwise.
        """
        if not self.config.access_token:
            return False

        if self.config.token_expiry and self.config.token_expiry > datetime.now(timezone.utc):
            return True

        if self.config.refresh_token:
            try:
                await self._refresh_token()
                return True
            except Exception:
                return False

        return False

    async def _refresh_token(self) -> None:
        """Refresh the Microsoft OAuth2 access token.

        Uses the refresh token to obtain a new access token from the
        Microsoft identity platform.

        Raises:
            AuthenticationError: If token refresh fails.
        """
        token_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
        data = {
            "grant_type": "refresh_token",
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "refresh_token": self.config.refresh_token,
            "scope": " ".join(self.config.scopes or self.SCOPES),
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(token_url, data=data)
            response.raise_for_status()
            token_data = response.json()

        self.config.access_token = token_data.get("access_token")
        self.config.refresh_token = token_data.get("refresh_token", self.config.refresh_token)
        expires_in = token_data.get("expires_in", 3600)
        self.config.token_expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        self._client = None

    async def list_calendars(self) -> list[Calendar]:
        """List all calendars accessible to the authenticated user.

        Returns:
            A list of `Calendar` models for each accessible calendar.

        Raises:
            AuthenticationError: If not authenticated.
            ProviderAPIError: If the Microsoft Graph API returns an error.
        """
        try:
            client = self._get_client()
            result = await client.me.calendars.get()
            calendars: list[Calendar] = []

            if result and result.value:
                for cal in result.value:
                    calendars.append(
                        Calendar(
                            id=cal.id or "",
                            name=cal.name or "",
                            description=cal.change_key,
                            timezone=cal.default_online_meeting_provider or "UTC",
                            is_primary=cal.is_default_calendar or False,
                            access_role="owner",
                            color=cal.hex_color,
                        )
                    )
            return calendars
        except APIError as e:
            raise ProviderAPIError(
                f"Microsoft Graph API error listing calendars: {e.message}",
                status_code=e.response_status_code,
            ) from e
        except Exception as e:
            raise ProviderAPIError(
                f"Unexpected error listing calendars: {str(e)}",
            ) from e

    async def get_events(
        self,
        calendar_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        max_results: int = 100,
        expand_recurring: bool = True,
    ) -> list[Event]:
        """Retrieve events within a specified time range from Outlook Calendar.

        Args:
            calendar_id: Calendar ID to query. Defaults to primary calendar.
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
        target_calendar = calendar_id or "calendar"
        if start_time is None:
            start_time = datetime.now(timezone.utc)
        if end_time is None:
            end_time = start_time + timedelta(hours=24)

        try:
            client = self._get_client()

            if expand_recurring:
                query_params = CalendarViewRequestBuilder.CalendarViewRequestBuilderGetQueryParameters(
                    start_date_time=self._format_datetime(start_time),
                    end_date_time=self._format_datetime(end_time),
                    top=max_results,
                )
                request_config = CalendarViewRequestBuilder.CalendarViewRequestBuilderGetRequestConfiguration(
                    query_parameters=query_params,
                )
                result = await client.me.calendar_view.get(request_configuration=request_config)
            else:
                query_params = EventsRequestBuilder.EventsRequestBuilderGetQueryParameters(
                    top=max_results,
                    filter=f"start/dateTime ge '{self._format_datetime(start_time)}' and start/dateTime le '{self._format_datetime(end_time)}'",
                )
                request_config = EventsRequestBuilder.EventsRequestBuilderGetRequestConfiguration(
                    query_parameters=query_params,
                )
                result = await client.me.calendars.by_calendar_id(target_calendar).events.get(request_configuration=request_config)

            events: list[Event] = []
            if result and result.value:
                for item in result.value:
                    events.append(self._parse_event(item, target_calendar))
            return events
        except APIError as e:
            if e.response_status_code == 404:
                raise CalendarNotFoundError(
                    f"Calendar '{target_calendar}' not found",
                    status_code=404,
                ) from e
            raise ProviderAPIError(
                f"Microsoft Graph API error getting events: {e.message}",
                status_code=e.response_status_code,
            ) from e
        except Exception as e:
            raise ProviderAPIError(
                f"Unexpected error getting events: {str(e)}",
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
        """Create a new event in Outlook Calendar.

        Args:
            title: Event title.
            start: Event start time.
            end: Event end time.
            timezone: IANA timezone for the event.
            calendar_id: Target calendar. Defaults to primary.
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

        target_calendar = calendar_id or "calendar"

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
            client = self._get_client()
            created = await client.me.calendars.by_calendar_id(target_calendar).events.post(body)
            if created is None:
                raise ProviderAPIError("Failed to create event: no response from API")
            return self._parse_event(created, target_calendar)
        except APIError as e:
            if e.response_status_code == 404:
                raise CalendarNotFoundError(
                    f"Calendar '{target_calendar}' not found",
                    status_code=404,
                ) from e
            raise ProviderAPIError(
                f"Microsoft Graph API error creating event: {e.message}",
                status_code=e.response_status_code,
            ) from e
        except Exception as e:
            raise ProviderAPIError(
                f"Unexpected error creating event: {str(e)}",
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
        """Update an existing event in Outlook Calendar.

        Only provided (non-None) fields are updated.

        Args:
            event_id: Event ID to update.
            calendar_id: Calendar containing the event. Defaults to primary.
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
        target_calendar = calendar_id or "calendar"

        try:
            client = self._get_client()
            existing = await client.me.calendars.by_calendar_id(target_calendar).events.by_event_id(event_id).get()
        except APIError as e:
            if e.response_status_code == 404:
                raise EventNotFoundError(
                    f"Event '{event_id}' not found in calendar '{target_calendar}'",
                    status_code=404,
                ) from e
            raise ProviderAPIError(
                f"Microsoft Graph API error fetching event: {e.message}",
                status_code=e.response_status_code,
            ) from e
        except Exception as e:
            raise ProviderAPIError(
                f"Unexpected error fetching event: {str(e)}",
            ) from e

        if existing is None:
            raise EventNotFoundError(
                f"Event '{event_id}' not found in calendar '{target_calendar}'",
                status_code=404,
            )

        if etag and existing.e_tag != etag:
            raise ConflictError(
                f"Event '{event_id}' has been modified since last read",
                status_code=409,
            )

        updated_body = self._merge_event_body(
            existing, title, description, location,
            start, end, timezone, attendees,
            reminders, recurrence, status,
        )

        if start and end and end <= start:
            raise ValidationError("Event end time must be after start time")

        try:
            client = self._get_client()
            headers = {}
            if etag:
                headers["If-Match"] = etag

            updated = await client.me.calendars.by_calendar_id(target_calendar).events.by_event_id(event_id).patch(
                updated_body,
            )
            if updated is None:
                updated = await client.me.calendars.by_calendar_id(target_calendar).events.by_event_id(event_id).get()
            if updated is None:
                raise ProviderAPIError("Failed to update event: no response from API")
            return self._parse_event(updated, target_calendar)
        except APIError as e:
            if e.response_status_code == 404:
                raise EventNotFoundError(
                    f"Event '{event_id}' not found in calendar '{target_calendar}'",
                    status_code=404,
                ) from e
            if e.response_status_code == 412:
                raise ConflictError(
                    f"Event '{event_id}' has been modified since last read",
                    status_code=409,
                ) from e
            raise ProviderAPIError(
                f"Microsoft Graph API error updating event: {e.message}",
                status_code=e.response_status_code,
            ) from e
        except Exception as e:
            raise ProviderAPIError(
                f"Unexpected error updating event: {str(e)}",
            ) from e

    async def delete_event(
        self,
        event_id: str,
        calendar_id: str | None = None,
        send_notifications: bool = True,
        delete_series: bool = False,
    ) -> bool:
        """Delete an event from Outlook Calendar.

        Args:
            event_id: Event ID to delete.
            calendar_id: Calendar containing the event. Defaults to primary.
            send_notifications: Whether to send cancellation notifications.
            delete_series: If True, deletes entire recurring series.

        Returns:
            True if successfully deleted.

        Raises:
            AuthenticationError: If not authenticated.
            ProviderAPIError: If the API returns an error.
            EventNotFoundError: If the event does not exist.
        """
        target_calendar = calendar_id or "calendar"

        try:
            client = self._get_client()
            await client.me.calendars.by_calendar_id(target_calendar).events.by_event_id(event_id).delete()
            return True
        except APIError as e:
            if e.response_status_code == 404:
                raise EventNotFoundError(
                    f"Event '{event_id}' not found in calendar '{target_calendar}'",
                    status_code=404,
                ) from e
            raise ProviderAPIError(
                f"Microsoft Graph API error deleting event: {e.message}",
                status_code=e.response_status_code,
            ) from e
        except Exception as e:
            raise ProviderAPIError(
                f"Unexpected error deleting event: {str(e)}",
            ) from e

    async def get_free_busy(
        self,
        start_time: datetime,
        end_time: datetime,
        calendar_ids: list[str] | None = None,
    ) -> list[FreeBusySlot]:
        """Retrieve free/busy information from Outlook Calendar.

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
        try:
            client = self._get_client()

            if calendar_ids is None:
                calendars = await self.list_calendars()
                calendar_ids = [c.id for c in calendars if c.id]

            slots: list[FreeBusySlot] = []

            for cal_id in calendar_ids:
                query_params = CalendarViewRequestBuilder.CalendarViewRequestBuilderGetQueryParameters(
                    start_date_time=self._format_datetime(start_time),
                    end_date_time=self._format_datetime(end_time),
                )
                request_config = CalendarViewRequestBuilder.CalendarViewRequestBuilderGetRequestConfiguration(
                    query_parameters=query_params,
                )
                result = await client.me.calendar_view.get(request_configuration=request_config)

                if result and result.value:
                    for item in result.value:
                        if item.start and item.end:
                            slots.append(
                                FreeBusySlot(
                                    start=self._parse_datetime(item.start.date_time, item.start.time_zone),
                                    end=self._parse_datetime(item.end.date_time, item.end.time_zone),
                                    status="busy",
                                )
                            )

            return slots
        except APIError as e:
            raise ProviderAPIError(
                f"Microsoft Graph API error querying free/busy: {e.message}",
                status_code=e.response_status_code,
            ) from e
        except Exception as e:
            raise ProviderAPIError(
                f"Unexpected error querying free/busy: {str(e)}",
            ) from e

    async def close(self) -> None:
        """Release resources held by the provider."""
        self._client = None
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _format_datetime(dt: datetime) -> str:
        """Format a datetime as an ISO 8601 string for the Microsoft Graph API.

        Args:
            dt: Datetime to format.

        Returns:
            ISO 8601 string.
        """
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()

    @staticmethod
    def _parse_datetime(value: str | None, tz_name: str | None = None) -> datetime:
        """Parse a datetime string from the Microsoft Graph API.

        Args:
            value: Datetime string.
            tz_name: Optional timezone name.

        Returns:
            Timezone-aware datetime.
        """
        if not value:
            return datetime.now(timezone.utc)

        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            dt = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    def _parse_event(self, raw: GraphEvent, calendar_id: str) -> Event:
        """Convert a raw Microsoft Graph event to a unified `Event`.

        Args:
            raw: Raw event from the Microsoft Graph API.
            calendar_id: Calendar ID the event belongs to.

        Returns:
            A unified `Event` model.
        """
        start_raw = raw.start
        end_raw = raw.end

        if start_raw and start_raw.date_time:
            start = self._parse_datetime(start_raw.date_time, start_raw.time_zone)
            tz = start_raw.time_zone or "UTC"
        else:
            start = datetime.now(timezone.utc)
            tz = "UTC"

        if end_raw and end_raw.date_time:
            end = self._parse_datetime(end_raw.date_time, end_raw.time_zone)
        else:
            end = start + timedelta(hours=1)

        attendees: list[EventAttendee] = []
        if raw.attendees:
            for att in raw.attendees:
                email_addr = att.email_address
                response = att.status
                attendees.append(
                    EventAttendee(
                        email=email_addr.address if email_addr else "",
                        name=email_addr.name if email_addr else None,
                        response_status=self._parse_response_type(response.response_type) if response else None,
                        is_organizer=False,
                    )
                )

        reminders_list: list[EventReminder] = []
        if raw.reminders:
            for reminder in raw.reminders:
                if reminder.minutes_before_start is not None:
                    reminders_list.append(
                        EventReminder(
                            method="popup",
                            minutes_before=reminder.minutes_before_start,
                        )
                    )

        recurrence_rule: RecurrenceRule | None = None
        if raw.recurrence:
            recurrence_rule = self._parse_recurrence(raw.recurrence)

        created_at = self._parse_datetime(raw.created_date_time.date_time) if raw.created_date_time else datetime.now(timezone.utc)
        updated_at = self._parse_datetime(raw.last_modified_date_time.date_time) if raw.last_modified_date_time else datetime.now(timezone.utc)

        recurrence_id = raw.recurring_event_id if raw.recurring_event_id else None
        is_recurring_master = bool(raw.recurrence) and not recurrence_id

        provider_metadata: dict[str, Any] = {}
        if raw.id:
            provider_metadata["id"] = raw.id
        if raw.web_link:
            provider_metadata["web_link"] = raw.web_link
        if raw.online_meeting_url:
            provider_metadata["online_meeting_url"] = raw.online_meeting_url

        return Event(
            id=raw.id or "",
            calendar_id=calendar_id,
            title=raw.subject or "",
            description=raw.body.content if raw.body else None,
            location=raw.location.display_name if raw.location else None,
            start=start,
            end=end,
            timezone=tz,
            attendees=attendees,
            reminders=reminders_list,
            recurrence=recurrence_rule,
            status=self._parse_show_as(raw.show_as),
            created_at=created_at,
            updated_at=updated_at,
            etag=raw.e_tag,
            is_recurring_master=is_recurring_master,
            recurrence_id=recurrence_id,
            provider_metadata=provider_metadata if provider_metadata else None,
        )

    @staticmethod
    def _parse_response_type(response_type) -> str | None:
        """Map Microsoft Graph response type to unified status string.

        Args:
            response_type: ResponseType enum value.

        Returns:
            Unified response status string.
        """
        mapping = {
            ResponseType.NONE: None,
            ResponseType.ORGANIZER: None,
            ResponseType.TENTATIVE: "tentative",
            ResponseType.ACCEPTED: "accepted",
            ResponseType.DECLINED: "declined",
            ResponseType.NOT_RESPONDED: "needsAction",
        }
        return mapping.get(response_type, None)

    @staticmethod
    def _parse_show_as(show_as) -> str:
        """Map Microsoft Graph show-as to unified status string.

        Args:
            show_as: FreeBusyStatus enum value.

        Returns:
            Unified status string.
        """
        if show_as is None:
            return "confirmed"
        show_as_str = str(show_as).lower()
        if "free" in show_as_str:
            return "confirmed"
        if "tentative" in show_as_str:
            return "tentative"
        if "oof" in show_as_str or "out" in show_as_str:
            return "cancelled"
        return "confirmed"

    def _parse_recurrence(self, recurrence: PatternedRecurrence | None) -> RecurrenceRule | None:
        """Parse a Microsoft Graph recurrence into a `RecurrenceRule`.

        Args:
            recurrence: PatternedRecurrence from Microsoft Graph.

        Returns:
            A `RecurrenceRule` model, or None if parsing fails.
        """
        if not recurrence or not recurrence.pattern:
            return None

        pattern = recurrence.pattern
        range_info = recurrence.range

        kwargs: dict[str, Any] = {}

        if pattern.type:
            freq_mapping = {
                "daily": "daily",
                "weekly": "weekly",
                "absoluteMonthly": "monthly",
                "relativeMonthly": "monthly",
                "absoluteYearly": "yearly",
                "relativeYearly": "yearly",
            }
            kwargs["frequency"] = freq_mapping.get(pattern.type, "weekly")

        if pattern.interval:
            kwargs["interval"] = pattern.interval

        if pattern.days_of_week:
            kwargs["by_day"] = [d.value if hasattr(d, 'value') else str(d) for d in pattern.days_of_week]

        if pattern.day_of_month:
            kwargs["by_month_day"] = [pattern.day_of_month]

        if range_info:
            if range_info.number_of_occurrences:
                kwargs["count"] = range_info.number_of_occurrences
            if range_info.end_date:
                kwargs["until"] = self._parse_datetime(range_info.end_date)

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
    ) -> GraphEvent:
        """Build a Microsoft Graph API event body from unified parameters.

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
            A `GraphEvent` object suitable for the Microsoft Graph API.
        """
        body = GraphEvent()
        body.subject = title
        body.start = DateTimeTimeZone(
            date_time=self._format_datetime(start),
            time_zone=timezone,
        )
        body.end = DateTimeTimeZone(
            date_time=self._format_datetime(end),
            time_zone=timezone,
        )

        if description:
            body.body_type = BodyType.HTML
            body.content = description

        if location:
            body.location = Location(display_name=location)

        if attendees:
            body.attendees = [
                Attendee(
                    email_address=EmailAddress(
                        address=a.email,
                        name=a.name,
                    ),
                    type=AttendeeType.REQUIRED,
                )
                for a in attendees
            ]

        if reminders:
            body.is_reminder_on = True

        if recurrence:
            body.recurrence = self._build_patterned_recurrence(recurrence)

        return body

    def _merge_event_body(
        self,
        existing: GraphEvent,
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
    ) -> GraphEvent:
        """Merge updated fields into an existing Microsoft Graph event.

        Only non-None fields overwrite existing values.

        Args:
            existing: The existing event from Microsoft Graph.
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
            The merged event body.
        """
        body = GraphEvent()
        body.id = existing.id
        body.e_tag = existing.e_tag

        body.subject = title if title is not None else existing.subject
        body.body_type = existing.body_type

        if description is not None:
            body.content = description
        elif existing.body:
            body.content = existing.body.content

        if location is not None:
            body.location = Location(display_name=location)
        elif existing.location:
            body.location = existing.location

        tz = timezone
        if tz is None:
            if existing.start and existing.start.time_zone:
                tz = existing.start.time_zone
            else:
                tz = "UTC"

        if start is not None or end is not None:
            current_start = existing.start
            current_end = existing.end
            body.start = DateTimeTimeZone(
                date_time=self._format_datetime(start) if start else (current_start.date_time if current_start else ""),
                time_zone=tz,
            )
            body.end = DateTimeTimeZone(
                date_time=self._format_datetime(end) if end else (current_end.date_time if current_end else ""),
                time_zone=tz,
            )
        else:
            body.start = existing.start
            body.end = existing.end

        if attendees is not None:
            body.attendees = [
                Attendee(
                    email_address=EmailAddress(
                        address=a.email,
                        name=a.name,
                    ),
                    type=AttendeeType.REQUIRED,
                )
                for a in attendees
            ]
        elif existing.attendees:
            body.attendees = existing.attendees

        if reminders is not None:
            body.is_reminder_on = len(reminders) > 0
        else:
            body.is_reminder_on = existing.is_reminder_on

        if recurrence is not None:
            body.recurrence = self._build_patterned_recurrence(recurrence)
        elif existing.recurrence:
            body.recurrence = existing.recurrence

        return body

    def _build_patterned_recurrence(self, rule: RecurrenceRule) -> PatternedRecurrence:
        """Build a PatternedRecurrence from a `RecurrenceRule` model.

        Args:
            rule: The recurrence rule model.

        Returns:
            A `PatternedRecurrence` object for the Microsoft Graph API.
        """
        pattern = RecurrencePattern()

        freq_mapping = {
            "daily": "daily",
            "weekly": "weekly",
            "monthly": "absoluteMonthly",
            "yearly": "absoluteYearly",
        }
        pattern.type = freq_mapping.get(rule.frequency, "weekly")
        pattern.interval = rule.interval

        if rule.by_day:
            from msgraph.generated.models.day_of_week import DayOfWeek
            day_mapping = {
                "MO": DayOfWeek.MONDAY,
                "TU": DayOfWeek.TUESDAY,
                "WE": DayOfWeek.WEDNESDAY,
                "TH": DayOfWeek.THURSDAY,
                "FR": DayOfWeek.FRIDAY,
                "SA": DayOfWeek.SATURDAY,
                "SU": DayOfWeek.SUNDAY,
            }
            pattern.days_of_week = [day_mapping.get(d, DayOfWeek.MONDAY) for d in rule.by_day]

        if rule.by_month_day and len(rule.by_month_day) > 0:
            pattern.day_of_month = rule.by_month_day[0]

        range_info = RecurrenceRange()
        range_info.type = "noEnd"

        if rule.count is not None:
            range_info.type = "numbered"
            range_info.number_of_occurrences = rule.count

        if rule.until is not None:
            range_info.type = "endDate"
            range_info.end_date = rule.until.strftime("%Y-%m-%d")

        return PatternedRecurrence(pattern=pattern, range=range_info)


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
