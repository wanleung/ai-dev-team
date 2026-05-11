"""Test configuration for ai-software-house tests.

Provides shared fixtures used across the test suite.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_memory_store(tmp_path: Path, monkeypatch):
    """Redirect MemoryStore to a per-test temp DB to prevent state leakage."""
    try:
        import memory_store as _ms

        _original_init = _ms.MemoryStore.__init__

        def _patched_init(self: "_ms.MemoryStore", db_path: object = None) -> None:
            _original_init(self, str(tmp_path / "memory.db"))

        monkeypatch.setattr(_ms.MemoryStore, "__init__", _patched_init)
    except ImportError:
        pass  # memory_store not available in all test environments


@pytest.fixture(autouse=True)
def _clear_structlog_context():
    """Clear structlog contextvars after each test to prevent run_id leaking between tests."""
    yield
    try:
        import structlog
        structlog.contextvars.clear_contextvars()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _restore_root_handlers():
    """Restore logging.root handlers and level after each test to prevent accumulation."""
    original_handlers = logging.root.handlers[:]
    original_level = logging.root.level
    yield
    for h in logging.root.handlers:
        if h not in original_handlers:
            try:
                h.close()
            except Exception:
                pass
    logging.root.handlers = original_handlers
    logging.root.setLevel(original_level)


@pytest.fixture(autouse=True)
def _restore_global_ledger():
    """Ensure each test starts with a fresh TokenLedger and the global is restored after."""
    from agents.token_ledger import get_ledger, set_ledger, TokenLedger
    original = get_ledger()
    set_ledger(TokenLedger())
    yield
    set_ledger(original)
