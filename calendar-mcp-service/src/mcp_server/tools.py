"""MCP tool definitions for Calendar MCP Service.

Registers calendar operation tools with the MCP message handler,
providing the interface for MCP clients to interact with calendars.
"""

import logging
from typing import Any, Callable

from src.models.calendar import Event, Calendar, FreeBusySlot
from src.models.mcp import (
    ListCalendarsRequest,
    GetEventsRequest,
    CreateEventRequest,
    UpdateEventRequest,
    DeleteEventRequest,
    GetFreeBusyRequest,
)

logger = logging.getLogger(__name__)


class MCPServerInfo:
    """MCP server information for protocol handshake."""
    
    name: str = "calendar-mcp-service"
    version: str = "1.0.0"


class MCPTool:
    """Definition of an MCP tool."""
    
    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: Callable,
    ) -> None:
        """Initialize MCP tool definition.
        
        Args:
            name: Tool name identifier.
            description: Human-readable tool description.
            parameters: JSON Schema for tool parameters.
            handler: Async callable that executes the tool.
        """
        self.name = name
        self.description = description
        self.parameters = parameters
        self.handler = handler


def register_calendar_tools(handler: Any) -> None:
    """Register all calendar tools with the MCP message handler.
    
    Args:
        handler: MCPMessageHandler instance to register tools with.
    """
    tools = [
        _create_list_calendars_tool(handler),
        _create_get_events_tool(handler),
        _create_create_event_tool(handler),
        _create_update_event_tool(handler),
        _create_delete_event_tool(handler),
        _create_get_free_busy_tool(handler),
    ]
    
    for tool in tools:
        handler.register_tool(tool)
        logger.info(f"Registered MCP tool: {tool.name}")


def _create_list_calendars_tool(handler: Any) -> MCPTool:
    """Create list_calendars tool definition."""
    
    async def execute(params: dict[str, Any]) -> dict[str, Any]:
        """Execute list_calendars tool.
        
        Args:
            params: Tool parameters including optional provider filter.
            
        Returns:
            Dictionary with list of calendars.
        """
        request = ListCalendarsRequest(**params)
        result = await handler.execute_tool("list_calendars", request)
        return result
    
    return MCPTool(
        name="list_calendars",
        description="List all accessible calendars for the authenticated user",
        parameters={
            "type": "object",
            "properties": {
                "provider": {
                    "type": "string",
                    "enum": ["google", "outlook"],
                    "description": "Optional provider filter (google or outlook)",
                },
            },
            "required": [],
        },
        handler=execute,
    )


def _create_get_events_tool(handler: Any) -> MCPTool:
    """Create get_events tool definition."""
    
    async def execute(params: dict[str, Any]) -> dict[str, Any]:
        """Execute get_events tool.
        
        Args:
            params: Tool parameters for event retrieval.
            
        Returns:
            Dictionary with list of events.
        """
        request = GetEventsRequest(**params)
        result = await handler.execute_tool("get_events", request)
        return result
    
    return MCPTool(
        name="get_events",
        description="Retrieve calendar events for a specified date range",
        parameters={
            "type": "object",
            "properties": {
                "calendar_id": {
                    "type": "string",
                    "description": "Optional calendar ID (uses primary if not specified)",
                },
                "start_time": {
                    "type": "string",
                    "format": "date-time",
                    "description": "Start of the date range (ISO 8601)",
                },
                "end_time": {
                    "type": "string",
                    "format": "date-time",
                    "description": "End of the date range (ISO 8601)",
                },
                "provider": {
                    "type": "string",
                    "enum": ["google", "outlook"],
                    "description": "Optional provider filter",
                },
                "max_results": {
                    "type": "integer",
                    "default": 100,
                    "description": "Maximum number of events to return",
                },
                "expand_recurring": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether to expand recurring events",
                },
            },
            "required": ["start_time", "end_time"],
        },
        handler=execute,
    )


def _create_create_event_tool(handler: Any) -> MCPTool:
    """Create create_event tool definition."""
    
    async def execute(params: dict[str, Any]) -> dict[str, Any]:
        """Execute create_event tool.
        
        Args:
            params: Tool parameters for event creation.
            
        Returns:
            Dictionary with created event.
        """
        request = CreateEventRequest(**params)
        result = await handler.execute_tool("create_event", request)
        return result
    
    return MCPTool(
        name="create_event",
        description="Create a new calendar event",
        parameters={
            "type": "object",
            "properties": {
                "calendar_id": {
                    "type": "string",
                    "description": "Optional calendar ID (uses primary if not specified)",
                },
                "title": {
                    "type": "string",
                    "description": "Event title",
                },
                "description": {
                    "type": "string",
                    "description": "Event description",
                },
                "location": {
                    "type": "string",
                    "description": "Event location",
                },
                "start": {
                    "type": "string",
                    "format": "date-time",
                    "description": "Event start time (ISO 8601)",
                },
                "end": {
                    "type": "string",
                    "format": "date-time",
                    "description": "Event end time (ISO 8601)",
                },
                "timezone": {
                    "type": "string",
                    "description": "IANA timezone for the event",
                },
                "attendees": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "email": {"type": "string"},
                            "name": {"type": "string"},
                        },
                    },
                    "description": "List of event attendees",
                },
                "reminders": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "method": {"type": "string", "enum": ["email", "popup"]},
                            "minutes_before": {"type": "integer"},
                        },
                    },
                    "description": "List of event reminders",
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
                    "description": "Recurrence rule for repeating events",
                },
                "provider": {
                    "type": "string",
                    "enum": ["google", "outlook"],
                    "description": "Optional provider specification",
                },
            },
            "required": ["title", "start", "end", "timezone"],
        },
        handler=execute,
    )


