"""Tests for X-API-Key auth dependency."""
import warnings

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import server.auth as auth_mod
from server.auth import require_api_key, set_api_key


@pytest.fixture(autouse=True)
def reset_auth_key():
    """Restore auth state after each test to prevent cross-test contamination."""
    original = auth_mod._configured_key
    yield
    auth_mod._configured_key = original


def _make_app(key: str) -> FastAPI:
    set_api_key(key)
    app = FastAPI()

    @app.get("/protected", dependencies=[require_api_key()])
    def protected():
        return {"ok": True}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


class TestApiKeyAuth:
    def test_valid_key_passes(self):
        client = TestClient(_make_app("secret"))
        resp = client.get("/protected", headers={"X-API-Key": "secret"})
        assert resp.status_code == 200

    def test_wrong_key_rejected(self):
        client = TestClient(_make_app("secret"))
        resp = client.get("/protected", headers={"X-API-Key": "wrong"})
        assert resp.status_code == 401

    def test_missing_key_rejected(self):
        client = TestClient(_make_app("secret"))
        resp = client.get("/protected")
        assert resp.status_code == 401

    def test_health_no_key_needed(self):
        """Health endpoint has no auth dependency — always works."""
        client = TestClient(_make_app("secret"))
        resp = client.get("/health")
        assert resp.status_code == 200


class TestDevMode:
    def test_no_key_configured_allows_all(self):
        """Dev mode: empty key → open access (no auth required)."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            auth_mod.set_api_key("")
        app = FastAPI()

        @app.get("/protected", dependencies=[require_api_key()])
        def protected():
            return {"ok": True}

        client = TestClient(app)
        resp = client.get("/protected")  # no header — should be 200
        assert resp.status_code == 200
