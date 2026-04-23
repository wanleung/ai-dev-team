"""Test configuration for ai-software-house tests.

Provides shared fixtures used across the test suite.
"""
from __future__ import annotations

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