def _create_update_event_tool(handler: Any) -> MCPTool:
    """Create update_event tool definition."""
    
    async def execute(params: dict[str, Any]) -> dict[str, Any]:
        """Execute update_event tool.
        
        Args:
            params: Tool parameters for event update.
            
        Returns:
            Dictionary with updated event.
        """
        request = UpdateEventRequest(**params)
        result = await handler.execute_tool("update_event", request)
        return result
    
    return MCPTool(
        name="update_event",
        description="Update an existing calendar event",
        parameters={
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "ID of the event to update",
                },
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar ID containing the event",
                },
                "title": {"type": "string", "description": "New event title"},
                "description": {"type": "string", "description": "New event description"},
                "location": {"type": "string", "description": "New event location"},
                "start": {"type": "string", "format": "date-time", "description": "New start time"},
                "end": {"type": "string", "format": "date-time", "description": "New end time"},
                "timezone": {"type": "string", "description": "New timezone"},
                "attendees": {
                    "type": "array",
                    "description": "Updated attendee list",
                },
                "reminders": {
                    "type": "array",
                    "description": "Updated reminder list",
                },
                "recurrence": {
                    "type": "object",
                    "description": "Updated recurrence rule",
                },
                "status": {
                    "type": "string",
                    "enum": ["confirmed", "tentative", "cancelled"],
                    "description": "Event status",
                },
                "send_notifications": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether to send notifications to attendees",
                },
                "update_series": {
                    "type": "boolean",
                    "default": False,
                    "description": "Whether to update entire recurring series",
                },
                "provider": {
                    "type": "string",
                    "enum": ["google", "outlook"],
                    "description": "Provider specification",
                },
            },
            "required": ["event_id"],
        },
        handler=execute,
    )


def _create_delete_event_tool(handler: Any) -> MCPTool:
    """Create delete_event tool definition."""
    
    async def execute(params: dict[str, Any]) -> dict[str, Any]:
        """Execute delete_event tool.
        
        Args:
            params: Tool parameters for event deletion.
            
        Returns:
            Dictionary with deletion result.
        """
        request = DeleteEventRequest(**params)
        result = await handler.execute_tool("delete_event", request)
        return result
    
    return MCPTool(
        name="delete_event",
        description="Delete a calendar event",
        parameters={
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "ID of the event to delete",
                },
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar ID containing the event",
                },
                "send_notifications": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether to send cancellation notifications",
                },
                "delete_series": {
                    "type": "boolean",
                    "default": False,
                    "description": "Whether to delete entire recurring series",
                },
                "provider": {
                    "type": "string",
                    "enum": ["google", "outlook"],
                    "description": "Provider specification",
                },
            },
            "required": ["event_id"],
        },
        handler=execute,
    )


def _create_get_free_busy_tool(handler: Any) -> MCPTool:
    """Create get_free_busy tool definition."""
    
    async def execute(params: dict[str, Any]) -> dict[str, Any]:
        """Execute get_free_busy tool.
        
        Args:
            params: Tool parameters for availability check.
            
        Returns:
            Dictionary with free/busy time slots.
        """
        request = GetFreeBusyRequest(**params)
        result = await handler.execute_tool("get_free_busy", request)
        return result
    
    return MCPTool(
        name="get_free_busy",
        description="Check availability for a specified time range",
        parameters={
            "type": "object",
            "properties": {
                "calendar_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of calendar IDs to check (all if not specified)",
                },
                "start_time": {
                    "type": "string",
                    "format": "date-time",
                    "description": "Start of the time range (ISO 8601)",
                },
                "end_time": {
                    "type": "string",
                    "format": "date-time",
                    "description": "End of the time range (ISO 8601)",
                },
                "provider": {
                    "type": "string",
                    "enum": ["google", "outlook"],
                    "description": "Optional provider filter",
                },
            },
            "required": ["start_time", "end_time"],
        },
        handler=execute,
    )
