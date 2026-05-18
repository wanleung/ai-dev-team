"""REST API Gateway for MCP Email Service.

FastAPI routers, Pydantic request/response schemas, and error handlers
for the REST API endpoints.
"""

from api.router import api_router

__all__ = ["api_router"]
