"""Structured logging setup using structlog.

Usage:
    from logging_setup import configure_logging, bind_run_id
    configure_logging(log_level="INFO", log_file=Path("logs/app.log"))
    bind_run_id("abc12345")   # all subsequent log calls include run_id=abc12345
"""
from __future__ import annotations

import logging
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

import structlog


def configure_logging(
    log_level: str = "INFO",
    log_file: Optional[Path] = None,
) -> None:
    """Configure stdlib logging to use structlog processors.

    Console output uses human-readable ConsoleRenderer.
    File output (if log_file given) uses JSONRenderer (one JSON object per line).

    This function is idempotent — calling it multiple times only adds handlers
    if they don't already exist. To reset, call logging.root.handlers.clear() first.
    """
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    structlog.configure(
        processors=shared_processors
        + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    root = logging.getLogger()
    level = getattr(logging, log_level.upper(), logging.INFO)
    root.setLevel(level)

    # Console handler — human-readable
    if not any(isinstance(h, logging.StreamHandler) and h.stream is sys.stderr
               for h in root.handlers):
        console_fmt = structlog.stdlib.ProcessorFormatter(
            processor=structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty()),
            foreign_pre_chain=shared_processors,
        )
        ch = logging.StreamHandler(sys.stderr)
        ch.setFormatter(console_fmt)
        root.addHandler(ch)

    # File handler — JSON lines
    if log_file:
        log_file = Path(log_file)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        already_has_file_handler = any(
            isinstance(h, logging.FileHandler) and h.baseFilename == str(log_file.resolve())
            for h in root.handlers
        )
        if not already_has_file_handler:
            json_fmt = structlog.stdlib.ProcessorFormatter(
                processor=structlog.processors.JSONRenderer(),
                foreign_pre_chain=shared_processors,
            )
            fh = logging.FileHandler(log_file, encoding="utf-8")
            fh.setFormatter(json_fmt)
            root.addHandler(fh)


def bind_run_id(run_id: str) -> None:
    """Bind run_id to all log calls in the current thread via structlog context vars."""
    structlog.contextvars.bind_contextvars(run_id=run_id)


def clear_run_id() -> None:
    """Remove run_id binding (call between test runs or pipeline resets)."""
    structlog.contextvars.unbind_contextvars("run_id")


class _RunFilter(logging.Filter):
    """Only pass log records emitted from the thread that created this handler."""

    def __init__(self) -> None:
        super().__init__()
        self._tid = threading.get_ident()

    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        return threading.get_ident() == self._tid


@contextmanager
def file_logging(log_file: "str | Path") -> "Generator[logging.FileHandler, None, None]":
    """Context manager: add a per-run JSON FileHandler for the duration of a with-block.

    Creates the handler directly (bypassing configure_logging's idempotency check)
    so concurrent callers with different log paths never interfere with each other.
    Removes and closes the handler on exit, even if an exception occurs.

    Usage:
        with file_logging(log_file):
            run_orchestrator(...)
    """
    log_file = Path(log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]
    json_fmt = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=shared_processors,
    )
    fh = logging.FileHandler(str(log_file), encoding="utf-8")
    fh.setFormatter(json_fmt)
    fh.addFilter(_RunFilter())   # ← only pass records from the creating thread
    logging.getLogger().addHandler(fh)
    try:
        yield fh
    finally:
        logging.getLogger().removeHandler(fh)
        fh.close()
