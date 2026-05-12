# tests/test_metrics_sink.py
import json
import logging
from unittest.mock import MagicMock, patch
from urllib.error import URLError

import pytest

from core.events import CircuitBreakerEvent, DLQEvent, DegradationEvent


def test_build_callback_posts_correct_json(monkeypatch):
    posted = []

    def fake_urlopen(req, timeout=None):
        posted.append({
            "url": req.full_url,
            "body": json.loads(req.data.decode()),
            "method": req.method,
        })
        return MagicMock()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    from core.metrics_sink import build_callback
    cb = build_callback("http://localhost:9091")
    event = CircuitBreakerEvent(name="backend", state="open", failure_count=3)
    cb(event)

    assert len(posted) == 1
    assert posted[0]["url"] == "http://localhost:9091/event"
    assert posted[0]["method"] == "POST"
    body = posted[0]["body"]
    assert body["event_type"] == "circuit_breaker"
    assert body["state"] == "open"
    assert body["name"] == "backend"
    assert body["failure_count"] == 3


def test_build_callback_strips_trailing_slash(monkeypatch):
    posted_urls = []

    def fake_urlopen(req, timeout=None):
        posted_urls.append(req.full_url)
        return MagicMock()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    from core.metrics_sink import build_callback
    cb = build_callback("http://localhost:9091/")  # trailing slash
    cb(DLQEvent(action="enqueue", entry_id="e1", backend="memory", attempt_count=1))

    assert posted_urls[0] == "http://localhost:9091/event"


def test_callback_swallows_connection_error(monkeypatch, caplog):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        MagicMock(side_effect=URLError("Connection refused")),
    )

    from core.metrics_sink import build_callback
    cb = build_callback("http://localhost:9091")
    event = DLQEvent(action="enqueue", entry_id="e1", backend="memory", attempt_count=1)

    with caplog.at_level(logging.DEBUG, logger="core.metrics_sink"):
        cb(event)  # must not raise

    assert any("failed to post" in r.message for r in caplog.records)


def test_callback_swallows_timeout(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        MagicMock(side_effect=TimeoutError("timed out")),
    )

    from core.metrics_sink import build_callback
    cb = build_callback("http://localhost:9091")
    cb(CircuitBreakerEvent(name="b", state="closed", failure_count=0))  # must not raise


def test_callback_posts_dlq_event(monkeypatch):
    posted = []

    def fake_urlopen(req, timeout=None):
        posted.append(json.loads(req.data.decode()))
        return MagicMock()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    from core.metrics_sink import build_callback
    cb = build_callback("http://localhost:9091")
    cb(DLQEvent(action="discard", entry_id="e42", backend="file", attempt_count=5))

    body = posted[0]
    assert body["event_type"] == "dlq"
    assert body["action"] == "discard"
    assert body["backend"] == "file"


def test_callback_posts_degradation_event(monkeypatch):
    posted = []

    def fake_urlopen(req, timeout=None):
        posted.append(json.loads(req.data.decode()))
        return MagicMock()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    from core.metrics_sink import build_callback
    cb = build_callback("http://localhost:9091")
    cb(DegradationEvent(trigger="cpu_high", actions_taken=["throttle_requests"]))

    body = posted[0]
    assert body["event_type"] == "degradation"
    assert body["trigger"] == "cpu_high"
