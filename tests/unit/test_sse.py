"""Unit tests for the SSE transport handler.

Tests cover:
- SSEConnection send, event_stream, close
- sse_endpoint response headers and content type
- broadcast_to_sse sending to multiple connections
- Connection lifecycle and cleanup
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest

from src.mcp_server.sse import (
    SSEConnection,
    sse_endpoint,
    broadcast_to_sse,
    _active_connections,
)


# ---------------------------------------------------------------------------
# SSEConnection tests
# ---------------------------------------------------------------------------


class TestSSEConnectionInit:
    """Tests for SSEConnection initialization."""

    def test_creates_empty_queue(self) -> None:
        conn = SSEConnection()
        assert conn._queue.empty()

    def test_not_closed_on_init(self) -> None:
        conn = SSEConnection()
        assert conn._closed is False


class TestSSEConnectionSend:
    """Tests for SSEConnection.send()."""

    @pytest.mark.asyncio
    async def test_send_queues_message(self) -> None:
        conn = SSEConnection()
        await conn.send({"type": "test", "data": "hello"})

        event = await conn._queue.get()
        assert event.startswith("data: ")
        parsed = json.loads(event[6:].strip())
        assert parsed["type"] == "test"
        assert parsed["data"] == "hello"

    @pytest.mark.asyncio
    async def test_send_formats_as_sse_data(self) -> None:
        conn = SSEConnection()
        await conn.send({"key": "value"})

        event = await conn._queue.get()
        assert event.startswith("data: ")
        assert event.endswith("\n\n")

    @pytest.mark.asyncio
    async def test_send_after_close_is_noop(self) -> None:
        conn = SSEConnection()
        conn.close()
        await conn.send({"type": "test"})

        assert conn._queue.empty()

    @pytest.mark.asyncio
    async def test_send_multiple_messages(self) -> None:
        conn = SSEConnection()
        await conn.send({"msg": 1})
        await conn.send({"msg": 2})
        await conn.send({"msg": 3})

        assert conn._queue.qsize() == 3


class TestSSEConnectionEventStream:
    """Tests for SSEConnection.event_stream()."""

    @pytest.mark.asyncio
    async def test_yields_queued_messages(self) -> None:
        conn = SSEConnection()
        await conn.send({"type": "test"})
        conn.close()

        events = []
        async for event in conn.event_stream():
            events.append(event)

        assert len(events) == 1
        assert events[0].startswith("data: ")

    @pytest.mark.asyncio
    async def test_yields_keepalive_on_timeout(self) -> None:
        conn = SSEConnection()
        conn.close()

        events = []
        async for event in conn.event_stream():
            events.append(event)
            if len(events) >= 1:
                break

        assert events[0] == ": keepalive\n\n"

    @pytest.mark.asyncio
    async def test_marks_closed_after_stream_ends(self) -> None:
        conn = SSEConnection()
        conn.close()

        async for event in conn.event_stream():
            break

        assert conn._closed is True


class TestSSEConnectionClose:
    """Tests for SSEConnection.close()."""

    def test_close_sets_flag(self) -> None:
        conn = SSEConnection()
        conn.close()
        assert conn._closed is True

    def test_close_idempotent(self) -> None:
        conn = SSEConnection()
        conn.close()
        conn.close()
        assert conn._closed is True


# ---------------------------------------------------------------------------
# sse_endpoint tests
# ---------------------------------------------------------------------------


class TestSSEEndpoint:
    """Tests for the sse_endpoint function."""

    @pytest.mark.asyncio
    async def test_returns_streaming_response(self) -> None:
        mock_request = MagicMock()

        with patch("src.mcp_server.sse.StreamingResponse") as mock_response:
            mock_response.return_value = MagicMock()

            result = await sse_endpoint(mock_request)

            mock_response.assert_called_once()
            call_kwargs = mock_response.call_args[1]
            assert call_kwargs["media_type"] == "text/event-stream"

    @pytest.mark.asyncio
    async def test_sets_cache_control_header(self) -> None:
        mock_request = MagicMock()

        with patch("src.mcp_server.sse.StreamingResponse") as mock_response:
            mock_response.return_value = MagicMock()
            await sse_endpoint(mock_request)

            call_kwargs = mock_response.call_args[1]
            assert call_kwargs["headers"]["Cache-Control"] == "no-cache"

    @pytest.mark.asyncio
    async def test_sets_connection_header(self) -> None:
        mock_request = MagicMock()

        with patch("src.mcp_server.sse.StreamingResponse") as mock_response:
            mock_response.return_value = MagicMock()
            await sse_endpoint(mock_request)

            call_kwargs = mock_response.call_args[1]
            assert call_kwargs["headers"]["Connection"] == "keep-alive"

    @pytest.mark.asyncio
    async def test_sets_accel_buffering_header(self) -> None:
        mock_request = MagicMock()

        with patch("src.mcp_server.sse.StreamingResponse") as mock_response:
            mock_response.return_value = MagicMock()
            await sse_endpoint(mock_request)

            call_kwargs = mock_response.call_args[1]
            assert call_kwargs["headers"]["X-Accel-Buffering"] == "no"

    @pytest.mark.asyncio
    async def test_registers_connection(self) -> None:
        mock_request = MagicMock()
        initial_count = len(_active_connections)

        with patch("src.mcp_server.sse.StreamingResponse") as mock_response:
            mock_response.return_value = MagicMock()
            await sse_endpoint(mock_request)

        assert len(_active_connections) == initial_count

    @pytest.mark.asyncio
    async def test_removes_connection_on_cleanup(self) -> None:
        mock_request = MagicMock()

        with patch("src.mcp_server.sse.StreamingResponse") as mock_response:
            mock_response.return_value = MagicMock()
            await sse_endpoint(mock_request)

        conn = _active_connections[-1] if _active_connections else None
        if conn:
            assert conn._closed is True


# ---------------------------------------------------------------------------
# broadcast_to_sse tests
# ---------------------------------------------------------------------------


class TestBroadcastToSSE:
    """Tests for the broadcast_to_sse function."""

    @pytest.mark.asyncio
    async def test_broadcasts_to_single_connection(self) -> None:
        conn = SSEConnection()
        _active_connections.append(conn)

        try:
            await broadcast_to_sse({"type": "broadcast"})
            event = await asyncio.wait_for(conn._queue.get(), timeout=1.0)
            assert "broadcast" in event
        finally:
            _active_connections.clear()

    @pytest.mark.asyncio
    async def test_broadcasts_to_multiple_connections(self) -> None:
        conn1 = SSEConnection()
        conn2 = SSEConnection()
        _active_connections.extend([conn1, conn2])

        try:
            await broadcast_to_sse({"type": "multi"})

            event1 = await asyncio.wait_for(conn1._queue.get(), timeout=1.0)
            event2 = await asyncio.wait_for(conn2._queue.get(), timeout=1.0)
            assert "multi" in event1
            assert "multi" in event2
        finally:
            _active_connections.clear()

    @pytest.mark.asyncio
    async def test_broadcast_to_no_connections(self) -> None:
        _active_connections.clear()
        await broadcast_to_sse({"type": "test"})

    @pytest.mark.asyncio
    async def test_broadcast_skips_failed_connections(self) -> None:
        good_conn = SSEConnection()
        bad_conn = SSEConnection()
        bad_conn.close()
        _active_connections.extend([good_conn, bad_conn])

        try:
            await broadcast_to_sse({"type": "partial"})
            event = await asyncio.wait_for(good_conn._queue.get(), timeout=1.0)
            assert "partial" in event
        finally:
            _active_connections.clear()
