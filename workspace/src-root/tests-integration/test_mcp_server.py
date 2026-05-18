"""Integration tests for the MCP server endpoints.

Tests the FastAPI application with mocked calendar providers to verify:
- MCP initialization handshake
- Tool listing via tools/list
- Tool invocation for all 6 calendar tools
- SSE endpoint availability
- Error handling and MCP-compliant error responses
- Provider selection (google vs outlook vs default)
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.models.calendar import (
    Calendar,
    Event,
    EventAttendee,
    EventReminder,
    FreeBusySlot,
    ProviderConfig,
    RecurrenceRule,
)
from src.mcp_server.app import create_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client() -> TestClient:
    """Create a test client for the FastAPI application."""
    app = create_app()
    return TestClient(app)


@pytest.fixture
def sample_calendar() -> Calendar:
    """Create a sample Calendar model."""
    return Calendar(
        id="cal-001",
        name="Work Calendar",
        description="Primary work calendar",
        timezone="America/New_York",
        is_primary=True,
        access_role="owner",
        color="#039BE5",
    )


@pytest.fixture
def sample_event() -> Event:
    """Create a sample Event model."""
    now = datetime.now(timezone.utc)
    return Event(
        id="evt-001",
        calendar_id="cal-001",
        title="Team Meeting",
        description="Weekly team sync",
        location="Conference Room A",
        start=now,
        end=now + timedelta(hours=1),
        timezone="America/New_York",
        attendees=[],
        reminders=[],
        status="confirmed",
        created_at=now - timedelta(days=7),
        updated_at=now - timedelta(days=1),
        is_recurring_master=False,
    )


@pytest.fixture
def sample_free_busy_slot() -> FreeBusySlot:
    """Create a sample FreeBusySlot model."""
    now = datetime.now(timezone.utc)
    return FreeBusySlot(
        start=now,
        end=now + timedelta(hours=1),
        status="busy",
    )


@pytest.fixture
def mock_google_provider(sample_calendar: Calendar, sample_event: Event, sample_free_busy_slot: FreeBusySlot) -> MagicMock:
    """Create a mock Google Calendar provider."""
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
def mock_outlook_provider(sample_calendar: Calendar, sample_event: Event, sample_free_busy_slot: FreeBusySlot) -> MagicMock:
    """Create a mock Outlook Calendar provider."""
    provider = MagicMock()
    provider.provider_name = "outlook"
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
def mock_auth_failed_provider() -> MagicMock:
    """Create a mock provider that fails authentication."""
    provider = MagicMock()
    provider.provider_name = "google"
    provider.authenticate = AsyncMock(return_value=False)
    provider.close = AsyncMock()
    return provider


@pytest.fixture
def mock_provider_error() -> MagicMock:
    """Create a mock provider that raises an error."""
    provider = MagicMock()
    provider.provider_name = "google"
    provider.authenticate = AsyncMock(return_value=True)
    provider.list_calendars = AsyncMock(side_effect=Exception("API connection failed"))
    provider.close = AsyncMock()
    return provider


# ---------------------------------------------------------------------------
# MCP Initialization Tests
# ---------------------------------------------------------------------------


class TestInitialize:
    """Tests for the MCP initialization handshake."""

    def test_initialize_returns_protocol_version(self, client: TestClient) -> None:
        """Initialize endpoint returns the correct protocol version."""
        response = client.post(
            "/initialize",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "1.0.0"},
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert data["id"] == 1
        assert data["result"]["protocolVersion"] == "2024-11-05"

    def test_initialize_returns_server_info(self, client: TestClient) -> None:
        """Initialize endpoint returns server info."""
        response = client.post(
            "/initialize",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["result"]["serverInfo"]["name"] == "calendar-mcp-service"
        assert data["result"]["serverInfo"]["version"] == "1.0.0"

    def test_initialize_returns_capabilities(self, client: TestClient) -> None:
        """Initialize endpoint returns tool capabilities."""
        response = client.post(
            "/initialize",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "tools" in data["result"]["capabilities"]
        assert data["result"]["capabilities"]["tools"]["list"] is True

    def test_initialize_without_id(self, client: TestClient) -> None:
        """Initialize without request ID omits id from response."""
        response = client.post(
            "/initialize",
            json={
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "id" not in data

    def test_initialize_invalid_json(self, client: TestClient) -> None:
        """Initialize with invalid JSON returns parse error."""
        response = client.post(
            "/initialize",
            content="not json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 400
        data = response.json()
        assert data["error"]["code"] == -32700


# ---------------------------------------------------------------------------
# Tool Listing Tests
# ---------------------------------------------------------------------------


class TestToolsList:
    """Tests for the tools/list MCP method."""

    def test_tools_list_returns_all_tools(self, client: TestClient) -> None:
        """Tools list returns all 6 calendar tools."""
        response = client.post(
            "/messages",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
            },
        )
        assert response.status_code == 200
        data = response.json()
        tools = data["result"]["tools"]
        assert len(tools) == 6
        tool_names = [t["name"] for t in tools]
        assert "list_calendars" in tool_names
        assert "get_events" in tool_names
        assert "create_event" in tool_names
        assert "update_event" in tool_names
        assert "delete_event" in tool_names
        assert "get_free_busy" in tool_names

    def test_tools_list_has_required_fields(self, client: TestClient) -> None:
        """Each tool has name, description, and inputSchema."""
        response = client.post(
            "/messages",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
            },
        )
        data = response.json()
        for tool in data["result"]["tools"]:
            assert "name" in tool
            assert "description" in tool
            assert "inputSchema" in tool

    def test_tools_list_via_messages_endpoint(self, client: TestClient) -> None:
        """Tools list works via /messages endpoint."""
        response = client.post(
            "/messages",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == 2
        assert "tools" in data["result"]


# ---------------------------------------------------------------------------
# Tool Invocation Tests
# ---------------------------------------------------------------------------


class TestListCalendars:
    """Tests for the list_calendars tool."""

    @patch("src.mcp_server.tools.create_provider")
    def test_list_calendars_success(
        self, mock_factory: MagicMock, client: TestClient, mock_google_provider: MagicMock
    ) -> None:
        """List calendars returns calendars from the provider."""
        mock_factory.return_value = mock_google_provider
        response = client.post(
            "/messages",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "list_calendars",
                    "arguments": {"provider": "google"},
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["result"]["isError"] is False
        content = json.loads(data["result"]["content"][0]["text"])
        assert "calendars" in content
        assert len(content["calendars"]) == 1
        assert content["calendars"][0]["id"] == "cal-001"
        mock_google_provider.authenticate.assert_awaited_once()
        mock_google_provider.list_calendars.assert_awaited_once()

    @patch("src.mcp_server.tools.create_provider")
    def test_list_calendars_without_provider_uses_default(
        self, mock_factory: MagicMock, client: TestClient, mock_google_provider: MagicMock
    ) -> None:
        """List calendars without provider uses the default provider."""
        mock_factory.return_value = mock_google_provider
        response = client.post(
            "/messages",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "list_calendars",
                    "arguments": {},
                },
            },
        )
        assert response.status_code == 200
        mock_factory.assert_called_once_with(None)

    @patch("src.mcp_server.tools.create_provider")
    def test_list_calendars_auth_failure(
        self, mock_factory: MagicMock, client: TestClient, mock_auth_failed_provider: MagicMock
    ) -> None:
        """List calendars returns error when authentication fails."""
        mock_factory.return_value = mock_auth_failed_provider
        response = client.post(
            "/messages",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "list_calendars",
                    "arguments": {"provider": "google"},
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        content = json.loads(data["result"]["content"][0]["text"])
        assert "error" in content
        assert content["error"]["message"] == "Authentication failed"

    @patch("src.mcp_server.tools.create_provider")
    def test_list_calendars_provider_error(
        self, mock_factory: MagicMock, client: TestClient, mock_provider_error: MagicMock
    ) -> None:
        """List calendars returns MCP error when provider raises exception."""
        mock_factory.return_value = mock_provider_error
        response = client.post(
            "/messages",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "list_calendars",
                    "arguments": {"provider": "google"},
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        content = json.loads(data["result"]["content"][0]["text"])
        assert "error" in content


class TestGetEvents:
    """Tests for the get_events tool."""

    @patch("src.mcp_server.tools.create_provider")
    def test_get_events_success(
        self, mock_factory: MagicMock, client: TestClient, mock_google_provider: MagicMock
    ) -> None:
        """Get events returns events from the provider."""
        mock_factory.return_value = mock_google_provider
        now = datetime.now(timezone.utc)
        response = client.post(
            "/messages",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "get_events",
                    "arguments": {
                        "calendar_id": "cal-001",
                        "start_time": now.isoformat(),
                        "end_time": (now + timedelta(days=1)).isoformat(),
                        "provider": "google",
                        "max_results": 50,
                        "expand_recurring": True,
                    },
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["result"]["isError"] is False
        content = json.loads(data["result"]["content"][0]["text"])
        assert "events" in content
        assert len(content["events"]) == 1
        assert content["events"][0]["id"] == "evt-001"
        mock_google_provider.get_events.assert_awaited_once()

    @patch("src.mcp_server.tools.create_provider")
    def test_get_events_defaults_to_primary_calendar(
        self, mock_factory: MagicMock, client: TestClient, mock_google_provider: MagicMock
    ) -> None:
        """Get events without calendar_id passes None to provider."""
        mock_factory.return_value = mock_google_provider
        now = datetime.now(timezone.utc)
        response = client.post(
            "/messages",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "get_events",
                    "arguments": {
                        "start_time": now.isoformat(),
                        "end_time": (now + timedelta(days=1)).isoformat(),
                    },
                },
            },
        )
        assert response.status_code == 200
        call_args = mock_google_provider.get_events.call_args
        assert call_args.kwargs["calendar_id"] is None


class TestCreateEvent:
    """Tests for the create_event tool."""

    @patch("src.mcp_server.tools.create_provider")
    def test_create_event_success(
        self, mock_factory: MagicMock, client: TestClient, mock_google_provider: MagicMock, sample_event: Event
    ) -> None:
        """Create event returns the created event."""
        mock_factory.return_value = mock_google_provider
        now = datetime.now(timezone.utc)
        response = client.post(
            "/messages",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "create_event",
                    "arguments": {
                        "title": "New Meeting",
                        "start": now.isoformat(),
                        "end": (now + timedelta(hours=1)).isoformat(),
                        "timezone": "America/New_York",
                        "calendar_id": "cal-001",
                        "description": "Test event",
                        "location": "Room B",
                        "provider": "google",
                    },
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["result"]["isError"] is False
        content = json.loads(data["result"]["content"][0]["text"])
        assert "event" in content
        mock_google_provider.create_event.assert_awaited_once()

    @patch("src.mcp_server.tools.create_provider")
    def test_create_event_with_attendees_and_reminders(
        self, mock_factory: MagicMock, client: TestClient, mock_google_provider: MagicMock
    ) -> None:
        """Create event with attendees and reminders passes them correctly."""
        mock_factory.return_value = mock_google_provider
        now = datetime.now(timezone.utc)
        response = client.post(
            "/messages",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "create_event",
                    "arguments": {
                        "title": "Team Sync",
                        "start": now.isoformat(),
                        "end": (now + timedelta(hours=1)).isoformat(),
                        "timezone": "UTC",
                        "attendees": [{"email": "user@example.com", "name": "Test User"}],
                        "reminders": [{"method": "popup", "minutes_before": 10}],
                    },
                },
            },
        )
        assert response.status_code == 200
        call_args = mock_google_provider.create_event.call_args
        assert len(call_args.kwargs["attendees"]) == 1
        assert call_args.kwargs["attendees"][0].email == "user@example.com"
        assert len(call_args.kwargs["reminders"]) == 1
        assert call_args.kwargs["reminders"][0].minutes_before == 10

    @patch("src.mcp_server.tools.create_provider")
    def test_create_event_with_recurrence(
        self, mock_factory: MagicMock, client: TestClient, mock_google_provider: MagicMock
    ) -> None:
        """Create event with recurrence rule passes it correctly."""
        mock_factory.return_value = mock_google_provider
        now = datetime.now(timezone.utc)
        response = client.post(
            "/messages",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "create_event",
                    "arguments": {
                        "title": "Weekly Standup",
                        "start": now.isoformat(),
                        "end": (now + timedelta(minutes=30)).isoformat(),
                        "timezone": "UTC",
                        "recurrence": {
                            "frequency": "weekly",
                            "interval": 1,
                            "by_day": ["MO"],
                            "count": 10,
                        },
                    },
                },
            },
        )
        assert response.status_code == 200
        call_args = mock_google_provider.create_event.call_args
        assert call_args.kwargs["recurrence"] is not None
        assert call_args.kwargs["recurrence"].frequency == "weekly"


class TestUpdateEvent:
    """Tests for the update_event tool."""

    @patch("src.mcp_server.tools.create_provider")
    def test_update_event_success(
        self, mock_factory: MagicMock, client: TestClient, mock_google_provider: MagicMock
    ) -> None:
        """Update event returns the updated event."""
        mock_factory.return_value = mock_google_provider
        now = datetime.now(timezone.utc)
        response = client.post(
            "/messages",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "update_event",
                    "arguments": {
                        "event_id": "evt-001",
                        "title": "Updated Meeting",
                        "calendar_id": "cal-001",
                        "provider": "google",
                    },
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["result"]["isError"] is False
        mock_google_provider.update_event.assert_awaited_once()

    @patch("src.mcp_server.tools.create_provider")
    def test_update_event_partial_update(
        self, mock_factory: MagicMock, client: TestClient, mock_google_provider: MagicMock
    ) -> None:
        """Update event with only title passes None for other fields."""
        mock_factory.return_value = mock_google_provider
        response = client.post(
            "/messages",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "update_event",
                    "arguments": {
                        "event_id": "evt-001",
                        "title": "New Title Only",
                    },
                },
            },
        )
        assert response.status_code == 200
        call_args = mock_google_provider.update_event.call_args
        assert call_args.kwargs["title"] == "New Title Only"
        assert call_args.kwargs["description"] is None
        assert call_args.kwargs["location"] is None

    @patch("src.mcp_server.tools.create_provider")
    def test_update_event_with_datetime(
        self, mock_factory: MagicMock, client: TestClient, mock_google_provider: MagicMock
    ) -> None:
        """Update event with new start/end times parses datetimes correctly."""
        mock_factory.return_value = mock_google_provider
        now = datetime.now(timezone.utc)
        response = client.post(
            "/messages",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "update_event",
                    "arguments": {
                        "event_id": "evt-001",
                        "start": now.isoformat(),
                        "end": (now + timedelta(hours=2)).isoformat(),
                    },
                },
            },
        )
        assert response.status_code == 200
        call_args = mock_google_provider.update_event.call_args
        assert call_args.kwargs["start"] is not None
        assert call_args.kwargs["end"] is not None


class TestDeleteEvent:
    """Tests for the delete_event tool."""

    @patch("src.mcp_server.tools.create_provider")
    def test_delete_event_success(
        self, mock_factory: MagicMock, client: TestClient, mock_google_provider: MagicMock
    ) -> None:
        """Delete event returns success response."""
        mock_factory.return_value = mock_google_provider
        response = client.post(
            "/messages",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "delete_event",
                    "arguments": {
                        "event_id": "evt-001",
                        "calendar_id": "cal-001",
                        "provider": "google",
                    },
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["result"]["isError"] is False
        content = json.loads(data["result"]["content"][0]["text"])
        assert content["success"] is True
        mock_google_provider.delete_event.assert_awaited_once()

    @patch("src.mcp_server.tools.create_provider")
    def test_delete_event_with_series_flag(
        self, mock_factory: MagicMock, client: TestClient, mock_google_provider: MagicMock
    ) -> None:
        """Delete event with delete_series passes flag to provider."""
        mock_factory.return_value = mock_google_provider
        response = client.post(
            "/messages",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "delete_event",
                    "arguments": {
                        "event_id": "evt-001",
                        "delete_series": True,
                        "send_notifications": False,
                    },
                },
            },
        )
        assert response.status_code == 200
        call_args = mock_google_provider.delete_event.call_args
        assert call_args.kwargs["delete_series"] is True
        assert call_args.kwargs["send_notifications"] is False


class TestGetFreeBusy:
    """Tests for the get_free_busy tool."""

    @patch("src.mcp_server.tools.create_provider")
    def test_get_free_busy_success(
        self, mock_factory: MagicMock, client: TestClient, mock_google_provider: MagicMock
    ) -> None:
        """Get free/busy returns availability slots."""
        mock_factory.return_value = mock_google_provider
        now = datetime.now(timezone.utc)
        response = client.post(
            "/messages",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "get_free_busy",
                    "arguments": {
                        "start_time": now.isoformat(),
                        "end_time": (now + timedelta(hours=4)).isoformat(),
                        "calendar_ids": ["cal-001"],
                        "provider": "google",
                    },
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["result"]["isError"] is False
        content = json.loads(data["result"]["content"][0]["text"])
        assert "slots" in content
        assert len(content["slots"]) == 1
        assert content["slots"][0]["status"] == "busy"
        mock_google_provider.get_free_busy.assert_awaited_once()

    @patch("src.mcp_server.tools.create_provider")
    def test_get_free_busy_without_calendar_ids(
        self, mock_factory: MagicMock, client: TestClient, mock_google_provider: MagicMock
    ) -> None:
        """Get free/busy without calendar_ids passes None to provider."""
        mock_factory.return_value = mock_google_provider
        now = datetime.now(timezone.utc)
        response = client.post(
            "/messages",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "get_free_busy",
                    "arguments": {
                        "start_time": now.isoformat(),
                        "end_time": (now + timedelta(hours=4)).isoformat(),
                    },
                },
            },
        )
        assert response.status_code == 200
        call_args = mock_google_provider.get_free_busy.call_args
        assert call_args.kwargs["calendar_ids"] is None


# ---------------------------------------------------------------------------
# Unknown Tool Tests
# ---------------------------------------------------------------------------


class TestUnknownTool:
    """Tests for unknown tool invocations."""

    def test_unknown_tool_returns_method_not_found(self, client: TestClient) -> None:
        """Invoking an unknown tool returns an error."""
        response = client.post(
            "/messages",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "nonexistent_tool",
                    "arguments": {},
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["result"]["isError"] is True
        content = json.loads(data["result"]["content"][0]["text"])
        assert content["error"]["code"] == -32601
        assert "nonexistent_tool" in content["error"]["message"]


# ---------------------------------------------------------------------------
# Unknown Method Tests
# ---------------------------------------------------------------------------


class TestUnknownMethod:
    """Tests for unknown MCP methods."""

    def test_unknown_method_returns_error(self, client: TestClient) -> None:
        """Invoking an unknown MCP method returns method not found."""
        response = client.post(
            "/messages",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "unknown/method",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "error" in data["result"]
        assert data["result"]["error"]["code"] == -32601


# ---------------------------------------------------------------------------
# SSE Endpoint Tests
# ---------------------------------------------------------------------------


class TestSSEEndpoint:
    """Tests for the SSE endpoint."""

    def test_sse_endpoint_exists(self, client: TestClient) -> None:
        """SSE endpoint is accessible."""
        with client.stream("GET", "/sse") as response:
            assert response.status_code == 200
            assert response.headers.get("content-type") == "text/event-stream; charset=utf-8"
            assert response.headers.get("cache-control") == "no-cache"


# ---------------------------------------------------------------------------
# Provider Selection Tests
# ---------------------------------------------------------------------------


class TestProviderSelection:
    """Tests for provider selection in tool calls."""

    @patch("src.mcp_server.tools.create_provider")
    def test_google_provider_selected(
        self, mock_factory: MagicMock, client: TestClient, mock_google_provider: MagicMock
    ) -> None:
        """Specifying google provider creates Google provider."""
        mock_factory.return_value = mock_google_provider
        response = client.post(
            "/messages",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "list_calendars",
                    "arguments": {"provider": "google"},
                },
            },
        )
        assert response.status_code == 200
        mock_factory.assert_called_once_with("google")

    @patch("src.mcp_server.tools.create_provider")
    def test_outlook_provider_selected(
        self, mock_factory: MagicMock, client: TestClient, mock_outlook_provider: MagicMock
    ) -> None:
        """Specifying outlook provider creates Outlook provider."""
        mock_factory.return_value = mock_outlook_provider
        response = client.post(
            "/messages",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "list_calendars",
                    "arguments": {"provider": "outlook"},
                },
            },
        )
        assert response.status_code == 200
        mock_factory.assert_called_once_with("outlook")


# ---------------------------------------------------------------------------
# Resource Cleanup Tests
# ---------------------------------------------------------------------------


class TestResourceCleanup:
    """Tests for provider resource cleanup after tool calls."""

    @patch("src.mcp_server.tools.create_provider")
    def test_provider_closed_after_successful_call(
        self, mock_factory: MagicMock, client: TestClient, mock_google_provider: MagicMock
    ) -> None:
        """Provider is closed after a successful tool call."""
        mock_factory.return_value = mock_google_provider
        response = client.post(
            "/messages",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "list_calendars",
                    "arguments": {"provider": "google"},
                },
            },
        )
        assert response.status_code == 200
        mock_google_provider.close.assert_awaited_once()

    @patch("src.mcp_server.tools.create_provider")
    def test_provider_closed_after_error(
        self, mock_factory: MagicMock, client: TestClient, mock_provider_error: MagicMock
    ) -> None:
        """Provider is closed even when an error occurs."""
        mock_factory.return_value = mock_provider_error
        response = client.post(
            "/messages",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "list_calendars",
                    "arguments": {"provider": "google"},
                },
            },
        )
        assert response.status_code == 200
        mock_provider_error.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# Rate Limiter Integration Tests
# ---------------------------------------------------------------------------


class TestRateLimiterIntegration:
    """Tests for rate limiter integration with tool calls."""

    @patch("src.mcp_server.tools.get_rate_limiter")
    @patch("src.mcp_server.tools.create_provider")
    def test_rate_limiter_acquire_called(
        self,
        mock_factory: MagicMock,
        mock_rate_limiter_factory: MagicMock,
        client: TestClient,
        mock_google_provider: MagicMock,
    ) -> None:
        """Rate limiter acquire is called before provider operations."""
        mock_factory.return_value = mock_google_provider
        mock_rate_limiter = MagicMock()
        mock_rate_limiter.acquire = AsyncMock()
        mock_rate_limiter_factory.return_value = mock_rate_limiter

        response = client.post(
            "/messages",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "list_calendars",
                    "arguments": {"provider": "google"},
                },
            },
        )
        assert response.status_code == 200
        mock_rate_limiter.acquire.assert_awaited_once()
