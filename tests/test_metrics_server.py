# tests/test_metrics_server.py
"""Tests for the standalone Prometheus metrics server."""
import json
import socket
import sys
import os
import threading
import time
import urllib.request
import urllib.error

import pytest


def _fresh_server():
    """Import metrics_server fresh (resetting counters) and start it on an OS-assigned port."""
    # Remove cached module so counters re-initialise on a new dedicated CollectorRegistry
    for mod_name in list(sys.modules.keys()):
        if mod_name == "metrics_server" or mod_name.startswith("metrics_server."):
            del sys.modules[mod_name]

    # Add project root to path so metrics_server is importable
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)

    import metrics_server as ms
    server = ms.ThreadingServer(("127.0.0.1", 0), ms.MetricsHandler)
    port = server.server_address[1]  # OS-assigned free port
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    # Poll until ready instead of sleeping
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.05).close()
            break
        except OSError:
            time.sleep(0.01)
    else:
        raise RuntimeError("metrics_server did not become ready within 2 seconds")
    return server, ms, port


def _post_event(port: int, payload: object) -> int:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/event",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=2)
        return resp.status
    except urllib.error.HTTPError as e:
        return e.code


def _get_metrics(port: int) -> str:
    resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=2)
    return resp.read().decode()


@pytest.fixture()
def metrics_server():
    server, ms, port = _fresh_server()
    yield port, ms
    server.shutdown()
    server.server_close()


def test_post_circuit_breaker_event_increments_counter(metrics_server):
    port, ms = metrics_server
    status = _post_event(port, {
        "event_type": "circuit_breaker",
        "name": "backend",
        "state": "open",
        "failure_count": 3,
        "timestamp": "2026-01-01T00:00:00+00:00",
    })
    assert status == 200
    metrics_text = _get_metrics(port)
    assert 'aisw_circuit_breaker_events_total{name="backend",state="open"} 1.0' in metrics_text


def test_post_dlq_event_increments_counter(metrics_server):
    port, ms = metrics_server
    status = _post_event(port, {
        "event_type": "dlq",
        "action": "enqueue",
        "backend": "memory",
        "entry_id": "e1",
        "attempt_count": 1,
        "timestamp": "2026-01-01T00:00:00+00:00",
    })
    assert status == 200
    metrics_text = _get_metrics(port)
    assert 'aisw_dlq_events_total{action="enqueue",backend="memory"} 1.0' in metrics_text


def test_post_degradation_event_increments_counter(metrics_server):
    port, ms = metrics_server
    status = _post_event(port, {
        "event_type": "degradation",
        "trigger": "cpu_high",
        "actions_taken": ["throttle"],
        "timestamp": "2026-01-01T00:00:00+00:00",
    })
    assert status == 200
    metrics_text = _get_metrics(port)
    assert 'aisw_degradation_events_total{trigger="cpu_high"} 1.0' in metrics_text


def test_post_unknown_event_returns_200_and_increments_unknown_counter(metrics_server):
    port, _ = metrics_server
    status = _post_event(port, {"event_type": "unknown_type", "data": "x"})
    assert status == 200
    metrics_text = _get_metrics(port)
    assert 'aisw_unknown_events_total{event_type="unknown_type"} 1.0' in metrics_text


def test_get_metrics_content_type(metrics_server):
    port, _ = metrics_server
    resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=2)
    ct = resp.headers.get("Content-Type", "")
    assert "text/plain" in ct


def test_get_unknown_path_returns_404(metrics_server):
    port, _ = metrics_server
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2)
        assert False, "Expected 404"
    except urllib.error.HTTPError as e:
        assert e.code == 404


def test_post_non_dict_json_returns_400(metrics_server):
    port, _ = metrics_server
    status = _post_event(port, [1, 2, 3])  # valid JSON but not a dict
    assert status == 400


def test_post_malformed_json_returns_400(metrics_server):
    port, _ = metrics_server
    # Send raw bytes that are not valid JSON
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/event",
        data=b"not-json{{{",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=2)
        assert resp.status == 400
    except urllib.error.HTTPError as e:
        assert e.code == 400


def test_post_oversized_payload_returns_413(metrics_server):
    port, _ = metrics_server
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/event",
        data=b"x",
        headers={"Content-Type": "application/json", "Content-Length": "99999"},
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=2)
        assert resp.status == 413
    except urllib.error.HTTPError as e:
        assert e.code == 413
