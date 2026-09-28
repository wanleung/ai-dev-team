"""Test configuration for ai-software-house tests.

Provides shared fixtures used across the test suite.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_memory_store(tmp_path: Path, monkeypatch):
    """Redirect MemoryStore to a per-test temp DB — unless the caller already
    isolated it themselves under this test's own tmp_path.

    Two things must both be true, and they pull in opposite directions:

    1. Code that resolves a path some other way (Orchestrator.__init__
       building `workspace_dir / "memory.db"`, workspace_dir defaulting to
       the real ./workspace unless a test overrides it) must never be
       allowed to touch the real project's database — that's real
       production data, thousands of rows, and a test must not read or
       write it. This is the leak an earlier version of this fixture
       correctly prevented by redirecting unconditionally.

    2. A test that deliberately builds a specific pre-existing file under
       its own tmp_path — to verify schema migration against a legacy
       shape, for example — must have that exact file opened, unmodified.
       Redirecting unconditionally (the earlier version's bug) silently
       defeated every such test: each one thought it was opening its own
       hand-crafted legacy file, but every call was rewritten to the same
       fresh, already-current-schema path, so the migration path it meant
       to exercise never actually ran and the test passed for the wrong
       reason.

    The distinguishing signal: is the requested path already inside this
    test's tmp_path? If yes, it's already isolated — leave it alone. If
    no (including no path given at all), redirect to tmp_path/memory.db.
    """
    try:
        import memory_store as _ms

        _original_init = _ms.MemoryStore.__init__
        tmp_resolved = tmp_path.resolve()

        def _patched_init(self: "_ms.MemoryStore", db_path: object = None) -> None:
            if db_path is not None:
                resolved = Path(db_path).resolve()
                if resolved == tmp_resolved or resolved.is_relative_to(tmp_resolved):
                    _original_init(self, db_path)
                    return
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
