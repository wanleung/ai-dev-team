"""Error handler service.

Translates provider-specific errors into MCP-compliant error responses
with appropriate error codes and messages.
"""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


# Mapping of HTTP status codes to MCP error codes
HTTP_TO_MCP_ERROR = {
    401: -32603,  # Authentication failed
    403: -32603,  # Permission denied
    404: -32602,  # Resource not found
    409: -32603,  # Conflict/concurrent edit
    429: -32603,  # Rate limited
    500: -32603,  # Internal server error
    503: -32603,  # Service unavailable
}


class ProviderError(Exception):
    """Base exception for provider errors."""
    
    def __init__(
        self,
        message: str,
        provider: str,
        status_code: Optional[int] = None,
        original_error: Optional[Exception] = None,
    ) -> None:
        """Initialize provider error.
        
        Args:
            message: Error message.
            provider: Provider name.
            status_code: HTTP status code from provider.
            original_error: Original exception.
        """
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.status_code = status_code
        self.original_error = original_error


class ErrorHandler:
    """Translates provider errors to MCP-compliant error responses."""
    
    def handle_provider_error(
        self,
        error: Exception,
        provider: str,
    ) -> ProviderError:
        """Convert a provider exception to a ProviderError.
        
        Args:
            error: Original exception from provider.
            provider: Provider name.
            
        Returns:
            ProviderError with extracted information.
        """
        status_code = self._extract_status_code(error)
        message = self._extract_error_message(error)
        
        logger.error(f"Provider error from {provider}: {message} (status: {status_code})")
        
        return ProviderError(
            message=message,
            provider=provider,
            status_code=status_code,
            original_error=error,
        )
    
    def format_mcp_error(
        self,
        error: ProviderError,
    ) -> dict[str, Any]:
        """Format a ProviderError as an MCP error response.
        
        Args:
            error: ProviderError to format.
            
        Returns:
            MCP-compliant error dictionary.
        """
        code = HTTP_TO_MCP_ERROR.get(error.status_code, -32603)
        
        return {
            "code": code,
            "message": error.message,
            "data": {
                "provider": error.provider,
                "status_code": error.status_code,
            },
        }
    
    def format_mcp_response(
        self,
        result: Any,
        message_id: Optional[int] = None,
    ) -> dict[str, Any]:
        """Format a successful result as an MCP response.
        
        Args:
            result: Result data.
            message_id: Original message ID.
            
        Returns:
            MCP-compliant response dictionary.
        """
        response = {
            "jsonrpc": "2.0",
            "result": result,
        }
        
        if message_id is not None:
            response["id"] = message_id
        
        return response
    
    def _extract_status_code(self, error: Exception) -> Optional[int]:
        """Extract HTTP status code from an exception.
        
        Args:
            error: Exception to inspect.
            
        Returns:
            HTTP status code or None.
        """
        # Check for httpx HTTPStatusError
        if hasattr(error, "response") and hasattr(error.response, "status_code"):
            return error.response.status_code
        
        # Check for googleapiclient errors
        if hasattr(error, "resp") and hasattr(error.resp, "status"):
            return int(error.resp.status)
        
        # Check for generic status attribute
        if hasattr(error, "status_code"):
            return error.status_code
        
        return None
    
    def _extract_error_message(self, error: Exception) -> str:
        """Extract error message from an exception.
        
        Args:
            error: Exception to inspect.
            
        Returns:
            Error message string.
        """
        # Check for httpx HTTPStatusError
        if hasattr(error, "response"):
            try:
                response_body = error.response.text
                if response_body:
                    return response_body[:500]
            except Exception:
                pass
        
        # Check for googleapiclient errors
        if hasattr(error, "content"):
            try:
                return str(error.content)[:500]
            except Exception:
                pass
        
        return str(error)
