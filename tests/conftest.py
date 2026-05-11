"""Test configuration for ai-software-house tests.

Provides shared fixtures used across the test suite.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.models.calendar import Calendar, Event, EventAttendee, EventReminder


# ---------------------------------------------------------------------------
# Calendar model fixtures (required by test_models.py)
# ---------------------------------------------------------------------------

@pytest.fixture
def utc_now() -> datetime:
    """Current time in UTC, frozen for the duration of a test."""
    return datetime.now(tz=timezone.utc)


@pytest.fixture
def future_time(utc_now: datetime) -> datetime:
    """One hour after utc_now."""
    return utc_now + timedelta(hours=1)


@pytest.fixture
def sample_calendar() -> Calendar:
    """A fully-populated Calendar instance for model snapshot tests."""
    return Calendar(
        id="cal_123",
        name="Test Calendar",
        description="A sample calendar for tests",
        timezone="America/New_York",
        is_primary=True,
        access_role="owner",
        color="#4285F4",
    )


@pytest.fixture
def sample_event(utc_now: datetime, future_time: datetime) -> Event:
    """A fully-populated Event instance for model snapshot tests."""
    return Event(
        id="evt_123",
        calendar_id="cal_123",
        title="Test Event",
        description="A test event",
        location="Test Location",
        start=utc_now,
        end=future_time,
        timezone="America/New_York",
        created_at=utc_now,
        updated_at=utc_now,
        attendees=[
            EventAttendee(
                email="test@example.com",
                name="Test User",
                response_status="accepted",
            )
        ],
        reminders=[EventReminder(method="popup", minutes_before=15)],
        status="confirmed",
        etag='"abc123"',
    )


@pytest.fixture
def sample_google_event_raw() -> dict:
    """Raw Google Calendar API event dict for event normalizer tests."""
    return {
        "id": "evt_google_123",
        "summary": "Google Test Event",
        "description": "A test event from Google Calendar",
        "location": "Google Office",
        "status": "confirmed",
        "etag": '"google_etag_123"',
        "start": {"dateTime": "2026-05-11T10:00:00-04:00", "timeZone": "America/New_York"},
        "end": {"dateTime": "2026-05-11T11:00:00-04:00", "timeZone": "America/New_York"},
        "created": "2026-05-01T08:00:00Z",
        "updated": "2026-05-10T09:00:00Z",
        "attendees": [
            {
                "email": "attendee@example.com",
                "displayName": "Attendee User",
                "responseStatus": "needsAction",
            }
        ],
        "reminders": {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": 15}],
        },
    }


@pytest.fixture(autouse=True)
def _isolate_memory_store(tmp_path: Path, monkeypatch):
    """Redirect MemoryStore to a per-test temp DB to prevent state leakage."""
    try:
        import memory_store as _ms

        _original_init = _ms.MemoryStore.__init__

        def _patched_init(self: "_ms.MemoryStore", db_path: object = None) -> None:
            _original_init(self, str(tmp_path / "memory.db"))

        monkeypatch.setattr(_ms.MemoryStore, "__init__", _patched_init)
    except ImportError:
        pass  # memory_store not available in all test environments


@pytest.fixture(autouse=True)
def _clear_structlog_context():
    """Clear structlog contextvars after each test to prevent run_id leaking between tests."""
    yield
    try:
        import structlog
        structlog.contextvars.clear_contextvars()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _restore_root_handlers():
    """Restore logging.root handlers and level after each test to prevent accumulation."""
    original_handlers = logging.root.handlers[:]
    original_level = logging.root.level
    yield
    for h in logging.root.handlers:
        if h not in original_handlers:
            try:
                h.close()
            except Exception:
                pass
    logging.root.handlers = original_handlers
    logging.root.setLevel(original_level)


@pytest.fixture(autouse=True)
def _restore_global_ledger():
    """Ensure each test starts with a fresh TokenLedger and the global is restored after."""
    from agents.token_ledger import get_ledger, set_ledger, TokenLedger
    original = get_ledger()
    set_ledger(TokenLedger())
    yield
    set_ledger(original)
