"""Unit tests for MCP request/response Pydantic models.

Tests cover:
- ListCalendarsRequest/Response
- GetEventsRequest/Response
- CreateEventRequest/Response
- UpdateEventRequest/Response
- DeleteEventRequest/Response
- GetFreeBusyRequest/Response
- Field validation, defaults, and serialization
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.models.mcp import (
    ListCalendarsRequest,
    ListCalendarsResponse,
    GetEventsRequest,
    GetEventsResponse,
    CreateEventRequest,
    CreateEventResponse,
    UpdateEventRequest,
    UpdateEventResponse,
    DeleteEventRequest,
    DeleteEventResponse,
    GetFreeBusyRequest,
    GetFreeBusyResponse,
)
from src.models.calendar import (
    Calendar,
    Event,
    EventAttendee,
    EventReminder,
    FreeBusySlot,
    RecurrenceRule,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture
def sample_calendar() -> Calendar:
    return Calendar(
        id="cal-001",
        name="Work",
        timezone="America/New_York",
        is_primary=True,
        access_role="owner",
    )


@pytest.fixture
def sample_event(now: datetime) -> Event:
    return Event(
        id="evt-001",
        calendar_id="cal-001",
        title="Meeting",
        start=now,
        end=now + timedelta(hours=1),
        timezone="UTC",
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def sample_slot(now: datetime) -> FreeBusySlot:
    return FreeBusySlot(
        start=now,
        end=now + timedelta(hours=1),
        status="busy",
    )


# ---------------------------------------------------------------------------
# ListCalendarsRequest tests
# ---------------------------------------------------------------------------


class TestListCalendarsRequest:
    def test_default_provider_is_none(self) -> None:
        req = ListCalendarsRequest()
        assert req.provider is None

    def test_with_provider(self) -> None:
        req = ListCalendarsRequest(provider="google")
        assert req.provider == "google"

    def test_model_dump(self) -> None:
        req = ListCalendarsRequest(provider="outlook")
        data = req.model_dump()
        assert data["provider"] == "outlook"


# ---------------------------------------------------------------------------
# ListCalendarsResponse tests
# ---------------------------------------------------------------------------


class TestListCalendarsResponse:
    def test_with_calendars(self, sample_calendar: Calendar) -> None:
        resp = ListCalendarsResponse(calendars=[sample_calendar])
        assert len(resp.calendars) == 1
        assert resp.calendars[0].id == "cal-001"

    def test_empty_calendars(self) -> None:
        resp = ListCalendarsResponse(calendars=[])
        assert resp.calendars == []

    def test_model_dump(self, sample_calendar: Calendar) -> None:
        resp = ListCalendarsResponse(calendars=[sample_calendar])
        data = resp.model_dump()
        assert len(data["calendars"]) == 1


# ---------------------------------------------------------------------------
# GetEventsRequest tests
# ---------------------------------------------------------------------------


class TestGetEventsRequest:
    def test_required_fields(self, now: datetime) -> None:
        req = GetEventsRequest(
            start_time=now,
            end_time=now + timedelta(hours=1),
        )
        assert req.calendar_id is None
        assert req.provider is None
        assert req.max_results == 100
        assert req.expand_recurring is True

    def test_with_all_fields(self, now: datetime) -> None:
        req = GetEventsRequest(
            calendar_id="cal-001",
            start_time=now,
            end_time=now + timedelta(days=1),
            provider="google",
            max_results=50,
            expand_recurring=False,
        )
        assert req.calendar_id == "cal-001"
        assert req.provider == "google"
        assert req.max_results == 50
        assert req.expand_recurring is False

    def test_max_results_validation_too_low(self, now: datetime) -> None:
        with pytest.raises(Exception):
            GetEventsRequest(start_time=now, end_time=now + timedelta(hours=1), max_results=0)

    def test_max_results_validation_too_high(self, now: datetime) -> None:
        with pytest.raises(Exception):
            GetEventsRequest(start_time=now, end_time=now + timedelta(hours=1), max_results=2501)


# ---------------------------------------------------------------------------
# GetEventsResponse tests
# ---------------------------------------------------------------------------


class TestGetEventsResponse:
    def test_with_events(self, sample_event: Event) -> None:
        resp = GetEventsResponse(events=[sample_event])
        assert len(resp.events) == 1
        assert resp.events[0].id == "evt-001"

    def test_empty_events(self) -> None:
        resp = GetEventsResponse(events=[])
        assert resp.events == []


# ---------------------------------------------------------------------------
# CreateEventRequest tests
# ---------------------------------------------------------------------------


class TestCreateEventRequest:
    def test_required_fields(self, now: datetime) -> None:
        req = CreateEventRequest(
            title="Meeting",
            start=now,
            end=now + timedelta(hours=1),
            timezone="UTC",
        )
        assert req.calendar_id is None
        assert req.description is None
        assert req.location is None
        assert req.attendees == []
        assert req.reminders == []
        assert req.recurrence is None
        assert req.provider is None

    def test_with_attendees(self, now: datetime) -> None:
        req = CreateEventRequest(
            title="Meeting",
            start=now,
            end=now + timedelta(hours=1),
            timezone="UTC",
            attendees=[EventAttendee(email="user@example.com", name="User")],
        )
        assert len(req.attendees) == 1
        assert req.attendees[0].email == "user@example.com"

    def test_with_reminders(self, now: datetime) -> None:
        req = CreateEventRequest(
            title="Meeting",
            start=now,
            end=now + timedelta(hours=1),
            timezone="UTC",
            reminders=[EventReminder(method="popup", minutes_before=15)],
        )
        assert len(req.reminders) == 1
        assert req.reminders[0].minutes_before == 15

    def test_with_recurrence(self, now: datetime) -> None:
        req = CreateEventRequest(
            title="Weekly",
            start=now,
            end=now + timedelta(hours=1),
            timezone="UTC",
            recurrence=RecurrenceRule(frequency="weekly", by_day=["MO"]),
        )
        assert req.recurrence is not None
        assert req.recurrence.frequency == "weekly"


# ---------------------------------------------------------------------------
# CreateEventResponse tests
# ---------------------------------------------------------------------------


class TestCreateEventResponse:
    def test_with_event(self, sample_event: Event) -> None:
        resp = CreateEventResponse(event=sample_event)
        assert resp.event.id == "evt-001"


# ---------------------------------------------------------------------------
# UpdateEventRequest tests
# ---------------------------------------------------------------------------


class TestUpdateEventRequest:
    def test_required_fields(self) -> None:
        req = UpdateEventRequest(event_id="evt-001")
        assert req.event_id == "evt-001"
        assert req.calendar_id is None
        assert req.title is None
        assert req.send_notifications is True
        assert req.update_series is False

    def test_with_all_fields(self, now: datetime) -> None:
        req = UpdateEventRequest(
            event_id="evt-001",
            calendar_id="cal-001",
            title="Updated",
            description="New desc",
            location="New location",
            start=now,
            end=now + timedelta(hours=2),
            timezone="Europe/London",
            attendees=[EventAttendee(email="a@b.com")],
            reminders=[EventReminder(method="email", minutes_before=30)],
            recurrence=RecurrenceRule(frequency="daily"),
            status="confirmed",
            send_notifications=False,
            update_series=True,
            provider="outlook",
        )
        assert req.event_id == "evt-001"
        assert req.title == "Updated"
        assert req.send_notifications is False
        assert req.update_series is True
        assert req.provider == "outlook"


# ---------------------------------------------------------------------------
# UpdateEventResponse tests
# ---------------------------------------------------------------------------


class TestUpdateEventResponse:
    def test_with_event(self, sample_event: Event) -> None:
        resp = UpdateEventResponse(event=sample_event)
        assert resp.event.id == "evt-001"


# ---------------------------------------------------------------------------
# DeleteEventRequest tests
# ---------------------------------------------------------------------------


class TestDeleteEventRequest:
    def test_required_fields(self) -> None:
        req = DeleteEventRequest(event_id="evt-001")
        assert req.event_id == "evt-001"
        assert req.calendar_id is None
        assert req.send_notifications is True
        assert req.delete_series is False
        assert req.provider is None

    def test_with_all_fields(self) -> None:
        req = DeleteEventRequest(
            event_id="evt-001",
            calendar_id="cal-001",
            send_notifications=False,
            delete_series=True,
            provider="google",
        )
        assert req.send_notifications is False
        assert req.delete_series is True
        assert req.provider == "google"


# ---------------------------------------------------------------------------
# DeleteEventResponse tests
# ---------------------------------------------------------------------------


class TestDeleteEventResponse:
    def test_success(self) -> None:
        resp = DeleteEventResponse(success=True, message="Deleted")
        assert resp.success is True
        assert resp.message == "Deleted"

    def test_failure(self) -> None:
        resp = DeleteEventResponse(success=False, message="Not found")
        assert resp.success is False


# ---------------------------------------------------------------------------
# GetFreeBusyRequest tests
# ---------------------------------------------------------------------------


class TestGetFreeBusyRequest:
    def test_required_fields(self, now: datetime) -> None:
        req = GetFreeBusyRequest(
            start_time=now,
            end_time=now + timedelta(hours=4),
        )
        assert req.calendar_ids is None
        assert req.provider is None

    def test_with_calendar_ids(self, now: datetime) -> None:
        req = GetFreeBusyRequest(
            start_time=now,
            end_time=now + timedelta(hours=4),
            calendar_ids=["cal-001", "cal-002"],
            provider="google",
        )
        assert req.calendar_ids == ["cal-001", "cal-002"]
        assert req.provider == "google"


# ---------------------------------------------------------------------------
# GetFreeBusyResponse tests
# ---------------------------------------------------------------------------


class TestGetFreeBusyResponse:
    def test_with_slots(self, sample_slot: FreeBusySlot) -> None:
        resp = GetFreeBusyResponse(slots=[sample_slot])
        assert len(resp.slots) == 1
        assert resp.slots[0].status == "busy"

    def test_empty_slots(self) -> None:
        resp = GetFreeBusyResponse(slots=[])
        assert resp.slots == []
