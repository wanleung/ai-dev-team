# core/metrics_sink.py
"""Prometheus metrics sink for the ai-software-house event bus.

Usage::

    from core.events import set_emit_callback
    from core.metrics_sink import build_callback

    set_emit_callback(build_callback("http://localhost:9091"))
"""

import dataclasses
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

    Args:
        metrics_url: Base URL of the metrics receiver (e.g. ``http://localhost:9091``).
            A trailing slash is stripped automatically.

    Returns:
        A callable that accepts any :class:`~core.events.AnyEvent` and POSTs it
        as JSON to ``<metrics_url>/event``.
    """
    endpoint = metrics_url.rstrip("/") + "/event"

    def _callback(event: AnyEvent) -> None:
        try:
            body = json.dumps(dataclasses.asdict(event)).encode()
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
