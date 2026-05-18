"""Deployment smoke tests for MCP Email Service.

Each test is stateless and can run independently.
Uses httpx for HTTP calls against the running container.
"""

import os

import httpx
import pytest

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")
TEST_USER_ID = "deploy-test-user"


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10) as c:
        yield c


@pytest.fixture
def auth_client():
    """Client with X-User-ID header for authenticated endpoints."""
    with httpx.Client(
        base_url=BASE_URL,
        timeout=10,
        headers={"X-User-ID": TEST_USER_ID},
    ) as c:
        yield c


@pytest.fixture
def created_account(auth_client):
    """Create a test account and clean it up after the test."""
    resp = auth_client.post(
        "/api/accounts",
        json={
            "email_address": "smoke-test@example.com",
            "imap_host": "imap.example.com",
            "imap_port": 993,
            "username": "smoke-test@example.com",
            "password": "smoketestpassword",
        },
    )
    assert resp.status_code == 201
    account = resp.json()
    yield account
    auth_client.delete(f"/api/accounts/{account['id']}")


class TestHealthCheck:
    def test_health_endpoint_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "healthy"
        assert "app" in body
        assert "version" in body


class TestAccountsAPI:
    def test_list_accounts_returns_200(self, client):
        resp = client.get("/api/accounts")
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert "total" in body

    def test_create_account_returns_201(self, auth_client):
        resp = auth_client.post(
            "/api/accounts",
            json={
                "email_address": "new@example.com",
                "imap_host": "imap.example.com",
                "imap_port": 993,
                "username": "new@example.com",
                "password": "password123",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["email_address"] == "new@example.com"
        assert body["is_active"] is True
        auth_client.delete(f"/api/accounts/{body['id']}")

    def test_get_account_by_id(self, auth_client, created_account):
        resp = auth_client.get(f"/api/accounts/{created_account['id']}")
        assert resp.status_code == 200
        assert resp.json()["email_address"] == "smoke-test@example.com"

    def test_get_nonexistent_account_returns_404(self, client):
        resp = client.get("/api/accounts/99999")
        assert resp.status_code == 404


class TestEmailsAPI:
    def test_list_emails_returns_200(self, client):
        resp = client.get("/api/emails")
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert "total" in body

    def test_list_emails_with_search(self, client):
        resp = client.get("/api/emails", params={"search": "nonexistent"})
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert body["total"] == 0

    def test_get_nonexistent_email_returns_404(self, client):
        resp = client.get("/api/emails/99999")
        assert resp.status_code == 404

    def test_mark_nonexistent_email_read_returns_404(self, client):
        resp = client.patch("/api/emails/99999/read")
        assert resp.status_code == 404


class TestAuthMiddleware:
    def test_protected_endpoint_without_auth_returns_401(self, client):
        """Attachments endpoint requires X-User-ID header."""
        resp = client.get("/api/accounts/1/emails/1/attachments/1")
        assert resp.status_code == 401


class TestNotFound:
    def test_unknown_route_returns_404(self, client):
        resp = client.get("/api/v1/nonexistent")
        assert resp.status_code == 404
