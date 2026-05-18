"""MCP tool definitions for the Calendar MCP Service.

Registers calendar operation tools (list_calendars, get_events, create_event,
update_event, delete_event, get_free_busy) with the MCP protocol.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import FastAPI

from src.calendar_provider.base import CalendarProvider
from src.calendar_provider.factory import create_provider
from src.models.calendar import EventAttendee, EventReminder, RecurrenceRule
from src.services.error_handler import handle_provider_error
from src.services.rate_limiter import get_rate_limiter

logger = logging.getLogger(__name__)

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "list_calendars",
        "description": "List all accessible calendars for the authenticated user",
        "inputSchema": {
            "type": "object",
            "properties": {
                "provider": {
                    "type": "string",
                    "description": "Optional provider filter (google/outlook)",
                    "enum": ["google", "outlook"],
                }
            },
        },
    },
    {
        "name": "get_events",
        "description": "Retrieve events within a specified time range",
        "inputSchema": {
            "type": "object",
            "properties": {
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar ID to query; defaults to primary",
                },
                "start_time": {
                    "type": "string",
                    "format": "date-time",
                    "description": "Start of the time window (ISO 8601)",
                },
                "end_time": {
                    "type": "string",
                    "format": "date-time",
                    "description": "End of the time window (ISO 8601)",
                },
                "provider": {
                    "type": "string",
                    "description": "Optional provider filter (google/outlook)",
                    "enum": ["google", "outlook"],
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of events to return",
                    "default": 100,
                },
                "expand_recurring": {
                    "type": "boolean",
                    "description": "Expand recurring events into individual occurrences",
                    "default": True,
                },
            },
            "required": ["start_time", "end_time"],
        },
    },
    {
        "name": "create_event",
        "description": "Create a new calendar event",
        "inputSchema": {
            "type": "object",
            "properties": {
                "calendar_id": {
                    "type": "string",
                    "description": "Target calendar ID; defaults to primary",
                },
                "title": {
                    "type": "string",
                    "description": "Title/summary of the event",
                },
                "description": {
                    "type": "string",
                    "description": "Detailed description of the event",
                },
                "location": {
                    "type": "string",
                    "description": "Physical or virtual location",
                },
                "start": {
                    "type": "string",
                    "format": "date-time",
                    "description": "Start time (ISO 8601)",
                },
                "end": {
                    "type": "string",
                    "format": "date-time",
                    "description": "End time (ISO 8601)",
                },
                "timezone": {
                    "type": "string",
                    "description": "IANA timezone string",
                },
                "attendees": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "email": {"type": "string"},
                            "name": {"type": "string"},
                            "response_status": {"type": "string"},
                            "is_organizer": {"type": "boolean"},
                        },
                        "required": ["email"],
                    },
                    "description": "List of attendees",
                },
                "reminders": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "method": {"type": "string", "enum": ["email", "popup"]},
                            "minutes_before": {"type": "integer"},
                        },
                        "required": ["method", "minutes_before"],
                    },
                    "description": "List of reminders",
                },
                "recurrence": {
                    "type": "object",
                    "properties": {
                        "frequency": {"type": "string", "enum": ["daily", "weekly", "monthly", "yearly"]},
                        "interval": {"type": "integer"},
                        "count": {"type": "integer"},
                        "until": {"type": "string", "format": "date-time"},
                        "by_day": {"type": "array", "items": {"type": "string"}},
                        "by_month_day": {"type": "array", "items": {"type": "integer"}},
                    },
                    "required": ["frequency"],
                    "description": "Recurrence rule for recurring events",
                },
                "provider": {
                    "type": "string",
                    "description": "Optional provider filter (google/outlook)",
                    "enum": ["google", "outlook"],
                },
            },
            "required": ["title", "start", "end", "timezone"],
        },
    },
    {
        "name": "update_event",
        "description": "Update an existing calendar event",
        "inputSchema": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "ID of the event to update",
                },
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar containing the event",
                },
                "title": {"type": "string"},
                "description": {"type": "string"},
                "location": {"type": "string"},
                "start": {"type": "string", "format": "date-time"},
                "end": {"type": "string", "format": "date-time"},
                "timezone": {"type": "string"},
                "attendees": {
                    "type": "array",
                    "items": {"type": "object"},
                },
                "reminders": {
                    "type": "array",
                    "items": {"type": "object"},
                },
                "recurrence": {"type": "object"},
                "status": {
                    "type": "string",
                    "enum": ["confirmed", "tentative", "cancelled"],
                },
                "send_notifications": {
                    "type": "boolean",
                    "default": True,
                },
                "update_series": {
                    "type": "boolean",
                    "default": False,
                    "description": "Update entire recurring series",
                },
                "provider": {
                    "type": "string",
                    "description": "Optional provider filter (google/outlook)",
                    "enum": ["google", "outlook"],
                },
            },
            "required": ["event_id"],
        },
    },
    {
        "name": "delete_event",
        "description": "Delete a calendar event",
        "inputSchema": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "ID of the event to delete",
                },
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar containing the event",
                },
                "send_notifications": {
                    "type": "boolean",
                    "default": True,
                },
                "delete_series": {
                    "type": "boolean",
                    "default": False,
                    "description": "Delete entire recurring series",
                },
                "provider": {
                    "type": "string",
                    "description": "Optional provider filter (google/outlook)",
                    "enum": ["google", "outlook"],
                },
            },
            "required": ["event_id"],
        },
    },
    {
        "name": "get_free_busy",
        "description": "Check availability for a time range",
        "inputSchema": {
            "type": "object",
            "properties": {
                "calendar_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Calendar IDs to check; defaults to all",
                },
                "start_time": {
                    "type": "string",
                    "format": "date-time",
                    "description": "Start of the query window (ISO 8601)",
                },
                "end_time": {
                    "type": "string",
                    "format": "date-time",
                    "description": "End of the query window (ISO 8601)",
                },
                "provider": {
                    "type": "string",
                    "description": "Optional provider filter (google/outlook)",
                    "enum": ["google", "outlook"],
                },
            },
            "required": ["start_time", "end_time"],
        },
    },
]


async def _execute_with_provider(
    provider_name: str | None,
    operation: str,
    func,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Execute an operation with a calendar provider, handling rate limiting and errors.

    Args:
        provider_name: Provider to use (google/outlook), or None for default.
        operation: Operation name for rate limiter context.
        func: Async callable that receives the provider as its first argument.
        *args: Positional arguments to pass to func after the provider.
        **kwargs: Keyword arguments to pass to func.

    Returns:
        The result of the callable.

    Raises:
        Propagates exceptions as MCP error responses.
    """
    rate_limiter = get_rate_limiter()
    provider: CalendarProvider = create_provider(provider_name)

    try:
        await rate_limiter.acquire(provider.provider_name, operation)
        authenticated = await provider.authenticate()
        if not authenticated:
            return {
                "error": {
                    "code": -32603,
                    "message": "Authentication failed",
                    "data": {"provider": provider.provider_name},
                }
            }
        result = await func(provider, *args, **kwargs)
        return result
    except Exception as e:
        return handle_provider_error(e)
    finally:
        try:
            await provider.close()
        except Exception:
            pass


