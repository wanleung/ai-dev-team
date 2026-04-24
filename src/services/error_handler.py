"""Error handler for translating provider errors to MCP-compliant responses.

Maps provider-specific exceptions (HTTP status codes, custom error types)
to JSON-RPC 2.0 / MCP error responses with appropriate error codes,
messages, and contextual data.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

from src.calendar_provider.google_provider import (
    ProviderAPIError,
    AuthenticationError,
    CalendarNotFoundError,
    EventNotFoundError,
    ConflictError,
    ValidationError,
)

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# MCP error code constants (JSON-RPC 2.0)
# ------------------------------------------------------------------ #

MCP_ERROR_PARSE_ERROR = -32700
MCP_ERROR_INVALID_REQUEST = -32600
MCP_ERROR_METHOD_NOT_FOUND = -32601
MCP_ERROR_INVALID_PARAMS = -32602
MCP_ERROR_INTERNAL_ERROR = -32603

# ------------------------------------------------------------------ #
# Mapping from HTTP status codes to MCP error codes
# ------------------------------------------------------------------ #

_STATUS_TO_MCP_CODE: dict[int, int] = {
    400: MCP_ERROR_INVALID_PARAMS,
    401: MCP_ERROR_INTERNAL_ERROR,
    403: MCP_ERROR_INTERNAL_ERROR,
    404: MCP_ERROR_INVALID_PARAMS,
    409: MCP_ERROR_INTERNAL_ERROR,
    429: MCP_ERROR_INTERNAL_ERROR,
    500: MCP_ERROR_INTERNAL_ERROR,
    502: MCP_ERROR_INTERNAL_ERROR,
    503: MCP_ERROR_INTERNAL_ERROR,
}

# ------------------------------------------------------------------ #
# Mapping from exception type to human-readable MCP message
# ------------------------------------------------------------------ #

_EXCEPTION_MESSAGES: dict[type[Exception], str] = {
    AuthenticationError: "Authentication failed — credentials are invalid or expired",
    CalendarNotFoundError: "Calendar not found",
    EventNotFoundError: "Event not found",
    ConflictError: "Conflict — the resource was modified by another request",
    ValidationError: "Validation error — the request data is invalid",
    ProviderAPIError: "Provider API error",
}


class MCPError(BaseModel):
    """JSON-RPC 2.0 compliant error object for MCP responses."""

    code: int
    message: str
    data: dict[str, Any] | None = None


class MCPErrorResponse(BaseModel):
    """Full JSON-RPC 2.0 error response envelope."""

    jsonrpc: str = "2.0"
    error: MCPError
    id: int | str | None = None


def format_mcp_error(
    code: int,
    message: str,
    data: dict[str, Any] | None = None,
    request_id: int | str | None = None,
) -> dict[str, Any]:
    """Build a JSON-RPC 2.0 error response dict.

    Args:
        code: JSON-RPC error code (e.g. -32603 for internal error).
        message: Human-readable error description.
        data: Optional contextual data for debugging.
        request_id: The original request ID to echo back.

    Returns:
        A dict serialisable to a JSON-RPC 2.0 error response.
    """
    return MCPErrorResponse(
        error=MCPError(code=code, message=message, data=data),
        id=request_id,
    ).model_dump(exclude_none=True)


def _map_status_code(status_code: int | None) -> int:
    """Map an HTTP status code to the corresponding MCP error code.

    Args:
        status_code: HTTP status code from the provider response.

    Returns:
        The matching MCP/JSON-RPC error code. Defaults to
        ``MCP_ERROR_INTERNAL_ERROR`` when unmapped.
    """
    if status_code is None:
        return MCP_ERROR_INTERNAL_ERROR
    return _STATUS_TO_MCP_CODE.get(status_code, MCP_ERROR_INTERNAL_ERROR)


def handle_provider_error(
    error: Exception,
    request_id: int | str | None = None,
) -> dict[str, Any]:
    """Translate a provider exception into an MCP-compliant error response.

    Inspects the exception type and any attached HTTP status code, then
    produces a JSON-RPC 2.0 error response with the appropriate MCP
    error code, message, and contextual payload.

    Args:
        error: The exception raised by a calendar provider.
        request_id: The original MCP request ID to include in the
            response envelope.

    Returns:
        A dict representing a JSON-RPC 2.0 error response.
    """
    status_code: int | None = None
    detail: str = str(error)
    error_type: str = type(error).__name__
    data_payload: dict[str, Any] = {
        "error_type": error_type,
        "detail": detail,
    }

    if isinstance(error, ProviderAPIError):
        status_code = error.status_code
        data_payload["status_code"] = status_code
        message = _EXCEPTION_MESSAGES.get(type(error), detail)
    else:
        message = "An unexpected error occurred"
        logger.exception("Unhandled exception in calendar provider")

    mcp_code = _map_status_code(status_code)

    return format_mcp_error(
        code=mcp_code,
        message=message,
        data=data_payload,
        request_id=request_id,
    )
