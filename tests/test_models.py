"""Tests for Pydantic calendar models."""
import pytest
from datetime import datetime, timedelta, timezone

from src.models.calendar import (
    Calendar, Event, EventAttendee, EventReminder,
    FreeBusySlot, RecurrenceRule, ProviderConfig,
)


class TestEventAttendee:
    def test_create_with_required_fields(self):
        attendee = EventAttendee(email="test@example.com")
        assert attendee.email == "test@example.com"
        assert attendee.name is None
        assert attendee.response_status is None
        assert attendee.is_organizer is False

    def test_create_with_all_fields(self):
        attendee = EventAttendee(
            email="test@example.com",
            name="Test User",
            response_status="accepted",
            is_organizer=True,
        )
        assert attendee.email == "test@example.com"
        assert attendee.name == "Test User"
        assert attendee.response_status == "accepted"
        assert attendee.is_organizer is True

    def test_model_dump(self):
        attendee = EventAttendee(email="test@example.com", name="Test User")
        data = attendee.model_dump()
        assert data["email"] == "test@example.com"
        assert data["name"] == "Test User"


class TestEventReminder:
    def test_create_with_required_fields(self):
        reminder = EventReminder(method="popup", minutes_before=15)
        assert reminder.method == "popup"
        assert reminder.minutes_before == 15

    def test_create_with_email_method(self):
        reminder = EventReminder(method="email", minutes_before=30)
        assert reminder.method == "email"
        assert reminder.minutes_before == 30

    def test_negative_minutes_raises(self):
        with pytest.raises(Exception):
            EventReminder(method="popup", minutes_before=-5)


class TestRecurrenceRule:
    def test_create_with_required_fields(self):
        rule = RecurrenceRule(frequency="daily")
        assert rule.frequency == "daily"
        assert rule.interval == 1
        assert rule.count is None
        assert rule.until is None
        assert rule.by_day is None
        assert rule.by_month_day is None

    def test_create_with_all_fields(self, utc_now):
        rule = RecurrenceRule(
            frequency="weekly",
            interval=2,
            count=10,
            until=utc_now + timedelta(days=30),
            by_day=["MO", "WE", "FR"],
            by_month_day=[1, 15],
        )
        assert rule.frequency == "weekly"
        assert rule.interval == 2
        assert rule.count == 10
        assert rule.by_day == ["MO", "WE", "FR"]
        assert rule.by_month_day == [1, 15]

    def test_invalid_interval_raises(self):
        with pytest.raises(Exception):
            RecurrenceRule(frequency="daily", interval=0)

    def test_invalid_count_raises(self):
        with pytest.raises(Exception):
            RecurrenceRule(frequency="daily", count=0)

    def test_model_dump(self):
        rule = RecurrenceRule(frequency="monthly", interval=3)
        data = rule.model_dump()
        assert data["frequency"] == "monthly"
        assert data["interval"] == 3


class TestCalendar:
    def test_create_with_required_fields(self):
        cal = Calendar(
            id="cal_123",
            name="Test Calendar",
            timezone="America/New_York",
            access_role="owner",
        )
        assert cal.id == "cal_123"
        assert cal.name == "Test Calendar"
        assert cal.timezone == "America/New_York"
        assert cal.access_role == "owner"
        assert cal.is_primary is False
        assert cal.description is None
        assert cal.color is None

    def test_create_with_all_fields(self):
        cal = Calendar(
            id="cal_123",
            name="Test Calendar",
            description="A test calendar",
            timezone="America/New_York",
            is_primary=True,
            access_role="writer",
            color="#123456",
        )
        assert cal.is_primary is True
        assert cal.description == "A test calendar"
        assert cal.color == "#123456"

    def test_model_dump(self, sample_calendar):
        data = sample_calendar.model_dump()
        assert data["id"] == "cal_123"
        assert data["name"] == "Test Calendar"
        assert data["is_primary"] is True


class TestEvent:
    def test_create_with_required_fields(self, utc_now, future_time):
        event = Event(
            id="evt_123",
            calendar_id="cal_123",
            title="Test Event",
            start=utc_now,
            end=future_time,
            timezone="America/New_York",
            created_at=utc_now,
            updated_at=utc_now,
        )
        assert event.id == "evt_123"
        assert event.calendar_id == "cal_123"
        assert event.title == "Test Event"
        assert event.description is None
        assert event.location is None
        assert event.attendees == []
        assert event.reminders == []
        assert event.recurrence is None
        assert event.status == "confirmed"
        assert event.etag is None
        assert event.is_recurring_master is False
        assert event.recurrence_id is None
        assert event.provider_metadata is None

    def test_create_with_all_fields(self, sample_event):
        assert sample_event.title == "Test Event"
        assert sample_event.description == "A test event"
        assert sample_event.location == "Test Location"
        assert len(sample_event.attendees) == 1
        assert len(sample_event.reminders) == 1
        assert sample_event.status == "confirmed"
        assert sample_event.etag == '"abc123"'

    def test_model_dump(self, sample_event):
        data = sample_event.model_dump()
        assert data["id"] == "evt_123"
        assert data["title"] == "Test Event"
        assert len(data["attendees"]) == 1
        assert len(data["reminders"]) == 1


class TestFreeBusySlot:
    def test_create_with_required_fields(self, utc_now, future_time):
        slot = FreeBusySlot(
            start=utc_now,
            end=future_time,
            status="busy",
        )
        assert slot.start == utc_now
        assert slot.end == future_time
        assert slot.status == "busy"

    def test_create_with_free_status(self, utc_now, future_time):
        slot = FreeBusySlot(
            start=utc_now,
            end=future_time,
            status="free",
        )
        assert slot.status == "free"

    def test_create_with_tentative_status(self, utc_now, future_time):
        slot = FreeBusySlot(
            start=utc_now,
            end=future_time,
            status="tentative",
        )
        assert slot.status == "tentative"


class TestProviderConfig:
    def test_create_with_required_fields(self):
        config = ProviderConfig(
            provider="google",
            client_id="client_id",
            client_secret="client_secret",
            redirect_uri="http://localhost/callback",
            scopes=["calendar.read"],
        )
        assert config.provider == "google"
        assert config.client_id == "client_id"
        assert config.client_secret == "client_secret"
        assert config.redirect_uri == "http://localhost/callback"
        assert config.scopes == ["calendar.read"]
        assert config.access_token is None
        assert config.refresh_token is None
        assert config.token_expiry is None

    def test_create_with_tokens(self, utc_now):
        config = ProviderConfig(
            provider="outlook",
            client_id="client_id",
            client_secret="client_secret",
            redirect_uri="http://localhost/callback",
            scopes=["calendars.read"],
            access_token="access_token",
            refresh_token="refresh_token",
            token_expiry=utc_now + timedelta(hours=1),
        )
        assert config.access_token == "access_token"
        assert config.refresh_token == "refresh_token"
        assert config.token_expiry is not None
