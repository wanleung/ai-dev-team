"""Tests for LLMPoolManager — per-backend connection pools."""
import threading
import time

import pytest

from llm_pool import LLMPoolManager


def test_default_limits():
    pool = LLMPoolManager()
    # Ollama default is 1 (safe for local), others default to 5
    assert pool.limit_for("ollama") == 1
    assert pool.limit_for("openai") == 5
    assert pool.limit_for("anything-else") == 5


def test_custom_limits_from_config():
    pool = LLMPoolManager({"ollama": 2, "openai": 8, "opencode-zen": 3})
    assert pool.limit_for("ollama") == 2
    assert pool.limit_for("openai") == 8
    assert pool.limit_for("opencode-zen") == 3
    # Unlisted backends still get the default
    assert pool.limit_for("nvidia_nim") == 5


def test_semaphore_blocks_above_limit():
    pool = LLMPoolManager({"ollama": 1})
    acquired = []
    blocked_started = threading.Event()
    blocked_acquired = threading.Event()

    def worker():
        blocked_started.set()
        with pool.acquire("ollama"):
            blocked_acquired.set()
            acquired.append("worker")

    with pool.acquire("ollama"):
        t = threading.Thread(target=worker)
        t.start()
        # Wait for the worker thread to start and try to acquire
        assert blocked_started.wait(1.0)
        # Give it a moment to try (and block)
        time.sleep(0.1)
        # The worker should NOT have acquired yet
        assert not blocked_acquired.is_set()
        assert acquired == []
    # We released — worker should now acquire
    t.join(timeout=2.0)
    assert blocked_acquired.is_set()
    assert acquired == ["worker"]


def test_acquire_is_context_manager():
    pool = LLMPoolManager({"openai": 1})
    with pool.acquire("openai"):
        pass  # should release on exit


def test_unknown_backend_uses_default():
    pool = LLMPoolManager()
    # No exception, uses default limit
    with pool.acquire("brand-new-backend"):
        pass


def test_singleton_helper():
    """get_pool() / set_pool() provide a process-wide singleton for base_agent."""
    from llm_pool import get_pool, set_pool
    custom = LLMPoolManager({"ollama": 3})
    set_pool(custom)
    assert get_pool() is custom
    # Reset to None for other tests
    set_pool(None)


def test_base_agent_acquires_pool_on_call(monkeypatch):
    """BaseAgent.call should acquire from the global pool before delegating."""
    from contextlib import contextmanager as contextmanager_wrap
    from llm_pool import LLMPoolManager, set_pool
    from agents.base_agent import BaseAgent

    acquired_backends: list[str] = []

    class TrackingPool(LLMPoolManager):
        @contextmanager_wrap
        def acquire(self, backend):
            acquired_backends.append(backend)
            yield

    set_pool(TrackingPool())

    # Build an agent with a fake backend
    class FakeBackend:
        model = "fake-model"
        _client = None
        def call(self, messages):
            return "ok"
        def supports_tools(self):
            return False
        def _pre_call(self):
            pass

    agent = BaseAgent.__new__(BaseAgent)
    agent._llm = FakeBackend()
    agent._backend = "openai"
    agent._history = []
    agent.system_prompt = ""
    agent._inter_call_delay = 0
    agent._api_model = "fake-model"
    agent.model = "fake-model"

    reply = agent.call("hello")
    assert reply == "ok"
    assert acquired_backends == ["openai"]

    set_pool(None)


def test_zero_limit_falls_back_to_default(caplog):
    """Limit=0 would deadlock — should be coerced to default with a warning."""
    import logging
    from llm_pool import LLMPoolManager

    with caplog.at_level(logging.WARNING):
        pool = LLMPoolManager({"ollama": 0, "openai": 0})

    assert pool.limit_for("ollama") == 1   # _DEFAULT_LIMITS["ollama"]
    assert pool.limit_for("openai") == 5   # _FALLBACK_LIMIT
    assert any("ollama" in r.message for r in caplog.records)


def test_negative_limit_falls_back_to_default(caplog):
    """Negative limit would crash Semaphore — should be coerced."""
    import logging
    from llm_pool import LLMPoolManager

    with caplog.at_level(logging.WARNING):
        pool = LLMPoolManager({"openai": -3})

    assert pool.limit_for("openai") == 5


def test_non_int_limit_falls_back_to_default(caplog):
    """Garbage value should be coerced, not raise."""
    import logging
    from llm_pool import LLMPoolManager

    with caplog.at_level(logging.WARNING):
        pool = LLMPoolManager({"openai": "many"})

    assert pool.limit_for("openai") == 5
