"""Integration tests for the AISW server REST routes."""
import json
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def reset_api_key():
    from server import auth as auth_mod
    yield
    auth_mod.set_api_key("")


def _make_client(api_key="test-key"):
    """Build a TestClient with a mocked job runner."""
    from server import auth as auth_mod
    auth_mod.set_api_key(api_key)

    mock_runner = MagicMock()
    mock_runner.submit.return_value = "run-123"
    mock_runner.cancel.return_value = True

    from server.models import JobRecord, RunDetail, RunSummary
    mock_store = MagicMock()
    mock_runner.store = mock_store

    _job = JobRecord(
        id="run-123", status="queued", requirement="Build X",
        repo="o/r", pipeline="ai-feature", engineers=2,
        created_at="2026-01-01T00:00:00Z", updated_at="2026-01-01T00:00:00Z",
        log_path="/tmp/run-123.log",
    )
    mock_store.get_job.return_value = _job
    mock_store.list_jobs.return_value = [_job]

    from server.app import create_app
    app = create_app(runner=mock_runner)
    return TestClient(app), mock_runner


class TestHealth:
    def test_health_no_auth(self):
        client, _ = _make_client()
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestPostRuns:
    def test_submit_returns_202(self):
        client, runner = _make_client()
        resp = client.post(
            "/runs",
            json={"requirement": "Build X"},
            headers={"X-API-Key": "test-key"},
        )
        assert resp.status_code == 202
        assert resp.json()["run_id"] == "run-123"
        assert "/runs/run-123/stream" in resp.json()["stream_url"]

    def test_no_api_key_rejected(self):
        client, _ = _make_client()
        resp = client.post("/runs", json={"requirement": "Build X"})
        assert resp.status_code == 401


class TestGetRuns:
    def test_list_runs(self):
        client, _ = _make_client()
        resp = client.get("/runs", headers={"X-API-Key": "test-key"})
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
        assert resp.json()[0]["run_id"] == "run-123"

    def test_get_run_detail(self):
        client, _ = _make_client()
        resp = client.get("/runs/run-123", headers={"X-API-Key": "test-key"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == "run-123"
        assert data["status"] == "queued"

    def test_get_run_not_found(self):
        client, runner = _make_client()
        runner.store.get_job.return_value = None
        resp = client.get("/runs/missing", headers={"X-API-Key": "test-key"})
        assert resp.status_code == 404


class TestDeleteRun:
    def test_cancel_run(self):
        client, runner = _make_client()
        resp = client.delete("/runs/run-123", headers={"X-API-Key": "test-key"})
        assert resp.status_code == 200
        runner.cancel.assert_called_once_with("run-123")

    def test_cancel_not_found(self):
        client, runner = _make_client()
        runner.store.get_job.return_value = None
        resp = client.delete("/runs/missing", headers={"X-API-Key": "test-key"})
        assert resp.status_code == 404

    def test_cancel_already_done(self):
        client, runner = _make_client()
        runner.cancel.return_value = False
        resp = client.delete("/runs/run-123", headers={"X-API-Key": "test-key"})
        assert resp.status_code == 409


class TestStreamRun:
    def test_stream_not_found_returns_404(self):
        client, runner = _make_client()
        runner.store.get_job.return_value = None
        resp = client.get("/runs/missing/stream", headers={"X-API-Key": "test-key"})
        assert resp.status_code == 404

    def test_stream_no_auth_returns_401(self):
        client, _ = _make_client()
        resp = client.get("/runs/run-123/stream")
        assert resp.status_code == 401

    def test_stream_sse_format(self):
        """SSE format: each event has 'event:' and 'data:' lines separated by blank lines."""
        import asyncio
        from server.models import JobRecord

        async def _mock_stream(run_id):
            yield ("log", "hello world")
            yield ("done", '{"verdict":"success"}')

        client, runner = _make_client()
        runner.stream_logs.side_effect = _mock_stream

        with client.stream("GET", "/runs/run-123/stream", headers={"X-API-Key": "test-key"}) as resp:
            assert resp.status_code == 200
            content = resp.read().decode()

        assert "event: log\ndata: hello world\n\n" in content
        assert "event: done\ndata:" in content

    def test_stream_newline_in_data_is_escaped(self):
        """Embedded newlines in data must produce multiple 'data:' lines."""
        async def _mock_stream(run_id):
            yield ("log", "line1\nline2")

        client, runner = _make_client()
        runner.stream_logs.side_effect = _mock_stream

        with client.stream("GET", "/runs/run-123/stream", headers={"X-API-Key": "test-key"}) as resp:
            content = resp.read().decode()

        # Embedded newline should be escaped to "data: line1\ndata: line2"
        assert "data: line1\ndata: line2" in content
