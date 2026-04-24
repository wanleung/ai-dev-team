"""Unit tests for MCP message handlers.

Tests cover:
- handle_initialize() returning protocol version, capabilities, serverInfo
- handle_tools_list() returning tool definitions
- handle_tool_call() dispatching to handlers, unknown tool errors
- handle_message() routing by method, JSON parse errors, unknown methods
- handle_initialize_endpoint() direct endpoint handling
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request
from fastapi.responses import JSONResponse

from src.mcp_server.handlers import (
    handle_initialize,
    handle_tools_list,
    handle_tool_call,
    handle_message,
    handle_initialize_endpoint,
    MCP_PROTOCOL_VERSION,
)
from src.mcp_server.tools import TOOL_DEFINITIONS, TOOL_HANDLERS


# ---------------------------------------------------------------------------
# handle_initialize tests
# ---------------------------------------------------------------------------


class TestHandleInitialize:
    """Tests for the handle_initialize function."""

    @pytest.mark.asyncio
    async def test_returns_protocol_version(self) -> None:
        result = await handle_initialize(1, {})
        assert result["protocolVersion"] == MCP_PROTOCOL_VERSION

    @pytest.mark.asyncio
    async def test_returns_capabilities(self) -> None:
        result = await handle_initialize(1, {})
        assert "tools" in result["capabilities"]
        assert result["capabilities"]["tools"]["list"] is True

    @pytest.mark.asyncio
    async def test_returns_server_info(self) -> None:
        result = await handle_initialize(1, {})
        assert result["serverInfo"]["name"] == "calendar-mcp-service"
        assert result["serverInfo"]["version"] == "1.0.0"

    @pytest.mark.asyncio
    async def test_ignores_params(self) -> None:
        result = await handle_initialize(1, {"clientInfo": {"name": "test"}})
        assert result["protocolVersion"] == MCP_PROTOCOL_VERSION

    @pytest.mark.asyncio
    async def test_ignores_request_id(self) -> None:
        result = await handle_initialize(None, {})
        assert "protocolVersion" in result


# ---------------------------------------------------------------------------
# handle_tools_list tests
# ---------------------------------------------------------------------------


class TestHandleToolsList:
    """Tests for the handle_tools_list function."""

    @pytest.mark.asyncio
    async def test_returns_tools(self) -> None:
        result = await handle_tools_list(1)
        assert "tools" in result
        assert len(result["tools"]) == 6

    @pytest.mark.asyncio
    async def test_returns_all_tool_names(self) -> None:
        result = await handle_tools_list(1)
        names = [t["name"] for t in result["tools"]]
        assert "list_calendars" in names
        assert "get_events" in names
        assert "create_event" in names
        assert "update_event" in names
        assert "delete_event" in names
        assert "get_free_busy" in names

    @pytest.mark.asyncio
    async def test_each_tool_has_required_fields(self) -> None:
        result = await handle_tools_list(1)
        for tool in result["tools"]:
            assert "name" in tool
            assert "description" in tool
            assert "inputSchema" in tool


# ---------------------------------------------------------------------------
# handle_tool_call tests
# ---------------------------------------------------------------------------


class TestHandleToolCall:
    """Tests for the handle_tool_call function."""

    @pytest.mark.asyncio
    async def test_dispatches_to_handler(self) -> None:
        mock_handler = AsyncMock(return_value={"calendars": []})

        with patch.dict(TOOL_HANDLERS, {"list_calendars": mock_handler}):
            result = await handle_tool_call(1, "list_calendars", {})

        mock_handler.assert_called_once_with({})
        assert result["isError"] is False

    @pytest.mark.asyncio
    async def test_returns_handler_result(self) -> None:
        mock_handler = AsyncMock(return_value={"events": [{"id": "evt-1"}]})

        with patch.dict(TOOL_HANDLERS, {"get_events": mock_handler}):
            result = await handle_tool_call(1, "get_events", {"start_time": "2026-01-01T00:00:00Z", "end_time": "2026-01-02T00:00:00Z"})

        content = json.loads(result["content"][0]["text"])
        assert "events" in content

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self) -> None:
        result = await handle_tool_call(1, "nonexistent_tool", {})

        assert result["isError"] is True
        content = json.loads(result["content"][0]["text"])
        assert content["error"]["code"] == -32601
        assert "nonexistent_tool" in content["error"]["message"]

    @pytest.mark.asyncio
    async def test_unknown_tool_lists_available_tools(self) -> None:
        result = await handle_tool_call(1, "unknown", {})

        content = json.loads(result["content"][0]["text"])
        assert "available_tools" in content["error"]["data"]

    @pytest.mark.asyncio
    async def test_handler_exception_returns_error(self) -> None:
        mock_handler = AsyncMock(side_effect=RuntimeError("handler broke"))

        with patch.dict(TOOL_HANDLERS, {"broken_tool": mock_handler}):
            result = await handle_tool_call(1, "broken_tool", {})

        assert result["isError"] is True
        content = json.loads(result["content"][0]["text"])
        assert content["error"]["code"] == -32603
        assert "broken_tool" in content["error"]["message"]

    @pytest.mark.asyncio
    async def test_handler_result_serialized_with_default_str(self) -> None:
        now = datetime.now(timezone.utc)
        mock_handler = AsyncMock(return_value={"timestamp": now})

        with patch.dict(TOOL_HANDLERS, {"time_tool": mock_handler}):
            result = await handle_tool_call(1, "time_tool", {})

        assert result["isError"] is False
        content = json.loads(result["content"][0]["text"])
        assert "timestamp" in content


# ---------------------------------------------------------------------------
# handle_message tests
# ---------------------------------------------------------------------------


class TestHandleMessage:
    """Tests for the handle_message function."""

    @pytest.mark.asyncio
    async def test_routes_to_initialize(self) -> None:
        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {},
        })

        response = await handle_message(mock_request)
        data = response.body if hasattr(response, 'body') else response
        if isinstance(response, JSONResponse):
            content = json.loads(response.body)
        else:
            content = json.loads(data)
        assert content["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION

    @pytest.mark.asyncio
    async def test_routes_to_tools_list(self) -> None:
        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
        })

        response = await handle_message(mock_request)
        content = json.loads(response.body)
        assert "tools" in content["result"]

    @pytest.mark.asyncio
    async def test_routes_to_tools_call(self) -> None:
        mock_handler = AsyncMock(return_value={"calendars": []})

        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "list_calendars", "arguments": {}},
        })

        with patch.dict(TOOL_HANDLERS, {"list_calendars": mock_handler}):
            response = await handle_message(mock_request)

        content = json.loads(response.body)
        assert content["result"]["isError"] is False

    @pytest.mark.asyncio
    async def test_unknown_method_returns_error(self) -> None:
        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "unknown/method",
        })

        response = await handle_message(mock_request)
        content = json.loads(response.body)
        assert "error" in content["result"]
        assert content["result"]["error"]["code"] == -32601

    @pytest.mark.asyncio
    async def test_invalid_json_returns_parse_error(self) -> None:
        mock_request = MagicMock()
        mock_request.json = AsyncMock(side_effect=Exception("bad json"))

        response = await handle_message(mock_request)
        assert response.status_code == 400
        content = json.loads(response.body)
        assert content["error"]["code"] == -32700

    @pytest.mark.asyncio
    async def test_response_includes_request_id(self) -> None:
        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={
            "jsonrpc": "2.0",
            "id": 42,
            "method": "initialize",
            "params": {},
        })

        response = await handle_message(mock_request)
        content = json.loads(response.body)
        assert content["id"] == 42

    @pytest.mark.asyncio
    async def test_response_omits_id_when_none(self) -> None:
        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {},
        })

        response = await handle_message(mock_request)
        content = json.loads(response.body)
        assert "id" not in content

    @pytest.mark.asyncio
    async def test_response_has_jsonrpc_version(self) -> None:
        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {},
        })

        response = await handle_message(mock_request)
        content = json.loads(response.body)
        assert content["jsonrpc"] == "2.0"


# ---------------------------------------------------------------------------
# handle_initialize_endpoint tests
# ---------------------------------------------------------------------------


class TestHandleInitializeEndpoint:
    """Tests for the handle_initialize_endpoint function."""

    @pytest.mark.asyncio
    async def test_returns_protocol_version(self) -> None:
        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={
            "id": 1,
            "params": {},
        })

        response = await handle_initialize_endpoint(mock_request)
        content = json.loads(response.body)
        assert content["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION

    @pytest.mark.asyncio
    async def test_returns_server_info(self) -> None:
        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={
            "id": 1,
            "params": {},
        })

        response = await handle_initialize_endpoint(mock_request)
        content = json.loads(response.body)
        assert content["result"]["serverInfo"]["name"] == "calendar-mcp-service"

    @pytest.mark.asyncio
    async def test_invalid_json_returns_parse_error(self) -> None:
        mock_request = MagicMock()
        mock_request.json = AsyncMock(side_effect=Exception("bad"))

        response = await handle_initialize_endpoint(mock_request)
        assert response.status_code == 400
        content = json.loads(response.body)
        assert content["error"]["code"] == -32700

    @pytest.mark.asyncio
    async def test_response_includes_id(self) -> None:
        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={
            "id": 99,
            "params": {},
        })

        response = await handle_initialize_endpoint(mock_request)
        content = json.loads(response.body)
        assert content["id"] == 99
