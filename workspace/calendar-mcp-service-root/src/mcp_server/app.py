"""FastAPI application setup for MCP Calendar Service.

Creates and configures the FastAPI application with MCP protocol support,
SSE transport, and calendar tool registration.
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from src.config.settings import settings
from src.mcp_server.sse import SSETransport
from src.mcp_server.tools import register_calendar_tools
from src.mcp_server.handlers import MCPMessageHandler

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifecycle and shared resources."""
    from src.auth.oauth_manager import OAuthManager
    from src.services.event_normalizer import EventNormalizer
    from src.services.rate_limiter import RateLimiter
    from src.services.error_handler import ErrorHandler
    
    # Initialize shared services
    oauth_manager = OAuthManager()
    event_normalizer = EventNormalizer()
    rate_limiter = RateLimiter()
    error_handler = ErrorHandler()
    
    # Store in app state
    app.state.oauth_manager = oauth_manager
    app.state.event_normalizer = event_normalizer
    app.state.rate_limiter = rate_limiter
    app.state.error_handler = error_handler
    
    yield
    
    # Cleanup
    await rate_limiter.close()


def register_mcp_routes(app: FastAPI) -> None:
    """Register MCP protocol routes on the FastAPI application.
    
    Args:
        app: FastAPI application instance.
    """
    
    @app.get("/sse")
    async def sse_endpoint(request: Request) -> StreamingResponse:
        """SSE endpoint for server-to-client streaming.
        
        Establishes a Server-Sent Events connection for real-time
        server-to-client message delivery.
        
        Returns:
            StreamingResponse with SSE event stream.
        """
        sse_transport: SSETransport = app.state.sse_transport
        client_id, queue = await sse_transport.register_client()
        return sse_transport.create_sse_response(client_id, queue)
    
    @app.post("/messages")
    async def messages_endpoint(request: Request) -> dict:
        """Client-to-server MCP message endpoint.
        
        Receives JSON-RPC 2.0 messages from MCP clients and routes
        them to appropriate handlers.
        
        Returns:
            JSON-RPC 2.0 response.
        """
        message_handler: MCPMessageHandler = app.state.message_handler
        body = await request.json()
        return await message_handler.handle_message(body)
    
    @app.post("/initialize")
    async def initialize_endpoint(request: Request) -> dict:
        """MCP initialization handshake endpoint.
        
        Handles the initial handshake between MCP client and server,
        exchanging protocol versions and capabilities.
        
        Returns:
            Server capabilities and information.
        """
        message_handler: MCPMessageHandler = app.state.message_handler
        body = await request.json()
        return await message_handler.handle_message(body)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.
    
    Returns:
        Configured FastAPI application instance with MCP endpoints.
    """
    app = FastAPI(
        title="Calendar MCP Service",
        description="MCP-compliant calendar service supporting Google Calendar and Outlook Calendar",
        version="1.0.0",
        lifespan=lifespan,
    )
    
    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Initialize MCP components
    sse_transport = SSETransport()
    message_handler = MCPMessageHandler()
    
    # Register MCP tools
    register_calendar_tools(message_handler)
    
    # Store in app state
    app.state.sse_transport = sse_transport
    app.state.message_handler = message_handler
    
    # Register MCP endpoints
    register_mcp_routes(app)
    
    # Register health check
    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        return {"status": "healthy", "version": "1.0.0"}
    
    return app
