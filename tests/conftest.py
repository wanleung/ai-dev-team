"""Shared fixtures for tests."""
import sys
from unittest.mock import MagicMock

# Mock external dependencies that may not be installed
_mock_modules = [
    "msgraph",
    "msgraph.generated",
    "msgraph.generated.calendars",
    "msgraph.generated.calendars.calendars_request_builder",
    "msgraph.generated.me",
    "msgraph.generated.me.me_request_builder",
    "msgraph.generated.models",
    "msgraph.generated.models.attendee",
    "msgraph.generated.models.attendee_type",
    "msgraph.generated.models.body_type",
    "msgraph.generated.models.date_time_time_zone",
    "msgraph.generated.models.email_address",
    "msgraph.generated.models.event",
    "msgraph.generated.models.location",
    "msgraph.generated.models.patterned_recurrence",
    "msgraph.generated.models.recurrence_pattern",
    "msgraph.generated.models.recurrence_range",
    "msgraph.generated.models.response_status",
    "msgraph.generated.models.response_type",
    "msgraph.generated.models.schedule_item",
    "msgraph.generated.models.day_of_week",
    "msgraph.generated.users",
    "msgraph.generated.users.item",
    "msgraph.generated.users.item.calendar_view",
    "msgraph.generated.users.item.calendar_view.calendar_view_request_builder",
    "msgraph.generated.users.item.calendars",
    "msgraph.generated.users.item.calendars.item",
    "msgraph.generated.users.item.calendars.item.events",
    "msgraph.generated.users.item.calendars.item.events.events_request_builder",
    "kiota_abstractions",
    "kiota_abstractions.api_error",
    "kiota_abstractions.authentication",
    "kiota_abstractions.authentication.anonymous_authentication_provider",
    "kiota_http",
    "kiota_http.httpx_request_adapter",
    "google",
    "google.auth",
    "google.auth.transport",
    "google.auth.transport.requests",
    "google.oauth2",
    "google.oauth2.credentials",
    "googleapiclient",
    "googleapiclient.discovery",
    "googleapiclient.errors",
]

for mod_name in _mock_modules:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, AsyncMock


# ── Memory store isolation ────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _isolate_memory_store(tmp_path, monkeypatch):
    """Redirect MemoryStore to an isolated per-test temp database.

    This prevents stale memory from previous pipeline runs leaking into
    orchestrator unit tests, making assertions about system prompts reliable.
    """
    try:
        import memory_store as _ms

        _original_init = _ms.MemoryStore.__init__

        def _patched_init(self: "_ms.MemoryStore", db_path: object = None) -> None:
            _original_init(self, str(tmp_path / "memory.db"))

        monkeypatch.setattr(_ms.MemoryStore, "__init__", _patched_init)
    except ImportError:
        pass  # memory_store not available in all test environments

from src.models.calendar import (
    Calendar, Event, EventAttendee, EventReminder,
    FreeBusySlot, RecurrenceRule, ProviderConfig,
)
from src.config.settings import Settings


@pytest.fixture
def utc_now():
    """Return current UTC time."""
    return datetime.now(timezone.utc)


@pytest.fixture
def future_time(utc_now):
    """Return a time 1 hour in the future."""
    return utc_now + timedelta(hours=1)


@pytest.fixture
def past_time(utc_now):
    """Return a time 1 hour in the past."""
    return utc_now - timedelta(hours=1)


@pytest.fixture
def sample_attendee():
    """Create a sample EventAttendee."""
    return EventAttendee(
        email="test@example.com",
        name="Test User",
        response_status="needsAction",
    )


@pytest.fixture
def sample_reminder():
    """Create a sample EventReminder."""
    return EventReminder(method="popup", minutes_before=15)


@pytest.fixture
def sample_recurrence():
    """Create a sample RecurrenceRule."""
    return RecurrenceRule(
        frequency="weekly",
        interval=1,
        by_day=["MO", "WE", "FR"],
    )


@pytest.fixture
def sample_calendar():
    """Create a sample Calendar."""
    return Calendar(
        id="cal_123",
        name="Test Calendar",
        description="A test calendar",
        timezone="America/New_York",
        is_primary=True,
        access_role="owner",
        color="#123456",
    )


@pytest.fixture
def sample_event(utc_now, future_time, sample_attendee, sample_reminder):
    """Create a sample Event."""
    return Event(
        id="evt_123",
        calendar_id="cal_123",
        title="Test Event",
        description="A test event",
        location="Test Location",
        start=utc_now,
        end=future_time,
        timezone="America/New_York",
        attendees=[sample_attendee],
        reminders=[sample_reminder],
        status="confirmed",
        created_at=utc_now - timedelta(days=1),
        updated_at=utc_now,
        etag='"abc123"',
    )


