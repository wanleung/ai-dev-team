"""Tests for event normalizer service."""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from src.services.event_normalizer import EventNormalizer
from src.models.calendar import Event, EventAttendee, EventReminder, RecurrenceRule


class TestNormalizeGoogleEvent:
    def test_normalize_basic_event(self, sample_google_event_raw):
        normalizer = EventNormalizer()
        event = normalizer.normalize_event("google", sample_google_event_raw, "cal_123")
        assert event.id == "evt_google_123"
        assert event.title == "Google Test Event"
        assert event.description == "A test event from Google Calendar"
        assert event.location == "Google Office"
        assert event.calendar_id == "cal_123"
        assert event.status == "confirmed"
        assert event.etag == '"google_etag_123"'

    def test_normalize_attendees(self, sample_google_event_raw):
        normalizer = EventNormalizer()
        event = normalizer.normalize_event("google", sample_google_event_raw, "cal_123")
        assert len(event.attendees) == 1
        assert event.attendees[0].email == "attendee@example.com"
        assert event.attendees[0].name == "Attendee User"
        assert event.attendees[0].response_status == "needsAction"

    def test_normalize_reminders(self, sample_google_event_raw):
        normalizer = EventNormalizer()
        event = normalizer.normalize_event("google", sample_google_event_raw, "cal_123")
        assert len(event.reminders) == 1
        assert event.reminders[0].method == "popup"
        assert event.reminders[0].minutes_before == 15

    def test_normalize_all_day_event(self):
        normalizer = EventNormalizer()
        raw = {
            "id": "evt_allday",
            "summary": "All Day Event",
            "start": {"date": "2026-04-20"},
            "end": {"date": "2026-04-21"},
            "status": "confirmed",
            "created": "2026-04-19T10:00:00Z",
            "updated": "2026-04-19T10:00:00Z",
        }
        event = normalizer.normalize_event("google", raw, "cal_123")
        assert event.title == "All Day Event"
        assert event.timezone == "UTC"

    def test_normalize_recurring_event(self):
        normalizer = EventNormalizer()
        raw = {
            "id": "evt_recurring",
            "summary": "Recurring Event",
            "start": {"dateTime": "2026-04-20T10:00:00-04:00", "timeZone": "America/New_York"},
            "end": {"dateTime": "2026-04-20T11:00:00-04:00", "timeZone": "America/New_York"},
            "status": "confirmed",
            "created": "2026-04-19T10:00:00Z",
            "updated": "2026-04-19T10:00:00Z",
            "recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR"],
        }
        event = normalizer.normalize_event("google", raw, "cal_123")
        assert event.recurrence is not None
        assert event.recurrence.frequency == "weekly"
        assert event.recurrence.by_day == ["MO", "WE", "FR"]
        assert event.is_recurring_master is True

    def test_normalize_recurring_instance(self):
        normalizer = EventNormalizer()
        raw = {
            "id": "evt_instance",
            "summary": "Recurring Instance",
            "start": {"dateTime": "2026-04-20T10:00:00-04:00", "timeZone": "America/New_York"},
            "end": {"dateTime": "2026-04-20T11:00:00-04:00", "timeZone": "America/New_York"},
            "status": "confirmed",
            "created": "2026-04-19T10:00:00Z",
            "updated": "2026-04-19T10:00:00Z",
            "recurringEventId": "evt_master",
        }
        event = normalizer.normalize_event("google", raw, "cal_123")
        assert event.recurrence_id == "evt_master"
        assert event.is_recurring_master is False

    def test_normalize_empty_attendees(self):
        normalizer = EventNormalizer()
        raw = {
            "id": "evt_no_attendees",
            "summary": "Solo Event",
            "start": {"dateTime": "2026-04-20T10:00:00Z"},
            "end": {"dateTime": "2026-04-20T11:00:00Z"},
            "status": "confirmed",
            "created": "2026-04-19T10:00:00Z",
            "updated": "2026-04-19T10:00:00Z",
        }
        event = normalizer.normalize_event("google", raw, "cal_123")
        assert event.attendees == []

    def test_normalize_empty_reminders(self):
        normalizer = EventNormalizer()
        raw = {
            "id": "evt_no_reminders",
            "summary": "No Reminders",
            "start": {"dateTime": "2026-04-20T10:00:00Z"},
            "end": {"dateTime": "2026-04-20T11:00:00Z"},
            "status": "confirmed",
            "created": "2026-04-19T10:00:00Z",
            "updated": "2026-04-19T10:00:00Z",
        }
        event = normalizer.normalize_event("google", raw, "cal_123")
        assert event.reminders == []

    def test_normalize_preserves_provider_metadata(self, sample_google_event_raw):
        normalizer = EventNormalizer()
        event = normalizer.normalize_event("google", sample_google_event_raw, "cal_123")
        assert event.provider_metadata is not None
        assert event.provider_metadata["id"] == "evt_google_123"


