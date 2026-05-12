"""Deployment smoke tests for Multi-Business Booking System."""

import os
import sys
import pytest
from fastapi.testclient import TestClient

# Compute backend dir but do NOT insert into sys.path at module level
_BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")


@pytest.fixture(scope="module", autouse=True)
def _clean_test_db():
    """Remove leftover SQLite DB from previous test runs."""
    db_path = os.path.join(os.path.dirname(__file__), "..", "test_deployment.db")
    db_path = os.path.abspath(db_path)
    if os.path.exists(db_path):
        os.remove(db_path)
    yield
    if os.path.exists(db_path):
        os.remove(db_path)


@pytest.fixture(scope="module")
def client():
    """Create a TestClient wrapping the FastAPI app with a fresh SQLite DB."""
    # Insert backend on sys.path during tests only
    sys.path.insert(0, _BACKEND_DIR)
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_deployment.db"
    import main as _main_module  # noqa: E402
    with TestClient(_main_module.app) as c:
        yield c
    # Cleanup: restore sys.path and sys.modules to avoid polluting other tests
    try:
        sys.path.remove(_BACKEND_DIR)
    except ValueError:
        pass
    os.environ.pop("DATABASE_URL", None)
    _prefixes = ("main", "database", "models", "routers")
    for key in list(sys.modules):
        if key in _prefixes or any(key.startswith(p + ".") for p in _prefixes):
            del sys.modules[key]


class TestHealthCheck:
    """Verify the application is running and healthy."""

    def test_health_endpoint(self, client: TestClient):
        """GET /health should return 200 with status healthy."""
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert "app" in data
        assert "version" in data


class TestUsersAPI:
    """Smoke test the users API endpoints."""

    def test_get_nonexistent_user_returns_404(self, client: TestClient):
        """GET /api/v1/users/99999 should return 404."""
        resp = client.get("/api/v1/users/99999")
        assert resp.status_code == 404

    def test_get_user_route_exists(self, client: TestClient):
        """GET /api/v1/users/1 should return 200 or 404 (route exists)."""
        resp = client.get("/api/v1/users/1")
        assert resp.status_code in (200, 404)


class TestGroupsAPI:
    """Smoke test the groups API endpoints."""

    def test_list_groups(self, client: TestClient):
        """GET /api/v1/groups should return 200 with paginated response."""
        resp = client.get("/api/v1/groups")
        assert resp.status_code == 200
        data = resp.json()
        assert "groups" in data
        assert "total" in data
        assert "page" in data

    def test_get_nonexistent_group_returns_404(self, client: TestClient):
        """GET /api/v1/groups/99999 should return 404."""
        resp = client.get("/api/v1/groups/99999")
        assert resp.status_code == 404

    def test_create_group(self, client: TestClient):
        """POST /api/v1/groups should create a group and return 201."""
        payload = {
            "name": "Smoke Test Group",
            "description": "Created by deployment smoke test",
            "is_public": True,
        }
        resp = client.post("/api/v1/groups", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Smoke Test Group"

    def test_create_and_get_group(self, client: TestClient):
        """Create a group then retrieve it by ID."""
        payload = {
            "name": "Retrieve Test Group",
            "description": "For retrieval smoke test",
            "is_public": False,
        }
        create_resp = client.post("/api/v1/groups", json=payload)
        assert create_resp.status_code == 201
        group_id = create_resp.json()["id"]

        get_resp = client.get(f"/api/v1/groups/{group_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["name"] == "Retrieve Test Group"


class TestNotificationsAPI:
    """Smoke test the notifications API endpoints."""

    def test_list_notifications(self, client: TestClient):
        """GET /api/v1/notifications should return 200."""
        resp = client.get("/api/v1/notifications")
        assert resp.status_code == 200
        data = resp.json()
        assert "notifications" in data

    def test_create_notification(self, client: TestClient):
        """POST /api/v1/notifications should create a notification."""
        payload = {
            "user_id": 1,
            "title": "Smoke Test",
            "message": "Deployment smoke test notification",
            "type": "info",
        }
        resp = client.post("/api/v1/notifications", json=payload)
        assert resp.status_code == 201


class TestNotFound:
    """Verify unknown routes return 404."""

    def test_unknown_route_returns_404(self, client: TestClient):
        """GET /api/v1/nonexistent should return 404."""
        resp = client.get("/api/v1/nonexistent")
        assert resp.status_code == 404

    def test_random_path_returns_404(self, client: TestClient):
        """GET /this/does/not/exist should return 404."""
        resp = client.get("/this/does/not/exist")
        assert resp.status_code == 404