async def _handle_list_calendars(params: dict[str, Any]) -> dict[str, Any]:
    """Handle the list_calendars tool invocation.

    Args:
        params: Tool invocation parameters.

    Returns:
        MCP-compliant response with calendar list.
    """
    provider_name = params.get("provider")

    async def _op(provider: CalendarProvider) -> dict[str, Any]:
        calendars = await provider.list_calendars()
        return {"calendars": [c.model_dump() for c in calendars]}

    return await _execute_with_provider(provider_name, "list_calendars", _op)


async def _handle_get_events(params: dict[str, Any]) -> dict[str, Any]:
    """Handle the get_events tool invocation.

    Args:
        params: Tool invocation parameters.

    Returns:
        MCP-compliant response with event list.
    """
    from datetime import datetime, timezone

    provider_name = params.get("provider")
    calendar_id = params.get("calendar_id")
    start_time_str = params.get("start_time")
    end_time_str = params.get("end_time")
    max_results = params.get("max_results", 100)
    expand_recurring = params.get("expand_recurring", True)

    start_time = datetime.fromisoformat(start_time_str) if start_time_str else datetime.now(timezone.utc)
    end_time = datetime.fromisoformat(end_time_str) if end_time_str else start_time.replace(hour=23, minute=59, second=59)

    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)

    async def _op(provider: CalendarProvider) -> dict[str, Any]:
        events = await provider.get_events(
            calendar_id=calendar_id,
            start_time=start_time,
            end_time=end_time,
            max_results=max_results,
            expand_recurring=expand_recurring,
        )
        return {"events": [e.model_dump() for e in events]}

    return await _execute_with_provider(provider_name, "get_events", _op)


async def _handle_create_event(params: dict[str, Any]) -> dict[str, Any]:
    """Handle the create_event tool invocation.

    Args:
        params: Tool invocation parameters.

    Returns:
        MCP-compliant response with created event.
    """
    from datetime import datetime, timezone

    provider_name = params.get("provider")
    title = params["title"]
    start_str = params["start"]
    end_str = params["end"]
    timezone_str = params["timezone"]
    calendar_id = params.get("calendar_id")
    description = params.get("description")
    location = params.get("location")
    attendees_raw = params.get("attendees", [])
    reminders_raw = params.get("reminders", [])
    recurrence_raw = params.get("recurrence")

    start = datetime.fromisoformat(start_str)
    end = datetime.fromisoformat(end_str)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)

    attendees = [EventAttendee(**a) for a in attendees_raw] if attendees_raw else []
    reminders = [EventReminder(**r) for r in reminders_raw] if reminders_raw else []
    recurrence = RecurrenceRule(**recurrence_raw) if recurrence_raw else None

    async def _op(provider: CalendarProvider) -> dict[str, Any]:
        event = await provider.create_event(
            title=title,
            start=start,
            end=end,
            timezone=timezone_str,
            calendar_id=calendar_id,
            description=description,
            location=location,
            attendees=attendees if attendees else None,
            reminders=reminders if reminders else None,
            recurrence=recurrence,
        )
        return {"event": event.model_dump()}

    return await _execute_with_provider(provider_name, "create_event", _op)


