"""Deployment smoke tests for Calendar MCP Service.

Tests hit real HTTP endpoints on the running container using httpx.
Each test is stateless and works independently.
"""

import os
import pytest
import httpx

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")


def _mcp_request(method: str, params: dict | None = None, request_id: int = 1) -> dict:
    """Build a JSON-RPC 2.0 MCP request."""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params or {},
    }


class TestHealthCheck:
    """Test the health check endpoint."""

    def test_health_returns_200(self):
        response = httpx.get(f"{BASE_URL}/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "healthy"
        assert "version" in body

    def test_health_content_type(self):
        response = httpx.get(f"{BASE_URL}/health")
        assert "application/json" in response.headers.get("content-type", "")


class TestMCPInitialization:
    """Test MCP protocol initialization via /initialize endpoint."""

    def test_initialize_handshake(self):
        payload = _mcp_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0.0"},
        })
        response = httpx.post(f"{BASE_URL}/initialize", json=payload)
        assert response.status_code == 200
        body = response.json()
        assert body["jsonrpc"] == "2.0"
        assert body["result"]["protocolVersion"] == "2024-11-05"
        assert body["result"]["serverInfo"]["name"] == "calendar-mcp-service"

    def test_initialize_returns_capabilities(self):
        payload = _mcp_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0.0"},
        })
        response = httpx.post(f"{BASE_URL}/initialize", json=payload)
        body = response.json()
        assert "tools" in body["result"]["capabilities"]


class TestMCPToolsDiscovery:
    """Test MCP tools/list endpoint."""

    def test_tools_list_returns_tools(self):
        payload = _mcp_request("tools/list")
        response = httpx.post(f"{BASE_URL}/messages", json=payload)
        assert response.status_code == 200
        body = response.json()
        assert "tools" in body["result"]
        tool_names = [t["name"] for t in body["result"]["tools"]]
        expected_tools = [
            "list_calendars",
            "get_events",
            "create_event",
            "update_event",
            "delete_event",
            "get_free_busy",
        ]
        for tool in expected_tools:
            assert tool in tool_names

    def test_tools_have_descriptions(self):
        payload = _mcp_request("tools/list")
        response = httpx.post(f"{BASE_URL}/messages", json=payload)
        body = response.json()
        for tool in body["result"]["tools"]:
            assert "description" in tool
            assert "inputSchema" in tool


class TestMCPCallErrors:
    """Test MCP error handling for invalid calls."""

    def test_unknown_method_returns_error(self):
        payload = _mcp_request("nonexistent/method")
        response = httpx.post(f"{BASE_URL}/messages", json=payload)
        assert response.status_code == 200
        body = response.json()
        assert "error" in body
        assert body["error"]["code"] == -32601

    def test_unknown_tool_returns_error(self):
        payload = _mcp_request("tools/call", {
            "name": "nonexistent_tool",
            "arguments": {},
        })
        response = httpx.post(f"{BASE_URL}/messages", json=payload)
        assert response.status_code == 200
        body = response.json()
        assert "error" in body


class TestSSEEndpoint:
    """Test SSE endpoint availability."""

    def test_sse_endpoint_accepts_connection(self):
        with httpx.stream("GET", f"{BASE_URL}/sse", timeout=3.0) as response:
            assert response.status_code == 200
            content_type = response.headers.get("content-type", "")
            assert "text/event-stream" in content_type


class TestNotFound:
    """Test 404 handling for unknown routes."""

    def test_unknown_route_returns_404(self):
        response = httpx.get(f"{BASE_URL}/nonexistent-route")
        assert response.status_code == 404

    def test_unknown_post_route_returns_404(self):
        response = httpx.post(f"{BASE_URL}/api/unknown", json={})
        assert response.status_code == 404
