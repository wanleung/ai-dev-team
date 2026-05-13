#!/usr/bin/env python3
"""Standalone Prometheus metrics server for ai-software-house.

Receives events from the watcher via POST /event and exposes
counters on GET /metrics for Prometheus scraping.

Usage::

    METRICS_PORT=9091 python3 metrics_server.py

The watcher sends events when ``metrics_url: http://localhost:9091``
is set in the ``settings:`` block of watchers.yml.
"""

import json
import os
import socketserver
from http.server import BaseHTTPRequestHandler

from prometheus_client import CollectorRegistry, Counter, generate_latest

METRICS_REGISTRY = CollectorRegistry()

CB_COUNTER = Counter(
    "aisw_circuit_breaker_events_total",
    "Circuit breaker state-transition events",
    ["name", "state"],
    registry=METRICS_REGISTRY,
)
DLQ_COUNTER = Counter(
    "aisw_dlq_events_total",
    "Dead-letter-queue operation events",
    ["action", "backend"],
    registry=METRICS_REGISTRY,
)
DEG_COUNTER = Counter(
    "aisw_degradation_events_total",
    "Degradation policy events",
    ["trigger"],
    registry=METRICS_REGISTRY,
)
UNKNOWN_COUNTER = Counter(
    "aisw_unknown_events_total",
    "Events with unrecognised event_type (indicates a schema gap)",
    ["event_type"],
    registry=METRICS_REGISTRY,
)


class MetricsHandler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        if self.path != "/event":
            self.send_response(404)
            self.end_headers()
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self.send_response(400)
            self.end_headers()
            return
        if length < 0:
            length = 0
        if length > 65_536:
            self.send_response(413)
            self.end_headers()
            return
        body = self.rfile.read(length)
        try:
            event = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            self.send_response(400)
            self.end_headers()
            return

        if not isinstance(event, dict):
            self.send_response(400)
            self.end_headers()
            return

        event_type = event.get("event_type")
        if event_type == "circuit_breaker":
            CB_COUNTER.labels(
                name=event.get("name", ""),
                state=event.get("state", ""),
            ).inc()
        elif event_type == "dlq":
            DLQ_COUNTER.labels(
                action=event.get("action", ""),
                backend=event.get("backend", ""),
            ).inc()
        elif event_type == "degradation":
            DEG_COUNTER.labels(
                trigger=event.get("trigger", ""),
            ).inc()
        else:
            UNKNOWN_COUNTER.labels(event_type=event_type or "").inc()

        self.send_response(200)
        self.end_headers()

    def do_GET(self):  # noqa: N802
        if self.path != "/metrics":
            self.send_response(404)
            self.end_headers()
            return

        output = generate_latest(METRICS_REGISTRY)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.end_headers()
        self.wfile.write(output)

    def log_message(self, format, *args):  # noqa: A002
        pass  # suppress Apache-style access log


class ThreadingServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    port = int(os.environ.get("METRICS_PORT", "9091"))
    print(f"Metrics server starting on :{port}")
    print("  POST /event   — receive event JSON, increment counter")
    print("  GET  /metrics — Prometheus scrape endpoint")
    print(f"\nSet metrics_url: http://localhost:{port} in watchers.yml settings:")
    with ThreadingServer(("", port), MetricsHandler) as server:
        server.serve_forever()
