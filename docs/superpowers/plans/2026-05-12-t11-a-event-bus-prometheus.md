# T11-A: Event Bus Wiring + Prometheus Metrics Sink — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire `set_emit_callback()` into production `watch()` and provide a standalone Prometheus metrics server that counts circuit breaker, DLQ, and degradation events.

**Architecture:** A new `core/metrics_sink.py` provides `build_callback(url)` which returns a callable posting each event as JSON via `urllib.request` to a standalone `metrics_server.py`. The server uses Python's built-in `http.server` + Prometheus `Counter` objects to serve `/metrics`. `watch()` wires the callback at startup when `metrics_url` is present in `settings:`.

**Tech Stack:** Python `http.server` + `socketserver.ThreadingMixIn`, `prometheus-client>=0.20.0`, `urllib.request` (stdlib, no new runtime dep for the sink).

---

### Task 1: Add `prometheus-client` to `requirements.txt`

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add dependency**

  Open `requirements.txt` and append:
  ```
  prometheus-client>=0.20.0
  ```

- [ ] **Step 2: Install**

  ```bash
  pip install prometheus-client
  ```
  Expected: `Successfully installed prometheus-client-...`

- [ ] **Step 3: Commit**

  ```bash
  git add requirements.txt
  git commit -m "chore: add prometheus-client dependency for T11-A"
  ```

---

### Task 2: Write Failing Tests for `core/metrics_sink.py`

**Files:**
- Create: `tests/test_metrics_sink.py`

- [ ] **Step 1: Create test file**

  ```python
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
  ```

- [ ] **Step 2: Run to confirm failure**

  ```bash
  pytest tests/test_metrics_sink.py -v 2>&1 | head -20
  ```
  Expected: `ModuleNotFoundError: No module named 'core.metrics_sink'`

---

### Task 3: Implement `core/metrics_sink.py`

**Files:**
- Create: `core/metrics_sink.py`

- [ ] **Step 1: Create the module**

  ```python
  # core/metrics_sink.py
  """Prometheus metrics sink for the ai-software-house event bus.

  Usage::

      from core.events import set_emit_callback
      from core.metrics_sink import build_callback

      set_emit_callback(build_callback("http://localhost:9091"))
  """

  import json
  import logging
  import urllib.request
  from typing import Callable

  from core.events import AnyEvent

  _log = logging.getLogger(__name__)


  def build_callback(metrics_url: str) -> Callable[[AnyEvent], None]:
      """Return a callback that POSTs each event as JSON to ``metrics_url/event``.

      The callback is fire-and-forget: any exception (server down, timeout) is
      logged at DEBUG level and swallowed so the watcher is never interrupted.
      """
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
              _log.debug("metrics_sink: failed to post event %s: %s", event.event_type, exc)

      return _callback
  ```

- [ ] **Step 2: Run tests**

  ```bash
  pytest tests/test_metrics_sink.py -v
  ```
  Expected: `6 passed`

- [ ] **Step 3: Commit**

  ```bash
  git add core/metrics_sink.py tests/test_metrics_sink.py
  git commit -m "feat: add core/metrics_sink.py with build_callback() and tests"
  ```

---

### Task 4: Write Failing Tests for `metrics_server.py`

**Files:**
- Create: `tests/test_metrics_server.py`

- [ ] **Step 1: Create test file**

  ```python
  # tests/test_metrics_server.py
  """Tests for the standalone Prometheus metrics server."""
  import importlib
  import json
  import threading
  import time
  import urllib.request
  from http.client import HTTPResponse

  import pytest


  def _start_server(port: int):
      """Import and start the metrics server in a daemon thread. Returns the module."""
      import sys, os
      sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

      # Fresh import so counters start at zero for each test
      if "metrics_server" in sys.modules:
          del sys.modules["metrics_server"]
      # Wipe prometheus registry between tests by re-importing with fresh counters
      import prometheus_client
      prometheus_client.REGISTRY._names_to_collectors.clear()  # reset for test isolation

      import metrics_server as ms
      server = ms.ThreadingServer(("127.0.0.1", port), ms.MetricsHandler)
      t = threading.Thread(target=server.serve_forever, daemon=True)
      t.start()
      time.sleep(0.05)  # let it bind
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
      server, ms = _start_server(port)
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
  ```

