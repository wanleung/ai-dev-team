"""MCP message handlers for Calendar MCP Service.

Handles MCP protocol messages including initialization, tool discovery,
and tool invocation with proper error handling and response formatting.
"""

import logging
from typing import Any, Callable, Awaitable

from src.services.error_handler import ErrorHandler

logger = logging.getLogger(__name__)


class MCPMessageHandler:
    """Handler for MCP protocol messages.
    
    Manages tool registration, message routing, and response formatting
    according to the MCP protocol specification.
    """
    
    def __init__(self) -> None:
        """Initialize message handler with empty tool registry."""
        self._tools: dict[str, Any] = {}
        self._initialized = False
    
    def register_tool(self, tool: Any) -> None:
        """Register an MCP tool.
        
        Args:
            tool: MCPTool instance to register.
        """
        self._tools[tool.name] = tool
    
    def get_tools(self) -> list[dict[str, Any]]:
        """Get list of registered tools in MCP format.
        
        Returns:
            List of tool definitions for MCP protocol.
        """
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.parameters,
            }
            for tool in self._tools.values()
        ]
    
    async def handle_message(self, message: dict[str, Any]) -> dict[str, Any]:
        """Handle an incoming MCP message.
        
        Args:
            message: JSON-RPC 2.0 message dictionary.
            
        Returns:
            JSON-RPC 2.0 response dictionary.
        """
        method = message.get("method")
        params = message.get("params", {})
        message_id = message.get("id")
        
        try:
            if method == "initialize":
                result = await self._handle_initialize(params)
            elif method == "tools/list":
                result = await self._handle_tools_list(params)
            elif method == "tools/call":
                result = await self._handle_tools_call(params)
            else:
                return self._format_error(
                    message_id,
                    -32601,
                    f"Method not found: {method}",
                )
            
            return self._format_response(message_id, result)
            
        except Exception as e:
            logger.error(f"Error handling message: {e}", exc_info=True)
            return self._format_error(
                message_id,
                -32603,
                f"Internal error: {str(e)}",
            )
    
    async def execute_tool(self, tool_name: str, request: Any) -> dict[str, Any]:
        """Execute a registered tool with the given request.
        
        Args:
            tool_name: Name of the tool to execute.
            request: Request object with tool parameters.
            
        Returns:
            Tool execution result dictionary.
            
        Raises:
            ValueError: If tool is not found.
        """
        if tool_name not in self._tools:
            raise ValueError(f"Tool not found: {tool_name}")
        
        tool = self._tools[tool_name]
        
        # Convert request to dict for handler
        if hasattr(request, "model_dump"):
            params = request.model_dump(exclude_none=True)
        elif hasattr(request, "dict"):
            params = request.dict(exclude_none=True)
        else:
            params = request
        
        # Execute tool handler
        result = await tool.handler(params)
        return result
    
    async def _handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle MCP initialization handshake.
        
        Args:
            params: Initialization parameters from client.
            
        Returns:
            Server capabilities and information.
        """
        self._initialized = True
        
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {
                    "listChanged": True,
                },
            },
            "serverInfo": {
                "name": "calendar-mcp-service",
                "version": "1.0.0",
            },
        }
    
    async def _handle_tools_list(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle tools/list request.
        
        Args:
            params: Request parameters (unused).
            
        Returns:
            List of available tools.
        """
        return {
            "tools": self.get_tools(),
        }
    
    async def _handle_tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle tools/call request.
        
        Args:
            params: Tool call parameters including name and arguments.
            
        Returns:
            Tool execution result.
            
        Raises:
            ValueError: If tool not found or required params missing.
        """
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        
        if not tool_name:
            raise ValueError("Tool name is required")
        
        if tool_name not in self._tools:
            raise ValueError(f"Unknown tool: {tool_name}")
        
        tool = self._tools[tool_name]
        
        try:
            result = await tool.handler(arguments)
            return {
                "content": [
                    {
                        "type": "text",
                        "text": str(result),
                    }
                ],
            }
        except Exception as e:
            logger.error(f"Tool execution failed: {e}", exc_info=True)
            raise
    
    def _format_response(self, message_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        """Format a successful JSON-RPC response.
        
        Args:
            message_id: Original message ID.
            result: Response result data.
            
        Returns:
            Formatted JSON-RPC 2.0 response.
        """
        return {
            "jsonrpc": "2.0",
            "id": message_id,
            "result": result,
        }
    
    def _format_error(
        self,
        message_id: Any,
        code: int,
        message: str,
        data: Any = None,
    ) -> dict[str, Any]:
        """Format a JSON-RPC error response.
        
        Args:
            message_id: Original message ID.
            code: Error code.
            message: Error message.
            data: Optional error details.
            
        Returns:
            Formatted JSON-RPC 2.0 error response.
        """
        error = {
            "code": code,
            "message": message,
        }
        if data is not None:
            error["data"] = data
        
        return {
            "jsonrpc": "2.0",
            "id": message_id,
            "error": error,
        }
