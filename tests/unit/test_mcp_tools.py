"""Unit tests for MCP tool handler functions.

Tests cover:
- _execute_with_provider rate limiting, auth, error handling, cleanup
- _handle_list_calendars
- _handle_get_events
- _handle_create_event
- _handle_update_event
- _handle_delete_event
- _handle_get_free_busy
- TOOL_DEFINITIONS structure validation
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.mcp_server.tools import (
    TOOL_DEFINITIONS,
    TOOL_HANDLERS,
    _execute_with_provider,
    _handle_list_calendars,
    _handle_get_events,
    _handle_create_event,
    _handle_update_event,
    _handle_delete_event,
    _handle_get_free_busy,
)


# ---------------------------------------------------------------------------
# TOOL_DEFINITIONS validation
# ---------------------------------------------------------------------------


class TestToolDefinitions:
    """Tests for the TOOL_DEFINITIONS structure."""

    def test_has_six_tools(self) -> None:
        assert len(TOOL_DEFINITIONS) == 6

    def test_all_tools_have_name(self) -> None:
        for tool in TOOL_DEFINITIONS:
            assert "name" in tool

    def test_all_tools_have_description(self) -> None:
        for tool in TOOL_DEFINITIONS:
            assert "description" in tool
            assert len(tool["description"]) > 0

    def test_all_tools_have_input_schema(self) -> None:
        for tool in TOOL_DEFINITIONS:
            assert "inputSchema" in tool
            assert tool["inputSchema"]["type"] == "object"

    def test_tool_names(self) -> None:
        names = [t["name"] for t in TOOL_DEFINITIONS]
        expected = [
            "list_calendars",
            "get_events",
            "create_event",
            "update_event",
            "delete_event",
            "get_free_busy",
        ]
        assert names == expected

    def test_get_events_requires_start_and_end_time(self) -> None:
        tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "get_events")
        assert "start_time" in tool["inputSchema"]["required"]
        assert "end_time" in tool["inputSchema"]["required"]

    def test_create_event_requires_title_start_end_timezone(self) -> None:
        tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "create_event")
        required = tool["inputSchema"]["required"]
        assert "title" in required
        assert "start" in required
        assert "end" in required
        assert "timezone" in required

    def test_update_event_requires_event_id(self) -> None:
        tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "update_event")
        assert "event_id" in tool["inputSchema"]["required"]

    def test_delete_event_requires_event_id(self) -> None:
        tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "delete_event")
        assert "event_id" in tool["inputSchema"]["required"]

    def test_get_free_busy_requires_start_and_end_time(self) -> None:
        tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "get_free_busy")
        assert "start_time" in tool["inputSchema"]["required"]
        assert "end_time" in tool["inputSchema"]["required"]

    def test_provider_enum_in_tools(self) -> None:
        for tool in TOOL_DEFINITIONS:
            props = tool["inputSchema"].get("properties", {})
            if "provider" in props:
                assert props["provider"]["enum"] == ["google", "outlook"]


# ---------------------------------------------------------------------------
# TOOL_HANDLERS validation
# ---------------------------------------------------------------------------


class TestToolHandlers:
    """Tests for the TOOL_HANDLERS mapping."""

    def test_has_six_handlers(self) -> None:
        assert len(TOOL_HANDLERS) == 6

    def test_all_handlers_are_coroutines(self) -> None:
        for name, handler in TOOL_HANDLERS.items():
            assert callable(handler)

    def test_handler_names_match_definitions(self) -> None:
        definition_names = {t["name"] for t in TOOL_DEFINITIONS}
        handler_names = set(TOOL_HANDLERS.keys())
        assert definition_names == handler_names


# ---------------------------------------------------------------------------
# _execute_with_provider tests
# ---------------------------------------------------------------------------


class TestExecuteWithProvider:
    """Tests for the _execute_with_provider helper."""

    @pytest.mark.asyncio
    async def test_calls_rate_limiter_acquire(self) -> None:
        mock_provider = MagicMock()
        mock_provider.provider_name = "google"
        mock_provider.authenticate = AsyncMock(return_value=True)
        mock_provider.close = AsyncMock()

        mock_rate_limiter = MagicMock()
        mock_rate_limiter.acquire = AsyncMock()

        operation_fn = AsyncMock(return_value={"result": "ok"})

        with patch("src.mcp_server.tools.create_provider", return_value=mock_provider):
            with patch("src.mcp_server.tools.get_rate_limiter", return_value=mock_rate_limiter):
                await _execute_with_provider("google", "test_op", operation_fn)

        mock_rate_limiter.acquire.assert_called_once_with("google", "test_op")

    @pytest.mark.asyncio
    async def test_calls_authenticate(self) -> None:
        mock_provider = MagicMock()
        mock_provider.provider_name = "google"
        mock_provider.authenticate = AsyncMock(return_value=True)
        mock_provider.close = AsyncMock()

        mock_rate_limiter = MagicMock()
        mock_rate_limiter.acquire = AsyncMock()

        operation_fn = AsyncMock(return_value={"result": "ok"})

        with patch("src.mcp_server.tools.create_provider", return_value=mock_provider):
            with patch("src.mcp_server.tools.get_rate_limiter", return_value=mock_rate_limiter):
                await _execute_with_provider("google", "test_op", operation_fn)

        mock_provider.authenticate.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_auth_error_on_failure(self) -> None:
        mock_provider = MagicMock()
        mock_provider.provider_name = "google"
        mock_provider.authenticate = AsyncMock(return_value=False)
        mock_provider.close = AsyncMock()

        mock_rate_limiter = MagicMock()
        mock_rate_limiter.acquire = AsyncMock()

        operation_fn = AsyncMock(return_value={"result": "ok"})

        with patch("src.mcp_server.tools.create_provider", return_value=mock_provider):
            with patch("src.mcp_server.tools.get_rate_limiter", return_value=mock_rate_limiter):
                result = await _execute_with_provider("google", "test_op", operation_fn)

        assert result["error"]["message"] == "Authentication failed"

    @pytest.mark.asyncio
    async def test_calls_operation_with_provider(self) -> None:
        mock_provider = MagicMock()
        mock_provider.provider_name = "google"
        mock_provider.authenticate = AsyncMock(return_value=True)
        mock_provider.close = AsyncMock()

        mock_rate_limiter = MagicMock()
        mock_rate_limiter.acquire = AsyncMock()

        operation_fn = AsyncMock(return_value={"result": "ok"})

        with patch("src.mcp_server.tools.create_provider", return_value=mock_provider):
            with patch("src.mcp_server.tools.get_rate_limiter", return_value=mock_rate_limiter):
                await _execute_with_provider("google", "test_op", operation_fn, "arg1", kwarg1="val1")

        operation_fn.assert_called_once_with(mock_provider, "arg1", kwarg1="val1")

    @pytest.mark.asyncio
    async def test_returns_operation_result(self) -> None:
        mock_provider = MagicMock()
        mock_provider.provider_name = "google"
        mock_provider.authenticate = AsyncMock(return_value=True)
        mock_provider.close = AsyncMock()

        mock_rate_limiter = MagicMock()
        mock_rate_limiter.acquire = AsyncMock()

        operation_fn = AsyncMock(return_value={"calendars": [{"id": "cal-1"}]})

        with patch("src.mcp_server.tools.create_provider", return_value=mock_provider):
            with patch("src.mcp_server.tools.get_rate_limiter", return_value=mock_rate_limiter):
                result = await _execute_with_provider("google", "test_op", operation_fn)

        assert result == {"calendars": [{"id": "cal-1"}]}

    @pytest.mark.asyncio
    async def test_closes_provider_on_success(self) -> None:
        mock_provider = MagicMock()
        mock_provider.provider_name = "google"
        mock_provider.authenticate = AsyncMock(return_value=True)
        mock_provider.close = AsyncMock()

        mock_rate_limiter = MagicMock()
        mock_rate_limiter.acquire = AsyncMock()

        operation_fn = AsyncMock(return_value={"result": "ok"})

        with patch("src.mcp_server.tools.create_provider", return_value=mock_provider):
            with patch("src.mcp_server.tools.get_rate_limiter", return_value=mock_rate_limiter):
                await _execute_with_provider("google", "test_op", operation_fn)

        mock_provider.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_closes_provider_on_error(self) -> None:
        mock_provider = MagicMock()
        mock_provider.provider_name = "google"
        mock_provider.authenticate = AsyncMock(return_value=True)
        mock_provider.close = AsyncMock()

        mock_rate_limiter = MagicMock()
        mock_rate_limiter.acquire = AsyncMock()

        operation_fn = AsyncMock(side_effect=RuntimeError("boom"))

        with patch("src.mcp_server.tools.create_provider", return_value=mock_provider):
            with patch("src.mcp_server.tools.get_rate_limiter", return_value=mock_rate_limiter):
                await _execute_with_provider("google", "test_op", operation_fn)

        mock_provider.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_error_on_exception(self) -> None:
        mock_provider = MagicMock()
        mock_provider.provider_name = "google"
        mock_provider.authenticate = AsyncMock(return_value=True)
        mock_provider.close = AsyncMock()

        mock_rate_limiter = MagicMock()
        mock_rate_limiter.acquire = AsyncMock()

        operation_fn = AsyncMock(side_effect=RuntimeError("something broke"))

        with patch("src.mcp_server.tools.create_provider", return_value=mock_provider):
            with patch("src.mcp_server.tools.get_rate_limiter", return_value=mock_rate_limiter):
                result = await _execute_with_provider("google", "test_op", operation_fn)

        assert "error" in result

    @pytest.mark.asyncio
    async def test_uses_none_provider_name(self) -> None:
        mock_provider = MagicMock()
        mock_provider.provider_name = "google"
        mock_provider.authenticate = AsyncMock(return_value=True)
        mock_provider.close = AsyncMock()

        mock_rate_limiter = MagicMock()
        mock_rate_limiter.acquire = AsyncMock()

        operation_fn = AsyncMock(return_value={"result": "ok"})

        with patch("src.mcp_server.tools.create_provider", return_value=mock_provider) as mock_factory:
            with patch("src.mcp_server.tools.get_rate_limiter", return_value=mock_rate_limiter):
                await _execute_with_provider(None, "test_op", operation_fn)

        mock_factory.assert_called_once_with(None)


# ---------------------------------------------------------------------------
# _handle_list_calendars tests
# ---------------------------------------------------------------------------


class TestHandleListCalendars:
    """Tests for the _handle_list_calendars function."""

    @pytest.mark.asyncio
    async def test_calls_provider_list_calendars(self) -> None:
        mock_provider = MagicMock()
        mock_provider.provider_name = "google"
        mock_provider.authenticate = AsyncMock(return_value=True)
        mock_provider.list_calendars = AsyncMock(return_value=[])
        mock_provider.close = AsyncMock()

        mock_rate_limiter = MagicMock()
        mock_rate_limiter.acquire = AsyncMock()

        with patch("src.mcp_server.tools.create_provider", return_value=mock_provider):
            with patch("src.mcp_server.tools.get_rate_limiter", return_value=mock_rate_limiter):
                result = await _handle_list_calendars({"provider": "google"})

        mock_provider.list_calendars.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_calendars_as_dicts(self) -> None:
        mock_cal = MagicMock()
        mock_cal.model_dump.return_value = {"id": "cal-1", "name": "Test"}

        mock_provider = MagicMock()
        mock_provider.provider_name = "google"
        mock_provider.authenticate = AsyncMock(return_value=True)
        mock_provider.list_calendars = AsyncMock(return_value=[mock_cal])
        mock_provider.close = AsyncMock()

        mock_rate_limiter = MagicMock()
        mock_rate_limiter.acquire = AsyncMock()

        with patch("src.mcp_server.tools.create_provider", return_value=mock_provider):
            with patch("src.mcp_server.tools.get_rate_limiter", return_value=mock_rate_limiter):
                result = await _handle_list_calendars({"provider": "google"})

        assert result["calendars"] == [{"id": "cal-1", "name": "Test"}]

    @pytest.mark.asyncio
    async def test_passes_provider_to_factory(self) -> None:
        mock_provider = MagicMock()
        mock_provider.provider_name = "outlook"
        mock_provider.authenticate = AsyncMock(return_value=True)
        mock_provider.list_calendars = AsyncMock(return_value=[])
        mock_provider.close = AsyncMock()

        mock_rate_limiter = MagicMock()
        mock_rate_limiter.acquire = AsyncMock()

        with patch("src.mcp_server.tools.create_provider", return_value=mock_provider) as mock_factory:
            with patch("src.mcp_server.tools.get_rate_limiter", return_value=mock_rate_limiter):
                await _handle_list_calendars({"provider": "outlook"})

        mock_factory.assert_called_once_with("outlook")


# ---------------------------------------------------------------------------
# _handle_get_events tests
# ---------------------------------------------------------------------------


class TestHandleGetEvents:
    """Tests for the _handle_get_events function."""

    @pytest.mark.asyncio
    async def test_calls_provider_get_events(self) -> None:
        mock_provider = MagicMock()
        mock_provider.provider_name = "google"
        mock_provider.authenticate = AsyncMock(return_value=True)
        mock_provider.get_events = AsyncMock(return_value=[])
        mock_provider.close = AsyncMock()

        mock_rate_limiter = MagicMock()
        mock_rate_limiter.acquire = AsyncMock()

        now = datetime.now(timezone.utc)
        params = {
            "calendar_id": "cal-1",
            "start_time": now.isoformat(),
            "end_time": (now + timedelta(days=1)).isoformat(),
            "provider": "google",
            "max_results": 50,
            "expand_recurring": True,
        }

        with patch("src.mcp_server.tools.create_provider", return_value=mock_provider):
            with patch("src.mcp_server.tools.get_rate_limiter", return_value=mock_rate_limiter):
                result = await _handle_get_events(params)

        mock_provider.get_events.assert_called_once()
        call_kwargs = mock_provider.get_events.call_args.kwargs
        assert call_kwargs["calendar_id"] == "cal-1"
        assert call_kwargs["max_results"] == 50
        assert call_kwargs["expand_recurring"] is True

    @pytest.mark.asyncio
    async def test_returns_events_as_dicts(self) -> None:
        mock_event = MagicMock()
        mock_event.model_dump.return_value = {"id": "evt-1", "title": "Test"}

        mock_provider = MagicMock()
        mock_provider.provider_name = "google"
        mock_provider.authenticate = AsyncMock(return_value=True)
        mock_provider.get_events = AsyncMock(return_value=[mock_event])
        mock_provider.close = AsyncMock()

        mock_rate_limiter = MagicMock()
        mock_rate_limiter.acquire = AsyncMock()

        now = datetime.now(timezone.utc)
        params = {
            "start_time": now.isoformat(),
            "end_time": (now + timedelta(hours=1)).isoformat(),
        }

        with patch("src.mcp_server.tools.create_provider", return_value=mock_provider):
            with patch("src.mcp_server.tools.get_rate_limiter", return_value=mock_rate_limiter):
                result = await _handle_get_events(params)

        assert result["events"] == [{"id": "evt-1", "title": "Test"}]


# ---------------------------------------------------------------------------
# _handle_create_event tests
# ---------------------------------------------------------------------------


class TestHandleCreateEvent:
    """Tests for the _handle_create_event function."""

    @pytest.mark.asyncio
    async def test_calls_provider_create_event(self) -> None:
        mock_provider = MagicMock()
        mock_provider.provider_name = "google"
        mock_provider.authenticate = AsyncMock(return_value=True)
        mock_provider.create_event = AsyncMock()
        mock_provider.close = AsyncMock()

        mock_rate_limiter = MagicMock()
        mock_rate_limiter.acquire = AsyncMock()

        now = datetime.now(timezone.utc)
        params = {
            "title": "New Meeting",
            "start": now.isoformat(),
            "end": (now + timedelta(hours=1)).isoformat(),
            "timezone": "UTC",
            "provider": "google",
        }

        with patch("src.mcp_server.tools.create_provider", return_value=mock_provider):
            with patch("src.mcp_server.tools.get_rate_limiter", return_value=mock_rate_limiter):
                await _handle_create_event(params)

        mock_provider.create_event.assert_called_once()
        call_kwargs = mock_provider.create_event.call_args.kwargs
        assert call_kwargs["title"] == "New Meeting"
        assert call_kwargs["timezone"] == "UTC"

    @pytest.mark.asyncio
    async def test_returns_created_event(self) -> None:
        mock_event = MagicMock()
        mock_event.model_dump.return_value = {"id": "new-evt", "title": "New"}

        mock_provider = MagicMock()
        mock_provider.provider_name = "google"
        mock_provider.authenticate = AsyncMock(return_value=True)
        mock_provider.create_event = AsyncMock(return_value=mock_event)
        mock_provider.close = AsyncMock()

        mock_rate_limiter = MagicMock()
        mock_rate_limiter.acquire = AsyncMock()

        now = datetime.now(timezone.utc)
        params = {
            "title": "New Meeting",
            "start": now.isoformat(),
            "end": (now + timedelta(hours=1)).isoformat(),
            "timezone": "UTC",
        }

        with patch("src.mcp_server.tools.create_provider", return_value=mock_provider):
            with patch("src.mcp_server.tools.get_rate_limiter", return_value=mock_rate_limiter):
                result = await _handle_create_event(params)

        assert result["event"]["id"] == "new-evt"

    @pytest.mark.asyncio
    async def test_with_attendees_and_reminders(self) -> None:
        mock_provider = MagicMock()
        mock_provider.provider_name = "google"
        mock_provider.authenticate = AsyncMock(return_value=True)
        mock_provider.create_event = AsyncMock()
        mock_provider.close = AsyncMock()

        mock_rate_limiter = MagicMock()
        mock_rate_limiter.acquire = AsyncMock()

        now = datetime.now(timezone.utc)
        params = {
            "title": "Meeting",
            "start": now.isoformat(),
            "end": (now + timedelta(hours=1)).isoformat(),
            "timezone": "UTC",
            "attendees": [{"email": "user@example.com"}],
            "reminders": [{"method": "popup", "minutes_before": 10}],
        }

        with patch("src.mcp_server.tools.create_provider", return_value=mock_provider):
            with patch("src.mcp_server.tools.get_rate_limiter", return_value=mock_rate_limiter):
                await _handle_create_event(params)

        call_kwargs = mock_provider.create_event.call_args.kwargs
        assert len(call_kwargs["attendees"]) == 1
        assert len(call_kwargs["reminders"]) == 1


# ---------------------------------------------------------------------------
# _handle_update_event tests
# ---------------------------------------------------------------------------


class TestHandleUpdateEvent:
    """Tests for the _handle_update_event function."""

    @pytest.mark.asyncio
    async def test_calls_provider_update_event(self) -> None:
        mock_provider = MagicMock()
        mock_provider.provider_name = "google"
        mock_provider.authenticate = AsyncMock(return_value=True)
        mock_provider.update_event = AsyncMock()
        mock_provider.close = AsyncMock()

        mock_rate_limiter = MagicMock()
        mock_rate_limiter.acquire = AsyncMock()

        params = {
            "event_id": "evt-1",
            "title": "Updated Title",
            "provider": "google",
        }

        with patch("src.mcp_server.tools.create_provider", return_value=mock_provider):
            with patch("src.mcp_server.tools.get_rate_limiter", return_value=mock_rate_limiter):
                await _handle_update_event(params)

        mock_provider.update_event.assert_called_once()
        call_kwargs = mock_provider.update_event.call_args.kwargs
        assert call_kwargs["event_id"] == "evt-1"
        assert call_kwargs["title"] == "Updated Title"

    @pytest.mark.asyncio
    async def test_partial_update(self) -> None:
        mock_provider = MagicMock()
        mock_provider.provider_name = "google"
        mock_provider.authenticate = AsyncMock(return_value=True)
        mock_provider.update_event = AsyncMock()
        mock_provider.close = AsyncMock()

        mock_rate_limiter = MagicMock()
        mock_rate_limiter.acquire = AsyncMock()

        params = {
            "event_id": "evt-1",
            "title": "Only Title",
        }

        with patch("src.mcp_server.tools.create_provider", return_value=mock_provider):
            with patch("src.mcp_server.tools.get_rate_limiter", return_value=mock_rate_limiter):
                await _handle_update_event(params)

        call_kwargs = mock_provider.update_event.call_args.kwargs
        assert call_kwargs["description"] is None
        assert call_kwargs["location"] is None
        assert call_kwargs["send_notifications"] is True
        assert call_kwargs["update_series"] is False


# ---------------------------------------------------------------------------
# _handle_delete_event tests
# ---------------------------------------------------------------------------


class TestHandleDeleteEvent:
    """Tests for the _handle_delete_event function."""

    @pytest.mark.asyncio
    async def test_calls_provider_delete_event(self) -> None:
        mock_provider = MagicMock()
        mock_provider.provider_name = "google"
        mock_provider.authenticate = AsyncMock(return_value=True)
        mock_provider.delete_event = AsyncMock(return_value=True)
        mock_provider.close = AsyncMock()

        mock_rate_limiter = MagicMock()
        mock_rate_limiter.acquire = AsyncMock()

        params = {
            "event_id": "evt-1",
            "calendar_id": "cal-1",
            "provider": "google",
        }

        with patch("src.mcp_server.tools.create_provider", return_value=mock_provider):
            with patch("src.mcp_server.tools.get_rate_limiter", return_value=mock_rate_limiter):
                result = await _handle_delete_event(params)

        mock_provider.delete_event.assert_called_once()
        call_kwargs = mock_provider.delete_event.call_args.kwargs
        assert call_kwargs["event_id"] == "evt-1"
        assert call_kwargs["calendar_id"] == "cal-1"
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_returns_deletion_confirmation(self) -> None:
        mock_provider = MagicMock()
        mock_provider.provider_name = "google"
        mock_provider.authenticate = AsyncMock(return_value=True)
        mock_provider.delete_event = AsyncMock(return_value=True)
        mock_provider.close = AsyncMock()

        mock_rate_limiter = MagicMock()
        mock_rate_limiter.acquire = AsyncMock()

        params = {"event_id": "evt-1"}

        with patch("src.mcp_server.tools.create_provider", return_value=mock_provider):
            with patch("src.mcp_server.tools.get_rate_limiter", return_value=mock_rate_limiter):
                result = await _handle_delete_event(params)

        assert result["success"] is True
        assert "deleted successfully" in result["message"]

    @pytest.mark.asyncio
    async def test_returns_failure_message(self) -> None:
        mock_provider = MagicMock()
        mock_provider.provider_name = "google"
        mock_provider.authenticate = AsyncMock(return_value=True)
        mock_provider.delete_event = AsyncMock(return_value=False)
        mock_provider.close = AsyncMock()

        mock_rate_limiter = MagicMock()
        mock_rate_limiter.acquire = AsyncMock()

        params = {"event_id": "evt-1"}

        with patch("src.mcp_server.tools.create_provider", return_value=mock_provider):
            with patch("src.mcp_server.tools.get_rate_limiter", return_value=mock_rate_limiter):
                result = await _handle_delete_event(params)

        assert result["success"] is False
        assert "Failed to delete" in result["message"]


# ---------------------------------------------------------------------------
# _handle_get_free_busy tests
# ---------------------------------------------------------------------------


class TestHandleGetFreeBusy:
    """Tests for the _handle_get_free_busy function."""

    @pytest.mark.asyncio
    async def test_calls_provider_get_free_busy(self) -> None:
        mock_provider = MagicMock()
        mock_provider.provider_name = "google"
        mock_provider.authenticate = AsyncMock(return_value=True)
        mock_provider.get_free_busy = AsyncMock(return_value=[])
        mock_provider.close = AsyncMock()

        mock_rate_limiter = MagicMock()
        mock_rate_limiter.acquire = AsyncMock()

        now = datetime.now(timezone.utc)
        params = {
            "start_time": now.isoformat(),
            "end_time": (now + timedelta(hours=4)).isoformat(),
            "calendar_ids": ["cal-1"],
            "provider": "google",
        }

        with patch("src.mcp_server.tools.create_provider", return_value=mock_provider):
            with patch("src.mcp_server.tools.get_rate_limiter", return_value=mock_rate_limiter):
                result = await _handle_get_free_busy(params)

        mock_provider.get_free_busy.assert_called_once()
        call_kwargs = mock_provider.get_free_busy.call_args.kwargs
        assert call_kwargs["calendar_ids"] == ["cal-1"]

    @pytest.mark.asyncio
    async def test_returns_slots_as_dicts(self) -> None:
        mock_slot = MagicMock()
        mock_slot.model_dump.return_value = {"start": "2026-01-01T00:00:00Z", "end": "2026-01-01T01:00:00Z", "status": "busy"}

        mock_provider = MagicMock()
        mock_provider.provider_name = "google"
        mock_provider.authenticate = AsyncMock(return_value=True)
        mock_provider.get_free_busy = AsyncMock(return_value=[mock_slot])
        mock_provider.close = AsyncMock()

        mock_rate_limiter = MagicMock()
        mock_rate_limiter.acquire = AsyncMock()

        now = datetime.now(timezone.utc)
        params = {
            "start_time": now.isoformat(),
            "end_time": (now + timedelta(hours=1)).isoformat(),
        }

        with patch("src.mcp_server.tools.create_provider", return_value=mock_provider):
            with patch("src.mcp_server.tools.get_rate_limiter", return_value=mock_rate_limiter):
                result = await _handle_get_free_busy(params)

        assert len(result["slots"]) == 1
        assert result["slots"][0]["status"] == "busy"
