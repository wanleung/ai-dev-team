"""Tests for middleware/auth.py - user scoping middleware."""

import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

from middleware.auth import (
    UserContext,
    get_user_from_header,
    user_scoping_middleware,
    get_current_user,
    require_auth,
)


class TestUserContext:
    """Tests for UserContext class."""

    def test_default_user_context(self):
        """Given no arguments, then user_id is 'default' and not authenticated."""
        ctx = UserContext()
        assert ctx.user_id == "default"
        assert ctx.is_authenticated is False

    def test_authenticated_user_context(self):
        """Given a user_id, then is_authenticated is True."""
        ctx = UserContext(user_id="user-123", is_authenticated=True)
        assert ctx.user_id == "user-123"
        assert ctx.is_authenticated is True


class TestGetUserFromHeader:
    """Tests for get_user_from_header function."""

    def test_with_x_user_id_header(self):
        """Given X-User-ID header, then user_id is extracted."""
        app = FastAPI()

        @app.get("/test")
        def test_endpoint(request):
            return {"user_id": request.headers.get("X-User-ID", "default")}

        client = TestClient(app)
        response = client.get("/test", headers={"X-User-ID": "user-456"})
        assert response.json()["user_id"] == "user-456"

    def test_without_x_user_id_header(self):
        """Given no X-User-ID header, then user_id defaults to 'default'."""
        from unittest.mock import MagicMock
        mock_request = MagicMock()
        mock_request.headers = {}

        ctx = get_user_from_header(mock_request)
        assert ctx.user_id == "default"
        assert ctx.is_authenticated is False

    def test_with_custom_user_id(self):
        """Given X-User-ID header with custom value, then it is used."""
        from unittest.mock import MagicMock
        mock_request = MagicMock()
        mock_request.headers = {"X-User-ID": "custom-user"}

        ctx = get_user_from_header(mock_request)
        assert ctx.user_id == "custom-user"
        assert ctx.is_authenticated is True


class TestUserScopingMiddleware:
    """Tests for user_scoping_middleware."""

    def test_middleware_attaches_user_context(self):
        """Given a request, then user context is attached to request.state."""
        app = FastAPI()
        app.middleware("http")(user_scoping_middleware)

        @app.get("/test")
        def test_endpoint(request):
            return {"user_id": request.state.user.user_id}

        client = TestClient(app)
        response = client.get("/test", headers={"X-User-ID": "user-789"})
        assert response.json()["user_id"] == "user-789"

    def test_middleware_default_user_without_header(self):
        """Given no X-User-ID header, then default user is attached."""
        app = FastAPI()
        app.middleware("http")(user_scoping_middleware)

        @app.get("/test")
        def test_endpoint(request):
            return {"user_id": request.state.user.user_id, "auth": request.state.user.is_authenticated}

        client = TestClient(app)
        response = client.get("/test")
        data = response.json()
        assert data["user_id"] == "default"
        assert data["auth"] is False


class TestGetCurrentUser:
    """Tests for get_current_user dependency."""

    def test_returns_user_from_request_state(self):
        """Given request.state.user, then it is returned."""
        app = FastAPI()
        app.middleware("http")(user_scoping_middleware)

        @app.get("/test")
        def test_endpoint(user: UserContext = Depends(get_current_user)):
            return {"user_id": user.user_id, "authenticated": user.is_authenticated}

        client = TestClient(app)
        response = client.get("/test", headers={"X-User-ID": "user-abc"})
        data = response.json()
        assert data["user_id"] == "user-abc"
        assert data["authenticated"] is True

    def test_returns_default_when_no_user_in_state(self):
        """Given no user in request.state, then default UserContext is returned."""
        app = FastAPI()

        @app.get("/test")
        def test_endpoint(user: UserContext = Depends(get_current_user)):
            return {"user_id": user.user_id, "authenticated": user.is_authenticated}

        client = TestClient(app)
        response = client.get("/test")
        data = response.json()
        assert data["user_id"] == "default"
        assert data["authenticated"] is False


class TestRequireAuth:
    """Tests for require_auth dependency."""

    def test_returns_user_when_authenticated(self):
        """Given authenticated user, then user context is returned."""
        app = FastAPI()

        async def mock_middleware(request, call_next):
            from middleware.auth import UserContext
            request.state.user = UserContext(user_id="auth-user", is_authenticated=True)
            return await call_next(request)

        app.middleware("http")(mock_middleware)

        @app.get("/test")
        def test_endpoint(user: UserContext = Depends(require_auth)):
            return {"user_id": user.user_id}

        client = TestClient(app)
        response = client.get("/test")
        assert response.status_code == 200
        assert response.json()["user_id"] == "auth-user"

    def test_raises_401_when_not_authenticated(self):
        """Given unauthenticated user, then 401 is raised."""
        app = FastAPI()

        async def mock_middleware(request, call_next):
            from middleware.auth import UserContext
            request.state.user = UserContext(user_id="default", is_authenticated=False)
            return await call_next(request)

        app.middleware("http")(mock_middleware)

        @app.get("/test")
        def test_endpoint(user: UserContext = Depends(require_auth)):
            return {"user_id": user.user_id}

        client = TestClient(app)
        response = client.get("/test")
        assert response.status_code == 401
        assert "Authentication required" in response.json()["detail"]

    def test_raises_401_when_no_user_in_state(self):
        """Given no user in request.state, then 401 is raised."""
        app = FastAPI()

        @app.get("/test")
        def test_endpoint(user: UserContext = Depends(require_auth)):
            return {"user_id": user.user_id}

        client = TestClient(app)
        response = client.get("/test")
        assert response.status_code == 401
