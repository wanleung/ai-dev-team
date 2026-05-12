"""Unit tests for the event normalizer implementation.

Tests cover all public methods of `EventNormalizer`:
- normalize_event() for Google and Outlook providers
- denormalize_event() for Google and Outlook providers
- Internal helpers (datetime parsing/formatting, RRULE parsing/building, Outlook enum mapping)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.services.event_normalizer import EventNormalizer
from src.models.calendar import (
    Event,
    EventAttendee,
    EventReminder,
    RecurrenceRule,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def normalizer() -> EventNormalizer:
    """Create an EventNormalizer instance."""
    return EventNormalizer()


@pytest.fixture
def now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture
def google_event_dict(now: datetime) -> dict[str, Any]:
    """A minimal Google Calendar event dict."""
    return {
        "id": "google-evt-001",
        "summary": "Team Standup",
        "description": "Daily sync",
        "location": "Zoom Room 1",
        "start": {"dateTime": now.isoformat(), "timeZone": "America/New_York"},
        "end": {"dateTime": (now + timedelta(hours=1)).isoformat(), "timeZone": "America/New_York"},
        "status": "confirmed",
        "created": (now - timedelta(days=7)).isoformat(),
        "updated": (now - timedelta(days=1)).isoformat(),
        "etag": '"google-etag-123"',
    }


@pytest.fixture
def google_event_with_attendees(now: datetime) -> dict[str, Any]:
    """Google event with attendees."""
    return {
        "id": "google-evt-002",
        "summary": "Planning Meeting",
        "start": {"dateTime": now.isoformat(), "timeZone": "UTC"},
        "end": {"dateTime": (now + timedelta(hours=2)).isoformat(), "timeZone": "UTC"},
        "status": "confirmed",
        "created": now.isoformat(),
        "updated": now.isoformat(),
        "attendees": [
            {"email": "alice@example.com", "displayName": "Alice", "responseStatus": "accepted", "organizer": True},
            {"email": "bob@example.com", "displayName": "Bob", "responseStatus": "needsAction"},
        ],
    }


@pytest.fixture
def google_event_with_reminders(now: datetime) -> dict[str, Any]:
    """Google event with reminder overrides."""
    return {
        "id": "google-evt-003",
        "summary": "Important Call",
        "start": {"dateTime": now.isoformat(), "timeZone": "UTC"},
        "end": {"dateTime": (now + timedelta(hours=1)).isoformat(), "timeZone": "UTC"},
        "status": "confirmed",
        "created": now.isoformat(),
        "updated": now.isoformat(),
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "email", "minutes": 60},
                {"method": "popup", "minutes": 10},
            ],
        },
    }


@pytest.fixture
def google_event_with_recurrence(now: datetime) -> dict[str, Any]:
    """Google event with recurrence rule."""
    return {
        "id": "google-evt-004",
        "summary": "Weekly Sync",
        "start": {"dateTime": now.isoformat(), "timeZone": "UTC"},
        "end": {"dateTime": (now + timedelta(hours=1)).isoformat(), "timeZone": "UTC"},
        "status": "confirmed",
        "created": now.isoformat(),
        "updated": now.isoformat(),
        "recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR;COUNT=10"],
    }


@pytest.fixture
def google_event_all_day(now: datetime) -> dict[str, Any]:
    """Google all-day event."""
    return {
        "id": "google-evt-005",
        "summary": "Company Holiday",
        "start": {"date": "2026-04-20"},
        "end": {"date": "2026-04-21"},
        "status": "confirmed",
        "created": now.isoformat(),
        "updated": now.isoformat(),
    }


@pytest.fixture
def google_recurring_instance(now: datetime) -> dict[str, Any]:
    """Google recurring event instance."""
    return {
        "id": "google-evt-006",
        "summary": "Weekly Sync (instance)",
        "start": {"dateTime": now.isoformat(), "timeZone": "UTC"},
        "end": {"dateTime": (now + timedelta(hours=1)).isoformat(), "timeZone": "UTC"},
        "status": "confirmed",
        "created": now.isoformat(),
        "updated": now.isoformat(),
        "recurringEventId": "master-event-id",
    }


@pytest.fixture
def mock_graph_event(now: datetime) -> MagicMock:
    """Create a mock Microsoft Graph Event object."""
    event = MagicMock()
    event.id = "outlook-evt-001"
    event.subject = "Team Standup"
    event.body = MagicMock()
    event.body.content = "Daily sync"
    event.location = MagicMock()
    event.location.display_name = "Teams Room 1"

    event.start = MagicMock()
    event.start.date_time = now.isoformat()
    event.start.time_zone = "America/New_York"

    event.end = MagicMock()
    event.end.date_time = (now + timedelta(hours=1)).isoformat()
    event.end.time_zone = "America/New_York"

    event.attendees = []
    event.reminders = []
    event.recurrence = None

    event.created_date_time = MagicMock()
    event.created_date_time.date_time = (now - timedelta(days=7)).isoformat()

    event.last_modified_date_time = MagicMock()
    event.last_modified_date_time.date_time = (now - timedelta(days=1)).isoformat()

    event.recurring_event_id = None
    event.show_as = "busy"
    event.e_tag = '"outlook-etag-123"'
    event.web_link = "https://outlook.live.com/calendar/0/event/evt-001"
    event.online_meeting_url = "https://teams.microsoft.com/meeting/123"

    return event


# ---------------------------------------------------------------------------
# normalize_event() dispatch tests
# ---------------------------------------------------------------------------


class TestNormalizeEventDispatch:
    """Tests for the normalize_event() dispatch method."""

    def test_normalize_google_event(
        self, normalizer: EventNormalizer, google_event_dict: dict[str, Any]
    ) -> None:
        event = normalizer.normalize_event("google", google_event_dict, "cal-001")
        assert event.id == "google-evt-001"
        assert event.calendar_id == "cal-001"

    def test_normalize_outlook_event(
        self, normalizer: EventNormalizer, mock_graph_event: MagicMock
    ) -> None:
        with patch("src.services.event_normalizer.EventNormalizer._normalize_outlook_event") as mock_norm:
            mock_norm.return_value = MagicMock()
            normalizer.normalize_event("outlook", mock_graph_event, "cal-001")
            mock_norm.assert_called_once_with(mock_graph_event, "cal-001")

    def test_normalize_unsupported_provider_raises(
        self, normalizer: EventNormalizer
    ) -> None:
        with pytest.raises(ValueError, match="Unsupported provider for normalization: yahoo"):
            normalizer.normalize_event("yahoo", {}, "cal-001")


# ---------------------------------------------------------------------------
# Google normalization tests
# ---------------------------------------------------------------------------


class TestNormalizeGoogleEvent:
    """Tests for _normalize_google_event()."""

    def test_basic_fields(
        self, normalizer: EventNormalizer, google_event_dict: dict[str, Any]
    ) -> None:
        event = normalizer._normalize_google_event(google_event_dict, "cal-001")
        assert event.id == "google-evt-001"
        assert event.calendar_id == "cal-001"
        assert event.title == "Team Standup"
        assert event.description == "Daily sync"
        assert event.location == "Zoom Room 1"
        assert event.status == "confirmed"
        assert event.etag == '"google-etag-123"'

    def test_datetime_fields(
        self, normalizer: EventNormalizer, google_event_dict: dict[str, Any], now: datetime
    ) -> None:
        event = normalizer._normalize_google_event(google_event_dict, "cal-001")
        assert event.start.tzinfo is not None
        assert event.end.tzinfo is not None
        assert event.timezone == "America/New_York"

    def test_created_updated_fields(
        self, normalizer: EventNormalizer, google_event_dict: dict[str, Any], now: datetime
    ) -> None:
        event = normalizer._normalize_google_event(google_event_dict, "cal-001")
        assert event.created_at.tzinfo is not None
        assert event.updated_at.tzinfo is not None

    def test_provider_metadata_preserved(
        self, normalizer: EventNormalizer, google_event_dict: dict[str, Any]
    ) -> None:
        event = normalizer._normalize_google_event(google_event_dict, "cal-001")
        assert event.provider_metadata is not None
        assert event.provider_metadata["id"] == "google-evt-001"

    def test_attendees_parsed(
        self, normalizer: EventNormalizer, google_event_with_attendees: dict[str, Any]
    ) -> None:
        event = normalizer._normalize_google_event(google_event_with_attendees, "cal-001")
        assert len(event.attendees) == 2
        assert event.attendees[0].email == "alice@example.com"
        assert event.attendees[0].name == "Alice"
        assert event.attendees[0].response_status == "accepted"
        assert event.attendees[0].is_organizer is True
        assert event.attendees[1].email == "bob@example.com"
        assert event.attendees[1].is_organizer is False

    def test_attendees_empty_when_missing(
        self, normalizer: EventNormalizer, google_event_dict: dict[str, Any]
    ) -> None:
        event = normalizer._normalize_google_event(google_event_dict, "cal-001")
        assert event.attendees == []

    def test_reminders_parsed(
        self, normalizer: EventNormalizer, google_event_with_reminders: dict[str, Any]
    ) -> None:
        event = normalizer._normalize_google_event(google_event_with_reminders, "cal-001")
        assert len(event.reminders) == 2
        assert event.reminders[0].method == "email"
        assert event.reminders[0].minutes_before == 60
        assert event.reminders[1].method == "popup"
        assert event.reminders[1].minutes_before == 10

    def test_reminders_empty_when_missing(
        self, normalizer: EventNormalizer, google_event_dict: dict[str, Any]
    ) -> None:
        event = normalizer._normalize_google_event(google_event_dict, "cal-001")
        assert event.reminders == []

    def test_recurrence_parsed(
        self, normalizer: EventNormalizer, google_event_with_recurrence: dict[str, Any]
    ) -> None:
        event = normalizer._normalize_google_event(google_event_with_recurrence, "cal-001")
        assert event.recurrence is not None
        assert event.recurrence.frequency == "weekly"
        assert event.recurrence.by_day == ["MO", "WE", "FR"]
        assert event.recurrence.count == 10
        assert event.is_recurring_master is True

    def test_all_day_event(
        self, normalizer: EventNormalizer, google_event_all_day: dict[str, Any]
    ) -> None:
        event = normalizer._normalize_google_event(google_event_all_day, "cal-001")
        assert event.start.tzinfo is not None
        assert event.start.year == 2026
        assert event.start.month == 4
        assert event.start.day == 20
        assert event.timezone == "UTC"

    def test_recurring_instance(
        self, normalizer: EventNormalizer, google_recurring_instance: dict[str, Any]
    ) -> None:
        event = normalizer._normalize_google_event(google_recurring_instance, "cal-001")
        assert event.recurrence_id == "master-event-id"
        assert event.is_recurring_master is False

    def test_missing_summary_defaults_to_empty(
        self, normalizer: EventNormalizer, now: datetime
    ) -> None:
        raw = {
            "id": "minimal",
            "start": {"dateTime": now.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": (now + timedelta(hours=1)).isoformat(), "timeZone": "UTC"},
            "created": now.isoformat(),
            "updated": now.isoformat(),
        }
        event = normalizer._normalize_google_event(raw, "cal-001")
        assert event.title == ""

    def test_missing_created_updated_defaults_to_now(
        self, normalizer: EventNormalizer, now: datetime
    ) -> None:
        raw = {
            "id": "no-dates",
            "summary": "No dates",
            "start": {"dateTime": now.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": (now + timedelta(hours=1)).isoformat(), "timeZone": "UTC"},
        }
        event = normalizer._normalize_google_event(raw, "cal-001")
        assert event.created_at.tzinfo is not None
        assert event.updated_at.tzinfo is not None


# ---------------------------------------------------------------------------
# Google denormalization tests
# ---------------------------------------------------------------------------


class TestDenormalizeGoogleEvent:
    """Tests for _denormalize_google_event()."""

    def test_basic_fields(self, normalizer: EventNormalizer, now: datetime) -> None:
        event = Event(
            id="evt-001",
            calendar_id="cal-001",
            title="Test Meeting",
            description="Test description",
            location="Room A",
            start=now,
            end=now + timedelta(hours=1),
            timezone="UTC",
            status="confirmed",
            created_at=now,
            updated_at=now,
        )
        body = normalizer._denormalize_google_event(event)
        assert body["summary"] == "Test Meeting"
        assert body["description"] == "Test description"
        assert body["location"] == "Room A"

    def test_datetime_fields(self, normalizer: EventNormalizer, now: datetime) -> None:
        event = Event(
            id="evt-001",
            calendar_id="cal-001",
            title="Test",
            start=now,
            end=now + timedelta(hours=1),
            timezone="America/New_York",
            status="confirmed",
            created_at=now,
            updated_at=now,
        )
        body = normalizer._denormalize_google_event(event)
        assert body["start"]["timeZone"] == "America/New_York"
        assert body["end"]["timeZone"] == "America/New_York"
        assert "dateTime" in body["start"]
        assert "dateTime" in body["end"]

    def test_attendees_converted(self, normalizer: EventNormalizer, now: datetime) -> None:
        event = Event(
            id="evt-001",
            calendar_id="cal-001",
            title="Test",
            start=now,
            end=now + timedelta(hours=1),
            timezone="UTC",
            status="confirmed",
            created_at=now,
            updated_at=now,
            attendees=[
                EventAttendee(email="alice@example.com", name="Alice"),
                EventAttendee(email="bob@example.com"),
            ],
        )
        body = normalizer._denormalize_google_event(event)
        assert len(body["attendees"]) == 2
        assert body["attendees"][0]["email"] == "alice@example.com"
        assert body["attendees"][0]["displayName"] == "Alice"
        assert body["attendees"][1]["displayName"] is None

    def test_reminders_converted(self, normalizer: EventNormalizer, now: datetime) -> None:
        event = Event(
            id="evt-001",
            calendar_id="cal-001",
            title="Test",
            start=now,
            end=now + timedelta(hours=1),
            timezone="UTC",
            status="confirmed",
            created_at=now,
            updated_at=now,
            reminders=[
                EventReminder(method="email", minutes_before=30),
                EventReminder(method="popup", minutes_before=5),
            ],
        )
        body = normalizer._denormalize_google_event(event)
        assert body["reminders"]["useDefault"] is False
        assert len(body["reminders"]["overrides"]) == 2
        assert body["reminders"]["overrides"][0]["method"] == "email"
        assert body["reminders"]["overrides"][0]["minutes"] == 30

    def test_recurrence_converted(self, normalizer: EventNormalizer, now: datetime) -> None:
        event = Event(
            id="evt-001",
            calendar_id="cal-001",
            title="Test",
            start=now,
            end=now + timedelta(hours=1),
            timezone="UTC",
            status="confirmed",
            created_at=now,
            updated_at=now,
            recurrence=RecurrenceRule(
                frequency="weekly",
                interval=2,
                by_day=["MO", "FR"],
            ),
        )
        body = normalizer._denormalize_google_event(event)
        assert body["recurrence"] == ["RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,FR"]

    def test_status_included(self, normalizer: EventNormalizer, now: datetime) -> None:
        event = Event(
            id="evt-001",
            calendar_id="cal-001",
            title="Test",
            start=now,
            end=now + timedelta(hours=1),
            timezone="UTC",
            status="cancelled",
            created_at=now,
            updated_at=now,
        )
        body = normalizer._denormalize_google_event(event)
        assert body["status"] == "cancelled"

    def test_optional_fields_omitted_when_none(self, normalizer: EventNormalizer, now: datetime) -> None:
        event = Event(
            id="evt-001",
            calendar_id="cal-001",
            title="Minimal",
            start=now,
            end=now + timedelta(hours=1),
            timezone="UTC",
            status="confirmed",
            created_at=now,
            updated_at=now,
        )
        body = normalizer._denormalize_google_event(event)
        assert "description" not in body
        assert "location" not in body
        assert "attendees" not in body
        assert "reminders" not in body
        assert "recurrence" not in body


# ---------------------------------------------------------------------------
# Outlook normalization tests
# ---------------------------------------------------------------------------


class TestNormalizeOutlookEvent:
    """Tests for _normalize_outlook_event()."""

    @pytest.fixture(autouse=True)
    def patch_graph_event_class(self):
        """Patch GraphEvent to MagicMock so the availability guard passes.

        MagicMock instances (used as mock_graph_event) satisfy
        isinstance(mock, MagicMock), so the type check also passes.
        """
        with patch("src.services.event_normalizer.GraphEvent", MagicMock):
            yield

    def test_basic_fields(
        self, normalizer: EventNormalizer, mock_graph_event: MagicMock
    ) -> None:
        event = normalizer._normalize_outlook_event(mock_graph_event, "cal-001")
        assert event.id == "outlook-evt-001"
        assert event.calendar_id == "cal-001"
        assert event.title == "Team Standup"
        assert event.description == "Daily sync"
        assert event.location == "Teams Room 1"

    def test_datetime_fields(
        self, normalizer: EventNormalizer, mock_graph_event: MagicMock
    ) -> None:
        event = normalizer._normalize_outlook_event(mock_graph_event, "cal-001")
        assert event.start.tzinfo is not None
        assert event.end.tzinfo is not None
        assert event.timezone == "America/New_York"

    def test_provider_metadata(
        self, normalizer: EventNormalizer, mock_graph_event: MagicMock
    ) -> None:
        event = normalizer._normalize_outlook_event(mock_graph_event, "cal-001")
        assert event.provider_metadata is not None
        assert event.provider_metadata["id"] == "outlook-evt-001"
        assert "web_link" in event.provider_metadata
        assert "online_meeting_url" in event.provider_metadata

    def test_attendees_parsed(
        self, normalizer: EventNormalizer, mock_graph_event: MagicMock, now: datetime
    ) -> None:
        email_addr = MagicMock()
        email_addr.address = "alice@example.com"
        email_addr.name = "Alice"

        response = MagicMock()
        response.response_type = MagicMock()

        attendee = MagicMock()
        attendee.email_address = email_addr
        attendee.status = response

        mock_graph_event.attendees = [attendee]

        with patch("src.services.event_normalizer.EventNormalizer._parse_outlook_response_type", return_value="accepted"):
            event = normalizer._normalize_outlook_event(mock_graph_event, "cal-001")

        assert len(event.attendees) == 1
        assert event.attendees[0].email == "alice@example.com"
        assert event.attendees[0].name == "Alice"

    def test_empty_attendees_when_none(
        self, normalizer: EventNormalizer, mock_graph_event: MagicMock
    ) -> None:
        mock_graph_event.attendees = None
        event = normalizer._normalize_outlook_event(mock_graph_event, "cal-001")
        assert event.attendees == []

    def test_reminders_parsed(
        self, normalizer: EventNormalizer, mock_graph_event: MagicMock
    ) -> None:
        reminder = MagicMock()
        reminder.minutes_before_start = 15
        mock_graph_event.reminders = [reminder]

        event = normalizer._normalize_outlook_event(mock_graph_event, "cal-001")
        assert len(event.reminders) == 1
        assert event.reminders[0].method == "popup"
        assert event.reminders[0].minutes_before == 15

    def test_reminders_empty_when_none(
        self, normalizer: EventNormalizer, mock_graph_event: MagicMock
    ) -> None:
        mock_graph_event.reminders = None
        event = normalizer._normalize_outlook_event(mock_graph_event, "cal-001")
        assert event.reminders == []

    def test_recurrence_parsed(
        self, normalizer: EventNormalizer, mock_graph_event: MagicMock
    ) -> None:
        pattern = MagicMock()
        pattern.type = "weekly"
        pattern.interval = 1
        pattern.days_of_week = [MagicMock(value="MO"), MagicMock(value="WE")]
        pattern.day_of_month = None

        range_info = MagicMock()
        range_info.number_of_occurrences = 10
        range_info.end_date = None

        recurrence = MagicMock()
        recurrence.pattern = pattern
        recurrence.range = range_info

        mock_graph_event.recurrence = recurrence

        event = normalizer._normalize_outlook_event(mock_graph_event, "cal-001")
        assert event.recurrence is not None
        assert event.recurrence.frequency == "weekly"
        assert event.recurrence.interval == 1
        assert event.recurrence.count == 10
        assert event.is_recurring_master is True

    def test_recurring_instance(
        self, normalizer: EventNormalizer, mock_graph_event: MagicMock
    ) -> None:
        mock_graph_event.recurring_event_id = "master-outlook-id"
        mock_graph_event.recurrence = None

        event = normalizer._normalize_outlook_event(mock_graph_event, "cal-001")
        assert event.recurrence_id == "master-outlook-id"
        assert event.is_recurring_master is False

    def test_wrong_type_raises(
        self, normalizer: EventNormalizer
    ) -> None:
        # Create a proper class mock for isinstance to work
        class MockGraphEvent:
            pass
        
        with patch("src.services.event_normalizer.GraphEvent", MockGraphEvent):
            with pytest.raises(TypeError, match="Expected GraphEvent"):
                normalizer._normalize_outlook_event({"not": "a graph event"}, "cal-001")

    def test_missing_start_defaults_to_now(
        self, normalizer: EventNormalizer, mock_graph_event: MagicMock
    ) -> None:
        mock_graph_event.start = None
        event = normalizer._normalize_outlook_event(mock_graph_event, "cal-001")
        assert event.start.tzinfo is not None

    def test_missing_end_defaults_to_start_plus_one_hour(
        self, normalizer: EventNormalizer, mock_graph_event: MagicMock
    ) -> None:
        mock_graph_event.end = None
        event = normalizer._normalize_outlook_event(mock_graph_event, "cal-001")
        assert event.end >= event.start

    def test_etag_preserved(
        self, normalizer: EventNormalizer, mock_graph_event: MagicMock
    ) -> None:
        event = normalizer._normalize_outlook_event(mock_graph_event, "cal-001")
        assert event.etag == '"outlook-etag-123"'


# ---------------------------------------------------------------------------
# Outlook denormalization tests
# ---------------------------------------------------------------------------


class TestDenormalizeOutlookEvent:
    """Tests for _denormalize_outlook_event()."""

    @pytest.fixture(autouse=True)
    def mock_msgraph_classes(self):
        """Auto-patch all msgraph classes used by _denormalize_outlook_event.
        
        Only patches constructor classes, not enums like BodyType and AttendeeType.
        """
        with patch("src.services.event_normalizer.GraphEvent", return_value=MagicMock()):
            with patch("src.services.event_normalizer.DateTimeTimeZone", return_value=MagicMock()):
                with patch("src.services.event_normalizer.Location", return_value=MagicMock()):
                    with patch("src.services.event_normalizer.Attendee", return_value=MagicMock()):
                        with patch("src.services.event_normalizer.EmailAddress", return_value=MagicMock()):
                            with patch("src.services.event_normalizer.PatternedRecurrence", return_value=MagicMock()):
                                with patch("src.services.event_normalizer.RecurrencePattern", return_value=MagicMock()):
                                    with patch("src.services.event_normalizer.RecurrenceRange", return_value=MagicMock()):
                                        # Don't patch BodyType, AttendeeType, DayOfWeek - they're enums (attribute access only)
                                        # Also need to patch them as None → MagicMock for attribute access
                                        mock_body_type = MagicMock()
                                        mock_body_type.HTML = MagicMock()
                                        mock_attendee_type = MagicMock()
                                        mock_attendee_type.REQUIRED = MagicMock()
                                        mock_day_of_week = MagicMock()
                                        with patch("src.services.event_normalizer.BodyType", mock_body_type):
                                            with patch("src.services.event_normalizer.AttendeeType", mock_attendee_type):
                                                with patch("src.services.event_normalizer.DayOfWeek", mock_day_of_week):
                                                    yield

    def test_basic_fields(self, normalizer: EventNormalizer, now: datetime) -> None:
        event = Event(
            id="evt-001",
            calendar_id="cal-001",
            title="Test Meeting",
            description="Test description",
            location="Room A",
            start=now,
            end=now + timedelta(hours=1),
            timezone="UTC",
            status="confirmed",
            created_at=now,
            updated_at=now,
        )
        with patch("src.services.event_normalizer.GraphEvent", return_value=MagicMock()) as mock_cls:
            normalizer._denormalize_outlook_event(event)
            # Verify the GraphEvent was instantiated
            mock_cls.assert_called_once()

    def test_subject_set(self, normalizer: EventNormalizer, now: datetime) -> None:
        event = Event(
            id="evt-001",
            calendar_id="cal-001",
            title="Planning Session",
            start=now,
            end=now + timedelta(hours=1),
            timezone="UTC",
            status="confirmed",
            created_at=now,
            updated_at=now,
        )

        mock_body = MagicMock()
        with patch("src.services.event_normalizer.GraphEvent", return_value=mock_body):
            normalizer._denormalize_outlook_event(event)
            assert mock_body.subject == "Planning Session"

    def test_datetime_timezone_set(self, normalizer: EventNormalizer, now: datetime) -> None:
        event = Event(
            id="evt-001",
            calendar_id="cal-001",
            title="Test",
            start=now,
            end=now + timedelta(hours=1),
            timezone="America/New_York",
            status="confirmed",
            created_at=now,
            updated_at=now,
        )

        mock_body = MagicMock()
        mock_dt_tz = MagicMock()
        with patch("src.services.event_normalizer.GraphEvent", return_value=mock_body):
            with patch("src.services.event_normalizer.DateTimeTimeZone", return_value=mock_dt_tz):
                normalizer._denormalize_outlook_event(event)
                assert mock_body.start == mock_dt_tz
                assert mock_body.end == mock_dt_tz

    def test_description_sets_body_type(
        self, normalizer: EventNormalizer, now: datetime
    ) -> None:
        event = Event(
            id="evt-001",
            calendar_id="cal-001",
            title="Test",
            description="Important notes",
            start=now,
            end=now + timedelta(hours=1),
            timezone="UTC",
            status="confirmed",
            created_at=now,
            updated_at=now,
        )

        mock_body = MagicMock()
        with patch("src.services.event_normalizer.GraphEvent", return_value=mock_body):
            with patch("src.services.event_normalizer.BodyType") as mock_body_type:
                normalizer._denormalize_outlook_event(event)
                # Verify body_type was set to BodyType.HTML
                assert mock_body.body_type == mock_body_type.HTML

    def test_location_set(self, normalizer: EventNormalizer, now: datetime) -> None:
        event = Event(
            id="evt-001",
            calendar_id="cal-001",
            title="Test",
            location="Conference Room B",
            start=now,
            end=now + timedelta(hours=1),
            timezone="UTC",
            status="confirmed",
            created_at=now,
            updated_at=now,
        )

        mock_body = MagicMock()
        mock_location = MagicMock()
        with patch("src.services.event_normalizer.GraphEvent", return_value=mock_body):
            with patch("src.services.event_normalizer.Location", return_value=mock_location):
                normalizer._denormalize_outlook_event(event)
                assert mock_body.location == mock_location

    def test_attendees_converted(self, normalizer: EventNormalizer, now: datetime) -> None:
        event = Event(
            id="evt-001",
            calendar_id="cal-001",
            title="Test",
            start=now,
            end=now + timedelta(hours=1),
            timezone="UTC",
            status="confirmed",
            created_at=now,
            updated_at=now,
            attendees=[
                EventAttendee(email="alice@example.com", name="Alice"),
                EventAttendee(email="bob@example.com"),
            ],
        )

        mock_body = MagicMock()
        mock_attendee = MagicMock()
        with patch("src.services.event_normalizer.GraphEvent", return_value=mock_body):
            with patch("src.services.event_normalizer.Attendee", return_value=mock_attendee):
                with patch("src.services.event_normalizer.EmailAddress"):
                    with patch("src.services.event_normalizer.AttendeeType"):
                        normalizer._denormalize_outlook_event(event)
                        assert mock_body.attendees is not None

    def test_reminders_enable_flag(self, normalizer: EventNormalizer, now: datetime) -> None:
        event = Event(
            id="evt-001",
            calendar_id="cal-001",
            title="Test",
            start=now,
            end=now + timedelta(hours=1),
            timezone="UTC",
            status="confirmed",
            created_at=now,
            updated_at=now,
            reminders=[EventReminder(method="popup", minutes_before=10)],
        )

        mock_body = MagicMock()
        with patch("src.services.event_normalizer.GraphEvent", return_value=mock_body):
            normalizer._denormalize_outlook_event(event)
            assert mock_body.is_reminder_on is True

    def test_recurrence_converted(self, normalizer: EventNormalizer, now: datetime) -> None:
        event = Event(
            id="evt-001",
            calendar_id="cal-001",
            title="Test",
            start=now,
            end=now + timedelta(hours=1),
            timezone="UTC",
            status="confirmed",
            created_at=now,
            updated_at=now,
            recurrence=RecurrenceRule(
                frequency="weekly",
                by_day=["MO"],
            ),
        )

        mock_body = MagicMock()
        mock_recurrence = MagicMock()
        with patch("src.services.event_normalizer.GraphEvent", return_value=mock_body):
            with patch("src.services.event_normalizer.EventNormalizer._build_outlook_recurrence", return_value=mock_recurrence):
                normalizer._denormalize_outlook_event(event)
                assert mock_body.recurrence == mock_recurrence


# ---------------------------------------------------------------------------
# Shared utility tests
# ---------------------------------------------------------------------------


class TestFormatDatetime:
    """Tests for _format_datetime()."""

    def test_aware_datetime(self) -> None:
        dt = datetime(2026, 4, 20, 12, 0, 0, tzinfo=timezone.utc)
        result = EventNormalizer._format_datetime(dt)
        assert "2026-04-20" in result
        assert "+00:00" in result

    def test_naive_datetime_gets_utc(self) -> None:
        dt = datetime(2026, 4, 20, 12, 0, 0)
        result = EventNormalizer._format_datetime(dt)
        assert "2026-04-20" in result

    def test_non_utc_timezone(self) -> None:
        tz = timezone(timedelta(hours=-5))
        dt = datetime(2026, 4, 20, 7, 0, 0, tzinfo=tz)
        result = EventNormalizer._format_datetime(dt)
        assert "-05:00" in result


class TestParseDatetime:
    """Tests for _parse_datetime()."""

    def test_aware_datetime(self) -> None:
        result = EventNormalizer._parse_datetime("2026-04-20T12:00:00+00:00")
        assert result.tzinfo is not None
        assert result.year == 2026
        assert result.month == 4
        assert result.day == 20

    def test_naive_datetime_gets_utc(self) -> None:
        result = EventNormalizer._parse_datetime("2026-04-20T12:00:00")
        assert result.tzinfo is not None

    def test_empty_string_returns_now(self) -> None:
        result = EventNormalizer._parse_datetime("")
        assert result.tzinfo is not None

    def test_none_returns_now(self) -> None:
        # Note: the method expects a string, but we test the empty path
        result = EventNormalizer._parse_datetime("")
        assert result.tzinfo is not None


class TestParseDate:
    """Tests for _parse_date()."""

    def test_valid_date(self) -> None:
        result = EventNormalizer._parse_date("2026-04-20")
        assert result.year == 2026
        assert result.month == 4
        assert result.day == 20
        assert result.tzinfo is not None

    def test_empty_string_returns_now(self) -> None:
        result = EventNormalizer._parse_date("")
        assert result.tzinfo is not None


class TestParseOutlookDatetime:
    """Tests for _parse_outlook_datetime()."""

    def test_valid_iso_datetime(self) -> None:
        result = EventNormalizer._parse_outlook_datetime("2026-04-20T12:00:00+00:00")
        assert result.tzinfo is not None
        assert result.year == 2026

    def test_naive_datetime_gets_utc(self) -> None:
        result = EventNormalizer._parse_outlook_datetime("2026-04-20T12:00:00")
        assert result.tzinfo is not None

    def test_fallback_format(self) -> None:
        result = EventNormalizer._parse_outlook_datetime("2026-04-20T12:00:00")
        assert result.year == 2026
        assert result.month == 4

    def test_none_returns_now(self) -> None:
        result = EventNormalizer._parse_outlook_datetime(None)
        assert result.tzinfo is not None

    def test_timezone_name_ignored(self) -> None:
        result = EventNormalizer._parse_outlook_datetime("2026-04-20T12:00:00", "Eastern Standard Time")
        assert result.tzinfo is not None


# ---------------------------------------------------------------------------
# RRULE parsing/building tests
# ---------------------------------------------------------------------------


class TestParseRrule:
    """Tests for _parse_rrule()."""

    def test_simple_weekly(self) -> None:
        result = EventNormalizer._parse_rrule(["RRULE:FREQ=WEEKLY"])
        assert result is not None
        assert result.frequency == "weekly"
        assert result.interval == 1

    def test_with_by_day(self) -> None:
        result = EventNormalizer._parse_rrule(["RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR"])
        assert result is not None
        assert result.by_day == ["MO", "WE", "FR"]

    def test_with_count(self) -> None:
        result = EventNormalizer._parse_rrule(["RRULE:FREQ=DAILY;COUNT=10"])
        assert result is not None
        assert result.count == 10

    def test_with_until(self) -> None:
        result = EventNormalizer._parse_rrule(["RRULE:FREQ=MONTHLY;UNTIL=20261231T235959Z"])
        assert result is not None
        assert result.until is not None
        assert result.until.year == 2026
        assert result.until.month == 12

    def test_with_by_month_day(self) -> None:
        result = EventNormalizer._parse_rrule(["RRULE:FREQ=MONTHLY;BYMONTHDAY=1,15"])
        assert result is not None
        assert result.by_month_day == [1, 15]

    def test_complex_rrule(self) -> None:
        result = EventNormalizer._parse_rrule(["RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,FR;COUNT=20"])
        assert result is not None
        assert result.frequency == "weekly"
        assert result.interval == 2
        assert result.by_day == ["MO", "FR"]
        assert result.count == 20

    def test_none_returns_none(self) -> None:
        assert EventNormalizer._parse_rrule(None) is None

    def test_empty_list_returns_none(self) -> None:
        assert EventNormalizer._parse_rrule([]) is None

    def test_missing_rrule_prefix_returns_none(self) -> None:
        assert EventNormalizer._parse_rrule(["FREQ=WEEKLY"]) is None

    def test_missing_frequency_returns_none(self) -> None:
        assert EventNormalizer._parse_rrule(["RRULE:BYDAY=MO"]) is None


class TestBuildRrule:
    """Tests for _build_rrule()."""

    def test_simple_weekly(self) -> None:
        rule = RecurrenceRule(frequency="weekly")
        result = EventNormalizer._build_rrule(rule)
        assert result == "RRULE:FREQ=WEEKLY"

    def test_with_interval(self) -> None:
        rule = RecurrenceRule(frequency="weekly", interval=2)
        result = EventNormalizer._build_rrule(rule)
        assert "FREQ=WEEKLY" in result
        assert "INTERVAL=2" in result

    def test_with_count(self) -> None:
        rule = RecurrenceRule(frequency="daily", count=10)
        result = EventNormalizer._build_rrule(rule)
        assert "FREQ=DAILY" in result
        assert "COUNT=10" in result

    def test_with_until(self) -> None:
        until = datetime(2026, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
        rule = RecurrenceRule(frequency="monthly", until=until)
        result = EventNormalizer._build_rrule(rule)
        assert "FREQ=MONTHLY" in result
        assert "UNTIL=20261231T235959Z" in result

    def test_with_by_day(self) -> None:
        rule = RecurrenceRule(frequency="weekly", by_day=["MO", "WE", "FR"])
        result = EventNormalizer._build_rrule(rule)
        assert "BYDAY=MO,WE,FR" in result

    def test_with_by_month_day(self) -> None:
        rule = RecurrenceRule(frequency="monthly", by_month_day=[1, 15])
        result = EventNormalizer._build_rrule(rule)
        assert "BYMONTHDAY=1,15" in result

    def test_complex_rrule(self) -> None:
        rule = RecurrenceRule(
            frequency="weekly",
            interval=2,
            count=20,
            by_day=["MO", "FR"],
        )
        result = EventNormalizer._build_rrule(rule)
        assert "FREQ=WEEKLY" in result
        assert "INTERVAL=2" in result
        assert "COUNT=20" in result
        assert "BYDAY=MO,FR" in result

    def test_interval_one_omitted(self) -> None:
        rule = RecurrenceRule(frequency="weekly", interval=1)
        result = EventNormalizer._build_rrule(rule)
        assert "INTERVAL" not in result


# ---------------------------------------------------------------------------
# Outlook enum mapping tests
# ---------------------------------------------------------------------------


class TestParseOutlookResponseType:
    """Tests for _parse_outlook_response_type()."""

    def test_accepted(self) -> None:
        with patch("src.services.event_normalizer.ResponseType") as mock_rt:
            mock_rt.ACCEPTED = "accepted_enum"
            result = EventNormalizer._parse_outlook_response_type("accepted_enum")
            assert result == "accepted"

    def test_declined(self) -> None:
        with patch("src.services.event_normalizer.ResponseType") as mock_rt:
            mock_rt.DECLINED = "declined_enum"
            result = EventNormalizer._parse_outlook_response_type("declined_enum")
            assert result == "declined"

    def test_tentative(self) -> None:
        with patch("src.services.event_normalizer.ResponseType") as mock_rt:
            mock_rt.TENTATIVE = "tentative_enum"
            result = EventNormalizer._parse_outlook_response_type("tentative_enum")
            assert result == "tentative"

    def test_not_responded(self) -> None:
        with patch("src.services.event_normalizer.ResponseType") as mock_rt:
            mock_rt.NOT_RESPONDED = "not_responded_enum"
            result = EventNormalizer._parse_outlook_response_type("not_responded_enum")
            assert result == "needsAction"

    def test_none_returns_none(self) -> None:
        with patch("src.services.event_normalizer.ResponseType") as mock_rt:
            mock_rt.NONE = "none_enum"
            mock_rt.ORGANIZER = "organizer_enum"
            result = EventNormalizer._parse_outlook_response_type("none_enum")
            assert result is None

    def test_organizer_returns_none(self) -> None:
        with patch("src.services.event_normalizer.ResponseType") as mock_rt:
            mock_rt.ORGANIZER = "organizer_enum"
            result = EventNormalizer._parse_outlook_response_type("organizer_enum")
            assert result is None

    def test_unknown_returns_none(self) -> None:
        with patch("src.services.event_normalizer.ResponseType") as mock_rt:
            mock_rt.NONE = "none_enum"
            mock_rt.ORGANIZER = "organizer_enum"
            mock_rt.ACCEPTED = "accepted_enum"
            mock_rt.TENTATIVE = "tentative_enum"
            mock_rt.DECLINED = "declined_enum"
            mock_rt.NOT_RESPONDED = "not_responded_enum"
            result = EventNormalizer._parse_outlook_response_type("unknown_enum")
            assert result is None


class TestParseOutlookShowAs:
    """Tests for _parse_outlook_show_as()."""

    def test_free_returns_confirmed(self) -> None:
        result = EventNormalizer._parse_outlook_show_as("free")
        assert result == "confirmed"

    def test_busy_returns_confirmed(self) -> None:
        result = EventNormalizer._parse_outlook_show_as("busy")
        assert result == "confirmed"

    def test_tentative_returns_tentative(self) -> None:
        result = EventNormalizer._parse_outlook_show_as("tentative")
        assert result == "tentative"

    def test_oof_returns_cancelled(self) -> None:
        result = EventNormalizer._parse_outlook_show_as("oof")
        assert result == "cancelled"

    def test_out_of_office_returns_cancelled(self) -> None:
        result = EventNormalizer._parse_outlook_show_as("outOfOffice")
        assert result == "cancelled"

    def test_none_returns_confirmed(self) -> None:
        result = EventNormalizer._parse_outlook_show_as(None)
        assert result == "confirmed"

    def test_unknown_returns_confirmed(self) -> None:
        result = EventNormalizer._parse_outlook_show_as("unknown")
        assert result == "confirmed"


# ---------------------------------------------------------------------------
# Outlook recurrence parsing/building tests
# ---------------------------------------------------------------------------


class TestParseOutlookRecurrence:
    """Tests for _parse_outlook_recurrence()."""

    def test_weekly_pattern(self) -> None:
        pattern = MagicMock()
        pattern.type = "weekly"
        pattern.interval = 1
        pattern.days_of_week = [MagicMock(value="MO"), MagicMock(value="WE")]
        pattern.day_of_month = None

        range_info = MagicMock()
        range_info.number_of_occurrences = None
        range_info.end_date = None

        recurrence = MagicMock()
        recurrence.pattern = pattern
        recurrence.range = range_info

        result = EventNormalizer._parse_outlook_recurrence(recurrence)
        assert result is not None
        assert result.frequency == "weekly"
        assert result.interval == 1

    def test_absolute_monthly(self) -> None:
        pattern = MagicMock()
        pattern.type = "absoluteMonthly"
        pattern.interval = 1
        pattern.days_of_week = []
        pattern.day_of_month = 15

        range_info = MagicMock()
        range_info.number_of_occurrences = 12
        range_info.end_date = None

        recurrence = MagicMock()
        recurrence.pattern = pattern
        recurrence.range = range_info

        result = EventNormalizer._parse_outlook_recurrence(recurrence)
        assert result is not None
        assert result.frequency == "monthly"
        assert result.by_month_day == [15]
        assert result.count == 12

    def test_absolute_yearly(self) -> None:
        pattern = MagicMock()
        pattern.type = "absoluteYearly"
        pattern.interval = 1
        pattern.days_of_week = []
        pattern.day_of_month = None

        range_info = MagicMock()
        range_info.number_of_occurrences = None
        range_info.end_date = "2027-01-01"

        recurrence = MagicMock()
        recurrence.pattern = pattern
        recurrence.range = range_info

        result = EventNormalizer._parse_outlook_recurrence(recurrence)
        assert result is not None
        assert result.frequency == "yearly"
        assert result.until is not None

    def test_relative_monthly(self) -> None:
        pattern = MagicMock()
        pattern.type = "relativeMonthly"
        pattern.interval = 1
        pattern.days_of_week = [MagicMock(value="MO")]
        pattern.day_of_month = None

        range_info = MagicMock()
        range_info.number_of_occurrences = None
        range_info.end_date = None

        recurrence = MagicMock()
        recurrence.pattern = pattern
        recurrence.range = range_info

        result = EventNormalizer._parse_outlook_recurrence(recurrence)
        assert result is not None
        assert result.frequency == "monthly"
        assert result.by_day == ["MO"]

    def test_relative_yearly(self) -> None:
        pattern = MagicMock()
        pattern.type = "relativeYearly"
        pattern.interval = 1
        pattern.days_of_week = [MagicMock(value="MO")]
        pattern.day_of_month = None

        range_info = MagicMock()
        range_info.number_of_occurrences = None
        range_info.end_date = None

        recurrence = MagicMock()
        recurrence.pattern = pattern
        recurrence.range = range_info

        result = EventNormalizer._parse_outlook_recurrence(recurrence)
        assert result is not None
        assert result.frequency == "yearly"

    def test_none_recurrence_returns_none(self) -> None:
        result = EventNormalizer._parse_outlook_recurrence(None)
        assert result is None

    def test_no_pattern_returns_none(self) -> None:
        recurrence = MagicMock()
        recurrence.pattern = None
        result = EventNormalizer._parse_outlook_recurrence(recurrence)
        assert result is None

    def test_unknown_frequency_defaults_to_weekly(self) -> None:
        pattern = MagicMock()
        pattern.type = "unknown"
        pattern.interval = 1
        pattern.days_of_week = []
        pattern.day_of_month = None

        range_info = MagicMock()
        range_info.number_of_occurrences = None
        range_info.end_date = None

        recurrence = MagicMock()
        recurrence.pattern = pattern
        recurrence.range = range_info

        result = EventNormalizer._parse_outlook_recurrence(recurrence)
        assert result is not None
        assert result.frequency == "weekly"


class TestBuildOutlookRecurrence:
    """Tests for _build_outlook_recurrence()."""

    def test_weekly(self) -> None:
        rule = RecurrenceRule(frequency="weekly", by_day=["MO"])
        with patch("src.services.event_normalizer.PatternedRecurrence") as mock_cls:
            with patch("src.services.event_normalizer.RecurrencePattern") as mock_pattern:
                with patch("src.services.event_normalizer.RecurrenceRange") as mock_range:
                    with patch("src.services.event_normalizer.DayOfWeek") as mock_day:
                        mock_day.MONDAY = "monday"
                        EventNormalizer._build_outlook_recurrence(rule)
                        mock_cls.assert_called_once()

    def test_monthly(self) -> None:
        rule = RecurrenceRule(frequency="monthly", by_month_day=[15])
        with patch("src.services.event_normalizer.PatternedRecurrence") as mock_cls:
            with patch("src.services.event_normalizer.RecurrencePattern") as mock_pattern:
                with patch("src.services.event_normalizer.RecurrenceRange") as mock_range:
                    with patch("src.services.event_normalizer.DayOfWeek"):
                        EventNormalizer._build_outlook_recurrence(rule)
                        mock_pattern_instance = mock_pattern.return_value
                        assert mock_pattern_instance.type == "absoluteMonthly"
                        assert mock_pattern_instance.day_of_month == 15

    def test_yearly(self) -> None:
        rule = RecurrenceRule(frequency="yearly")
        with patch("src.services.event_normalizer.PatternedRecurrence") as mock_cls:
            with patch("src.services.event_normalizer.RecurrencePattern") as mock_pattern:
                with patch("src.services.event_normalizer.RecurrenceRange") as mock_range:
                    with patch("src.services.event_normalizer.DayOfWeek"):
                        EventNormalizer._build_outlook_recurrence(rule)
                        mock_pattern_instance = mock_pattern.return_value
                        assert mock_pattern_instance.type == "absoluteYearly"

    def test_with_count(self) -> None:
        rule = RecurrenceRule(frequency="weekly", count=10)
        with patch("src.services.event_normalizer.PatternedRecurrence") as mock_cls:
            with patch("src.services.event_normalizer.RecurrencePattern"):
                with patch("src.services.event_normalizer.RecurrenceRange") as mock_range:
                    with patch("src.services.event_normalizer.DayOfWeek"):
                        EventNormalizer._build_outlook_recurrence(rule)
                        mock_range_instance = mock_range.return_value
                        assert mock_range_instance.type == "numbered"
                        assert mock_range_instance.number_of_occurrences == 10

    def test_with_until(self) -> None:
        until = datetime(2027, 6, 30, tzinfo=timezone.utc)
        rule = RecurrenceRule(frequency="weekly", until=until)
        with patch("src.services.event_normalizer.PatternedRecurrence") as mock_cls:
            with patch("src.services.event_normalizer.RecurrencePattern"):
                with patch("src.services.event_normalizer.RecurrenceRange") as mock_range:
                    with patch("src.services.event_normalizer.DayOfWeek"):
                        EventNormalizer._build_outlook_recurrence(rule)
                        mock_range_instance = mock_range.return_value
                        assert mock_range_instance.type == "endDate"
                        assert mock_range_instance.end_date == "2027-06-30"

    def test_unknown_frequency_defaults_to_weekly(self) -> None:
        rule = RecurrenceRule(frequency="biweekly")
        with patch("src.services.event_normalizer.PatternedRecurrence") as mock_cls:
            with patch("src.services.event_normalizer.RecurrencePattern") as mock_pattern:
                with patch("src.services.event_normalizer.RecurrenceRange"):
                    with patch("src.services.event_normalizer.DayOfWeek"):
                        EventNormalizer._build_outlook_recurrence(rule)
                        mock_pattern_instance = mock_pattern.return_value
                        assert mock_pattern_instance.type == "weekly"
