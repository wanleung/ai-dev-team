"""User scoping middleware for API request authentication.

Extracts and validates user identity from request headers,
attaching user context to the request state for downstream use.
"""

import logging
from typing import Optional

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class UserContext:
    """Holds the authenticated user context for a request.

    Attributes:
        user_id: The authenticated user's unique identifier
        is_authenticated: Whether the user has been authenticated
    """

    def __init__(self, user_id: str = "default", is_authenticated: bool = False) -> None:
        """Initialize user context.

        Args:
            user_id: The user's unique identifier
            is_authenticated: Whether the user is authenticated
        """
        self.user_id = user_id
        self.is_authenticated = is_authenticated


def get_user_from_header(request: Request) -> UserContext:
    """Extract user identity from request headers.

    Reads the X-User-ID header to identify the caller.
    In production, this would be replaced with JWT/OAuth2 validation.

    Args:
        request: The incoming FastAPI request

    Returns:
        UserContext with the extracted user identity
    """
    user_id = request.headers.get("X-User-ID", "default")
    return UserContext(user_id=user_id, is_authenticated=user_id != "default")


async def user_scoping_middleware(
    request: Request,
    call_next,
) -> JSONResponse:
    """FastAPI middleware that attaches user context to request state.

    Extracts user identity from headers and stores it in request.state
    for downstream endpoints to use for scoping queries.

    Args:
        request: The incoming request
        call_next: The next middleware/handler in the chain

    Returns:
        The response from the next handler
    """
    user_context = get_user_from_header(request)
    request.state.user = user_context

    response = await call_next(request)
    return response


def get_current_user(request: Request) -> UserContext:
    """Dependency that returns the current user context.

    Use this as a FastAPI Depends() parameter in endpoints
    that need user scoping.

    Args:
        request: The incoming request (injected by FastAPI)

    Returns:
        UserContext for the current request
    """
    return getattr(request.state, "user", UserContext())


def require_auth(request: Request) -> UserContext:
    """Dependency that requires an authenticated user.

    Raises a 401 error if the user is not authenticated.

    Args:
        request: The incoming request (injected by FastAPI)

    Returns:
        UserContext for the authenticated user

    Raises:
        HTTPException: 401 if the user is not authenticated
    """
    user = getattr(request.state, "user", None)
    if user is None or not user.is_authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return user
