"""Deployment smoke tests for WordPress Database Integration Feature."""

import os

import httpx
import pytest

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


class TestHealthCheck:
    """Verify the application is running and healthy."""

    def test_health_endpoint(self, client: httpx.Client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "app" in data
        assert "version" in data


class TestImportJobsAPI:
    """Smoke test the WordPress import job endpoints."""

    def test_create_import_job(self, client: httpx.Client):
        response = client.post("/api/v1/import", json={})
        assert response.status_code == 201
        data = response.json()
        assert "job_id" in data
        assert "status" in data
        assert data["status"] == "pending"

    def test_get_import_job_status(self, client: httpx.Client):
        response = client.get("/api/v1/import/1")
        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert "status" in data
        assert "progress_pct" in data
        assert "total_entities" in data
        assert "processed_entities" in data
        assert "failed_entities" in data

    def test_get_nonexistent_job(self, client: httpx.Client):
        response = client.get("/api/v1/import/99999")
        assert response.status_code == 404


class TestImportLogsAPI:
    """Smoke test the import logs endpoint."""

    def test_get_import_job_logs(self, client: httpx.Client):
        response = client.get("/api/v1/import/1/logs")
        assert response.status_code == 200
        data = response.json()
        assert "logs" in data
        assert "total" in data
        assert isinstance(data["logs"], list)

    def test_get_logs_for_nonexistent_job(self, client: httpx.Client):
        response = client.get("/api/v1/import/99999/logs")
        assert response.status_code == 404


class TestUsersAPI:
    """Smoke test the users endpoint (auth-optional in test mode)."""

    def test_get_nonexistent_user(self, client: httpx.Client):
        response = client.get("/api/v1/users/99999")
        assert response.status_code == 404


class TestNotFound:
    """Verify proper 404 handling for unknown routes."""

    def test_unknown_route(self, client: httpx.Client):
        response = client.get("/nonexistent-route")
        assert response.status_code == 404

    def test_unknown_api_route(self, client: httpx.Client):
        response = client.get("/api/v1/nonexistent")
        assert response.status_code == 404
