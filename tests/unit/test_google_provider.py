"""Unit tests for the Google Calendar provider implementation.

Tests cover all public methods of `GoogleCalendarProvider`:
- Initialization and configuration
- Authentication and token refresh
- Calendar listing
- Event CRUD operations (create, read, update, delete)
- Free/busy queries
- Error handling for various HTTP error codes
- Internal helpers (datetime parsing, event building, recurrence)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, call
from typing import Generator

import pytest

from src.calendar_provider.google_provider import (
    GoogleCalendarProvider,
    ProviderAPIError,
    AuthenticationError,
    CalendarNotFoundError,
    EventNotFoundError,
    ConflictError,
    ValidationError,
)
from src.models.calendar import (
    Calendar,
    Event,
    EventAttendee,
    EventReminder,
    FreeBusySlot,
    ProviderConfig,
    RecurrenceRule,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def google_config() -> ProviderConfig:
    """Valid Google provider config with non-expired tokens."""
    return ProviderConfig(
        provider="google",
        client_id="test-client-id",
        client_secret="test-client-secret",
        redirect_uri="http://localhost:8080/callback",
        scopes=[
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/calendar.events",
        ],
        access_token="test-access-token",
        refresh_token="test-refresh-token",
        token_expiry=datetime.now(timezone.utc) + timedelta(hours=1),
    )


@pytest.fixture
def google_config_expired() -> ProviderConfig:
    """Google provider config with an expired token."""
    return ProviderConfig(
        provider="google",
        client_id="test-client-id",
        client_secret="test-client-secret",
        redirect_uri="http://localhost:8080/callback",
        scopes=[
            "https://www.googleapis.com/auth/calendar",
        ],
        access_token="expired-access-token",
        refresh_token="test-refresh-token",
        token_expiry=datetime.now(timezone.utc) - timedelta(hours=1),
    )


@pytest.fixture
def google_config_no_token() -> ProviderConfig:
    """Google provider config without any access token."""
    return ProviderConfig(
        provider="google",
        client_id="test-client-id",
        client_secret="test-client-secret",
        redirect_uri="http://localhost:8080/callback",
        scopes=[
            "https://www.googleapis.com/auth/calendar",
        ],
        access_token=None,
        refresh_token=None,
        token_expiry=None,
    )


@pytest.fixture
def sample_attendee() -> EventAttendee:
    return EventAttendee(
        email="attendee@example.com",
        name="John Doe",
        response_status="needsAction",
        is_organizer=False,
    )


@pytest.fixture
def sample_reminder() -> EventReminder:
    return EventReminder(method="popup", minutes_before=15)


@pytest.fixture
def sample_recurrence() -> RecurrenceRule:
    return RecurrenceRule(
        frequency="weekly",
        interval=1,
        by_day=["MO", "WE", "FR"],
    )


@pytest.fixture
def now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture
def mock_credentials():
    """Mock google.oauth2.credentials.Credentials."""
    mock_instance = MagicMock()
    mock_instance.valid = True
    mock_instance.expired = False
    mock_instance.token = "test-access-token"
    mock_instance.refresh_token = "test-refresh-token"
    mock_instance.expiry = datetime.now(timezone.utc) + timedelta(hours=1)
    with patch("src.calendar_provider.google_provider.Credentials", return_value=mock_instance) as mock:
        yield mock, mock_instance


@pytest.fixture
def mock_request():
    """Mock google.auth.transport.requests.Request."""
    with patch("src.calendar_provider.google_provider.Request") as mock:
        yield mock


@pytest.fixture
def mock_build():
    """Mock googleapiclient.discovery.build."""
    mock_service = MagicMock()
    with patch("src.calendar_provider.google_provider.build", return_value=mock_service) as mock:
        yield mock, mock_service


@pytest.fixture
def mock_http_error():
    """Factory for creating mock HttpError instances."""
    from googleapiclient.errors import HttpError

    def _create(status_code: int = 404, reason: str = "Not Found") -> HttpError:
        mock_resp = MagicMock()
        mock_resp.status = status_code
        mock_resp.reason = reason
        return HttpError(mock_resp, content=b"{}")

    return _create


# ---------------------------------------------------------------------------
# Initialization tests
# ---------------------------------------------------------------------------


class TestGoogleCalendarProviderInit:
    """Tests for provider initialization."""

    def test_init_with_valid_config(self, google_config: ProviderConfig) -> None:
        provider = GoogleCalendarProvider(google_config)
        assert provider.config == google_config
        assert provider._service is None
        assert provider._credentials is None

    def test_provider_name(self, google_config: ProviderConfig) -> None:
        provider = GoogleCalendarProvider(google_config)
        assert provider.provider_name == "google"

    def test_scopes_default(self, google_config: ProviderConfig) -> None:
        assert "https://www.googleapis.com/auth/calendar" in GoogleCalendarProvider.SCOPES
        assert "https://www.googleapis.com/auth/calendar.events" in GoogleCalendarProvider.SCOPES


# ---------------------------------------------------------------------------
# Credential building tests
# ---------------------------------------------------------------------------


class TestBuildCredentials:
    """Tests for _build_credentials method."""

    def test_build_credentials_with_valid_config(
        self, google_config: ProviderConfig, mock_credentials: tuple
    ) -> None:
        mock_cls, mock_instance = mock_credentials
        provider = GoogleCalendarProvider(google_config)
        creds = provider._build_credentials()

        mock_cls.assert_called_once()
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["token"] == "test-access-token"
        assert call_kwargs["refresh_token"] == "test-refresh-token"
        assert call_kwargs["client_id"] == "test-client-id"
        assert call_kwargs["client_secret"] == "test-client-secret"

    def test_build_credentials_raises_on_missing_token(
        self, google_config_no_token: ProviderConfig
    ) -> None:
        provider = GoogleCalendarProvider(google_config_no_token)
        with pytest.raises(ValueError, match="access_token is required"):
            provider._build_credentials()

    def test_build_credentials_handles_naive_expiry(
        self, mock_credentials: tuple
    ) -> None:
        mock_cls, _ = mock_credentials
        config = ProviderConfig(
            provider="google",
            client_id="id",
            client_secret="secret",
            redirect_uri="http://localhost",
            scopes=["calendar"],
            access_token="token",
            token_expiry=datetime(2026, 1, 1, 12, 0, 0),  # naive
        )
        provider = GoogleCalendarProvider(config)
        provider._build_credentials()

        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["expiry"].tzinfo is not None


# ---------------------------------------------------------------------------
# Service creation tests
# ---------------------------------------------------------------------------


class TestGetService:
    """Tests for _get_service method."""

    def test_get_service_creates_service(
        self, google_config: ProviderConfig, mock_credentials: tuple, mock_build: tuple
    ) -> None:
        mock_cls, _ = mock_credentials
        mock_build_fn, mock_service = mock_build
        provider = GoogleCalendarProvider(google_config)

        service = provider._get_service()

        mock_build_fn.assert_called_once_with("calendar", "v3", credentials=mock_cls.return_value)
        assert service is mock_service
        assert provider._service is mock_service

    def test_get_service_reuses_existing_service(
        self, google_config: ProviderConfig, mock_credentials: tuple, mock_build: tuple
    ) -> None:
        mock_cls, _ = mock_credentials
        mock_build_fn, mock_service = mock_build
        provider = GoogleCalendarProvider(google_config)

        provider._get_service()
        provider._get_service()

        assert mock_build_fn.call_count == 1


# ---------------------------------------------------------------------------
# Authentication tests
# ---------------------------------------------------------------------------


class TestAuthenticate:
    """Tests for authenticate method."""

    @pytest.mark.asyncio
    async def test_authenticate_valid_token(
        self, google_config: ProviderConfig, mock_credentials: tuple
    ) -> None:
        mock_cls, mock_instance = mock_credentials
        mock_instance.valid = True
        mock_instance.expired = False

        provider = GoogleCalendarProvider(google_config)
        result = await provider.authenticate()

        assert result is True

    @pytest.mark.asyncio
    async def test_authenticate_refreshes_expired_token(
        self, google_config_expired: ProviderConfig, mock_credentials: tuple, mock_request: MagicMock
    ) -> None:
        mock_cls, mock_instance = mock_credentials
        mock_instance.expired = True
        mock_instance.refresh_token = "test-refresh-token"
        mock_instance.valid = True
        mock_instance.token = "refreshed-token"
        mock_instance.expiry = datetime.now(timezone.utc) + timedelta(hours=1)

        provider = GoogleCalendarProvider(google_config_expired)
        result = await provider.authenticate()

        mock_instance.refresh.assert_called_once()
        assert result is True
        assert provider.config.access_token == "refreshed-token"

    @pytest.mark.asyncio
    async def test_authenticate_returns_false_on_error(
        self, google_config: ProviderConfig
    ) -> None:
        with patch("src.calendar_provider.google_provider.Credentials", side_effect=Exception("auth error")):
            provider = GoogleCalendarProvider(google_config)
            result = await provider.authenticate()
            assert result is False

    @pytest.mark.asyncio
    async def test_authenticate_no_refresh_token_when_expired(
        self, google_config_expired: ProviderConfig
    ) -> None:
        config = ProviderConfig(
            provider="google",
            client_id="id",
            client_secret="secret",
            redirect_uri="http://localhost",
            scopes=["calendar"],
            access_token="expired-token",
            refresh_token=None,
            token_expiry=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = None
        mock_creds.token = "expired-token"

        with patch("src.calendar_provider.google_provider.Credentials", return_value=mock_creds):
            provider = GoogleCalendarProvider(config)
            result = await provider.authenticate()
            assert result is False


# ---------------------------------------------------------------------------
# List calendars tests
# ---------------------------------------------------------------------------


class TestListCalendars:
    """Tests for list_calendars method."""

    def _setup_list_calendars_mock(self, mock_build: tuple, items: list[dict]) -> MagicMock:
        mock_build_fn, mock_service = mock_build
        mock_cal_list = MagicMock()
        mock_cal_list_resp = MagicMock()
        mock_cal_list_resp.execute.return_value = {"items": items}
        mock_cal_list.list.return_value = mock_cal_list_resp
        mock_service.calendarList.return_value = mock_cal_list
        return mock_service

    @pytest.mark.asyncio
    async def test_list_calendars_returns_calendars(
        self, google_config: ProviderConfig, mock_credentials: tuple, mock_build: tuple
    ) -> None:
        mock_cls, _ = mock_credentials
        items = [
            {
                "id": "primary",
                "summary": "My Calendar",
                "description": "Primary calendar",
                "timeZone": "America/New_York",
                "primary": True,
                "accessRole": "owner",
                "backgroundColor": "#123456",
            },
            {
                "id": "work-calendar-id",
                "summary": "Work Calendar",
                "timeZone": "Europe/London",
                "primary": False,
                "accessRole": "writer",
            },
        ]
        self._setup_list_calendars_mock(mock_build, items)

        provider = GoogleCalendarProvider(google_config)
        calendars = await provider.list_calendars()

        assert len(calendars) == 2
        assert calendars[0].id == "primary"
        assert calendars[0].name == "My Calendar"
        assert calendars[0].timezone == "America/New_York"
        assert calendars[0].is_primary is True
        assert calendars[0].access_role == "owner"
        assert calendars[0].color == "#123456"
        assert calendars[1].id == "work-calendar-id"
        assert calendars[1].is_primary is False
        assert calendars[1].access_role == "writer"

    @pytest.mark.asyncio
    async def test_list_calendars_empty_result(
        self, google_config: ProviderConfig, mock_credentials: tuple, mock_build: tuple
    ) -> None:
        self._setup_list_calendars_mock(mock_build, [])

        provider = GoogleCalendarProvider(google_config)
        calendars = await provider.list_calendars()

        assert calendars == []

    @pytest.mark.asyncio
    async def test_list_calendars_handles_missing_fields(
        self, google_config: ProviderConfig, mock_credentials: tuple, mock_build: tuple
    ) -> None:
        items = [{"id": "minimal-cal"}]
        self._setup_list_calendars_mock(mock_build, items)

        provider = GoogleCalendarProvider(google_config)
        calendars = await provider.list_calendars()

        assert len(calendars) == 1
        assert calendars[0].id == "minimal-cal"
        assert calendars[0].name == ""
        assert calendars[0].timezone == "UTC"
        assert calendars[0].is_primary is False
        assert calendars[0].access_role == "reader"

    @pytest.mark.asyncio
    async def test_list_calendars_api_error(
        self, google_config: ProviderConfig, mock_credentials: tuple, mock_build: tuple, mock_http_error
    ) -> None:
        mock_cls, _ = mock_credentials
        mock_build_fn, mock_service = mock_build
        mock_cal_list = MagicMock()
        mock_cal_list.list.side_effect = mock_http_error(500, "Internal Server Error")
        mock_service.calendarList.return_value = mock_cal_list

        provider = GoogleCalendarProvider(google_config)
        with pytest.raises(ProviderAPIError) as exc_info:
            await provider.list_calendars()

        assert exc_info.value.status_code == 500
        assert "listing calendars" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_list_calendars_no_items_key(
        self, google_config: ProviderConfig, mock_credentials: tuple, mock_build: tuple
    ) -> None:
        mock_cls, _ = mock_credentials
        mock_build_fn, mock_service = mock_build
        mock_cal_list = MagicMock()
        mock_cal_list_resp = MagicMock()
        mock_cal_list_resp.execute.return_value = {}
        mock_cal_list.list.return_value = mock_cal_list_resp
        mock_service.calendarList.return_value = mock_cal_list

        provider = GoogleCalendarProvider(google_config)
        calendars = await provider.list_calendars()

        assert calendars == []


# ---------------------------------------------------------------------------
# Get events tests
# ---------------------------------------------------------------------------


class TestGetEvents:
    """Tests for get_events method."""

    def _setup_events_mock(self, mock_build: tuple, items: list[dict]) -> MagicMock:
        mock_build_fn, mock_service = mock_build
        mock_events_list = MagicMock()
        mock_events_resp = MagicMock()
        mock_events_resp.execute.return_value = {"items": items}
        mock_events_list.list.return_value = mock_events_resp
        mock_service.events.return_value = mock_events_list
        return mock_service

    @pytest.mark.asyncio
    async def test_get_events_returns_events(
        self, google_config: ProviderConfig, mock_credentials: tuple, mock_build: tuple, now: datetime
    ) -> None:
        items = [
            {
                "id": "event-1",
                "summary": "Meeting",
                "start": {"dateTime": now.isoformat(), "timeZone": "UTC"},
                "end": {"dateTime": (now + timedelta(hours=1)).isoformat(), "timeZone": "UTC"},
                "status": "confirmed",
                "created": now.isoformat(),
                "updated": now.isoformat(),
            }
        ]
        self._setup_events_mock(mock_build, items)

        provider = GoogleCalendarProvider(google_config)
        events = await provider.get_events(
            calendar_id="primary",
            start_time=now,
            end_time=now + timedelta(hours=2),
        )

        assert len(events) == 1
        assert events[0].id == "event-1"
        assert events[0].title == "Meeting"
        assert events[0].calendar_id == "primary"

    @pytest.mark.asyncio
    async def test_get_events_defaults_to_primary(
        self, google_config: ProviderConfig, mock_credentials: tuple, mock_build: tuple, now: datetime
    ) -> None:
        self._setup_events_mock(mock_build, [])

        provider = GoogleCalendarProvider(google_config)
        await provider.get_events(start_time=now, end_time=now + timedelta(hours=1))

        mock_build_fn, mock_service = mock_build
        mock_service.events.return_value.list.assert_called_once()
        call_kwargs = mock_service.events.return_value.list.call_args[1]
        assert call_kwargs["calendarId"] == "primary"

    @pytest.mark.asyncio
    async def test_get_events_defaults_start_time_to_now(
        self, google_config: ProviderConfig, mock_credentials: tuple, mock_build: tuple
    ) -> None:
        self._setup_events_mock(mock_build, [])

        provider = GoogleCalendarProvider(google_config)
        await provider.get_events()

        mock_build_fn, mock_service = mock_build
        call_kwargs = mock_service.events.return_value.list.call_args[1]
        assert "timeMin" in call_kwargs
        assert "timeMax" in call_kwargs

    @pytest.mark.asyncio
    async def test_get_events_expands_recurring(
        self, google_config: ProviderConfig, mock_credentials: tuple, mock_build: tuple, now: datetime
    ) -> None:
        self._setup_events_mock(mock_build, [])

        provider = GoogleCalendarProvider(google_config)
        await provider.get_events(start_time=now, end_time=now + timedelta(hours=1), expand_recurring=True)

        call_kwargs = mock_build[1].events.return_value.list.call_args[1]
        assert call_kwargs["singleEvents"] is True
        assert call_kwargs["orderBy"] == "startTime"

    @pytest.mark.asyncio
    async def test_get_events_does_not_expand_recurring(
        self, google_config: ProviderConfig, mock_credentials: tuple, mock_build: tuple, now: datetime
    ) -> None:
        self._setup_events_mock(mock_build, [])

        provider = GoogleCalendarProvider(google_config)
        await provider.get_events(start_time=now, end_time=now + timedelta(hours=1), expand_recurring=False)

        call_kwargs = mock_build[1].events.return_value.list.call_args[1]
        assert call_kwargs["singleEvents"] is False
        assert call_kwargs["orderBy"] is None

    @pytest.mark.asyncio
    async def test_get_events_calendar_not_found(
        self, google_config: ProviderConfig, mock_credentials: tuple, mock_build: tuple, mock_http_error, now: datetime
    ) -> None:
        mock_cls, _ = mock_credentials
        mock_build_fn, mock_service = mock_build
        mock_events_list = MagicMock()
        mock_events_list.list.side_effect = mock_http_error(404, "Not Found")
        mock_service.events.return_value = mock_events_list

        provider = GoogleCalendarProvider(google_config)
        with pytest.raises(CalendarNotFoundError) as exc_info:
            await provider.get_events(calendar_id="nonexistent", start_time=now, end_time=now + timedelta(hours=1))

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_events_api_error(
        self, google_config: ProviderConfig, mock_credentials: tuple, mock_build: tuple, mock_http_error, now: datetime
    ) -> None:
        mock_cls, _ = mock_credentials
        mock_build_fn, mock_service = mock_build
        mock_events_list = MagicMock()
        mock_events_list.list.side_effect = mock_http_error(500, "Server Error")
        mock_service.events.return_value = mock_events_list

        provider = GoogleCalendarProvider(google_config)
        with pytest.raises(ProviderAPIError) as exc_info:
            await provider.get_events(start_time=now, end_time=now + timedelta(hours=1))

        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_get_events_parses_all_day_events(
        self, google_config: ProviderConfig, mock_credentials: tuple, mock_build: tuple, now: datetime
    ) -> None:
        items = [
            {
                "id": "all-day-event",
                "summary": "Holiday",
                "start": {"date": "2026-04-20"},
                "end": {"date": "2026-04-21"},
                "status": "confirmed",
                "created": now.isoformat(),
                "updated": now.isoformat(),
            }
        ]
        self._setup_events_mock(mock_build, items)

        provider = GoogleCalendarProvider(google_config)
        events = await provider.get_events(start_time=now, end_time=now + timedelta(days=2))

        assert len(events) == 1
        assert events[0].timezone == "UTC"

    @pytest.mark.asyncio
    async def test_get_events_parses_attendees(
        self, google_config: ProviderConfig, mock_credentials: tuple, mock_build: tuple, now: datetime
    ) -> None:
        items = [
            {
                "id": "event-with-attendees",
                "summary": "Team Meeting",
                "start": {"dateTime": now.isoformat(), "timeZone": "UTC"},
                "end": {"dateTime": (now + timedelta(hours=1)).isoformat(), "timeZone": "UTC"},
                "status": "confirmed",
                "created": now.isoformat(),
                "updated": now.isoformat(),
                "attendees": [
                    {"email": "alice@example.com", "displayName": "Alice", "responseStatus": "accepted", "organizer": True},
                    {"email": "bob@example.com", "displayName": "Bob", "responseStatus": "needsAction"},
                ],
            }
        ]
        self._setup_events_mock(mock_build, items)

        provider = GoogleCalendarProvider(google_config)
        events = await provider.get_events(start_time=now, end_time=now + timedelta(hours=2))

        assert len(events[0].attendees) == 2
        assert events[0].attendees[0].is_organizer is True
        assert events[0].attendees[1].is_organizer is False

    @pytest.mark.asyncio
    async def test_get_events_parses_reminders(
        self, google_config: ProviderConfig, mock_credentials: tuple, mock_build: tuple, now: datetime
    ) -> None:
        items = [
            {
                "id": "event-with-reminders",
                "summary": "Meeting",
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
        ]
        self._setup_events_mock(mock_build, items)

        provider = GoogleCalendarProvider(google_config)
        events = await provider.get_events(start_time=now, end_time=now + timedelta(hours=2))

        assert len(events[0].reminders) == 2
        assert events[0].reminders[0].method == "email"
        assert events[0].reminders[0].minutes_before == 60

    @pytest.mark.asyncio
    async def test_get_events_parses_recurrence(
        self, google_config: ProviderConfig, mock_credentials: tuple, mock_build: tuple, now: datetime
    ) -> None:
        items = [
            {
                "id": "recurring-event",
                "summary": "Weekly Standup",
                "start": {"dateTime": now.isoformat(), "timeZone": "UTC"},
                "end": {"dateTime": (now + timedelta(hours=1)).isoformat(), "timeZone": "UTC"},
                "status": "confirmed",
                "created": now.isoformat(),
                "updated": now.isoformat(),
                "recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR"],
            }
        ]
        self._setup_events_mock(mock_build, items)

        provider = GoogleCalendarProvider(google_config)
        events = await provider.get_events(start_time=now, end_time=now + timedelta(hours=2))

        assert events[0].recurrence is not None
        assert events[0].recurrence.frequency == "weekly"
        assert events[0].recurrence.by_day == ["MO", "WE", "FR"]
        assert events[0].is_recurring_master is True

    @pytest.mark.asyncio
    async def test_get_events_parses_recurring_instance(
        self, google_config: ProviderConfig, mock_credentials: tuple, mock_build: tuple, now: datetime
    ) -> None:
        items = [
            {
                "id": "instance-1",
                "summary": "Weekly Standup",
                "start": {"dateTime": now.isoformat(), "timeZone": "UTC"},
                "end": {"dateTime": (now + timedelta(hours=1)).isoformat(), "timeZone": "UTC"},
                "status": "confirmed",
                "created": now.isoformat(),
                "updated": now.isoformat(),
                "recurringEventId": "master-event-id",
            }
        ]
        self._setup_events_mock(mock_build, items)

        provider = GoogleCalendarProvider(google_config)
        events = await provider.get_events(start_time=now, end_time=now + timedelta(hours=2))

        assert events[0].recurrence_id == "master-event-id"
        assert events[0].is_recurring_master is False


# ---------------------------------------------------------------------------
# Create event tests
# ---------------------------------------------------------------------------


class TestCreateEvent:
    """Tests for create_event method."""

    @pytest.mark.asyncio
    async def test_create_event_success(
        self, google_config: ProviderConfig, mock_credentials: tuple, mock_build: tuple, now: datetime,
        sample_attendee: EventAttendee, sample_reminder: EventReminder
    ) -> None:
        mock_cls, _ = mock_credentials
        mock_build_fn, mock_service = mock_build

        created_event = {
            "id": "new-event-id",
            "summary": "New Meeting",
            "description": "Description here",
            "location": "Room A",
            "start": {"dateTime": now.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": (now + timedelta(hours=1)).isoformat(), "timeZone": "UTC"},
            "status": "confirmed",
            "created": now.isoformat(),
            "updated": now.isoformat(),
            "attendees": [{"email": "attendee@example.com", "displayName": "John Doe"}],
            "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 15}]},
        }

        mock_insert = MagicMock()
        mock_insert.execute.return_value = created_event
        mock_insert.insert.return_value = mock_insert
        mock_service.events.return_value = mock_insert

        provider = GoogleCalendarProvider(google_config)
        event = await provider.create_event(
            title="New Meeting",
            start=now,
            end=now + timedelta(hours=1),
            timezone="UTC",
            description="Description here",
            location="Room A",
            attendees=[sample_attendee],
            reminders=[sample_reminder],
        )

        assert event.id == "new-event-id"
        assert event.title == "New Meeting"
        mock_service.events.return_value.insert.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_event_validation_error_end_before_start(
        self, google_config: ProviderConfig, now: datetime
    ) -> None:
        provider = GoogleCalendarProvider(google_config)
        with pytest.raises(ValidationError, match="end time must be after start time"):
            await provider.create_event(
                title="Bad Event",
                start=now + timedelta(hours=1),
                end=now,
                timezone="UTC",
            )

    @pytest.mark.asyncio
    async def test_create_event_validation_error_same_time(
        self, google_config: ProviderConfig, now: datetime
    ) -> None:
        provider = GoogleCalendarProvider(google_config)
        with pytest.raises(ValidationError, match="end time must be after start time"):
            await provider.create_event(
                title="Bad Event",
                start=now,
                end=now,
                timezone="UTC",
            )

    @pytest.mark.asyncio
    async def test_create_event_calendar_not_found(
        self, google_config: ProviderConfig, mock_credentials: tuple, mock_build: tuple, mock_http_error, now: datetime
    ) -> None:
        mock_cls, _ = mock_credentials
        mock_build_fn, mock_service = mock_build
        mock_insert = MagicMock()
        mock_insert.insert.side_effect = mock_http_error(404, "Not Found")
        mock_service.events.return_value = mock_insert

        provider = GoogleCalendarProvider(google_config)
        with pytest.raises(CalendarNotFoundError) as exc_info:
            await provider.create_event(
                title="Meeting",
                start=now,
                end=now + timedelta(hours=1),
                timezone="UTC",
                calendar_id="nonexistent",
            )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_create_event_api_error(
        self, google_config: ProviderConfig, mock_credentials: tuple, mock_build: tuple, mock_http_error, now: datetime
    ) -> None:
        mock_cls, _ = mock_credentials
        mock_build_fn, mock_service = mock_build
        mock_insert = MagicMock()
        mock_insert.insert.side_effect = mock_http_error(400, "Bad Request")
        mock_service.events.return_value = mock_insert

        provider = GoogleCalendarProvider(google_config)
        with pytest.raises(ProviderAPIError) as exc_info:
            await provider.create_event(
                title="Meeting",
                start=now,
                end=now + timedelta(hours=1),
                timezone="UTC",
            )

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_create_event_with_recurrence(
        self, google_config: ProviderConfig, mock_credentials: tuple, mock_build: tuple, now: datetime,
        sample_recurrence: RecurrenceRule
    ) -> None:
        mock_cls, _ = mock_credentials
        mock_build_fn, mock_service = mock_build

        created_event = {
            "id": "recurring-new",
            "summary": "Weekly Sync",
            "start": {"dateTime": now.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": (now + timedelta(hours=1)).isoformat(), "timeZone": "UTC"},
            "status": "confirmed",
            "created": now.isoformat(),
            "updated": now.isoformat(),
            "recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR"],
        }

        mock_insert = MagicMock()
        mock_insert.execute.return_value = created_event
        mock_insert.insert.return_value = mock_insert
        mock_service.events.return_value = mock_insert

        provider = GoogleCalendarProvider(google_config)
        event = await provider.create_event(
            title="Weekly Sync",
            start=now,
            end=now + timedelta(hours=1),
            timezone="UTC",
            recurrence=sample_recurrence,
        )

        assert event.recurrence is not None
        assert event.recurrence.frequency == "weekly"


# ---------------------------------------------------------------------------
# Update event tests
# ---------------------------------------------------------------------------


class TestUpdateEvent:
    """Tests for update_event method."""

    def _setup_get_event_mock(self, mock_service: MagicMock, event_data: dict) -> None:
        mock_get = MagicMock()
        mock_get.execute.return_value = event_data
        mock_get.get.return_value = mock_get
        mock_service.events.return_value = mock_get

    def _setup_update_event_mock(self, mock_service: MagicMock, updated_data: dict) -> None:
        mock_update = MagicMock()
        mock_update.execute.return_value = updated_data
        mock_update.update.return_value = mock_update
        mock_service.events.return_value = mock_update

    @pytest.mark.asyncio
    async def test_update_event_success(
        self, google_config: ProviderConfig, mock_credentials: tuple, mock_build: tuple, now: datetime
    ) -> None:
        mock_cls, _ = mock_credentials
        mock_build_fn, mock_service = mock_build

        existing_event = {
            "id": "event-123",
            "summary": "Old Title",
            "start": {"dateTime": now.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": (now + timedelta(hours=1)).isoformat(), "timeZone": "UTC"},
            "status": "confirmed",
            "created": now.isoformat(),
            "updated": now.isoformat(),
        }

        updated_event = {
            "id": "event-123",
            "summary": "New Title",
            "start": {"dateTime": now.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": (now + timedelta(hours=1)).isoformat(), "timeZone": "UTC"},
            "status": "confirmed",
            "created": now.isoformat(),
            "updated": (now + timedelta(hours=1)).isoformat(),
        }

        mock_get = MagicMock()
        mock_get.execute.return_value = existing_event
        mock_get.get.return_value = mock_get

        mock_update = MagicMock()
        mock_update.execute.return_value = updated_event
        mock_update.update.return_value = mock_update

        mock_service.events.side_effect = [mock_get, mock_update]

        provider = GoogleCalendarProvider(google_config)
        event = await provider.update_event(
            event_id="event-123",
            title="New Title",
        )

        assert event.title == "New Title"

    @pytest.mark.asyncio
    async def test_update_event_not_found(
        self, google_config: ProviderConfig, mock_credentials: tuple, mock_build: tuple, mock_http_error, now: datetime
    ) -> None:
        mock_cls, _ = mock_credentials
        mock_build_fn, mock_service = mock_build
        mock_get = MagicMock()
        mock_get.get.side_effect = mock_http_error(404, "Not Found")
        mock_service.events.return_value = mock_get

        provider = GoogleCalendarProvider(google_config)
        with pytest.raises(EventNotFoundError) as exc_info:
            await provider.update_event(event_id="nonexistent", title="New Title")

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_update_event_etag_conflict(
        self, google_config: ProviderConfig, mock_credentials: tuple, mock_build: tuple, now: datetime
    ) -> None:
        mock_cls, _ = mock_credentials
        mock_build_fn, mock_service = mock_build

        existing_event = {
            "id": "event-123",
            "summary": "Old Title",
            "etag": "old-etag",
            "start": {"dateTime": now.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": (now + timedelta(hours=1)).isoformat(), "timeZone": "UTC"},
            "status": "confirmed",
            "created": now.isoformat(),
            "updated": now.isoformat(),
        }

        mock_get = MagicMock()
        mock_get.execute.return_value = existing_event
        mock_get.get.return_value = mock_get
        mock_service.events.return_value = mock_get

        provider = GoogleCalendarProvider(google_config)
        with pytest.raises(ConflictError) as exc_info:
            await provider.update_event(
                event_id="event-123",
                title="New Title",
                etag="different-etag",
            )

        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_update_event_validation_error(
        self, google_config: ProviderConfig, mock_credentials: tuple, mock_build: tuple, now: datetime
    ) -> None:
        mock_cls, _ = mock_credentials
        mock_build_fn, mock_service = mock_build

        existing_event = {
            "id": "event-123",
            "summary": "Title",
            "start": {"dateTime": now.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": (now + timedelta(hours=1)).isoformat(), "timeZone": "UTC"},
            "status": "confirmed",
            "created": now.isoformat(),
            "updated": now.isoformat(),
        }

        mock_get = MagicMock()
        mock_get.execute.return_value = existing_event
        mock_get.get.return_value = mock_get
        mock_service.events.return_value = mock_get

        provider = GoogleCalendarProvider(google_config)
        with pytest.raises(ValidationError, match="end time must be after start time"):
            await provider.update_event(
                event_id="event-123",
                start=now + timedelta(hours=2),
                end=now + timedelta(hours=1),
            )

    @pytest.mark.asyncio
    async def test_update_event_http_error_on_update(
        self, google_config: ProviderConfig, mock_credentials: tuple, mock_build: tuple, mock_http_error, now: datetime
    ) -> None:
        mock_cls, _ = mock_credentials
        mock_build_fn, mock_service = mock_build

        existing_event = {
            "id": "event-123",
            "summary": "Title",
            "start": {"dateTime": now.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": (now + timedelta(hours=1)).isoformat(), "timeZone": "UTC"},
            "status": "confirmed",
            "created": now.isoformat(),
            "updated": now.isoformat(),
        }

        mock_get = MagicMock()
        mock_get.execute.return_value = existing_event
        mock_get.get.return_value = mock_get

        mock_update = MagicMock()
        mock_update.update.side_effect = mock_http_error(412, "Precondition Failed")

        mock_service.events.side_effect = [mock_get, mock_update]

        provider = GoogleCalendarProvider(google_config)
        with pytest.raises(ConflictError) as exc_info:
            await provider.update_event(event_id="event-123", title="New Title", etag="some-etag")

        assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# Delete event tests
# ---------------------------------------------------------------------------


class TestDeleteEvent:
    """Tests for delete_event method."""

    @pytest.mark.asyncio
    async def test_delete_event_success(
        self, google_config: ProviderConfig, mock_credentials: tuple, mock_build: tuple
    ) -> None:
        mock_cls, _ = mock_credentials
        mock_build_fn, mock_service = mock_build

        mock_delete = MagicMock()
        mock_delete.execute.return_value = None
        mock_delete.delete.return_value = mock_delete
        mock_service.events.return_value = mock_delete

        provider = GoogleCalendarProvider(google_config)
        result = await provider.delete_event(event_id="event-123")

        assert result is True

    @pytest.mark.asyncio
    async def test_delete_event_not_found(
        self, google_config: ProviderConfig, mock_credentials: tuple, mock_build: tuple, mock_http_error
    ) -> None:
        mock_cls, _ = mock_credentials
        mock_build_fn, mock_service = mock_build
        mock_delete = MagicMock()
        mock_delete.delete.side_effect = mock_http_error(404, "Not Found")
        mock_service.events.return_value = mock_delete

        provider = GoogleCalendarProvider(google_config)
        with pytest.raises(EventNotFoundError) as exc_info:
            await provider.delete_event(event_id="nonexistent")

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_event_api_error(
        self, google_config: ProviderConfig, mock_credentials: tuple, mock_build: tuple, mock_http_error
    ) -> None:
        mock_cls, _ = mock_credentials
        mock_build_fn, mock_service = mock_build
        mock_delete = MagicMock()
        mock_delete.delete.side_effect = mock_http_error(500, "Server Error")
        mock_service.events.return_value = mock_delete

        provider = GoogleCalendarProvider(google_config)
        with pytest.raises(ProviderAPIError) as exc_info:
            await provider.delete_event(event_id="event-123")

        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_delete_event_defaults_to_primary(
        self, google_config: ProviderConfig, mock_credentials: tuple, mock_build: tuple
    ) -> None:
        mock_cls, _ = mock_credentials
        mock_build_fn, mock_service = mock_build

        mock_delete = MagicMock()
        mock_delete.execute.return_value = None
        mock_delete.delete.return_value = mock_delete
        mock_service.events.return_value = mock_delete

        provider = GoogleCalendarProvider(google_config)
        await provider.delete_event(event_id="event-123")

        call_kwargs = mock_service.events.return_value.delete.call_args[1]
        assert call_kwargs["calendarId"] == "primary"

    @pytest.mark.asyncio
    async def test_delete_event_send_notifications(
        self, google_config: ProviderConfig, mock_credentials: tuple, mock_build: tuple
    ) -> None:
        mock_cls, _ = mock_credentials
        mock_build_fn, mock_service = mock_build

        mock_delete = MagicMock()
        mock_delete.execute.return_value = None
        mock_delete.delete.return_value = mock_delete
        mock_service.events.return_value = mock_delete

        provider = GoogleCalendarProvider(google_config)
        await provider.delete_event(event_id="event-123", send_notifications=False)

        call_kwargs = mock_service.events.return_value.delete.call_args[1]
        assert call_kwargs["sendNotifications"] is False


# ---------------------------------------------------------------------------
# Free/busy tests
# ---------------------------------------------------------------------------


class TestGetFreeBusy:
    """Tests for get_free_busy method."""

    @pytest.mark.asyncio
    async def test_get_free_busy_returns_slots(
        self, google_config: ProviderConfig, mock_credentials: tuple, mock_build: tuple, now: datetime
    ) -> None:
        mock_cls, _ = mock_credentials
        mock_build_fn, mock_service = mock_build

        freebusy_result = {
            "calendars": {
                "primary": {
                    "busy": [
                        {"start": now.isoformat(), "end": (now + timedelta(hours=1)).isoformat()},
                        {"start": (now + timedelta(hours=2)).isoformat(), "end": (now + timedelta(hours=3)).isoformat()},
                    ]
                }
            }
        }

        mock_query = MagicMock()
        mock_query.execute.return_value = freebusy_result
        mock_query.query.return_value = mock_query
        mock_service.freebusy.return_value = mock_query

        # Mock list_calendars to return calendar IDs
        mock_cal_list = MagicMock()
        mock_cal_list_resp = MagicMock()
        mock_cal_list_resp.execute.return_value = {"items": [{"id": "primary"}]}
        mock_cal_list.list.return_value = mock_cal_list_resp
        mock_service.calendarList.return_value = mock_cal_list

        provider = GoogleCalendarProvider(google_config)
        slots = await provider.get_free_busy(
            start_time=now,
            end_time=now + timedelta(hours=4),
            calendar_ids=["primary"],
        )

        assert len(slots) == 2
        assert slots[0].status == "busy"

    @pytest.mark.asyncio
    async def test_get_free_busy_defaults_to_all_calendars(
        self, google_config: ProviderConfig, mock_credentials: tuple, mock_build: tuple, now: datetime
    ) -> None:
        mock_cls, _ = mock_credentials
        mock_build_fn, mock_service = mock_build

        freebusy_result = {"calendars": {}}

        mock_query = MagicMock()
        mock_query.execute.return_value = freebusy_result
        mock_query.query.return_value = mock_query
        mock_service.freebusy.return_value = mock_query

        # Mock list_calendars
        mock_cal_list = MagicMock()
        mock_cal_list_resp = MagicMock()
        mock_cal_list_resp.execute.return_value = {
            "items": [
                {"id": "cal-1", "summary": "Cal 1", "timeZone": "UTC", "accessRole": "owner"},
                {"id": "cal-2", "summary": "Cal 2", "timeZone": "UTC", "accessRole": "owner"},
            ]
        }
        mock_cal_list.list.return_value = mock_cal_list_resp
        mock_service.calendarList.return_value = mock_cal_list

        provider = GoogleCalendarProvider(google_config)
        slots = await provider.get_free_busy(
            start_time=now,
            end_time=now + timedelta(hours=1),
        )

        assert slots == []
        mock_query.query.assert_called_once()
        body = mock_query.query.call_args[1]["body"]
        assert len(body["items"]) == 2

    @pytest.mark.asyncio
    async def test_get_free_busy_api_error(
        self, google_config: ProviderConfig, mock_credentials: tuple, mock_build: tuple, mock_http_error, now: datetime
    ) -> None:
        mock_cls, _ = mock_credentials
        mock_build_fn, mock_service = mock_build
        mock_query = MagicMock()
        mock_query.query.side_effect = mock_http_error(500, "Server Error")
        mock_service.freebusy.return_value = mock_query

        provider = GoogleCalendarProvider(google_config)
        with pytest.raises(ProviderAPIError) as exc_info:
            await provider.get_free_busy(
                start_time=now,
                end_time=now + timedelta(hours=1),
                calendar_ids=["primary"],
            )

        assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# Close tests
# ---------------------------------------------------------------------------


class TestClose:
    """Tests for close method."""

    @pytest.mark.asyncio
    async def test_close_clears_resources(
        self, google_config: ProviderConfig, mock_credentials: tuple, mock_build: tuple
    ) -> None:
        mock_cls, _ = mock_credentials
        mock_build_fn, mock_service = mock_build

        provider = GoogleCalendarProvider(google_config)
        provider._service = mock_service
        provider._credentials = mock_cls.return_value

        await provider.close()

        assert provider._service is None
        assert provider._credentials is None


# ---------------------------------------------------------------------------
# Internal helper tests
# ---------------------------------------------------------------------------


class TestFormatDatetime:
    """Tests for _format_datetime static method."""

    def test_format_aware_datetime(self) -> None:
        dt = datetime(2026, 4, 20, 12, 0, 0, tzinfo=timezone.utc)
        result = GoogleCalendarProvider._format_datetime(dt)
        assert "2026-04-20" in result
        assert "+00:00" in result

    def test_format_naive_datetime(self) -> None:
        dt = datetime(2026, 4, 20, 12, 0, 0)
        result = GoogleCalendarProvider._format_datetime(dt)
        assert "2026-04-20" in result


class TestParseDatetime:
    """Tests for _parse_datetime static method."""

    def test_parse_aware_datetime(self) -> None:
        result = GoogleCalendarProvider._parse_datetime("2026-04-20T12:00:00+00:00")
        assert result.tzinfo is not None
        assert result.year == 2026
        assert result.month == 4
        assert result.day == 20

    def test_parse_naive_datetime(self) -> None:
        result = GoogleCalendarProvider._parse_datetime("2026-04-20T12:00:00")
        assert result.tzinfo is not None


class TestBuildRrule:
    """Tests for _build_rrule static method."""

    def test_build_simple_rrule(self) -> None:
        rule = RecurrenceRule(frequency="weekly", interval=1)
        result = GoogleCalendarProvider._build_rrule(rule)
        assert result == "RRULE:FREQ=WEEKLY"

    def test_build_rrule_with_interval(self) -> None:
        rule = RecurrenceRule(frequency="weekly", interval=2)
        result = GoogleCalendarProvider._build_rrule(rule)
        assert "FREQ=WEEKLY" in result
        assert "INTERVAL=2" in result

    def test_build_rrule_with_count(self) -> None:
        rule = RecurrenceRule(frequency="daily", count=10)
        result = GoogleCalendarProvider._build_rrule(rule)
        assert "FREQ=DAILY" in result
        assert "COUNT=10" in result

    def test_build_rrule_with_until(self) -> None:
        until = datetime(2026, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
        rule = RecurrenceRule(frequency="monthly", until=until)
        result = GoogleCalendarProvider._build_rrule(rule)
        assert "FREQ=MONTHLY" in result
        assert "UNTIL=20261231T235959Z" in result

    def test_build_rrule_with_by_day(self) -> None:
        rule = RecurrenceRule(frequency="weekly", by_day=["MO", "WE", "FR"])
        result = GoogleCalendarProvider._build_rrule(rule)
        assert "BYDAY=MO,WE,FR" in result

    def test_build_rrule_with_by_month_day(self) -> None:
        rule = RecurrenceRule(frequency="monthly", by_month_day=[1, 15])
        result = GoogleCalendarProvider._build_rrule(rule)
        assert "BYMONTHDAY=1,15" in result

    def test_build_rrule_complex(self) -> None:
        until = datetime(2027, 1, 1, tzinfo=timezone.utc)
        rule = RecurrenceRule(
            frequency="weekly",
            interval=2,
            count=20,
            by_day=["MO", "FR"],
        )
        result = GoogleCalendarProvider._build_rrule(rule)
        assert "FREQ=WEEKLY" in result
        assert "INTERVAL=2" in result
        assert "COUNT=20" in result
        assert "BYDAY=MO,FR" in result


class TestParseRecurrence:
    """Tests for _parse_recurrence method."""

    def test_parse_simple_rrule(self, google_config: ProviderConfig) -> None:
        provider = GoogleCalendarProvider(google_config)
        result = provider._parse_recurrence(["RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR"])

        assert result is not None
        assert result.frequency == "weekly"
        assert result.by_day == ["MO", "WE", "FR"]

    def test_parse_rrule_with_interval(self, google_config: ProviderConfig) -> None:
        provider = GoogleCalendarProvider(google_config)
        result = provider._parse_recurrence(["RRULE:FREQ=DAILY;INTERVAL=3"])

        assert result is not None
        assert result.frequency == "daily"
        assert result.interval == 3

    def test_parse_rrule_with_count(self, google_config: ProviderConfig) -> None:
        provider = GoogleCalendarProvider(google_config)
        result = provider._parse_recurrence(["RRULE:FREQ=WEEKLY;COUNT=10"])

        assert result is not None
        assert result.count == 10

    def test_parse_rrule_with_until(self, google_config: ProviderConfig) -> None:
        provider = GoogleCalendarProvider(google_config)
        result = provider._parse_recurrence(["RRULE:FREQ=MONTHLY;UNTIL=20261231T235959Z"])

        assert result is not None
        assert result.until is not None
        assert result.until.year == 2026
        assert result.until.month == 12

    def test_parse_rrule_with_by_month_day(self, google_config: ProviderConfig) -> None:
        provider = GoogleCalendarProvider(google_config)
        result = provider._parse_recurrence(["RRULE:FREQ=MONTHLY;BYMONTHDAY=1,15"])

        assert result is not None
        assert result.by_month_day == [1, 15]

    def test_parse_empty_list(self, google_config: ProviderConfig) -> None:
        provider = GoogleCalendarProvider(google_config)
        result = provider._parse_recurrence([])
        assert result is None

    def test_parse_none(self, google_config: ProviderConfig) -> None:
        provider = GoogleCalendarProvider(google_config)
        result = provider._parse_recurrence(None)
        assert result is None

    def test_parse_invalid_rrule(self, google_config: ProviderConfig) -> None:
        provider = GoogleCalendarProvider(google_config)
        result = provider._parse_recurrence(["INVALID"])
        assert result is None

    def test_parse_rrule_without_freq(self, google_config: ProviderConfig) -> None:
        provider = GoogleCalendarProvider(google_config)
        result = provider._parse_recurrence(["RRULE:INTERVAL=2"])
        assert result is None


class TestBuildEventBody:
    """Tests for _build_event_body method."""

    def test_build_minimal_body(
        self, google_config: ProviderConfig, now: datetime
    ) -> None:
        provider = GoogleCalendarProvider(google_config)
        body = provider._build_event_body(
            title="Meeting",
            start=now,
            end=now + timedelta(hours=1),
            timezone="UTC",
        )

        assert body["summary"] == "Meeting"
        assert "dateTime" in body["start"]
        assert "timeZone" in body["start"]
        assert body["start"]["timeZone"] == "UTC"

    def test_build_body_with_all_fields(
        self, google_config: ProviderConfig, now: datetime,
        sample_attendee: EventAttendee, sample_reminder: EventReminder, sample_recurrence: RecurrenceRule
    ) -> None:
        provider = GoogleCalendarProvider(google_config)
        body = provider._build_event_body(
            title="Full Meeting",
            start=now,
            end=now + timedelta(hours=1),
            timezone="America/New_York",
            description="Detailed description",
            location="Room B",
            attendees=[sample_attendee],
            reminders=[sample_reminder],
            recurrence=sample_recurrence,
        )

        assert body["summary"] == "Full Meeting"
        assert body["description"] == "Detailed description"
        assert body["location"] == "Room B"
        assert len(body["attendees"]) == 1
        assert body["attendees"][0]["email"] == "attendee@example.com"
        assert "reminders" in body
        assert body["reminders"]["useDefault"] is False
        assert len(body["reminders"]["overrides"]) == 1
        assert "recurrence" in body
        assert isinstance(body["recurrence"], list)

    def test_build_body_skips_optional_none_fields(
        self, google_config: ProviderConfig, now: datetime
    ) -> None:
        provider = GoogleCalendarProvider(google_config)
        body = provider._build_event_body(
            title="Minimal",
            start=now,
            end=now + timedelta(hours=1),
            timezone="UTC",
            description=None,
            location=None,
            attendees=None,
            reminders=None,
            recurrence=None,
        )

        assert "description" not in body
        assert "location" not in body
        assert "attendees" not in body
        assert "reminders" not in body
        assert "recurrence" not in body


class TestMergeEventBody:
    """Tests for _merge_event_body method."""

    def test_merge_title_only(
        self, google_config: ProviderConfig, now: datetime
    ) -> None:
        provider = GoogleCalendarProvider(google_config)
        existing = {
            "id": "event-1",
            "summary": "Old Title",
            "start": {"dateTime": now.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": (now + timedelta(hours=1)).isoformat(), "timeZone": "UTC"},
            "status": "confirmed",
        }

        body = provider._merge_event_body(existing, title="New Title")

        assert body["summary"] == "New Title"
        assert body["start"] == existing["start"]
        assert body["end"] == existing["end"]

    def test_merge_does_not_modify_existing(
        self, google_config: ProviderConfig, now: datetime
    ) -> None:
        provider = GoogleCalendarProvider(google_config)
        existing = {
            "id": "event-1",
            "summary": "Title",
            "start": {"dateTime": now.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": (now + timedelta(hours=1)).isoformat(), "timeZone": "UTC"},
            "status": "confirmed",
        }

        provider._merge_event_body(existing, title="New Title")

        assert existing["summary"] == "Title"

    def test_merge_status(
        self, google_config: ProviderConfig, now: datetime
    ) -> None:
        provider = GoogleCalendarProvider(google_config)
        existing = {
            "id": "event-1",
            "summary": "Title",
            "start": {"dateTime": now.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": (now + timedelta(hours=1)).isoformat(), "timeZone": "UTC"},
            "status": "confirmed",
        }

        body = provider._merge_event_body(existing, status="cancelled")

        assert body["status"] == "cancelled"

    def test_merge_none_fields_preserve_existing(
        self, google_config: ProviderConfig, now: datetime
    ) -> None:
        provider = GoogleCalendarProvider(google_config)
        existing = {
            "id": "event-1",
            "summary": "Title",
            "description": "Description",
            "start": {"dateTime": now.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": (now + timedelta(hours=1)).isoformat(), "timeZone": "UTC"},
            "status": "confirmed",
        }

        body = provider._merge_event_body(existing, title=None, description=None)

        assert body["summary"] == "Title"
        assert body["description"] == "Description"


# ---------------------------------------------------------------------------
# Exception class tests
# ---------------------------------------------------------------------------


class TestExceptionClasses:
    """Tests for custom exception classes."""

    def test_provider_api_error(self) -> None:
        exc = ProviderAPIError("API error", status_code=500)
        assert str(exc) == "API error"
        assert exc.status_code == 500

    def test_provider_api_error_no_status(self) -> None:
        exc = ProviderAPIError("API error")
        assert exc.status_code is None

    def test_authentication_error(self) -> None:
        exc = AuthenticationError("Auth failed", status_code=401)
        assert isinstance(exc, ProviderAPIError)
        assert exc.status_code == 401

    def test_calendar_not_found_error(self) -> None:
        exc = CalendarNotFoundError("Calendar missing", status_code=404)
        assert isinstance(exc, ProviderAPIError)
        assert exc.status_code == 404

    def test_event_not_found_error(self) -> None:
        exc = EventNotFoundError("Event missing", status_code=404)
        assert isinstance(exc, ProviderAPIError)
        assert exc.status_code == 404

    def test_conflict_error(self) -> None:
        exc = ConflictError("Conflict", status_code=409)
        assert isinstance(exc, ProviderAPIError)
        assert exc.status_code == 409

    def test_validation_error(self) -> None:
        exc = ValidationError("Invalid data", status_code=400)
        assert isinstance(exc, ProviderAPIError)
        assert exc.status_code == 400
