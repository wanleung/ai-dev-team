"""MCP message handlers for the Calendar MCP Service.

Handles MCP protocol messages including initialization, tool listing,
and tool invocation via the /messages endpoint.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.mcp_server.tools import TOOL_HANDLERS, TOOL_DEFINITIONS

logger = logging.getLogger(__name__)

MCP_PROTOCOL_VERSION = "2024-11-05"


async def handle_initialize(request_id: int | str | None, params: dict[str, Any]) -> dict[str, Any]:
    """Handle MCP initialization handshake.

    Args:
        request_id: The original request ID to echo back.
        params: Initialization parameters from the client.

    Returns:
        MCP initialization response with server capabilities.
    """
    return {
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "capabilities": {
            "tools": {
                "list": True,
            },
        },
        "serverInfo": {
            "name": "calendar-mcp-service",
            "version": "1.0.0",
        },
    }


async def handle_tools_list(request_id: int | str | None) -> dict[str, Any]:
    """Handle tool listing request.

    Args:
        request_id: The original request ID to echo back.

    Returns:
        Response with list of available MCP tools.
    """
    return {"tools": TOOL_DEFINITIONS}


async def handle_tool_call(
    request_id: int | str | None,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Handle a tool invocation request.

    Dispatches to the appropriate tool handler based on the tool name.

    Args:
        request_id: The original request ID to echo back.
        tool_name: Name of the tool to invoke.
        arguments: Tool invocation arguments.

    Returns:
        Tool invocation result or error response.
    """
    handler = TOOL_HANDLERS.get(tool_name)
    if handler is None:
        return {
            "content": [{"type": "text", "text": json.dumps({
                "error": {
                    "code": -32601,
                    "message": f"Unknown tool: {tool_name}",
                    "data": {"available_tools": [t["name"] for t in TOOL_DEFINITIONS]},
                }
            })}],
            "isError": True,
        }

    try:
        result = await handler(arguments)
        return {"content": [{"type": "text", "text": json.dumps(result, default=str)}], "isError": False}
    except Exception as e:
        logger.exception(f"Error invoking tool '{tool_name}'")
        return {
            "content": [{"type": "text", "text": json.dumps({
                "error": {
                    "code": -32603,
                    "message": f"Internal error invoking tool '{tool_name}': {e}",
                    "data": {"tool": tool_name},
                }
            })}],
            "isError": True,
        }


async def handle_message(request: Request) -> JSONResponse:
    """Handle incoming MCP messages on the /messages endpoint.

    Routes messages based on the method field to the appropriate handler.

    Args:
        request: The incoming FastAPI request.

    Returns:
        JSONResponse with the MCP-compliant response.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={
                "jsonrpc": "2.0",
                "error": {
                    "code": -32700,
                    "message": "Parse error: invalid JSON",
                },
            },
        )

    method = body.get("method")
    request_id = body.get("id")
    params = body.get("params", {})

    if method == "initialize":
        result = await handle_initialize(request_id, params)
    elif method == "tools/list":
        result = await handle_tools_list(request_id)
    elif method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        result = await handle_tool_call(request_id, tool_name, arguments)
    else:
        result = {
            "error": {
                "code": -32601,
                "message": f"Method not found: {method}",
            }
        }

    response = {"jsonrpc": "2.0", "result": result}
    if request_id is not None:
        response["id"] = request_id

    return JSONResponse(content=response)


def register_handlers(app: FastAPI) -> None:
    """Register MCP message handlers with the application.

    Adds the /messages POST endpoint and /initialize POST endpoint.

    Args:
        app: The FastAPI application instance.
    """
    app.add_api_route("/messages", handle_message, methods=["POST"])
    app.add_api_route("/initialize", handle_initialize_endpoint, methods=["POST"])
    logger.info("Registered MCP message handlers")


async def handle_initialize_endpoint(request: Request) -> JSONResponse:
    """Handle the /initialize endpoint directly.

    Args:
        request: The incoming FastAPI request.

    Returns:
        JSONResponse with the initialization result.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={
                "jsonrpc": "2.0",
                "error": {
                    "code": -32700,
                    "message": "Parse error: invalid JSON",
                },
            },
        )

    request_id = body.get("id")
    params = body.get("params", {})
    result = await handle_initialize(request_id, params)

    response = {"jsonrpc": "2.0", "result": result}
    if request_id is not None:
        response["id"] = request_id

    return JSONResponse(content=response)