- [ ] **Step 2: Run to confirm failure**

  ```bash
  pytest tests/test_metrics_server.py -v 2>&1 | head -10
  ```
  Expected: `ModuleNotFoundError: No module named 'metrics_server'`

---

### Task 5: Implement `metrics_server.py`

**Files:**
- Create: `metrics_server.py`

- [ ] **Step 1: Create the server**

  ```python
  #!/usr/bin/env python3
  """Standalone Prometheus metrics server for ai-software-house.

  Receives events from the watcher via POST /event and exposes
  counters on GET /metrics for Prometheus scraping.

  Usage::

      METRICS_PORT=9091 python metrics_server.py

  The watcher sends events when ``metrics_url: http://localhost:9091``
  is set in the ``settings:`` block of watchers.yml.
  """

  import json
  import os
  import socketserver
  from http.server import BaseHTTPRequestHandler

  from prometheus_client import Counter, generate_latest, REGISTRY

  CB_COUNTER = Counter(
      "aisw_circuit_breaker_events_total",
      "Circuit breaker state-transition events",
      ["name", "state"],
  )
  DLQ_COUNTER = Counter(
      "aisw_dlq_events_total",
      "Dead-letter-queue operation events",
      ["action", "backend"],
  )
  DEG_COUNTER = Counter(
      "aisw_degradation_events_total",
      "Degradation policy events",
      ["trigger"],
  )


  class MetricsHandler(BaseHTTPRequestHandler):
      def do_POST(self):  # noqa: N802
          if self.path != "/event":
              self.send_response(404)
              self.end_headers()
              return

          length = int(self.headers.get("Content-Length", 0))
          body = self.rfile.read(length)
          try:
              event = json.loads(body)
          except (json.JSONDecodeError, ValueError):
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
              self.send_response(400)
              self.end_headers()
              return

          self.send_response(200)
          self.end_headers()

      def do_GET(self):  # noqa: N802
          if self.path != "/metrics":
              self.send_response(404)
              self.end_headers()
              return

          output = generate_latest(REGISTRY)
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
  ```

- [ ] **Step 2: Run tests**

  ```bash
  pytest tests/test_metrics_server.py -v
  ```
  Expected: `6 passed`

- [ ] **Step 3: Commit**

  ```bash
  git add metrics_server.py tests/test_metrics_server.py
  git commit -m "feat: add standalone Prometheus metrics_server.py with tests"
  ```

---

### Task 6: Write Failing Test for Watcher Wiring

**Files:**
- Create: `tests/test_watcher_metrics_wiring.py`

- [ ] **Step 1: Create test file**

  ```python
  # tests/test_watcher_metrics_wiring.py
  """Tests that watch() wires the metrics callback when metrics_url is configured."""
  import json
  import os
  from pathlib import Path
  from unittest.mock import MagicMock, patch

  import pytest
  import yaml


  def _write_minimal_config(tmp_path: Path, settings: dict | None = None) -> Path:
      config = {
          "settings": settings or {},
          "watchers": [],
      }
      path = tmp_path / "watchers.yml"
      path.write_text(yaml.dump(config))
      return path


  def test_watch_wires_metrics_callback_when_url_set(tmp_path, monkeypatch):
      config_path = _write_minimal_config(
          tmp_path, settings={"metrics_url": "http://localhost:9091"}
      )

      wired = []
      monkeypatch.setattr("core.events.set_emit_callback", lambda fn: wired.append(fn))

      # Abort after first iteration (avoid infinite loop)
      monkeypatch.setattr("watcher.check_waiting_issues", MagicMock())
      monkeypatch.setattr("watcher._process_resume_queue", MagicMock(return_value=[]))
      monkeypatch.setattr("watcher._setup_logging", MagicMock(return_value=MagicMock()))
      monkeypatch.setattr("watcher.bind_run_id", MagicMock())
      call_count = {"n": 0}

      def fake_sleep(_):
          call_count["n"] += 1
          if call_count["n"] >= 1:
              raise KeyboardInterrupt

      monkeypatch.setattr("time.sleep", fake_sleep)

      # Also mock the poll function that reads GitHub
      monkeypatch.setattr("watcher._poll_watchers", MagicMock(return_value=[]))

      try:
          from watcher import watch
          watch(config_path)
      except KeyboardInterrupt:
          pass

      assert len(wired) == 1, "set_emit_callback should be called once"
      assert callable(wired[0])


  def test_watch_skips_metrics_wiring_when_url_absent(tmp_path, monkeypatch):
      config_path = _write_minimal_config(tmp_path, settings={})  # no metrics_url

      wired = []
      monkeypatch.setattr("core.events.set_emit_callback", lambda fn: wired.append(fn))

      monkeypatch.setattr("watcher.check_waiting_issues", MagicMock())
      monkeypatch.setattr("watcher._process_resume_queue", MagicMock(return_value=[]))
      monkeypatch.setattr("watcher._setup_logging", MagicMock(return_value=MagicMock()))
      monkeypatch.setattr("watcher.bind_run_id", MagicMock())
      monkeypatch.setattr("watcher._poll_watchers", MagicMock(return_value=[]))

      def fake_sleep(_):
          raise KeyboardInterrupt

      monkeypatch.setattr("time.sleep", fake_sleep)

      try:
          from watcher import watch
          watch(config_path)
      except KeyboardInterrupt:
          pass

      assert len(wired) == 0, "set_emit_callback should NOT be called without metrics_url"
  ```

