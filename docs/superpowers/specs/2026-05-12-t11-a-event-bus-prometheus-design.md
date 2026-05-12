# T11-A Design: Event Bus Wiring + Prometheus Metrics Sink

**Date:** 2026-05-12
**Branch:** `t11-a-event-bus-prometheus`
**PR target:** `master`

---

## Problem Statement

T2-B implemented `core/events.py` with `emit_event()`, `set_emit_callback()`, and event hooks in `core/circuit_breaker.py`, `core/dead_letter.py`, and `core/degradation.py`. However, `set_emit_callback()` is never called in production code — every event silently falls through to the default `logger.info()` call. The entire observability infrastructure is dead code at the integration boundary.

T11-A wires the event bus to a standalone Prometheus metrics server so that circuit breaker state transitions, DLQ activity, and degradation events are visible to external monitoring systems.

---

## Architecture Overview

Three components:

1. **`core/metrics_sink.py`** — in-process callback factory. `build_callback(url)` returns a callable that POSTs each `Event` as JSON to the metrics server's `/event` endpoint. Fire-and-forget: failures are logged and swallowed so a down metrics server never crashes the watcher.

2. **`metrics_server.py`** (root-level standalone script) — a minimal HTTP server (using Python's built-in `http.server` with `socketserver.ThreadingMixIn`) that:
   - Accepts `POST /event` — deserialises the JSON body, increments the matching Prometheus `Counter`
   - Accepts `GET /metrics` — serves Prometheus text format via `prometheus_client.generate_latest()`
   - Runs on configurable port (env var `METRICS_PORT`, default `9091`)

3. **`watcher.py` wiring** — at the top of `watch()`, read `metrics_url` from config. If present, call `set_emit_callback(build_callback(metrics_url))`.

---

## Task 1: `core/metrics_sink.py`

**File:** `core/metrics_sink.py` (new)

**Implementation:**

```python
import json
import logging
import urllib.request
from typing import Callable
from core.events import AnyEvent

_log = logging.getLogger(__name__)

def build_callback(metrics_url: str) -> Callable[[Event], None]:
    """Return a callback that POSTs each Event to the metrics server."""
    endpoint = metrics_url.rstrip("/") + "/event"

    def _callback(event: AnyEvent) -> None:
        try:
            body = json.dumps(vars(event)).encode()
            req = urllib.request.Request(
                endpoint,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=1)
        except Exception as exc:  # noqa: BLE001
            _log.debug("metrics_sink: failed to post event %s: %s", event.type, exc)

    return _callback
```

No new dependencies — uses only stdlib `urllib.request`.

---

## Task 2: `metrics_server.py`

**File:** `metrics_server.py` (new, root-level)

**Metrics registered:**

| Counter name | Labels | Incremented on |
|---|---|---|
| `aisw_circuit_breaker_events_total` | `name`, `state` | `CircuitBreakerEvent` — state values: `"open"`, `"half_open"`, `"closed"` |
| `aisw_dlq_events_total` | `action`, `backend` | `DLQEvent` — action values: `"enqueue"`, `"ack"`, `"nack"`, `"discard"` |
| `aisw_degradation_events_total` | `service` | `DegradationEvent` — one increment per event |

**Endpoints:**

- `POST /event` — JSON body `{"type": "<EventType>", "payload": {...}}`. Increments matching counter. Returns 200 on success, 400 on unknown event type (but still logs and continues).
- `GET /metrics` — returns `prometheus_client.generate_latest(REGISTRY)` with content-type `text/plain; version=0.0.4`.

**Implementation notes:**
- Use `socketserver.ThreadingTCPServer` + `http.server.BaseHTTPRequestHandler` — no new web framework dependency.
- `prometheus_client` added to `requirements.txt`.
- Port from `METRICS_PORT` env var, defaulting to `9091`.
- `if __name__ == "__main__"` guard for standalone invocation.
- Include a `--help` flag documenting the `METRICS_PORT` env var and expected event schema.

---

## Task 3: Wire in `watcher.py`

**File:** `watcher.py`, `watch()` function

**Change:** At the start of `watch()`, after config is loaded but before the poll loop:

```python
from core.events import set_emit_callback
from core.metrics_sink import build_callback

if metrics_url := config.get("metrics_url"):
    set_emit_callback(build_callback(metrics_url))
    _log.info("metrics sink wired to %s", metrics_url)
```

**Config key:** `metrics_url` — optional, e.g. `http://localhost:9091`. Document in `README.md`'s configuration section and in `repos.conf` comments.

---

## Task 4: Tests

**File:** `tests/test_metrics_sink.py` (new)

Tests:
1. `test_build_callback_posts_json` — mock `urllib.request.urlopen`; verify POST is made to correct URL with correct JSON body for a `CircuitBreakerEvent(name="backend", state="open", failure_count=3)`
2. `test_callback_swallows_connection_error` — urlopen raises `OSError`; verify no exception propagates and `_log.debug` is called
3. `test_callback_swallows_timeout` — urlopen raises `TimeoutError`; same as above

**File:** `tests/test_metrics_server.py` (new)

Start a `metrics_server` instance on a random port in a thread fixture; exercise real HTTP:
1. `test_post_cb_open_increments_counter` — POST `CircuitBreakerEvent(name="backend", state="open", failure_count=1)`; GET `/metrics` contains `aisw_circuit_breaker_events_total{name="backend",state="open"} 1.0`
2. `test_post_dlq_enqueue_increments_counter` — POST `DLQEvent(action="enqueue", ...)`; check `aisw_dlq_events_total{action="enqueue",...} 1.0`
3. `test_post_unknown_event_returns_400` — POST unknown type; assert 400, server still running
4. `test_get_metrics_content_type` — verify `Content-Type: text/plain` header on `/metrics`

**File:** `tests/test_watcher_metrics_wiring.py` (new)

1. `test_watch_wires_metrics_callback_when_url_set` — monkeypatch config to include `metrics_url`; verify `set_emit_callback` is called once with a callable
2. `test_watch_skips_metrics_wiring_when_url_absent` — config without `metrics_url`; verify `set_emit_callback` not called

---

## Dependencies

Add to `requirements.txt`:
```
prometheus-client>=0.20.0
```

---

## Error Handling

- Metrics server down → callback logs at DEBUG level and returns; watcher is unaffected
- Unknown event type → server returns 400 but logs and continues; counter not incremented
- Server port already in use → `OSError` from `TCPServer.server_bind()`; exits with error message and non-zero code

---

## Acceptance Criteria

- [ ] `set_emit_callback` is called in production `watch()` when `metrics_url` is configured
- [ ] `metrics_server.py` starts, accepts events, serves `/metrics` in Prometheus text format
- [ ] Circuit breaker open/close events appear as counter increments on `/metrics`
- [ ] DLQ and degradation events likewise appear
- [ ] A down metrics server does not raise in the watcher process
- [ ] All new tests pass; no existing tests broken