class TestDenormalizeGoogleEvent:
    def test_denormalize_basic_event(self, sample_event):
        normalizer = EventNormalizer()
        body = normalizer.denormalize_event("google", sample_event)
        assert body["summary"] == "Test Event"
        assert "start" in body
        assert "end" in body
        assert body["start"]["timeZone"] == "America/New_York"

    def test_denormalize_with_attendees(self, sample_event):
        normalizer = EventNormalizer()
        body = normalizer.denormalize_event("google", sample_event)
        assert "attendees" in body
        assert len(body["attendees"]) == 1
        assert body["attendees"][0]["email"] == "test@example.com"
        assert body["attendees"][0]["displayName"] == "Test User"

    def test_denormalize_with_reminders(self, sample_event):
        normalizer = EventNormalizer()
        body = normalizer.denormalize_event("google", sample_event)
        assert "reminders" in body
        assert body["reminders"]["useDefault"] is False
        assert len(body["reminders"]["overrides"]) == 1

    def test_denormalize_with_recurrence(self, sample_event):
        sample_event.recurrence = RecurrenceRule(frequency="daily", interval=2)
        normalizer = EventNormalizer()
        body = normalizer.denormalize_event("google", sample_event)
        assert "recurrence" in body
        assert body["recurrence"][0].startswith("RRULE:FREQ=DAILY")

    def test_denormalize_without_optional_fields(self, utc_now, future_time):
        normalizer = EventNormalizer()
        event = Event(
            id="evt_minimal",
            calendar_id="cal_123",
            title="Minimal Event",
            start=utc_now,
            end=future_time,
            timezone="UTC",
            created_at=utc_now,
            updated_at=utc_now,
        )
        body = normalizer.denormalize_event("google", event)
        assert body["summary"] == "Minimal Event"
        assert "description" not in body
        assert "location" not in body
        assert "attendees" not in body


class TestNormalizeOutlookEvent:
    def test_normalize_unsupported_provider(self):
        normalizer = EventNormalizer()
        with pytest.raises(ValueError) as exc_info:
            normalizer.normalize_event("unknown", {}, "cal_123")
        assert "Unsupported provider" in str(exc_info.value)

    def test_denormalize_unsupported_provider(self, sample_event):
        normalizer = EventNormalizer()
        with pytest.raises(ValueError) as exc_info:
            normalizer.denormalize_event("unknown", sample_event)
        assert "Unsupported provider" in str(exc_info.value)


class TestParseRRULE:
    def test_parse_weekly_rrule(self):
        normalizer = EventNormalizer()
        rule = normalizer._parse_rrule(["RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR"])
        assert rule is not None
        assert rule.frequency == "weekly"
        assert rule.by_day == ["MO", "WE", "FR"]

    def test_parse_daily_rrule_with_count(self):
        normalizer = EventNormalizer()
        rule = normalizer._parse_rrule(["RRULE:FREQ=DAILY;COUNT=10"])
        assert rule is not None
        assert rule.frequency == "daily"
        assert rule.count == 10

    def test_parse_monthly_rrule_with_interval(self):
        normalizer = EventNormalizer()
        rule = normalizer._parse_rrule(["RRULE:FREQ=MONTHLY;INTERVAL=2"])
        assert rule is not None
        assert rule.frequency == "monthly"
        assert rule.interval == 2

    def test_parse_rrule_with_until(self):
        normalizer = EventNormalizer()
        rule = normalizer._parse_rrule(["RRULE:FREQ=WEEKLY;UNTIL=20261231T235959Z"])
        assert rule is not None
        assert rule.until is not None
        assert rule.until.year == 2026

    def test_parse_rrule_with_bymonthday(self):
        normalizer = EventNormalizer()
        rule = normalizer._parse_rrule(["RRULE:FREQ=MONTHLY;BYMONTHDAY=1,15"])
        assert rule is not None
        assert rule.by_month_day == [1, 15]

    def test_parse_empty_rrule(self):
        normalizer = EventNormalizer()
        assert normalizer._parse_rrule(None) is None
        assert normalizer._parse_rrule([]) is None

    def test_parse_invalid_rrule(self):
        normalizer = EventNormalizer()
        assert normalizer._parse_rrule(["INVALID"]) is None

    def test_parse_rrule_missing_freq(self):
        normalizer = EventNormalizer()
        assert normalizer._parse_rrule(["RRULE:COUNT=10"]) is None


