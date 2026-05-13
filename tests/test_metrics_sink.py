# tests/test_metrics_sink.py
import json
import logging
import threading
from unittest.mock import MagicMock
from urllib.error import URLError

from core.events import CircuitBreakerEvent, DLQEvent, DegradationEvent
from core.metrics_sink import build_callback


def test_build_callback_posts_correct_json(monkeypatch):
    posted = []
    done = threading.Event()

    def fake_urlopen(req, timeout=None):
        posted.append({
            "url": req.full_url,
            "body": json.loads(req.data.decode()),
            "method": req.method,
        })
        done.set()
        return MagicMock()

    monkeypatch.setattr("core.metrics_sink.urllib.request.urlopen", fake_urlopen)

    cb = build_callback("http://localhost:9091")
    event = CircuitBreakerEvent(name="backend", state="open", failure_count=3)
    cb(event)
    assert done.wait(timeout=2), "callback thread did not fire"

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
    done = threading.Event()

    def fake_urlopen(req, timeout=None):
        posted_urls.append(req.full_url)
        done.set()
        return MagicMock()

    monkeypatch.setattr("core.metrics_sink.urllib.request.urlopen", fake_urlopen)

    cb = build_callback("http://localhost:9091/")  # trailing slash
    cb(DLQEvent(action="enqueue", entry_id="e1", backend="memory", attempt_count=1))
    assert done.wait(timeout=2), "callback thread did not fire"

    assert posted_urls[0] == "http://localhost:9091/event"


def test_callback_swallows_connection_error(monkeypatch, caplog):
    done = threading.Event()

    def fake_urlopen(req, timeout=None):
        done.set()
        raise URLError("Connection refused")

    monkeypatch.setattr("core.metrics_sink.urllib.request.urlopen", fake_urlopen)

    cb = build_callback("http://localhost:9091")
    event = DLQEvent(action="enqueue", entry_id="e1", backend="memory", attempt_count=1)

    with caplog.at_level(logging.DEBUG, logger="core.metrics_sink"):
        cb(event)  # must not raise
        assert done.wait(timeout=2), "callback thread did not fire"

    assert any("failed to post" in r.message for r in caplog.records)


def test_callback_swallows_timeout(monkeypatch):
    done = threading.Event()

    def fake_urlopen(req, timeout=None):
        done.set()
        raise TimeoutError("timed out")

    monkeypatch.setattr("core.metrics_sink.urllib.request.urlopen", fake_urlopen)

    cb = build_callback("http://localhost:9091")
    cb(CircuitBreakerEvent(name="b", state="closed", failure_count=0))  # must not raise
    assert done.wait(timeout=2), "callback thread did not fire"


def test_callback_posts_dlq_event(monkeypatch):
    posted = []
    done = threading.Event()

    def fake_urlopen(req, timeout=None):
        posted.append(json.loads(req.data.decode()))
        done.set()
        return MagicMock()

    monkeypatch.setattr("core.metrics_sink.urllib.request.urlopen", fake_urlopen)

    cb = build_callback("http://localhost:9091")
    cb(DLQEvent(action="discard", entry_id="e42", backend="file", attempt_count=5))
    assert done.wait(timeout=2), "callback thread did not fire"

    body = posted[0]
    assert body["event_type"] == "dlq"
    assert body["action"] == "discard"
    assert body["backend"] == "file"


def test_callback_posts_degradation_event(monkeypatch):
    posted = []
    done = threading.Event()

    def fake_urlopen(req, timeout=None):
        posted.append(json.loads(req.data.decode()))
        done.set()
        return MagicMock()

    monkeypatch.setattr("core.metrics_sink.urllib.request.urlopen", fake_urlopen)

    cb = build_callback("http://localhost:9091")
    cb(DegradationEvent(trigger="cpu_high", actions_taken=["throttle_requests"]))
    assert done.wait(timeout=2), "callback thread did not fire"

    body = posted[0]
    assert body["event_type"] == "degradation"
    assert body["trigger"] == "cpu_high"
