"""SSE transport handler for MCP protocol.

Implements Server-Sent Events transport for server-to-client message streaming
as required by the MCP protocol specification.
"""

import asyncio
import json
import logging
from typing import Any, AsyncGenerator

from fastapi import Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)


class SSETransport:
    """Server-Sent Events transport for MCP protocol.
    
    Manages SSE connections and provides methods to send messages
    to connected clients.
    """
    
    def __init__(self) -> None:
        """Initialize SSE transport with empty client registry."""
        self._client_queues: dict[str, asyncio.Queue] = {}
        self._client_counter = 0
    
    async def register_client(self) -> tuple[str, asyncio.Queue]:
        """Register a new SSE client connection.
        
        Returns:
            Tuple of (client_id, message_queue) for the new client.
        """
        self._client_counter += 1
        client_id = f"client_{self._client_counter}"
        queue: asyncio.Queue = asyncio.Queue()
        self._client_queues[client_id] = queue
        logger.info(f"Client registered: {client_id}")
        return client_id, queue
    
    async def unregister_client(self, client_id: str) -> None:
        """Remove a client from the SSE transport.
        
        Args:
            client_id: The ID of the client to unregister.
        """
        if client_id in self._client_queues:
            del self._client_queues[client_id]
            logger.info(f"Client unregistered: {client_id}")
    
    async def send_to_client(self, client_id: str, message: dict[str, Any]) -> bool:
        """Send a message to a specific client.
        
        Args:
            client_id: The ID of the target client.
            message: The message dictionary to send.
            
        Returns:
            True if message was queued successfully, False otherwise.
        """
        if client_id in self._client_queues:
            await self._client_queues[client_id].put(message)
            return True
        logger.warning(f"Attempted to send to unregistered client: {client_id}")
        return False
    
    async def broadcast(self, message: dict[str, Any]) -> int:
        """Broadcast a message to all connected clients.
        
        Args:
            message: The message dictionary to broadcast.
            
        Returns:
            Number of clients the message was sent to.
        """
        sent_count = 0
        for client_id in list(self._client_queues.keys()):
            if await self.send_to_client(client_id, message):
                sent_count += 1
        return sent_count
    
    def create_sse_response(self, client_id: str, queue: asyncio.Queue) -> StreamingResponse:
        """Create a StreamingResponse for SSE transport.
        
        Args:
            client_id: The ID of the client connection.
            queue: The message queue for this client.
            
        Returns:
            StreamingResponse configured for SSE.
        """
        async def event_stream() -> AsyncGenerator[str, None]:
            try:
                # Send connected event
                yield f"event: connected\ndata: {json.dumps({'client_id': client_id})}\n\n"
                
                while True:
                    message = await queue.get()
                    data = json.dumps(message)
                    yield f"event: message\ndata: {data}\n\n"
            except asyncio.CancelledError:
                logger.info(f"SSE stream cancelled for client: {client_id}")
            finally:
                await self.unregister_client(client_id)
        
        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
