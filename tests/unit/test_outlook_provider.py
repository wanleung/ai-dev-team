"""Unit tests for the Outlook Calendar provider implementation.

Tests cover all public methods of `OutlookCalendarProvider`:
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
from unittest.mock import MagicMock, patch, AsyncMock
from typing import Any

import pytest
import pytest_asyncio

from src.calendar_provider.outlook_provider import (
    OutlookCalendarProvider,
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
def outlook_config() -> ProviderConfig:
    """Valid Outlook provider config with non-expired tokens."""
    return ProviderConfig(
        provider="outlook",
        client_id="test-client-id",
        client_secret="test-client-secret",
        redirect_uri="http://localhost:8080/callback",
        scopes=[
            "Calendars.Read",
            "Calendars.ReadWrite",
            "User.Read",
        ],
        access_token="test-access-token",
        refresh_token="test-refresh-token",
        token_expiry=datetime.now(timezone.utc) + timedelta(hours=1),
    )


@pytest.fixture
def outlook_config_expired() -> ProviderConfig:
    """Outlook provider config with an expired token."""
    return ProviderConfig(
        provider="outlook",
        client_id="test-client-id",
        client_secret="test-client-secret",
        redirect_uri="http://localhost:8080/callback",
        scopes=[
            "Calendars.Read",
            "Calendars.ReadWrite",
            "User.Read",
        ],
        access_token="expired-access-token",
        refresh_token="test-refresh-token",
        token_expiry=datetime.now(timezone.utc) - timedelta(hours=1),
    )


@pytest.fixture
def outlook_config_no_token() -> ProviderConfig:
    """Outlook provider config without any access token."""
    return ProviderConfig(
        provider="outlook",
        client_id="test-client-id",
        client_secret="test-client-secret",
        redirect_uri="http://localhost:8080/callback",
        scopes=[
            "Calendars.Read",
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


# ---------------------------------------------------------------------------
# Initialization tests
# ---------------------------------------------------------------------------


class TestOutlookCalendarProviderInit:
    """Tests for provider initialization."""

    def test_init_with_valid_config(self, outlook_config: ProviderConfig) -> None:
        provider = OutlookCalendarProvider(outlook_config)
        assert provider.config == outlook_config
        assert provider._client is None
        assert provider._http_client is None

    def test_provider_name(self, outlook_config: ProviderConfig) -> None:
        provider = OutlookCalendarProvider(outlook_config)
        assert provider.provider_name == "outlook"

    def test_scopes_default(self) -> None:
        assert "Calendars.Read" in OutlookCalendarProvider.SCOPES
        assert "Calendars.ReadWrite" in OutlookCalendarProvider.SCOPES
        assert "User.Read" in OutlookCalendarProvider.SCOPES


# ---------------------------------------------------------------------------
# Graph client building tests
# ---------------------------------------------------------------------------


class TestBuildGraphClient:
    """Tests for _build_graph_client method."""

    def test_build_client_with_valid_config(self, outlook_config: ProviderConfig) -> None:
        provider = OutlookCalendarProvider(outlook_config)
        client = provider._build_graph_client()

        assert client is not None

    def test_build_client_raises_on_missing_token(
        self, outlook_config_no_token: ProviderConfig
    ) -> None:
        provider = OutlookCalendarProvider(outlook_config_no_token)
        with pytest.raises(ValueError, match="access_token is required"):
            provider._build_graph_client()


class TestGetClient:
    """Tests for _get_client method."""

    def test_get_client_creates_client(self, outlook_config: ProviderConfig) -> None:
        provider = OutlookCalendarProvider(outlook_config)

        client = provider._get_client()

        assert client is not None
        assert provider._client is client

    def test_get_client_reuses_existing_client(self, outlook_config: ProviderConfig) -> None:
        provider = OutlookCalendarProvider(outlook_config)

        client1 = provider._get_client()
        client2 = provider._get_client()

        assert client1 is client2


# ---------------------------------------------------------------------------
# Authentication tests
# ---------------------------------------------------------------------------


class TestAuthenticate:
    """Tests for authenticate method."""

    @pytest.mark.asyncio
    async def test_authenticate_valid_token(
        self, outlook_config: ProviderConfig
    ) -> None:
        provider = OutlookCalendarProvider(outlook_config)
        result = await provider.authenticate()

        assert result is True

    @pytest.mark.asyncio
    async def test_authenticate_refreshes_expired_token(
        self, outlook_config_expired: ProviderConfig
    ) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "refreshed-access-token",
            "refresh_token": "new-refresh-token",
            "expires_in": 3600,
        }
        mock_response.raise_for_status = MagicMock()

        with patch("src.calendar_provider.outlook_provider.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            provider = OutlookCalendarProvider(outlook_config_expired)
            result = await provider.authenticate()

            assert result is True
            assert provider.config.access_token == "refreshed-access-token"
            assert provider.config.refresh_token == "new-refresh-token"

    @pytest.mark.asyncio
    async def test_authenticate_returns_false_on_no_token(
        self, outlook_config_no_token: ProviderConfig
    ) -> None:
        provider = OutlookCalendarProvider(outlook_config_no_token)
        result = await provider.authenticate()

        assert result is False

    @pytest.mark.asyncio
    async def test_authenticate_returns_false_on_refresh_failure(
        self, outlook_config_expired: ProviderConfig
    ) -> None:
        with patch("src.calendar_provider.outlook_provider.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = Exception("Token refresh failed")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            provider = OutlookCalendarProvider(outlook_config_expired)
            result = await provider.authenticate()

            assert result is False

    @pytest.mark.asyncio
    async def test_authenticate_returns_false_when_no_refresh_token(
        self, outlook_config_expired: ProviderConfig
    ) -> None:
        config = ProviderConfig(
            provider="outlook",
            client_id="id",
            client_secret="secret",
            redirect_uri="http://localhost",
            scopes=["Calendars.Read"],
            access_token="expired-token",
            refresh_token=None,
            token_expiry=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        provider = OutlookCalendarProvider(config)
        result = await provider.authenticate()

        assert result is False


# ---------------------------------------------------------------------------
# List calendars tests
# ---------------------------------------------------------------------------


class TestListCalendars:
    """Tests for list_calendars method."""

    @pytest.mark.asyncio
    async def test_list_calendars_returns_calendars(
        self, outlook_config: ProviderConfig
    ) -> None:
        mock_cal = MagicMock()
        mock_cal.id = "primary"
        mock_cal.name = "My Calendar"
        mock_cal.change_key = "change-key-1"
        mock_cal.default_online_meeting_provider = "teamsForBusiness"
        mock_cal.is_default_calendar = True
        mock_cal.hex_color = "#123456"

        mock_collection = MagicMock()
        mock_collection.value = [mock_cal]

        mock_client = MagicMock()
        mock_client.me.calendars.get = AsyncMock(return_value=mock_collection)

        with patch.object(OutlookCalendarProvider, "_get_client", return_value=mock_client):
            provider = OutlookCalendarProvider(outlook_config)
            calendars = await provider.list_calendars()

        assert len(calendars) == 1
        assert calendars[0].id == "primary"
        assert calendars[0].name == "My Calendar"
        assert calendars[0].is_primary is True
        assert calendars[0].color == "#123456"

    @pytest.mark.asyncio
    async def test_list_calendars_empty_result(
        self, outlook_config: ProviderConfig
    ) -> None:
        mock_collection = MagicMock()
        mock_collection.value = []

        mock_client = MagicMock()
        mock_client.me.calendars.get = AsyncMock(return_value=mock_collection)

        with patch.object(OutlookCalendarProvider, "_get_client", return_value=mock_client):
            provider = OutlookCalendarProvider(outlook_config)
            calendars = await provider.list_calendars()

        assert calendars == []

    @pytest.mark.asyncio
    async def test_list_calendars_handles_missing_fields(
        self, outlook_config: ProviderConfig
    ) -> None:
        mock_cal = MagicMock()
        mock_cal.id = "minimal-cal"
        mock_cal.name = None
        mock_cal.change_key = None
        mock_cal.default_online_meeting_provider = None
        mock_cal.is_default_calendar = False
        mock_cal.hex_color = None

        mock_collection = MagicMock()
        mock_collection.value = [mock_cal]

        mock_client = MagicMock()
        mock_client.me.calendars.get = AsyncMock(return_value=mock_collection)

        with patch.object(OutlookCalendarProvider, "_get_client", return_value=mock_client):
            provider = OutlookCalendarProvider(outlook_config)
            calendars = await provider.list_calendars()

        assert len(calendars) == 1
        assert calendars[0].id == "minimal-cal"
        assert calendars[0].name == ""
        assert calendars[0].timezone == "UTC"
        assert calendars[0].is_primary is False

    @pytest.mark.asyncio
    async def test_list_calendars_api_error(
        self, outlook_config: ProviderConfig
    ) -> None:
        from kiota_abstractions.api_error import APIError

        mock_client = MagicMock()
        mock_client.me.calendars.get = AsyncMock(
            side_effect=APIError(message="API error", response_status_code=500)
        )

        with patch.object(OutlookCalendarProvider, "_get_client", return_value=mock_client):
            provider = OutlookCalendarProvider(outlook_config)
            with pytest.raises(ProviderAPIError) as exc_info:
                await provider.list_calendars()

        assert exc_info.value.status_code == 500
        assert "listing calendars" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_list_calendars_null_result(
        self, outlook_config: ProviderConfig
    ) -> None:
        mock_client = MagicMock()
        mock_client.me.calendars.get = AsyncMock(return_value=None)

        with patch.object(OutlookCalendarProvider, "_get_client", return_value=mock_client):
            provider = OutlookCalendarProvider(outlook_config)
            calendars = await provider.list_calendars()

        assert calendars == []


# ---------------------------------------------------------------------------
# Get events tests
# ---------------------------------------------------------------------------


class TestGetEvents:
    """Tests for get_events method."""

    @pytest.mark.asyncio
    async def test_get_events_returns_events(
        self, outlook_config: ProviderConfig, now: datetime
    ) -> None:
        mock_event = MagicMock()
        mock_event.id = "event-1"
        mock_event.subject = "Meeting"
        mock_event.body = MagicMock()
        mock_event.body.content = "Meeting notes"
        mock_event.location = MagicMock()
        mock_event.location.display_name = "Room A"
        mock_event.start = MagicMock()
        mock_event.start.date_time = now.isoformat()
        mock_event.start.time_zone = "UTC"
        mock_event.end = MagicMock()
        mock_event.end.date_time = (now + timedelta(hours=1)).isoformat()
        mock_event.end.time_zone = "UTC"
        mock_event.attendees = []
        mock_event.reminders = None
        mock_event.recurrence = None
        mock_event.created_date_time = MagicMock()
        mock_event.created_date_time.date_time = now.isoformat()
        mock_event.last_modified_date_time = MagicMock()
        mock_event.last_modified_date_time.date_time = now.isoformat()
        mock_event.recurring_event_id = None
        mock_event.show_as = "busy"
        mock_event.e_tag = "etag-1"
        mock_event.web_link = None
        mock_event.online_meeting_url = None

        mock_collection = MagicMock()
        mock_collection.value = [mock_event]

        mock_client = MagicMock()
        mock_client.me.calendar_view.get = AsyncMock(return_value=mock_collection)

        with patch.object(OutlookCalendarProvider, "_get_client", return_value=mock_client):
            provider = OutlookCalendarProvider(outlook_config)
            events = await provider.get_events(
                calendar_id="primary",
                start_time=now,
                end_time=now + timedelta(hours=2),
            )

        assert len(events) == 1
        assert events[0].id == "event-1"
        assert events[0].title == "Meeting"

    @pytest.mark.asyncio
    async def test_get_events_defaults_to_primary(
        self, outlook_config: ProviderConfig, now: datetime
    ) -> None:
        mock_collection = MagicMock()
        mock_collection.value = []

        mock_client = MagicMock()
        mock_client.me.calendar_view.get = AsyncMock(return_value=mock_collection)

        with patch.object(OutlookCalendarProvider, "_get_client", return_value=mock_client):
            provider = OutlookCalendarProvider(outlook_config)
            await provider.get_events(start_time=now, end_time=now + timedelta(hours=1))

        mock_client.me.calendar_view.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_events_defaults_start_time_to_now(
        self, outlook_config: ProviderConfig
    ) -> None:
        mock_collection = MagicMock()
        mock_collection.value = []

        mock_client = MagicMock()
        mock_client.me.calendar_view.get = AsyncMock(return_value=mock_collection)

        with patch.object(OutlookCalendarProvider, "_get_client", return_value=mock_client):
            provider = OutlookCalendarProvider(outlook_config)
            await provider.get_events()

        mock_client.me.calendar_view.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_events_expands_recurring(
        self, outlook_config: ProviderConfig, now: datetime
    ) -> None:
        mock_collection = MagicMock()
        mock_collection.value = []

        mock_client = MagicMock()
        mock_client.me.calendar_view.get = AsyncMock(return_value=mock_collection)

        with patch.object(OutlookCalendarProvider, "_get_client", return_value=mock_client):
            provider = OutlookCalendarProvider(outlook_config)
            await provider.get_events(
                start_time=now,
                end_time=now + timedelta(hours=1),
                expand_recurring=True,
            )

        mock_client.me.calendar_view.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_events_does_not_expand_recurring(
        self, outlook_config: ProviderConfig, now: datetime
    ) -> None:
        mock_collection = MagicMock()
        mock_collection.value = []

        mock_client = MagicMock()
        mock_client.me.calendars.by_calendar_id.return_value.events.get = AsyncMock(
            return_value=mock_collection
        )

        with patch.object(OutlookCalendarProvider, "_get_client", return_value=mock_client):
            provider = OutlookCalendarProvider(outlook_config)
            await provider.get_events(
                start_time=now,
                end_time=now + timedelta(hours=1),
                expand_recurring=False,
            )

        mock_client.me.calendars.by_calendar_id.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_events_calendar_not_found(
        self, outlook_config: ProviderConfig, now: datetime
    ) -> None:
        from kiota_abstractions.api_error import APIError

        mock_client = MagicMock()
        mock_client.me.calendar_view.get = AsyncMock(
            side_effect=APIError(message="Not Found", response_status_code=404)
        )

        with patch.object(OutlookCalendarProvider, "_get_client", return_value=mock_client):
            provider = OutlookCalendarProvider(outlook_config)
            with pytest.raises(CalendarNotFoundError) as exc_info:
                await provider.get_events(
                    calendar_id="nonexistent",
                    start_time=now,
                    end_time=now + timedelta(hours=1),
                )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_events_api_error(
        self, outlook_config: ProviderConfig, now: datetime
    ) -> None:
        from kiota_abstractions.api_error import APIError

        mock_client = MagicMock()
        mock_client.me.calendar_view.get = AsyncMock(
            side_effect=APIError(message="Server Error", response_status_code=500)
        )

        with patch.object(OutlookCalendarProvider, "_get_client", return_value=mock_client):
            provider = OutlookCalendarProvider(outlook_config)
            with pytest.raises(ProviderAPIError) as exc_info:
                await provider.get_events(start_time=now, end_time=now + timedelta(hours=1))

        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_get_events_parses_attendees(
        self, outlook_config: ProviderConfig, now: datetime
    ) -> None:
        mock_email_1 = MagicMock()
        mock_email_1.address = "alice@example.com"
        mock_email_1.name = "Alice"

        mock_email_2 = MagicMock()
        mock_email_2.address = "bob@example.com"
        mock_email_2.name = "Bob"

        mock_att_1 = MagicMock()
        mock_att_1.email_address = mock_email_1
        mock_att_1.status = MagicMock()
        mock_att_1.status.response_type = "accepted"

        mock_att_2 = MagicMock()
        mock_att_2.email_address = mock_email_2
        mock_att_2.status = MagicMock()
        mock_att_2.status.response_type = "notResponded"

        mock_event = MagicMock()
        mock_event.id = "event-with-attendees"
        mock_event.subject = "Team Meeting"
        mock_event.body = MagicMock()
        mock_event.body.content = None
        mock_event.location = None
        mock_event.start = MagicMock()
        mock_event.start.date_time = now.isoformat()
        mock_event.start.time_zone = "UTC"
        mock_event.end = MagicMock()
        mock_event.end.date_time = (now + timedelta(hours=1)).isoformat()
        mock_event.end.time_zone = "UTC"
        mock_event.attendees = [mock_att_1, mock_att_2]
        mock_event.reminders = None
        mock_event.recurrence = None
        mock_event.created_date_time = MagicMock()
        mock_event.created_date_time.date_time = now.isoformat()
        mock_event.last_modified_date_time = MagicMock()
        mock_event.last_modified_date_time.date_time = now.isoformat()
        mock_event.recurring_event_id = None
        mock_event.show_as = "busy"
        mock_event.e_tag = None
        mock_event.web_link = None
        mock_event.online_meeting_url = None

        mock_collection = MagicMock()
        mock_collection.value = [mock_event]

        mock_client = MagicMock()
        mock_client.me.calendar_view.get = AsyncMock(return_value=mock_collection)

        with patch.object(OutlookCalendarProvider, "_get_client", return_value=mock_client):
            provider = OutlookCalendarProvider(outlook_config)
            events = await provider.get_events(start_time=now, end_time=now + timedelta(hours=2))

        assert len(events[0].attendees) == 2
        assert events[0].attendees[0].email == "alice@example.com"
        assert events[0].attendees[0].response_status == "accepted"
        assert events[0].attendees[1].response_status == "needsAction"

    @pytest.mark.asyncio
    async def test_get_events_parses_reminders(
        self, outlook_config: ProviderConfig, now: datetime
    ) -> None:
        mock_reminder = MagicMock()
        mock_reminder.minutes_before_start = 15

        mock_event = MagicMock()
        mock_event.id = "event-with-reminders"
        mock_event.subject = "Meeting"
        mock_event.body = None
        mock_event.location = None
        mock_event.start = MagicMock()
        mock_event.start.date_time = now.isoformat()
        mock_event.start.time_zone = "UTC"
        mock_event.end = MagicMock()
        mock_event.end.date_time = (now + timedelta(hours=1)).isoformat()
        mock_event.end.time_zone = "UTC"
        mock_event.attendees = []
        mock_event.reminders = [mock_reminder]
        mock_event.recurrence = None
        mock_event.created_date_time = MagicMock()
        mock_event.created_date_time.date_time = now.isoformat()
        mock_event.last_modified_date_time = MagicMock()
        mock_event.last_modified_date_time.date_time = now.isoformat()
        mock_event.recurring_event_id = None
        mock_event.show_as = "busy"
        mock_event.e_tag = None
        mock_event.web_link = None
        mock_event.online_meeting_url = None

        mock_collection = MagicMock()
        mock_collection.value = [mock_event]

        mock_client = MagicMock()
        mock_client.me.calendar_view.get = AsyncMock(return_value=mock_collection)

        with patch.object(OutlookCalendarProvider, "_get_client", return_value=mock_client):
            provider = OutlookCalendarProvider(outlook_config)
            events = await provider.get_events(start_time=now, end_time=now + timedelta(hours=2))

        assert len(events[0].reminders) == 1
        assert events[0].reminders[0].minutes_before == 15

    @pytest.mark.asyncio
    async def test_get_events_parses_recurrence(
        self, outlook_config: ProviderConfig, now: datetime
    ) -> None:
        mock_pattern = MagicMock()
        mock_pattern.type = "weekly"
        mock_pattern.interval = 1
        mock_pattern.days_of_week = ["monday", "wednesday", "friday"]
        mock_pattern.day_of_month = None

        mock_range = MagicMock()
        mock_range.number_of_occurrences = None
        mock_range.end_date = None

        mock_recurrence = MagicMock()
        mock_recurrence.pattern = mock_pattern
        mock_recurrence.range = mock_range

        mock_event = MagicMock()
        mock_event.id = "recurring-event"
        mock_event.subject = "Weekly Standup"
        mock_event.body = None
        mock_event.location = None
        mock_event.start = MagicMock()
        mock_event.start.date_time = now.isoformat()
        mock_event.start.time_zone = "UTC"
        mock_event.end = MagicMock()
        mock_event.end.date_time = (now + timedelta(hours=1)).isoformat()
        mock_event.end.time_zone = "UTC"
        mock_event.attendees = []
        mock_event.reminders = None
        mock_event.recurrence = mock_recurrence
        mock_event.created_date_time = MagicMock()
        mock_event.created_date_time.date_time = now.isoformat()
        mock_event.last_modified_date_time = MagicMock()
        mock_event.last_modified_date_time.date_time = now.isoformat()
        mock_event.recurring_event_id = None
        mock_event.show_as = "busy"
        mock_event.e_tag = None
        mock_event.web_link = None
        mock_event.online_meeting_url = None

        mock_collection = MagicMock()
        mock_collection.value = [mock_event]

        mock_client = MagicMock()
        mock_client.me.calendar_view.get = AsyncMock(return_value=mock_collection)

        with patch.object(OutlookCalendarProvider, "_get_client", return_value=mock_client):
            provider = OutlookCalendarProvider(outlook_config)
            events = await provider.get_events(start_time=now, end_time=now + timedelta(hours=2))

        assert events[0].recurrence is not None
        assert events[0].recurrence.frequency == "weekly"
        assert events[0].recurrence.by_day == ["monday", "wednesday", "friday"]
        assert events[0].is_recurring_master is True

    @pytest.mark.asyncio
    async def test_get_events_parses_recurring_instance(
        self, outlook_config: ProviderConfig, now: datetime
    ) -> None:
        mock_event = MagicMock()
        mock_event.id = "instance-1"
        mock_event.subject = "Weekly Standup"
        mock_event.body = None
        mock_event.location = None
        mock_event.start = MagicMock()
        mock_event.start.date_time = now.isoformat()
        mock_event.start.time_zone = "UTC"
        mock_event.end = MagicMock()
        mock_event.end.date_time = (now + timedelta(hours=1)).isoformat()
        mock_event.end.time_zone = "UTC"
        mock_event.attendees = []
        mock_event.reminders = None
        mock_event.recurrence = None
        mock_event.created_date_time = MagicMock()
        mock_event.created_date_time.date_time = now.isoformat()
        mock_event.last_modified_date_time = MagicMock()
        mock_event.last_modified_date_time.date_time = now.isoformat()
        mock_event.recurring_event_id = "master-event-id"
        mock_event.show_as = "busy"
        mock_event.e_tag = None
        mock_event.web_link = None
        mock_event.online_meeting_url = None

        mock_collection = MagicMock()
        mock_collection.value = [mock_event]

        mock_client = MagicMock()
        mock_client.me.calendar_view.get = AsyncMock(return_value=mock_collection)

        with patch.object(OutlookCalendarProvider, "_get_client", return_value=mock_client):
            provider = OutlookCalendarProvider(outlook_config)
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
        self, outlook_config: ProviderConfig, now: datetime,
        sample_attendee: EventAttendee, sample_reminder: EventReminder
    ) -> None:
        mock_created = MagicMock()
        mock_created.id = "new-event-id"
        mock_created.subject = "New Meeting"
        mock_created.body = MagicMock()
        mock_created.body.content = "Description here"
        mock_created.location = MagicMock()
        mock_created.location.display_name = "Room A"
        mock_created.start = MagicMock()
        mock_created.start.date_time = now.isoformat()
        mock_created.start.time_zone = "UTC"
        mock_created.end = MagicMock()
        mock_created.end.date_time = (now + timedelta(hours=1)).isoformat()
        mock_created.end.time_zone = "UTC"
        mock_created.attendees = []
        mock_created.reminders = None
        mock_created.recurrence = None
        mock_created.created_date_time = MagicMock()
        mock_created.created_date_time.date_time = now.isoformat()
        mock_created.last_modified_date_time = MagicMock()
        mock_created.last_modified_date_time.date_time = now.isoformat()
        mock_created.recurring_event_id = None
        mock_created.show_as = "busy"
        mock_created.e_tag = "new-etag"
        mock_created.web_link = None
        mock_created.online_meeting_url = None

        mock_client = MagicMock()
        mock_client.me.calendars.by_calendar_id.return_value.events.post = AsyncMock(
            return_value=mock_created
        )

        with patch.object(OutlookCalendarProvider, "_get_client", return_value=mock_client):
            provider = OutlookCalendarProvider(outlook_config)
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
        mock_client.me.calendars.by_calendar_id.return_value.events.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_event_validation_error_end_before_start(
        self, outlook_config: ProviderConfig, now: datetime
    ) -> None:
        provider = OutlookCalendarProvider(outlook_config)
        with pytest.raises(ValidationError, match="end time must be after start time"):
            await provider.create_event(
                title="Bad Event",
                start=now + timedelta(hours=1),
                end=now,
                timezone="UTC",
            )

    @pytest.mark.asyncio
    async def test_create_event_validation_error_same_time(
        self, outlook_config: ProviderConfig, now: datetime
    ) -> None:
        provider = OutlookCalendarProvider(outlook_config)
        with pytest.raises(ValidationError, match="end time must be after start time"):
            await provider.create_event(
                title="Bad Event",
                start=now,
                end=now,
                timezone="UTC",
            )

    @pytest.mark.asyncio
    async def test_create_event_calendar_not_found(
        self, outlook_config: ProviderConfig, now: datetime
    ) -> None:
        from kiota_abstractions.api_error import APIError

        mock_client = MagicMock()
        mock_client.me.calendars.by_calendar_id.return_value.events.post = AsyncMock(
            side_effect=APIError(message="Not Found", response_status_code=404)
        )

        with patch.object(OutlookCalendarProvider, "_get_client", return_value=mock_client):
            provider = OutlookCalendarProvider(outlook_config)
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
        self, outlook_config: ProviderConfig, now: datetime
    ) -> None:
        from kiota_abstractions.api_error import APIError

        mock_client = MagicMock()
        mock_client.me.calendars.by_calendar_id.return_value.events.post = AsyncMock(
            side_effect=APIError(message="Bad Request", response_status_code=400)
        )

        with patch.object(OutlookCalendarProvider, "_get_client", return_value=mock_client):
            provider = OutlookCalendarProvider(outlook_config)
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
        self, outlook_config: ProviderConfig, now: datetime,
        sample_recurrence: RecurrenceRule
    ) -> None:
        mock_created = MagicMock()
        mock_created.id = "recurring-new"
        mock_created.subject = "Weekly Sync"
        mock_created.body = None
        mock_created.location = None
        mock_created.start = MagicMock()
        mock_created.start.date_time = now.isoformat()
        mock_created.start.time_zone = "UTC"
        mock_created.end = MagicMock()
        mock_created.end.date_time = (now + timedelta(hours=1)).isoformat()
        mock_created.end.time_zone = "UTC"
        mock_created.attendees = []
        mock_created.reminders = None
        mock_created.recurrence = None
        mock_created.created_date_time = MagicMock()
        mock_created.created_date_time.date_time = now.isoformat()
        mock_created.last_modified_date_time = MagicMock()
        mock_created.last_modified_date_time.date_time = now.isoformat()
        mock_created.recurring_event_id = None
        mock_created.show_as = "busy"
        mock_created.e_tag = None
        mock_created.web_link = None
        mock_created.online_meeting_url = None

        mock_client = MagicMock()
        mock_client.me.calendars.by_calendar_id.return_value.events.post = AsyncMock(
            return_value=mock_created
        )

        with patch.object(OutlookCalendarProvider, "_get_client", return_value=mock_client):
            provider = OutlookCalendarProvider(outlook_config)
            event = await provider.create_event(
                title="Weekly Sync",
                start=now,
                end=now + timedelta(hours=1),
                timezone="UTC",
                recurrence=sample_recurrence,
            )

        assert event.id == "recurring-new"

    @pytest.mark.asyncio
    async def test_create_event_no_response(
        self, outlook_config: ProviderConfig, now: datetime
    ) -> None:
        mock_client = MagicMock()
        mock_client.me.calendars.by_calendar_id.return_value.events.post = AsyncMock(
            return_value=None
        )

        with patch.object(OutlookCalendarProvider, "_get_client", return_value=mock_client):
            provider = OutlookCalendarProvider(outlook_config)
            with pytest.raises(ProviderAPIError, match="no response from API"):
                await provider.create_event(
                    title="Meeting",
                    start=now,
                    end=now + timedelta(hours=1),
                    timezone="UTC",
                )


# ---------------------------------------------------------------------------
# Update event tests
# ---------------------------------------------------------------------------


class TestUpdateEvent:
    """Tests for update_event method."""

    @pytest.mark.asyncio
    async def test_update_event_success(
        self, outlook_config: ProviderConfig, now: datetime
    ) -> None:
        mock_existing = MagicMock()
        mock_existing.id = "event-123"
        mock_existing.subject = "Old Title"
        mock_existing.body = MagicMock()
        mock_existing.body.content = "Old description"
        mock_existing.location = MagicMock()
        mock_existing.location.display_name = "Old Room"
        mock_existing.start = MagicMock()
        mock_existing.start.date_time = now.isoformat()
        mock_existing.start.time_zone = "UTC"
        mock_existing.end = MagicMock()
        mock_existing.end.date_time = (now + timedelta(hours=1)).isoformat()
        mock_existing.end.time_zone = "UTC"
        mock_existing.attendees = []
        mock_existing.reminders = None
        mock_existing.recurrence = None
        mock_existing.created_date_time = MagicMock()
        mock_existing.created_date_time.date_time = now.isoformat()
        mock_existing.last_modified_date_time = MagicMock()
        mock_existing.last_modified_date_time.date_time = now.isoformat()
        mock_existing.recurring_event_id = None
        mock_existing.show_as = "busy"
        mock_existing.e_tag = "old-etag"
        mock_existing.web_link = None
        mock_existing.online_meeting_url = None
        mock_existing.is_reminder_on = False
        mock_existing.body_type = "html"

        mock_updated = MagicMock()
        mock_updated.id = "event-123"
        mock_updated.subject = "New Title"
        mock_updated.body = MagicMock()
        mock_updated.body.content = "Old description"
        mock_updated.location = MagicMock()
        mock_updated.location.display_name = "Old Room"
        mock_updated.start = MagicMock()
        mock_updated.start.date_time = now.isoformat()
        mock_updated.start.time_zone = "UTC"
        mock_updated.end = MagicMock()
        mock_updated.end.date_time = (now + timedelta(hours=1)).isoformat()
        mock_updated.end.time_zone = "UTC"
        mock_updated.attendees = []
        mock_updated.reminders = None
        mock_updated.recurrence = None
        mock_updated.created_date_time = MagicMock()
        mock_updated.created_date_time.date_time = now.isoformat()
        mock_updated.last_modified_date_time = MagicMock()
        mock_updated.last_modified_date_time.date_time = (now + timedelta(hours=1)).isoformat()
        mock_updated.recurring_event_id = None
        mock_updated.show_as = "busy"
        mock_updated.e_tag = "new-etag"
        mock_updated.web_link = None
        mock_updated.online_meeting_url = None
        mock_updated.is_reminder_on = False
        mock_updated.body_type = "html"

        mock_client = MagicMock()
        mock_client.me.calendars.by_calendar_id.return_value.events.by_event_id.return_value.get = AsyncMock(
            return_value=mock_existing
        )
        mock_client.me.calendars.by_calendar_id.return_value.events.by_event_id.return_value.patch = AsyncMock(
            return_value=mock_updated
        )

        with patch.object(OutlookCalendarProvider, "_get_client", return_value=mock_client):
            provider = OutlookCalendarProvider(outlook_config)
            event = await provider.update_event(
                event_id="event-123",
                title="New Title",
            )

        assert event.title == "New Title"

    @pytest.mark.asyncio
    async def test_update_event_not_found(
        self, outlook_config: ProviderConfig, now: datetime
    ) -> None:
        from kiota_abstractions.api_error import APIError

        mock_client = MagicMock()
        mock_client.me.calendars.by_calendar_id.return_value.events.by_event_id.return_value.get = AsyncMock(
            side_effect=APIError(message="Not Found", response_status_code=404)
        )

        with patch.object(OutlookCalendarProvider, "_get_client", return_value=mock_client):
            provider = OutlookCalendarProvider(outlook_config)
            with pytest.raises(EventNotFoundError) as exc_info:
                await provider.update_event(event_id="nonexistent", title="New Title")

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_update_event_etag_conflict(
        self, outlook_config: ProviderConfig, now: datetime
    ) -> None:
        mock_existing = MagicMock()
        mock_existing.id = "event-123"
        mock_existing.subject = "Old Title"
        mock_existing.body = MagicMock()
        mock_existing.body.content = "Old description"
        mock_existing.location = MagicMock()
        mock_existing.location.display_name = "Old Room"
        mock_existing.start = MagicMock()
        mock_existing.start.date_time = now.isoformat()
        mock_existing.start.time_zone = "UTC"
        mock_existing.end = MagicMock()
        mock_existing.end.date_time = (now + timedelta(hours=1)).isoformat()
        mock_existing.end.time_zone = "UTC"
        mock_existing.attendees = []
        mock_existing.reminders = None
        mock_existing.recurrence = None
        mock_existing.created_date_time = MagicMock()
        mock_existing.created_date_time.date_time = now.isoformat()
        mock_existing.last_modified_date_time = MagicMock()
        mock_existing.last_modified_date_time.date_time = now.isoformat()
        mock_existing.recurring_event_id = None
        mock_existing.show_as = "busy"
        mock_existing.e_tag = "old-etag"
        mock_existing.web_link = None
        mock_existing.online_meeting_url = None
        mock_existing.is_reminder_on = False
        mock_existing.body_type = "html"

        mock_client = MagicMock()
        mock_client.me.calendars.by_calendar_id.return_value.events.by_event_id.return_value.get = AsyncMock(
            return_value=mock_existing
        )

        with patch.object(OutlookCalendarProvider, "_get_client", return_value=mock_client):
            provider = OutlookCalendarProvider(outlook_config)
            with pytest.raises(ConflictError) as exc_info:
                await provider.update_event(
                    event_id="event-123",
                    title="New Title",
                    etag="different-etag",
                )

        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_update_event_validation_error(
        self, outlook_config: ProviderConfig, now: datetime
    ) -> None:
        mock_existing = MagicMock()
        mock_existing.id = "event-123"
        mock_existing.subject = "Title"
        mock_existing.body = MagicMock()
        mock_existing.body.content = "Description"
        mock_existing.location = MagicMock()
        mock_existing.location.display_name = "Room"
        mock_existing.start = MagicMock()
        mock_existing.start.date_time = now.isoformat()
        mock_existing.start.time_zone = "UTC"
        mock_existing.end = MagicMock()
        mock_existing.end.date_time = (now + timedelta(hours=1)).isoformat()
        mock_existing.end.time_zone = "UTC"
        mock_existing.attendees = []
        mock_existing.reminders = None
        mock_existing.recurrence = None
        mock_existing.created_date_time = MagicMock()
        mock_existing.created_date_time.date_time = now.isoformat()
        mock_existing.last_modified_date_time = MagicMock()
        mock_existing.last_modified_date_time.date_time = now.isoformat()
        mock_existing.recurring_event_id = None
        mock_existing.show_as = "busy"
        mock_existing.e_tag = "etag"
        mock_existing.web_link = None
        mock_existing.online_meeting_url = None
        mock_existing.is_reminder_on = False
        mock_existing.body_type = "html"

        mock_client = MagicMock()
        mock_client.me.calendars.by_calendar_id.return_value.events.by_event_id.return_value.get = AsyncMock(
            return_value=mock_existing
        )

        with patch.object(OutlookCalendarProvider, "_get_client", return_value=mock_client):
            provider = OutlookCalendarProvider(outlook_config)
            with pytest.raises(ValidationError, match="end time must be after start time"):
                await provider.update_event(
                    event_id="event-123",
                    start=now + timedelta(hours=2),
                    end=now + timedelta(hours=1),
                )

    @pytest.mark.asyncio
    async def test_update_event_http_error_on_update(
        self, outlook_config: ProviderConfig, now: datetime
    ) -> None:
        from kiota_abstractions.api_error import APIError

        mock_existing = MagicMock()
        mock_existing.id = "event-123"
        mock_existing.subject = "Title"
        mock_existing.body = MagicMock()
        mock_existing.body.content = "Description"
        mock_existing.location = MagicMock()
        mock_existing.location.display_name = "Room"
        mock_existing.start = MagicMock()
        mock_existing.start.date_time = now.isoformat()
        mock_existing.start.time_zone = "UTC"
        mock_existing.end = MagicMock()
        mock_existing.end.date_time = (now + timedelta(hours=1)).isoformat()
        mock_existing.end.time_zone = "UTC"
        mock_existing.attendees = []
        mock_existing.reminders = None
        mock_existing.recurrence = None
        mock_existing.created_date_time = MagicMock()
        mock_existing.created_date_time.date_time = now.isoformat()
        mock_existing.last_modified_date_time = MagicMock()
        mock_existing.last_modified_date_time.date_time = now.isoformat()
        mock_existing.recurring_event_id = None
        mock_existing.show_as = "busy"
        mock_existing.e_tag = "some-etag"
        mock_existing.web_link = None
        mock_existing.online_meeting_url = None
        mock_existing.is_reminder_on = False
        mock_existing.body_type = "html"

        mock_client = MagicMock()
        mock_client.me.calendars.by_calendar_id.return_value.events.by_event_id.return_value.get = AsyncMock(
            return_value=mock_existing
        )
        mock_client.me.calendars.by_calendar_id.return_value.events.by_event_id.return_value.patch = AsyncMock(
            side_effect=APIError(message="Precondition Failed", response_status_code=412)
        )

        with patch.object(OutlookCalendarProvider, "_get_client", return_value=mock_client):
            provider = OutlookCalendarProvider(outlook_config)
            with pytest.raises(ConflictError) as exc_info:
                await provider.update_event(event_id="event-123", title="New Title", etag="some-etag")

        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_update_event_fetches_after_null_patch(
        self, outlook_config: ProviderConfig, now: datetime
    ) -> None:
        mock_existing = MagicMock()
        mock_existing.id = "event-123"
        mock_existing.subject = "Old Title"
        mock_existing.body = MagicMock()
        mock_existing.body.content = "Old description"
        mock_existing.location = MagicMock()
        mock_existing.location.display_name = "Old Room"
        mock_existing.start = MagicMock()
        mock_existing.start.date_time = now.isoformat()
        mock_existing.start.time_zone = "UTC"
        mock_existing.end = MagicMock()
        mock_existing.end.date_time = (now + timedelta(hours=1)).isoformat()
        mock_existing.end.time_zone = "UTC"
        mock_existing.attendees = []
        mock_existing.reminders = None
        mock_existing.recurrence = None
        mock_existing.created_date_time = MagicMock()
        mock_existing.created_date_time.date_time = now.isoformat()
        mock_existing.last_modified_date_time = MagicMock()
        mock_existing.last_modified_date_time.date_time = now.isoformat()
        mock_existing.recurring_event_id = None
        mock_existing.show_as = "busy"
        mock_existing.e_tag = "old-etag"
        mock_existing.web_link = None
        mock_existing.online_meeting_url = None
        mock_existing.is_reminder_on = False
        mock_existing.body_type = "html"

        mock_updated = MagicMock()
        mock_updated.id = "event-123"
        mock_updated.subject = "New Title"
        mock_updated.body = MagicMock()
        mock_updated.body.content = "Old description"
        mock_updated.location = MagicMock()
        mock_updated.location.display_name = "Old Room"
        mock_updated.start = MagicMock()
        mock_updated.start.date_time = now.isoformat()
        mock_updated.start.time_zone = "UTC"
        mock_updated.end = MagicMock()
        mock_updated.end.date_time = (now + timedelta(hours=1)).isoformat()
        mock_updated.end.time_zone = "UTC"
        mock_updated.attendees = []
        mock_updated.reminders = None
        mock_updated.recurrence = None
        mock_updated.created_date_time = MagicMock()
        mock_updated.created_date_time.date_time = now.isoformat()
        mock_updated.last_modified_date_time = MagicMock()
        mock_updated.last_modified_date_time.date_time = (now + timedelta(hours=1)).isoformat()
        mock_updated.recurring_event_id = None
        mock_updated.show_as = "busy"
        mock_updated.e_tag = "new-etag"
        mock_updated.web_link = None
        mock_updated.online_meeting_url = None
        mock_updated.is_reminder_on = False
        mock_updated.body_type = "html"

        mock_events_builder = MagicMock()
        mock_events_builder.get = AsyncMock(side_effect=[mock_existing, mock_updated])
        mock_events_builder.patch = AsyncMock(return_value=None)

        mock_calendar_builder = MagicMock()
        mock_calendar_builder.events.by_event_id.return_value = mock_events_builder

        mock_me = MagicMock()
        mock_me.calendars.by_calendar_id.return_value = mock_calendar_builder

        mock_client = MagicMock()
        mock_client.me = mock_me

        with patch.object(OutlookCalendarProvider, "_get_client", return_value=mock_client):
            provider = OutlookCalendarProvider(outlook_config)
            event = await provider.update_event(
                event_id="event-123",
                title="New Title",
            )

        assert event.title == "New Title"


# ---------------------------------------------------------------------------
# Delete event tests
# ---------------------------------------------------------------------------


class TestDeleteEvent:
    """Tests for delete_event method."""

    @pytest.mark.asyncio
    async def test_delete_event_success(
        self, outlook_config: ProviderConfig
    ) -> None:
        mock_client = MagicMock()
        mock_client.me.calendars.by_calendar_id.return_value.events.by_event_id.return_value.delete = AsyncMock()

        with patch.object(OutlookCalendarProvider, "_get_client", return_value=mock_client):
            provider = OutlookCalendarProvider(outlook_config)
            result = await provider.delete_event(event_id="event-123")

        assert result is True

    @pytest.mark.asyncio
    async def test_delete_event_not_found(
        self, outlook_config: ProviderConfig
    ) -> None:
        from kiota_abstractions.api_error import APIError

        mock_client = MagicMock()
        mock_client.me.calendars.by_calendar_id.return_value.events.by_event_id.return_value.delete = AsyncMock(
            side_effect=APIError(message="Not Found", response_status_code=404)
        )

        with patch.object(OutlookCalendarProvider, "_get_client", return_value=mock_client):
            provider = OutlookCalendarProvider(outlook_config)
            with pytest.raises(EventNotFoundError) as exc_info:
                await provider.delete_event(event_id="nonexistent")

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_event_api_error(
        self, outlook_config: ProviderConfig
    ) -> None:
        from kiota_abstractions.api_error import APIError

        mock_client = MagicMock()
        mock_client.me.calendars.by_calendar_id.return_value.events.by_event_id.return_value.delete = AsyncMock(
            side_effect=APIError(message="Server Error", response_status_code=500)
        )

        with patch.object(OutlookCalendarProvider, "_get_client", return_value=mock_client):
            provider = OutlookCalendarProvider(outlook_config)
            with pytest.raises(ProviderAPIError) as exc_info:
                await provider.delete_event(event_id="event-123")

        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_delete_event_defaults_to_primary(
        self, outlook_config: ProviderConfig
    ) -> None:
        mock_client = MagicMock()
        mock_client.me.calendars.by_calendar_id.return_value.events.by_event_id.return_value.delete = AsyncMock()

        with patch.object(OutlookCalendarProvider, "_get_client", return_value=mock_client):
            provider = OutlookCalendarProvider(outlook_config)
            await provider.delete_event(event_id="event-123")

        mock_client.me.calendars.by_calendar_id.assert_called_once_with("calendar")


# ---------------------------------------------------------------------------
# Free/busy tests
# ---------------------------------------------------------------------------


class TestGetFreeBusy:
    """Tests for get_free_busy method."""

    @pytest.mark.asyncio
    async def test_get_free_busy_returns_slots(
        self, outlook_config: ProviderConfig, now: datetime
    ) -> None:
        mock_event = MagicMock()
        mock_event.start = MagicMock()
        mock_event.start.date_time = now.isoformat()
        mock_event.start.time_zone = "UTC"
        mock_event.end = MagicMock()
        mock_event.end.date_time = (now + timedelta(hours=1)).isoformat()
        mock_event.end.time_zone = "UTC"

        mock_collection = MagicMock()
        mock_collection.value = [mock_event]

        mock_client = MagicMock()
        mock_client.me.calendar_view.get = AsyncMock(return_value=mock_collection)

        with patch.object(OutlookCalendarProvider, "_get_client", return_value=mock_client):
            provider = OutlookCalendarProvider(outlook_config)
            slots = await provider.get_free_busy(
                start_time=now,
                end_time=now + timedelta(hours=4),
                calendar_ids=["primary"],
            )

        assert len(slots) == 1
        assert slots[0].status == "busy"

    @pytest.mark.asyncio
    async def test_get_free_busy_defaults_to_all_calendars(
        self, outlook_config: ProviderConfig, now: datetime
    ) -> None:
        mock_cal = MagicMock()
        mock_cal.id = "cal-1"
        mock_cal.name = "Cal 1"
        mock_cal.change_key = None
        mock_cal.default_online_meeting_provider = None
        mock_cal.is_default_calendar = False
        mock_cal.hex_color = None

        mock_cal_collection = MagicMock()
        mock_cal_collection.value = [mock_cal]

        mock_event_collection = MagicMock()
        mock_event_collection.value = []

        mock_client = MagicMock()
        mock_client.me.calendars.get = AsyncMock(return_value=mock_cal_collection)
        mock_client.me.calendar_view.get = AsyncMock(return_value=mock_event_collection)

        with patch.object(OutlookCalendarProvider, "_get_client", return_value=mock_client):
            provider = OutlookCalendarProvider(outlook_config)
            slots = await provider.get_free_busy(
                start_time=now,
                end_time=now + timedelta(hours=1),
            )

        assert slots == []

    @pytest.mark.asyncio
    async def test_get_free_busy_api_error(
        self, outlook_config: ProviderConfig, now: datetime
    ) -> None:
        from kiota_abstractions.api_error import APIError

        mock_client = MagicMock()
        mock_client.me.calendar_view.get = AsyncMock(
            side_effect=APIError(message="Server Error", response_status_code=500)
        )

        with patch.object(OutlookCalendarProvider, "_get_client", return_value=mock_client):
            provider = OutlookCalendarProvider(outlook_config)
            with pytest.raises(ProviderAPIError) as exc_info:
                await provider.get_free_busy(
                    start_time=now,
                    end_time=now + timedelta(hours=1),
                    calendar_ids=["primary"],
                )

        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_get_free_busy_empty_result(
        self, outlook_config: ProviderConfig, now: datetime
    ) -> None:
        mock_collection = MagicMock()
        mock_collection.value = None

        mock_client = MagicMock()
        mock_client.me.calendar_view.get = AsyncMock(return_value=mock_collection)

        with patch.object(OutlookCalendarProvider, "_get_client", return_value=mock_client):
            provider = OutlookCalendarProvider(outlook_config)
            slots = await provider.get_free_busy(
                start_time=now,
                end_time=now + timedelta(hours=1),
                calendar_ids=["primary"],
            )

        assert slots == []


# ---------------------------------------------------------------------------
# Close tests
# ---------------------------------------------------------------------------


class TestClose:
    """Tests for close method."""

    @pytest.mark.asyncio
    async def test_close_clears_resources(
        self, outlook_config: ProviderConfig
    ) -> None:
        mock_http_client = AsyncMock()

        provider = OutlookCalendarProvider(outlook_config)
        provider._client = MagicMock()
        provider._http_client = mock_http_client

        await provider.close()

        assert provider._client is None
        assert provider._http_client is None
        mock_http_client.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_with_no_resources(
        self, outlook_config: ProviderConfig
    ) -> None:
        provider = OutlookCalendarProvider(outlook_config)
        await provider.close()

        assert provider._client is None
        assert provider._http_client is None


# ---------------------------------------------------------------------------
# Internal helper tests
# ---------------------------------------------------------------------------


class TestFormatDatetime:
    """Tests for _format_datetime static method."""

    def test_format_aware_datetime(self) -> None:
        dt = datetime(2026, 4, 20, 12, 0, 0, tzinfo=timezone.utc)
        result = OutlookCalendarProvider._format_datetime(dt)
        assert "2026-04-20" in result
        assert "+00:00" in result

    def test_format_naive_datetime(self) -> None:
        dt = datetime(2026, 4, 20, 12, 0, 0)
        result = OutlookCalendarProvider._format_datetime(dt)
        assert "2026-04-20" in result
        assert "+00:00" in result


class TestParseDatetime:
    """Tests for _parse_datetime static method."""

    def test_parse_aware_datetime(self) -> None:
        result = OutlookCalendarProvider._parse_datetime("2026-04-20T12:00:00+00:00")
        assert result.tzinfo is not None
        assert result.year == 2026
        assert result.month == 4
        assert result.day == 20

    def test_parse_naive_datetime(self) -> None:
        result = OutlookCalendarProvider._parse_datetime("2026-04-20T12:00:00")
        assert result.tzinfo is not None

    def test_parse_invalid_datetime(self) -> None:
        with pytest.raises(ValueError):
            OutlookCalendarProvider._parse_datetime("invalid-date")

    def test_parse_none_datetime(self) -> None:
        result = OutlookCalendarProvider._parse_datetime(None)
        assert result.tzinfo is not None


class TestParseResponseType:
    """Tests for _parse_response_type static method."""

    def test_parse_accepted(self) -> None:
        from src.calendar_provider.outlook_provider import ResponseType
        result = OutlookCalendarProvider._parse_response_type(ResponseType.ACCEPTED)
        assert result == "accepted"

    def test_parse_declined(self) -> None:
        from src.calendar_provider.outlook_provider import ResponseType
        result = OutlookCalendarProvider._parse_response_type(ResponseType.DECLINED)
        assert result == "declined"

    def test_parse_tentative(self) -> None:
        from src.calendar_provider.outlook_provider import ResponseType
        result = OutlookCalendarProvider._parse_response_type(ResponseType.TENTATIVE)
        assert result == "tentative"

    def test_parse_not_responded(self) -> None:
        from src.calendar_provider.outlook_provider import ResponseType
        result = OutlookCalendarProvider._parse_response_type(ResponseType.NOT_RESPONDED)
        assert result == "needsAction"

    def test_parse_none(self) -> None:
        from src.calendar_provider.outlook_provider import ResponseType
        result = OutlookCalendarProvider._parse_response_type(ResponseType.NONE)
        assert result is None

    def test_parse_organizer(self) -> None:
        from src.calendar_provider.outlook_provider import ResponseType
        result = OutlookCalendarProvider._parse_response_type(ResponseType.ORGANIZER)
        assert result is None

    def test_parse_unknown(self) -> None:
        result = OutlookCalendarProvider._parse_response_type("unknown")
        assert result is None


class TestParseShowAs:
    """Tests for _parse_show_as static method."""

    def test_parse_free(self) -> None:
        result = OutlookCalendarProvider._parse_show_as("free")
        assert result == "confirmed"

    def test_parse_tentative(self) -> None:
        result = OutlookCalendarProvider._parse_show_as("tentative")
        assert result == "tentative"

    def test_parse_oof(self) -> None:
        result = OutlookCalendarProvider._parse_show_as("oof")
        assert result == "cancelled"

    def test_parse_busy(self) -> None:
        result = OutlookCalendarProvider._parse_show_as("busy")
        assert result == "confirmed"

    def test_parse_none(self) -> None:
        result = OutlookCalendarProvider._parse_show_as(None)
        assert result == "confirmed"


class TestParseRecurrence:
    """Tests for _parse_recurrence method."""

    def test_parse_simple_rrule(self, outlook_config: ProviderConfig) -> None:
        mock_pattern = MagicMock()
        mock_pattern.type = "weekly"
        mock_pattern.interval = 1
        mock_pattern.days_of_week = ["monday", "wednesday"]
        mock_pattern.day_of_month = None

        mock_range = MagicMock()
        mock_range.number_of_occurrences = None
        mock_range.end_date = None

        mock_recurrence = MagicMock()
        mock_recurrence.pattern = mock_pattern
        mock_recurrence.range = mock_range

        provider = OutlookCalendarProvider(outlook_config)
        result = provider._parse_recurrence(mock_recurrence)

        assert result is not None
        assert result.frequency == "weekly"
        assert result.by_day == ["monday", "wednesday"]

    def test_parse_rrule_with_interval(self, outlook_config: ProviderConfig) -> None:
        mock_pattern = MagicMock()
        mock_pattern.type = "daily"
        mock_pattern.interval = 3
        mock_pattern.days_of_week = []
        mock_pattern.day_of_month = None

        mock_range = MagicMock()
        mock_range.number_of_occurrences = None
        mock_range.end_date = None

        mock_recurrence = MagicMock()
        mock_recurrence.pattern = mock_pattern
        mock_recurrence.range = mock_range

        provider = OutlookCalendarProvider(outlook_config)
        result = provider._parse_recurrence(mock_recurrence)

        assert result is not None
        assert result.frequency == "daily"
        assert result.interval == 3

    def test_parse_rrule_with_count(self, outlook_config: ProviderConfig) -> None:
        mock_pattern = MagicMock()
        mock_pattern.type = "weekly"
        mock_pattern.interval = 1
        mock_pattern.days_of_week = []
        mock_pattern.day_of_month = None

        mock_range = MagicMock()
        mock_range.number_of_occurrences = 10
        mock_range.end_date = None

        mock_recurrence = MagicMock()
        mock_recurrence.pattern = mock_pattern
        mock_recurrence.range = mock_range

        provider = OutlookCalendarProvider(outlook_config)
        result = provider._parse_recurrence(mock_recurrence)

        assert result is not None
        assert result.count == 10

    def test_parse_rrule_with_end_date(self, outlook_config: ProviderConfig) -> None:
        mock_pattern = MagicMock()
        mock_pattern.type = "absoluteMonthly"
        mock_pattern.interval = 1
        mock_pattern.days_of_week = []
        mock_pattern.day_of_month = 15

        mock_range = MagicMock()
        mock_range.number_of_occurrences = None
        mock_range.end_date = "2026-12-31"

        mock_recurrence = MagicMock()
        mock_recurrence.pattern = mock_pattern
        mock_recurrence.range = mock_range

        provider = OutlookCalendarProvider(outlook_config)
        result = provider._parse_recurrence(mock_recurrence)

        assert result is not None
        assert result.frequency == "monthly"
        assert result.by_month_day == [15]

    def test_parse_recurrence_none(self, outlook_config: ProviderConfig) -> None:
        provider = OutlookCalendarProvider(outlook_config)
        result = provider._parse_recurrence(None)

        assert result is None

    def test_parse_recurrence_no_pattern(self, outlook_config: ProviderConfig) -> None:
        mock_recurrence = MagicMock()
        mock_recurrence.pattern = None
        mock_recurrence.range = None

        provider = OutlookCalendarProvider(outlook_config)
        result = provider._parse_recurrence(mock_recurrence)

        assert result is None

    def test_parse_recurrence_unknown_frequency(self, outlook_config: ProviderConfig) -> None:
        mock_pattern = MagicMock()
        mock_pattern.type = "unknownType"
        mock_pattern.interval = 1
        mock_pattern.days_of_week = []
        mock_pattern.day_of_month = None

        mock_range = MagicMock()
        mock_range.number_of_occurrences = None
        mock_range.end_date = None

        mock_recurrence = MagicMock()
        mock_recurrence.pattern = mock_pattern
        mock_recurrence.range = mock_range

        provider = OutlookCalendarProvider(outlook_config)
        result = provider._parse_recurrence(mock_recurrence)

        assert result is not None
        assert result.frequency == "weekly"


class TestBuildPatternedRecurrence:
    """Tests for _build_patterned_recurrence method."""

    def test_build_simple_rrule(self, outlook_config: ProviderConfig) -> None:
        rule = RecurrenceRule(frequency="weekly", interval=1)

        provider = OutlookCalendarProvider(outlook_config)
        result = provider._build_patterned_recurrence(rule)

        assert result is not None
        assert result.pattern.type == "weekly"
        assert result.pattern.interval == 1

    def test_build_rrule_with_by_day(self, outlook_config: ProviderConfig) -> None:
        rule = RecurrenceRule(frequency="weekly", interval=1, by_day=["MO", "WE", "FR"])

        provider = OutlookCalendarProvider(outlook_config)
        result = provider._build_patterned_recurrence(rule)

        assert result.pattern.days_of_week is not None
        assert len(result.pattern.days_of_week) == 3

    def test_build_rrule_with_by_month_day(self, outlook_config: ProviderConfig) -> None:
        rule = RecurrenceRule(frequency="monthly", interval=1, by_month_day=[1, 15])

        provider = OutlookCalendarProvider(outlook_config)
        result = provider._build_patterned_recurrence(rule)

        assert result.pattern.day_of_month == 1

    def test_build_rrule_with_count(self, outlook_config: ProviderConfig) -> None:
        rule = RecurrenceRule(frequency="daily", interval=1, count=10)

        provider = OutlookCalendarProvider(outlook_config)
        result = provider._build_patterned_recurrence(rule)

        assert result.range.type == "numbered"
        assert result.range.number_of_occurrences == 10

    def test_build_rrule_with_until(self, outlook_config: ProviderConfig) -> None:
        until = datetime(2026, 12, 31, tzinfo=timezone.utc)
        rule = RecurrenceRule(frequency="monthly", interval=1, until=until)

        provider = OutlookCalendarProvider(outlook_config)
        result = provider._build_patterned_recurrence(rule)

        assert result.range.type == "endDate"
        assert result.range.end_date == "2026-12-31"

    def test_build_rrule_complex(self, outlook_config: ProviderConfig) -> None:
        until = datetime(2027, 1, 1, tzinfo=timezone.utc)
        rule = RecurrenceRule(
            frequency="weekly",
            interval=2,
            count=20,
            by_day=["MO", "FR"],
        )

        provider = OutlookCalendarProvider(outlook_config)
        result = provider._build_patterned_recurrence(rule)

        assert result.pattern.type == "weekly"
        assert result.pattern.interval == 2
        assert result.range.type == "numbered"
        assert result.range.number_of_occurrences == 20


# ---------------------------------------------------------------------------
# Refresh token tests
# ---------------------------------------------------------------------------


class TestRefreshToken:
    """Tests for _refresh_token method."""

    @pytest.mark.asyncio
    async def test_refresh_token_success(
        self, outlook_config: ProviderConfig
    ) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "expires_in": 7200,
        }
        mock_response.raise_for_status = MagicMock()

        with patch("src.calendar_provider.outlook_provider.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            provider = OutlookCalendarProvider(outlook_config)
            await provider._refresh_token()

        assert provider.config.access_token == "new-access-token"
        assert provider.config.refresh_token == "new-refresh-token"
        assert provider.config.token_expiry is not None
        assert provider._client is None

    @pytest.mark.asyncio
    async def test_refresh_token_http_error(
        self, outlook_config: ProviderConfig
    ) -> None:
        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"
        mock_response.request = MagicMock()

        with patch("src.calendar_provider.outlook_provider.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.HTTPStatusError(
                "Bad Request", request=MagicMock(), response=mock_response
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            provider = OutlookCalendarProvider(outlook_config)
            with pytest.raises(httpx.HTTPStatusError):
                await provider._refresh_token()