class TestBuildRRULE:
    def test_build_basic_rrule(self):
        normalizer = EventNormalizer()
        rule = RecurrenceRule(frequency="daily")
        rrule = normalizer._build_rrule(rule)
        assert rrule == "RRULE:FREQ=DAILY"

    def test_build_rrule_with_interval(self):
        normalizer = EventNormalizer()
        rule = RecurrenceRule(frequency="weekly", interval=2)
        rrule = normalizer._build_rrule(rule)
        assert "FREQ=WEEKLY" in rrule
        assert "INTERVAL=2" in rrule

    def test_build_rrule_with_count(self):
        normalizer = EventNormalizer()
        rule = RecurrenceRule(frequency="monthly", count=10)
        rrule = normalizer._build_rrule(rule)
        assert "FREQ=MONTHLY" in rrule
        assert "COUNT=10" in rrule

    def test_build_rrule_with_byday(self):
        normalizer = EventNormalizer()
        rule = RecurrenceRule(frequency="weekly", by_day=["MO", "WE", "FR"])
        rrule = normalizer._build_rrule(rule)
        assert "BYDAY=MO,WE,FR" in rrule

    def test_build_rrule_with_bymonthday(self):
        normalizer = EventNormalizer()
        rule = RecurrenceRule(frequency="monthly", by_month_day=[1, 15])
        rrule = normalizer._build_rrule(rule)
        assert "BYMONTHDAY=1,15" in rrule

    def test_build_rrule_with_until(self, utc_now):
        normalizer = EventNormalizer()
        rule = RecurrenceRule(frequency="yearly", until=utc_now + timedelta(days=365))
        rrule = normalizer._build_rrule(rule)
        assert "FREQ=YEARLY" in rrule
        assert "UNTIL=" in rrule

    def test_build_rrule_interval_1_omitted(self):
        normalizer = EventNormalizer()
        rule = RecurrenceRule(frequency="daily", interval=1)
        rrule = normalizer._build_rrule(rule)
        assert "INTERVAL" not in rrule


class TestParseDatetime:
    def test_parse_iso_datetime(self):
        dt = EventNormalizer._parse_datetime("2026-04-20T10:00:00Z")
        assert dt.year == 2026
        assert dt.month == 4
        assert dt.day == 20

    def test_parse_datetime_with_offset(self):
        dt = EventNormalizer._parse_datetime("2026-04-20T10:00:00-04:00")
        assert dt.tzinfo is not None

    def test_parse_empty_string(self):
        dt = EventNormalizer._parse_datetime("")
        assert dt is not None

    def test_parse_naive_datetime(self):
        dt = EventNormalizer._parse_datetime("2026-04-20T10:00:00")
        assert dt.tzinfo is not None


class TestParseDate:
    def test_parse_date_string(self):
        dt = EventNormalizer._parse_date("2026-04-20")
        assert dt.year == 2026
        assert dt.month == 4
        assert dt.day == 20
        assert dt.tzinfo is not None

    def test_parse_empty_date(self):
        dt = EventNormalizer._parse_date("")
        assert dt is not None


class TestFormatDatetime:
    def test_format_utc_datetime(self):
        dt = datetime(2026, 4, 20, 10, 0, 0, tzinfo=timezone.utc)
        formatted = EventNormalizer._format_datetime(dt)
        assert "2026-04-20" in formatted

    def test_format_naive_datetime(self):
        dt = datetime(2026, 4, 20, 10, 0, 0)
        formatted = EventNormalizer._format_datetime(dt)
        assert dt.tzinfo is None
        assert "2026-04-20" in formatted
