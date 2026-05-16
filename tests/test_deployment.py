"""Deployment smoke tests for SaaS Site Builder Platform."""

import os

import httpx
import pytest

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")
API = f"{BASE_URL}/api/v1"


@pytest.fixture(scope="module")
def http_client():
    """Create a stateless httpx client for the test module."""
    with httpx.Client(base_url=BASE_URL, timeout=10) as client:
        yield client


class TestHealthCheck:
    """Verify the application is running and healthy."""

    def test_health_endpoint(self, http_client: httpx.Client):
        """GET /health should return 200 with status healthy."""
        resp = http_client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert "app" in data
        assert "version" in data


class TestSitesAPI:
    """Smoke test the sites / business API endpoints."""

    def test_list_groups(self, http_client: httpx.Client):
        """GET /api/v1/groups should return 200 with paginated response."""
        resp = http_client.get(f"{API}/groups")
        assert resp.status_code == 200
        data = resp.json()
        assert "groups" in data
        assert "total" in data
        assert "page" in data

    def test_create_group(self, http_client: httpx.Client):
        """POST /api/v1/groups should create a group and return 201."""
        payload = {
            "name": "Smoke Test Site",
            "description": "Created by deployment smoke test",
            "is_public": True,
        }
        resp = http_client.post(f"{API}/groups", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Smoke Test Site"

    def test_create_and_get_group(self, http_client: httpx.Client):
        """Create a group then retrieve it by ID."""
        payload = {
            "name": "Retrieve Test Site",
            "description": "For retrieval smoke test",
            "is_public": False,
        }
        create_resp = http_client.post(f"{API}/groups", json=payload)
        assert create_resp.status_code == 201
        group_id = create_resp.json()["id"]

        get_resp = http_client.get(f"{API}/groups/{group_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["name"] == "Retrieve Test Site"

    def test_get_nonexistent_group_returns_404(self, http_client: httpx.Client):
        """GET /api/v1/groups/99999 should return 404."""
        resp = http_client.get(f"{API}/groups/99999")
        assert resp.status_code == 404


class TestUsersAPI:
    """Smoke test the users API endpoints."""

    def test_get_nonexistent_user_returns_404(self, http_client: httpx.Client):
        """GET /api/v1/users/99999 should return 404."""
        resp = http_client.get(f"{API}/users/99999")
        assert resp.status_code == 404

    def test_get_user_route_exists(self, http_client: httpx.Client):
        """GET /api/v1/users/1 should return 200 or 404 (route exists)."""
        resp = http_client.get(f"{API}/users/1")
        assert resp.status_code in (200, 404)


class TestNotificationsAPI:
    """Smoke test the notifications API endpoints."""

    def test_list_notifications(self, http_client: httpx.Client):
        """GET /api/v1/notifications should return 200."""
        resp = http_client.get(f"{API}/notifications")
        assert resp.status_code == 200
        data = resp.json()
        assert "notifications" in data

    def test_create_notification(self, http_client: httpx.Client):
        """POST /api/v1/notifications should create a notification."""
        payload = {
            "user_id": 1,
            "title": "Smoke Test",
            "message": "Deployment smoke test notification",
            "type": "info",
        }
        resp = http_client.post(f"{API}/notifications", json=payload)
        assert resp.status_code == 201


class TestNotFound:
    """Verify unknown routes return 404."""

    def test_unknown_route_returns_404(self, http_client: httpx.Client):
        """GET /api/v1/nonexistent should return 404."""
        resp = http_client.get(f"{API}/nonexistent")
        assert resp.status_code == 404

    def test_random_path_returns_404(self, http_client: httpx.Client):
        """GET /this/does/not/exist should return 404."""
        resp = http_client.get("/this/does/not/exist")
        assert resp.status_code == 404
