"""Unit tests for the error handler service.

Tests cover:
- format_mcp_error() building JSON-RPC 2.0 error responses
- handle_provider_error() mapping provider exceptions to MCP errors
- _map_status_code() mapping HTTP status codes to MCP error codes
- MCPError and MCPErrorResponse model validation
- All provider error types (AuthenticationError, CalendarNotFoundError, etc.)
- Unknown exception handling
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.calendar_provider.google_provider import (
    ProviderAPIError,
    AuthenticationError,
    CalendarNotFoundError,
    EventNotFoundError,
    ConflictError,
    ValidationError,
)
from src.services.error_handler import (
    MCPError,
    MCPErrorResponse,
    format_mcp_error,
    handle_provider_error,
    _map_status_code,
    MCP_ERROR_PARSE_ERROR,
    MCP_ERROR_INVALID_REQUEST,
    MCP_ERROR_METHOD_NOT_FOUND,
    MCP_ERROR_INVALID_PARAMS,
    MCP_ERROR_INTERNAL_ERROR,
)


# ---------------------------------------------------------------------------
# MCPError model tests
# ---------------------------------------------------------------------------


class TestMCPErrorModel:
    """Tests for the MCPError Pydantic model."""

    def test_create_with_required_fields(self) -> None:
        error = MCPError(code=-32603, message="Internal error")
        assert error.code == -32603
        assert error.message == "Internal error"
        assert error.data is None

    def test_create_with_data(self) -> None:
        error = MCPError(code=-32601, message="Method not found", data={"method": "foo"})
        assert error.data == {"method": "foo"}

    def test_model_dump(self) -> None:
        error = MCPError(code=-32700, message="Parse error", data={"detail": "bad json"})
        data = error.model_dump()
        assert data["code"] == -32700
        assert data["message"] == "Parse error"
        assert data["data"] == {"detail": "bad json"}


# ---------------------------------------------------------------------------
# MCPErrorResponse model tests
# ---------------------------------------------------------------------------


class TestMCPErrorResponseModel:
    """Tests for the MCPErrorResponse Pydantic model."""

    def test_default_jsonrpc_version(self) -> None:
        response = MCPErrorResponse(error=MCPError(code=-32603, message="error"))
        assert response.jsonrpc == "2.0"

    def test_with_id(self) -> None:
        response = MCPErrorResponse(
            error=MCPError(code=-32601, message="not found"),
            id=42,
        )
        assert response.id == 42

    def test_without_id(self) -> None:
        response = MCPErrorResponse(error=MCPError(code=-32603, message="error"))
        assert response.id is None

    def test_model_dump_excludes_none(self) -> None:
        response = MCPErrorResponse(error=MCPError(code=-32603, message="error"))
        data = response.model_dump(exclude_none=True)
        assert "id" not in data
        assert "jsonrpc" in data
        assert "error" in data


# ---------------------------------------------------------------------------
# format_mcp_error tests
# ---------------------------------------------------------------------------


class TestFormatMcpError:
    """Tests for the format_mcp_error function."""

    def test_basic_format(self) -> None:
        result = format_mcp_error(code=-32603, message="Internal error")
        assert result["jsonrpc"] == "2.0"
        assert result["error"]["code"] == -32603
        assert result["error"]["message"] == "Internal error"
        assert "id" not in result

    def test_with_request_id(self) -> None:
        result = format_mcp_error(code=-32601, message="Not found", request_id=1)
        assert result["id"] == 1

    def test_with_string_request_id(self) -> None:
        result = format_mcp_error(code=-32601, message="Not found", request_id="abc")
        assert result["id"] == "abc"

    def test_with_data(self) -> None:
        result = format_mcp_error(
            code=-32603,
            message="Error",
            data={"detail": "something broke"},
        )
        assert result["error"]["data"] == {"detail": "something broke"}

    def test_without_data(self) -> None:
        result = format_mcp_error(code=-32603, message="Error")
        assert result["error"].get("data") is None


# ---------------------------------------------------------------------------
# _map_status_code tests
# ---------------------------------------------------------------------------


class TestMapStatusCode:
    """Tests for the _map_status_code function."""

    def test_400_maps_to_invalid_params(self) -> None:
        assert _map_status_code(400) == MCP_ERROR_INVALID_PARAMS

    def test_401_maps_to_internal_error(self) -> None:
        assert _map_status_code(401) == MCP_ERROR_INTERNAL_ERROR

    def test_403_maps_to_internal_error(self) -> None:
        assert _map_status_code(403) == MCP_ERROR_INTERNAL_ERROR

    def test_404_maps_to_invalid_params(self) -> None:
        assert _map_status_code(404) == MCP_ERROR_INVALID_PARAMS

    def test_409_maps_to_internal_error(self) -> None:
        assert _map_status_code(409) == MCP_ERROR_INTERNAL_ERROR

    def test_429_maps_to_internal_error(self) -> None:
        assert _map_status_code(429) == MCP_ERROR_INTERNAL_ERROR

    def test_500_maps_to_internal_error(self) -> None:
        assert _map_status_code(500) == MCP_ERROR_INTERNAL_ERROR

    def test_502_maps_to_internal_error(self) -> None:
        assert _map_status_code(502) == MCP_ERROR_INTERNAL_ERROR

    def test_503_maps_to_internal_error(self) -> None:
        assert _map_status_code(503) == MCP_ERROR_INTERNAL_ERROR

    def test_none_maps_to_internal_error(self) -> None:
        assert _map_status_code(None) == MCP_ERROR_INTERNAL_ERROR

    def test_unmapped_status_code_defaults_to_internal_error(self) -> None:
        assert _map_status_code(418) == MCP_ERROR_INTERNAL_ERROR


# ---------------------------------------------------------------------------
# handle_provider_error tests
# ---------------------------------------------------------------------------


class TestHandleProviderError:
    """Tests for the handle_provider_error function."""

    def test_authentication_error(self) -> None:
        error = AuthenticationError("Auth failed")
        result = handle_provider_error(error)

        assert result["jsonrpc"] == "2.0"
        assert result["error"]["code"] == MCP_ERROR_INTERNAL_ERROR
        assert "Authentication failed" in result["error"]["message"]
        assert result["error"]["data"]["error_type"] == "AuthenticationError"
        assert result["error"]["data"]["status_code"] is None

    def test_calendar_not_found_error(self) -> None:
        error = CalendarNotFoundError("Cal not found", status_code=404)
        result = handle_provider_error(error)

        assert result["error"]["code"] == MCP_ERROR_INVALID_PARAMS
        assert "Calendar not found" in result["error"]["message"]
        assert result["error"]["data"]["status_code"] == 404

    def test_event_not_found_error(self) -> None:
        error = EventNotFoundError("Event not found", status_code=404)
        result = handle_provider_error(error)

        assert result["error"]["code"] == MCP_ERROR_INVALID_PARAMS
        assert "Event not found" in result["error"]["message"]

    def test_conflict_error(self) -> None:
        error = ConflictError("Conflict detected", status_code=409)
        result = handle_provider_error(error)

        assert result["error"]["code"] == MCP_ERROR_INTERNAL_ERROR
        assert "Conflict" in result["error"]["message"]
        assert result["error"]["data"]["status_code"] == 409

    def test_validation_error(self) -> None:
        error = ValidationError("Invalid data", status_code=400)
        result = handle_provider_error(error)

        assert result["error"]["code"] == MCP_ERROR_INVALID_PARAMS
        assert "Validation error" in result["error"]["message"]

    def test_generic_provider_api_error(self) -> None:
        error = ProviderAPIError("API error", status_code=500)
        result = handle_provider_error(error)

        assert result["error"]["code"] == MCP_ERROR_INTERNAL_ERROR
        assert "Provider API error" in result["error"]["message"]
        assert result["error"]["data"]["status_code"] == 500

    def test_provider_api_error_without_status_code(self) -> None:
        error = ProviderAPIError("API error with no status")
        result = handle_provider_error(error)

        assert result["error"]["code"] == MCP_ERROR_INTERNAL_ERROR
        assert result["error"]["data"]["status_code"] is None

    def test_unknown_exception(self) -> None:
        error = RuntimeError("Something unexpected happened")
        result = handle_provider_error(error)

        assert result["error"]["code"] == MCP_ERROR_INTERNAL_ERROR
        assert result["error"]["message"] == "An unexpected error occurred"
        assert result["error"]["data"]["error_type"] == "RuntimeError"
        assert "Something unexpected happened" in result["error"]["data"]["detail"]

    def test_with_request_id(self) -> None:
        error = ProviderAPIError("Error", status_code=500)
        result = handle_provider_error(error, request_id=42)

        assert result["id"] == 42

    def test_with_string_request_id(self) -> None:
        error = ProviderAPIError("Error", status_code=500)
        result = handle_provider_error(error, request_id="req-123")

        assert result["id"] == "req-123"

    def test_error_data_contains_detail(self) -> None:
        error = ProviderAPIError("Specific error message", status_code=502)
        result = handle_provider_error(error)

        assert result["error"]["data"]["detail"] == "Specific error message"

    def test_nested_exception_preserves_message(self) -> None:
        error = CalendarNotFoundError("Calendar 'cal-xyz' not found", status_code=404)
        result = handle_provider_error(error)

        assert result["error"]["data"]["detail"] == "Calendar 'cal-xyz' not found"