async def _handle_update_event(params: dict[str, Any]) -> dict[str, Any]:
    """Handle the update_event tool invocation.

    Args:
        params: Tool invocation parameters.

    Returns:
        MCP-compliant response with updated event.
    """
    from datetime import datetime, timezone

    provider_name = params.get("provider")
    event_id = params["event_id"]
    calendar_id = params.get("calendar_id")
    send_notifications = params.get("send_notifications", True)
    update_series = params.get("update_series", False)

    start = None
    if params.get("start"):
        start = datetime.fromisoformat(params["start"])
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)

    end = None
    if params.get("end"):
        end = datetime.fromisoformat(params["end"])
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)

    attendees = None
    if params.get("attendees"):
        attendees = [EventAttendee(**a) for a in params["attendees"]]

    reminders = None
    if params.get("reminders"):
        reminders = [EventReminder(**r) for r in params["reminders"]]

    recurrence = None
    if params.get("recurrence"):
        recurrence = RecurrenceRule(**params["recurrence"])

    async def _op(provider: CalendarProvider) -> dict[str, Any]:
        event = await provider.update_event(
            event_id=event_id,
            calendar_id=calendar_id,
            title=params.get("title"),
            description=params.get("description"),
            location=params.get("location"),
            start=start,
            end=end,
            timezone=params.get("timezone"),
            attendees=attendees,
            reminders=reminders,
            recurrence=recurrence,
            status=params.get("status"),
            send_notifications=send_notifications,
            update_series=update_series,
        )
        return {"event": event.model_dump()}

    return await _execute_with_provider(provider_name, "update_event", _op)


async def _handle_delete_event(params: dict[str, Any]) -> dict[str, Any]:
    """Handle the delete_event tool invocation.

    Args:
        params: Tool invocation parameters.

    Returns:
        MCP-compliant response with deletion status.
    """
    provider_name = params.get("provider")
    event_id = params["event_id"]
    calendar_id = params.get("calendar_id")
    send_notifications = params.get("send_notifications", True)
    delete_series = params.get("delete_series", False)

    async def _op(provider: CalendarProvider) -> dict[str, Any]:
        success = await provider.delete_event(
            event_id=event_id,
            calendar_id=calendar_id,
            send_notifications=send_notifications,
            delete_series=delete_series,
        )
        return {
            "success": success,
            "message": f"Event {event_id} deleted successfully" if success else f"Failed to delete event {event_id}",
        }

    return await _execute_with_provider(provider_name, "delete_event", _op)


async def _handle_get_free_busy(params: dict[str, Any]) -> dict[str, Any]:
    """Handle the get_free_busy tool invocation.

    Args:
        params: Tool invocation parameters.

    Returns:
        MCP-compliant response with free/busy slots.
    """
    from datetime import datetime, timezone

    provider_name = params.get("provider")
    calendar_ids = params.get("calendar_ids")
    start_time_str = params.get("start_time")
    end_time_str = params.get("end_time")

    start_time = datetime.fromisoformat(start_time_str)
    end_time = datetime.fromisoformat(end_time_str)
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)

    async def _op(provider: CalendarProvider) -> dict[str, Any]:
        slots = await provider.get_free_busy(
            start_time=start_time,
            end_time=end_time,
            calendar_ids=calendar_ids,
        )
        return {"slots": [s.model_dump() for s in slots]}

    return await _execute_with_provider(provider_name, "get_free_busy", _op)


TOOL_HANDLERS: dict[str, callable] = {
    "list_calendars": _handle_list_calendars,
    "get_events": _handle_get_events,
    "create_event": _handle_create_event,
    "update_event": _handle_update_event,
    "delete_event": _handle_delete_event,
    "get_free_busy": _handle_get_free_busy,
}


def register_tools(app: FastAPI) -> None:
    """Register MCP tool definitions with the application.

    Stores tool definitions and handlers in the app state for use
    by the message handler.

    Args:
        app: The FastAPI application instance.
    """
    app.state.mcp_tools = TOOL_DEFINITIONS
    app.state.mcp_tool_handlers = TOOL_HANDLERS
    logger.info(f"Registered {len(TOOL_DEFINITIONS)} MCP tools")
