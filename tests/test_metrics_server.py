# tests/test_metrics_server.py
"""Tests for the standalone Prometheus metrics server."""
import json
import sys
import os
import threading
import time
import urllib.request
import urllib.error

import pytest


def _fresh_server(port: int):
    """Import metrics_server fresh (resetting counters) and start it on given port."""
    # Remove cached module so counters re-initialise
    for mod_name in list(sys.modules.keys()):
        if mod_name == "metrics_server" or mod_name.startswith("metrics_server."):
            del sys.modules[mod_name]

    # Reset prometheus registry to avoid "Duplicated timeseries" errors between tests
    import prometheus_client
    collectors_to_remove = [
        c for name, c in list(prometheus_client.REGISTRY._names_to_collectors.items())
        if name.startswith("aisw_")
    ]
    for c in set(collectors_to_remove):
        try:
            prometheus_client.REGISTRY.unregister(c)
        except Exception:
            pass

    # Add project root to path so metrics_server is importable
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)

    import metrics_server as ms
    server = ms.ThreadingServer(("127.0.0.1", port), ms.MetricsHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.05)
    return server, ms


def _post_event(port: int, payload: dict) -> int:
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
    port = 19091
    server, ms = _fresh_server(port)
    yield port, ms
    server.shutdown()


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


def test_post_unknown_event_returns_400(metrics_server):
    port, _ = metrics_server
    status = _post_event(port, {"event_type": "unknown_type", "data": "x"})
    assert status == 400


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
