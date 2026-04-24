"""Event normalizer service.

Converts between provider-specific event representations and the unified
internal event model. Supports Google Calendar (raw dict) and Outlook
Calendar (msgraph-sdk GraphEvent) formats.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.models.calendar import (
    Event,
    EventAttendee,
    EventReminder,
    RecurrenceRule,
)


class EventNormalizer:
    """Normalizes events between provider-specific and unified formats.

    Provides `normalize_event()` to convert raw provider responses into
    unified `Event` models, and `denormalize_event()` to convert unified
    events back into provider-specific request payloads.
    """

    def normalize_event(self, provider: str, raw_event: Any, calendar_id: str = "") -> Event:
        """Convert a provider-specific event to a unified `Event` model.

        Args:
            provider: Provider name ("google" or "outlook").
            raw_event: Raw event data from the provider API.
                For Google: a dict from the Google Calendar API.
                For Outlook: a GraphEvent object from msgraph-sdk.
            calendar_id: Calendar ID the event belongs to.

        Returns:
            A unified `Event` model.

        Raises:
            ValueError: If the provider is not supported.
        """
        if provider == "google":
            return self._normalize_google_event(raw_event, calendar_id)
        elif provider == "outlook":
            return self._normalize_outlook_event(raw_event, calendar_id)
        else:
            raise ValueError(f"Unsupported provider for normalization: {provider}")

    def denormalize_event(self, provider: str, event: Event) -> dict[str, Any] | Any:
        """Convert a unified `Event` model to a provider-specific payload.

        Args:
            provider: Provider name ("google" or "outlook").
            event: Unified event model to convert.

        Returns:
            For Google: a dict suitable for the Google Calendar API.
            For Outlook: a GraphEvent object for msgraph-sdk.

        Raises:
            ValueError: If the provider is not supported.
        """
        if provider == "google":
            return self._denormalize_google_event(event)
        elif provider == "outlook":
            return self._denormalize_outlook_event(event)
        else:
            raise ValueError(f"Unsupported provider for denormalization: {provider}")

    # ------------------------------------------------------------------ #
    # Google Calendar normalization
    # ------------------------------------------------------------------ #

    @staticmethod
    def _normalize_google_event(raw: dict[str, Any], calendar_id: str) -> Event:
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
            start = EventNormalizer._parse_datetime(start_raw["dateTime"])
            end = EventNormalizer._parse_datetime(end_raw.get("dateTime", ""))
            tz = start_raw.get("timeZone", "UTC")
        else:
            start = EventNormalizer._parse_date(start_raw.get("date", ""))
            end = EventNormalizer._parse_date(end_raw.get("date", ""))
            tz = "UTC"

        attendees = []
        for att in raw.get("attendees", []):
            attendees.append(
                EventAttendee(
                    email=att.get("email", ""),
                    name=att.get("displayName"),
                    response_status=att.get("responseStatus"),
                    is_organizer=att.get("organizer", False),
                )
            )

        reminders_list = []
        reminders_override = raw.get("reminders", {})
        for override in reminders_override.get("overrides", []):
            reminders_list.append(
                EventReminder(
                    method=override.get("method", "popup"),
                    minutes_before=override.get("minutes", 0),
                )
            )

        recurrence_rule = EventNormalizer._parse_rrule(raw.get("recurrence"))

        created_at = EventNormalizer._parse_datetime(raw["created"]) if "created" in raw else datetime.now(timezone.utc)
        updated_at = EventNormalizer._parse_datetime(raw["updated"]) if "updated" in raw else datetime.now(timezone.utc)

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

    @staticmethod
    def _denormalize_google_event(event: Event) -> dict[str, Any]:
        """Convert a unified `Event` to a Google Calendar API request body.

        Args:
            event: Unified event model.

        Returns:
            A dict suitable for the Google Calendar API.
        """
        body: dict[str, Any] = {
            "summary": event.title,
            "start": {
                "dateTime": EventNormalizer._format_datetime(event.start),
                "timeZone": event.timezone,
            },
            "end": {
                "dateTime": EventNormalizer._format_datetime(event.end),
                "timeZone": event.timezone,
            },
        }

        if event.description:
            body["description"] = event.description
        if event.location:
            body["location"] = event.location
        if event.attendees:
            body["attendees"] = [
                {"email": a.email, "displayName": a.name}
                for a in event.attendees
            ]
        if event.reminders:
            body["reminders"] = {
                "useDefault": False,
                "overrides": [
                    {"method": r.method, "minutes": r.minutes_before}
                    for r in event.reminders
                ],
            }
        if event.recurrence:
            body["recurrence"] = [EventNormalizer._build_rrule(event.recurrence)]
        if event.status:
            body["status"] = event.status

        return body

    # ------------------------------------------------------------------ #
    # Outlook Calendar normalization
    # ------------------------------------------------------------------ #

    @staticmethod
    def _normalize_outlook_event(raw: Any, calendar_id: str) -> Event:
        """Convert a raw Microsoft Graph event to a unified `Event`.

        Args:
            raw: Raw event object from the Microsoft Graph API (GraphEvent).
            calendar_id: Calendar ID the event belongs to.

        Returns:
            A unified `Event` model.
        """
        from msgraph.generated.models.event import Event as GraphEvent

        if not isinstance(raw, GraphEvent):
            raise TypeError(f"Expected GraphEvent, got {type(raw)}")

        start_raw = raw.start
        end_raw = raw.end

        if start_raw and start_raw.date_time:
            start = EventNormalizer._parse_outlook_datetime(start_raw.date_time, start_raw.time_zone)
            tz = start_raw.time_zone or "UTC"
        else:
            start = datetime.now(timezone.utc)
            tz = "UTC"

        if end_raw and end_raw.date_time:
            end = EventNormalizer._parse_outlook_datetime(end_raw.date_time, end_raw.time_zone)
        else:
            from datetime import timedelta
            end = start + timedelta(hours=1)

        attendees = []
        if raw.attendees:
            for att in raw.attendees:
                email_addr = att.email_address
                response = att.status
                attendees.append(
                    EventAttendee(
                        email=email_addr.address if email_addr else "",
                        name=email_addr.name if email_addr else None,
                        response_status=EventNormalizer._parse_outlook_response_type(response.response_type) if response else None,
                        is_organizer=False,
                    )
                )

        reminders_list = []
        if raw.reminders:
            for reminder in raw.reminders:
                if reminder.minutes_before_start is not None:
                    reminders_list.append(
                        EventReminder(
                            method="popup",
                            minutes_before=reminder.minutes_before_start,
                        )
                    )

        recurrence_rule = None
        if raw.recurrence:
            recurrence_rule = EventNormalizer._parse_outlook_recurrence(raw.recurrence)

        created_at = EventNormalizer._parse_outlook_datetime(raw.created_date_time.date_time) if raw.created_date_time else datetime.now(timezone.utc)
        updated_at = EventNormalizer._parse_outlook_datetime(raw.last_modified_date_time.date_time) if raw.last_modified_date_time else datetime.now(timezone.utc)

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
            status=EventNormalizer._parse_outlook_show_as(raw.show_as),
            created_at=created_at,
            updated_at=updated_at,
            etag=raw.e_tag,
            is_recurring_master=is_recurring_master,
            recurrence_id=recurrence_id,
            provider_metadata=provider_metadata if provider_metadata else None,
        )

    @staticmethod
    def _denormalize_outlook_event(event: Event) -> Any:
        """Convert a unified `Event` to a Microsoft Graph API event body.

        Args:
            event: Unified event model.

        Returns:
            A GraphEvent object suitable for the Microsoft Graph API.
        """
        from msgraph.generated.models.attendee import Attendee
        from msgraph.generated.models.attendee_type import AttendeeType
        from msgraph.generated.models.body_type import BodyType
        from msgraph.generated.models.date_time_time_zone import DateTimeTimeZone
        from msgraph.generated.models.email_address import EmailAddress
        from msgraph.generated.models.event import Event as GraphEvent
        from msgraph.generated.models.location import Location

        body = GraphEvent()
        body.subject = event.title
        body.start = DateTimeTimeZone(
            date_time=EventNormalizer._format_datetime(event.start),
            time_zone=event.timezone,
        )
        body.end = DateTimeTimeZone(
            date_time=EventNormalizer._format_datetime(event.end),
            time_zone=event.timezone,
        )

        if event.description:
            body.body_type = BodyType.HTML
            body.content = event.description

        if event.location:
            body.location = Location(display_name=event.location)

        if event.attendees:
            body.attendees = [
                Attendee(
                    email_address=EmailAddress(
                        address=a.email,
                        name=a.name,
                    ),
                    type=AttendeeType.REQUIRED,
                )
                for a in event.attendees
            ]

        if event.reminders:
            body.is_reminder_on = True

        if event.recurrence:
            body.recurrence = EventNormalizer._build_outlook_recurrence(event.recurrence)

        return body

    # ------------------------------------------------------------------ #
    # Shared utilities
    # ------------------------------------------------------------------ #

    @staticmethod
    def _format_datetime(dt: datetime) -> str:
        """Format a datetime as an ISO 8601 string.

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
        """Parse an ISO 8601 datetime string.

        Args:
            value: ISO 8601 string.

        Returns:
            Timezone-aware datetime.
        """
        if not value:
            return datetime.now(timezone.utc)
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    @staticmethod
    def _parse_date(value: str) -> datetime:
        """Parse a date string (YYYY-MM-DD) into a datetime.

        Args:
            value: Date string.

        Returns:
            Timezone-aware datetime at midnight UTC.
        """
        if not value:
            return datetime.now(timezone.utc)
        dt = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return dt

    @staticmethod
    def _parse_outlook_datetime(value: str | None, tz_name: str | None = None) -> datetime:
        """Parse a datetime string from the Microsoft Graph API.

        Args:
            value: Datetime string.
            tz_name: Optional timezone name (not used for conversion).

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

    @staticmethod
    def _parse_rrule(rrules: list[str] | None) -> RecurrenceRule | None:
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

    @staticmethod
    def _parse_outlook_response_type(response_type) -> str | None:
        """Map Microsoft Graph response type to unified status string.

        Args:
            response_type: ResponseType enum value.

        Returns:
            Unified response status string.
        """
        from msgraph.generated.models.response_type import ResponseType

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
    def _parse_outlook_show_as(show_as) -> str:
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

    @staticmethod
    def _parse_outlook_recurrence(recurrence: Any) -> RecurrenceRule | None:
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
                kwargs["until"] = EventNormalizer._parse_outlook_datetime(range_info.end_date)

        if "frequency" not in kwargs:
            return None

        return RecurrenceRule(**kwargs)

    @staticmethod
    def _build_outlook_recurrence(rule: RecurrenceRule) -> Any:
        """Build a PatternedRecurrence from a `RecurrenceRule` model.

        Args:
            rule: The recurrence rule model.

        Returns:
            A PatternedRecurrence object for the Microsoft Graph API.
        """
        from msgraph.generated.models.day_of_week import DayOfWeek
        from msgraph.generated.models.patterned_recurrence import PatternedRecurrence
        from msgraph.generated.models.recurrence_pattern import RecurrencePattern
        from msgraph.generated.models.recurrence_range import RecurrenceRange

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