@pytest.fixture
def sample_free_busy_slot(utc_now, future_time):
    """Create a sample FreeBusySlot."""
    return FreeBusySlot(
        start=utc_now,
        end=future_time,
        status="busy",
    )


@pytest.fixture
def google_provider_config():
    """Create a sample Google ProviderConfig."""
    return ProviderConfig(
        provider="google",
        client_id="google_client_id",
        client_secret="google_client_secret",
        redirect_uri="http://localhost:8000/auth/google/callback",
        scopes=["https://www.googleapis.com/auth/calendar"],
        access_token="google_access_token",
        refresh_token="google_refresh_token",
        token_expiry=datetime.now(timezone.utc) + timedelta(hours=1),
    )


@pytest.fixture
def outlook_provider_config():
    """Create a sample Outlook ProviderConfig."""
    return ProviderConfig(
        provider="outlook",
        client_id="outlook_client_id",
        client_secret="outlook_client_secret",
        redirect_uri="http://localhost:8000/auth/outlook/callback",
        scopes=["Calendars.Read", "Calendars.ReadWrite"],
        access_token="outlook_access_token",
        refresh_token="outlook_refresh_token",
        token_expiry=datetime.now(timezone.utc) + timedelta(hours=1),
    )


@pytest.fixture
def mock_settings():
    """Create a mock Settings object with test values."""
    return Settings(
        server_host="0.0.0.0",
        server_port=8000,
        debug=False,
        google_client_id="test_google_client_id",
        google_client_secret="test_google_client_secret",
        google_redirect_uri="http://localhost:8000/auth/google/callback",
        google_access_token="test_google_access_token",
        google_refresh_token="test_google_refresh_token",
        outlook_client_id="test_outlook_client_id",
        outlook_client_secret="test_outlook_client_secret",
        outlook_redirect_uri="http://localhost:8000/auth/outlook/callback",
        outlook_access_token="test_outlook_access_token",
        outlook_refresh_token="test_outlook_refresh_token",
        outlook_tenant_id="common",
        default_provider="google",
    )


@pytest.fixture
def mock_google_credentials():
    """Create mock Google OAuth2 credentials."""
    mock_creds = MagicMock()
    mock_creds.token = "google_access_token"
    mock_creds.refresh_token = "google_refresh_token"
    mock_creds.expired = False
    mock_creds.valid = True
    mock_creds.expiry = datetime.now(timezone.utc) + timedelta(hours=1)
    return mock_creds


@pytest.fixture
def mock_google_service():
    """Create a mock Google Calendar API service."""
    service = MagicMock()

    # Mock calendarList
    calendar_list = MagicMock()
    calendar_list.list.return_value.execute.return_value = {
        "items": [
            {
                "id": "primary",
                "summary": "Primary Calendar",
                "timeZone": "America/New_York",
                "primary": True,
                "accessRole": "owner",
                "backgroundColor": "#123456",
            },
            {
                "id": "cal_123",
                "summary": "Work Calendar",
                "timeZone": "America/New_York",
                "primary": False,
                "accessRole": "writer",
                "backgroundColor": "#654321",
            },
        ]
    }
    service.calendarList.return_value = calendar_list

    # Mock events
    events = MagicMock()
    events.list.return_value.execute.return_value = {
        "items": [
            {
                "id": "evt_1",
                "summary": "Test Event 1",
                "start": {"dateTime": "2026-04-20T10:00:00-04:00", "timeZone": "America/New_York"},
                "end": {"dateTime": "2026-04-20T11:00:00-04:00", "timeZone": "America/New_York"},
                "status": "confirmed",
                "created": "2026-04-19T10:00:00Z",
                "updated": "2026-04-19T10:00:00Z",
            }
        ]
    }
    events.insert.return_value.execute.return_value = {
        "id": "evt_new",
        "summary": "New Event",
        "start": {"dateTime": "2026-04-21T10:00:00-04:00", "timeZone": "America/New_York"},
        "end": {"dateTime": "2026-04-21T11:00:00-04:00", "timeZone": "America/New_York"},
        "status": "confirmed",
        "created": "2026-04-20T10:00:00Z",
        "updated": "2026-04-20T10:00:00Z",
    }
    events.get.return_value.execute.return_value = {
        "id": "evt_1",
        "summary": "Test Event 1",
        "start": {"dateTime": "2026-04-20T10:00:00-04:00", "timeZone": "America/New_York"},
        "end": {"dateTime": "2026-04-20T11:00:00-04:00", "timeZone": "America/New_York"},
        "status": "confirmed",
        "created": "2026-04-19T10:00:00Z",
        "updated": "2026-04-19T10:00:00Z",
        "etag": '"abc123"',
    }
    events.update.return_value.execute.return_value = {
        "id": "evt_1",
        "summary": "Updated Event",
        "start": {"dateTime": "2026-04-20T10:00:00-04:00", "timeZone": "America/New_York"},
        "end": {"dateTime": "2026-04-20T11:00:00-04:00", "timeZone": "America/New_York"},
        "status": "confirmed",
        "created": "2026-04-19T10:00:00Z",
        "updated": "2026-04-20T10:00:00Z",
        "etag": '"def456"',
    }
    events.delete.return_value.execute.return_value = None
    service.events.return_value = events

    # Mock freebusy
    freebusy = MagicMock()
    freebusy.query.return_value.execute.return_value = {
        "calendars": {
            "primary": {
                "busy": [
                    {"start": "2026-04-20T10:00:00Z", "end": "2026-04-20T11:00:00Z"},
                ]
            }
        }
    }
    service.freebusy.return_value = freebusy

    return service


