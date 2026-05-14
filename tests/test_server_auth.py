"""Tests for X-API-Key auth dependency."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from server.auth import require_api_key, set_api_key


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
