"""SSE transport handler for the Calendar MCP Service.

Provides a Server-Sent Events endpoint for streaming server-to-client
messages as part of the MCP protocol over HTTP.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncGenerator

from fastapi import Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)


class SSEConnection:
    """Manages a single SSE connection with a message queue."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._closed = False

    async def send(self, message: dict) -> None:
        """Send a message to the SSE client.

        Args:
            message: JSON-serialisable message dict.
        """
        if self._closed:
            return
        data = json.dumps(message)
        await self._queue.put(f"data: {data}\n\n")

    async def event_stream(self) -> AsyncGenerator[str, None]:
        """Yield SSE-formatted events from the queue.

        Yields:
            SSE-formatted string events.
        """
        try:
            while not self._closed:
                try:
                    event = await asyncio.wait_for(self._queue.get(), timeout=30.0)
                    yield event
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            self._closed = True

    def close(self) -> None:
        """Mark the connection as closed."""
        self._closed = True


_active_connections: list[SSEConnection] = []


async def sse_endpoint(request: Request) -> StreamingResponse:
    """SSE endpoint for server-to-client streaming.

    Establishes a long-lived SSE connection that clients can use to
    receive real-time notifications from the server.

    Args:
        request: The incoming FastAPI request.

    Returns:
        A StreamingResponse with text/event-stream content type.
    """
    connection = SSEConnection()
    _active_connections.append(connection)

    try:
        return StreamingResponse(
            connection.event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    finally:
        _active_connections.remove(connection)
        connection.close()


async def broadcast_to_sse(message: dict) -> None:
    """Broadcast a message to all active SSE connections.

    Args:
        message: JSON-serialisable message dict to send.
    """
    for conn in list(_active_connections):
        try:
            await conn.send(message)
        except Exception:
            logger.exception("Failed to send SSE message")