@pytest.fixture
def mock_graph_client():
    """Create a mock Microsoft Graph client."""
    client = MagicMock()

    # Mock calendars
    calendars_response = MagicMock()
    calendars_response.value = [
        MagicMock(
            id="primary",
            name="Primary Calendar",
            change_key=None,
            default_online_meeting_provider="UTC",
            is_default_calendar=True,
            hex_color="#123456",
        ),
        MagicMock(
            id="cal_123",
            name="Work Calendar",
            change_key=None,
            default_online_meeting_provider="UTC",
            is_default_calendar=False,
            hex_color="#654321",
        ),
    ]

    # Set up async chain for calendars
    async def mock_get_calendars():
        return calendars_response

    me_mock = MagicMock()
    calendars_mock = MagicMock()
    calendars_mock.get = mock_get_calendars
    me_mock.calendars = calendars_mock
    client.me = me_mock

    return client


@pytest.fixture
def sample_google_event_raw():
    """Create a raw Google Calendar event dict."""
    return {
        "id": "evt_google_123",
        "summary": "Google Test Event",
        "description": "A test event from Google Calendar",
        "location": "Google Office",
        "start": {
            "dateTime": "2026-04-20T10:00:00-04:00",
            "timeZone": "America/New_York",
        },
        "end": {
            "dateTime": "2026-04-20T11:00:00-04:00",
            "timeZone": "America/New_York",
        },
        "status": "confirmed",
        "created": "2026-04-19T10:00:00Z",
        "updated": "2026-04-19T10:00:00Z",
        "etag": '"google_etag_123"',
        "attendees": [
            {
                "email": "attendee@example.com",
                "displayName": "Attendee User",
                "responseStatus": "needsAction",
                "organizer": False,
            }
        ],
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": 15},
            ],
        },
    }


@pytest.fixture
def mcp_initialize_request():
    """Create a sample MCP initialize request."""
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0.0"},
        },
    }


@pytest.fixture
def mcp_tools_list_request():
    """Create a sample MCP tools/list request."""
    return {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
        "params": {},
    }


@pytest.fixture
def mcp_tool_call_request():
    """Create a sample MCP tools/call request."""
    return {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "list_calendars",
            "arguments": {},
        },
    }


@pytest.fixture
def mock_calendar_provider(sample_calendar, sample_event, sample_free_busy_slot):
    """Create a fully mocked calendar provider for integration tests."""
    provider = MagicMock()
    provider.provider_name = "google"
    provider.authenticate = AsyncMock(return_value=True)
    provider.list_calendars = AsyncMock(return_value=[sample_calendar])
    provider.get_events = AsyncMock(return_value=[sample_event])
    provider.create_event = AsyncMock(return_value=sample_event)
    provider.update_event = AsyncMock(return_value=sample_event)
    provider.delete_event = AsyncMock(return_value=True)
    provider.get_free_busy = AsyncMock(return_value=[sample_free_busy_slot])
    provider.close = AsyncMock()
    return provider


@pytest.fixture
def mock_rate_limiter():
    """Create a mocked rate limiter."""
    limiter = MagicMock()
    limiter.acquire = AsyncMock()
    return limiter