- [ ] **Step 2: Run to see failure**

  ```bash
  pytest tests/test_watcher_metrics_wiring.py -v 2>&1 | head -20
  ```
  Expected: tests fail (callback not wired yet) OR attribute errors if `_poll_watchers` doesn't exist. If `_poll_watchers` doesn't exist, adjust monkeypatching to match the actual loop structure by reading `watch()` lines 1291–1400 and patching the correct internal function.

---

### Task 7: Wire Metrics Callback in `watcher.py`

**Files:**
- Modify: `watcher.py` — inside `watch()` after `global_settings` is fully assembled

- [ ] **Step 1: Find the insertion point**

  In `watcher.py`, locate the `watch()` function (line ~1291). Find the block after `global_settings` is assembled (the `{**pr_defaults, **global_settings}` merge, around line 1340). The metrics wiring must go **after** this merge so `global_settings.get("metrics_url")` sees the final value.

- [ ] **Step 2: Add the wiring**

  Immediately after the comment `# Build list of tracker repos for checking waiting issues` (around line 1342), add:

  ```python
      # Wire Prometheus metrics sink if configured
      _metrics_url = global_settings.get("metrics_url")
      if _metrics_url:
          from core.events import set_emit_callback
          from core.metrics_sink import build_callback
          set_emit_callback(build_callback(_metrics_url))
          _log.info("Metrics sink wired to %s", _metrics_url)
  ```

- [ ] **Step 3: Run wiring tests**

  ```bash
  pytest tests/test_watcher_metrics_wiring.py -v
  ```
  Expected: `2 passed`. If test fails due to `_poll_watchers` not existing, adjust the monkeypatching in the test to match the actual watcher internal loop structure, then re-run.

- [ ] **Step 4: Run full suite to catch regressions**

  ```bash
  pytest --tb=short -q 2>&1 | tail -10
  ```
  Expected: all previously passing tests still pass.

- [ ] **Step 5: Commit**

  ```bash
  git add watcher.py tests/test_watcher_metrics_wiring.py
  git commit -m "feat: wire metrics callback in watch() when metrics_url configured"
  ```

---

### Task 8: Final Verification

**Files:** none

- [ ] **Step 1: Run full suite**

  ```bash
  pytest --tb=short -q
  ```
  Expected: all tests pass, 0 failures.

- [ ] **Step 2: Smoke-test the server manually**

  ```bash
  python metrics_server.py &
  SERVER_PID=$!
  sleep 0.5
  curl -s -X POST http://localhost:9091/event \
    -H 'Content-Type: application/json' \
    -d '{"event_type":"circuit_breaker","name":"backend","state":"open","failure_count":1,"timestamp":"2026-01-01T00:00:00Z"}'
  curl -s http://localhost:9091/metrics | grep aisw_
  kill $SERVER_PID
  ```
  Expected output contains:
  ```
  aisw_circuit_breaker_events_total{name="backend",state="open"} 1.0
  ```

- [ ] **Step 3: Commit and push**

  ```bash
  git push origin t11-a-event-bus-prometheus
  ```
