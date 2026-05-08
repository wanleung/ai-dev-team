"""Tests for circuit breaker integration in OpenAICompatibleBackend.call()."""
from __future__ import annotations
from unittest.mock import MagicMock
import pytest

from config_schema import CircuitBreakerConfig, CircuitBreakerScopeConfig
from core.circuit_breaker import CircuitOpenError
from core.circuit_breaker_registry import init_registry, get_registry


def _init_cb(threshold=2):
    scope = CircuitBreakerScopeConfig(threshold=threshold, recovery_timeout_s=3600)
    cfg = CircuitBreakerConfig(enabled=True, per_backend=scope,
                               per_agent=scope, per_repo=scope)
    init_registry(cfg)


def test_backend_records_failure_on_llm_error():
    _init_cb(threshold=5)
    reg = get_registry()
    cb = reg.get_or_create("backend", "gpt-4.1")
    assert cb._failure_count == 0

    # Simulate a backend call that raises (via the circuit breaker wrapping)
    with pytest.raises(RuntimeError):
        cb.call(lambda: (_ for _ in ()).throw(RuntimeError("api error")))
    assert cb._failure_count == 1


def test_backend_opens_after_threshold():
    _init_cb(threshold=2)
    reg = get_registry()
    cb = reg.get_or_create("backend", "test-model-open")

    for _ in range(2):
        try:
            cb.call(lambda: (_ for _ in ()).throw(ConnectionError("timeout")))
        except ConnectionError:
            pass
    assert cb.state == "open"

    with pytest.raises(CircuitOpenError):
        cb.call(lambda: "should not run")


def test_backend_call_succeeds_records_success():
    _init_cb(threshold=5)
    reg = get_registry()
    cb = reg.get_or_create("backend", "success-model")
    cb.record_failure()
    assert cb._failure_count == 1

    result = cb.call(lambda: "ok")
    assert result == "ok"
    assert cb._failure_count == 0


def test_open_circuit_skips_api_call():
    """When backend circuit is open, call() raises CircuitOpenError without hitting the API."""
    from agents.backends.base import OpenAICompatibleBackend

    _init_cb(threshold=1)
    reg = get_registry()
    cb = reg.get_or_create("backend", "gpt-circuit-test")
    cb.record_failure()
    assert cb.state == "open"

    backend = OpenAICompatibleBackend.__new__(OpenAICompatibleBackend)
    backend.model = "gpt-circuit-test"
    backend._stream = False
    backend._inter_call_delay = 0
    backend._max_retries = 1
    backend._retry_delay = 0.0
    mock_client = MagicMock()
    backend._client = mock_client

    with pytest.raises(CircuitOpenError):
        backend.call([{"role": "user", "content": "hello"}])

    mock_client.chat.completions.create.assert_not_called()


# ---------------------------------------------------------------------------
# New tests: _stream_call and call_with_tools also trip the breaker
# ---------------------------------------------------------------------------

def _make_backend(model: str):
    """Create a bare OpenAICompatibleBackend instance without calling __init__."""
    from agents.backends.base import OpenAICompatibleBackend

    backend = OpenAICompatibleBackend.__new__(OpenAICompatibleBackend)
    backend.model = model
    backend._stream = False
    backend._inter_call_delay = 0
    backend._max_retries = 1
    backend._retry_delay = 0.0
    backend._client = MagicMock()
    return backend


def test_stream_call_trips_circuit_after_threshold():
    """_stream_call should trip the circuit breaker after threshold failures."""
    from unittest.mock import patch
    from agents.backends.base import _CircuitOpenError
    from core.circuit_breaker_registry import CircuitBreakerRegistry

    model = "stream-cb-test-model"
    backend = _make_backend(model)
    backend._client.chat.completions.create.side_effect = ConnectionError("timeout")

    scope = CircuitBreakerScopeConfig(threshold=2, recovery_timeout_s=3600)
    cfg = CircuitBreakerConfig(enabled=True, per_backend=scope,
                               per_agent=scope, per_repo=scope)
    registry = CircuitBreakerRegistry(cfg)

    with patch("agents.backends.base._get_cb_registry", return_value=registry):
        # First two calls should raise the underlying ConnectionError
        for _ in range(2):
            with pytest.raises(ConnectionError):
                backend._stream_call([{"role": "user", "content": "hi"}])

        # Third call — circuit is open, should raise CircuitOpenError
        with pytest.raises(_CircuitOpenError):
            backend._stream_call([{"role": "user", "content": "hi"}])

        # Verify no further API calls are made when circuit is open
        call_count_before = backend._client.chat.completions.create.call_count
        with pytest.raises(_CircuitOpenError):
            backend._stream_call([{"role": "user", "content": "open circuit"}])
        assert backend._client.chat.completions.create.call_count == call_count_before


def test_call_with_tools_trips_circuit_after_threshold():
    """call_with_tools should trip the circuit breaker after threshold failures."""
    from unittest.mock import patch
    from agents.backends.base import _CircuitOpenError
    from core.circuit_breaker_registry import CircuitBreakerRegistry

    model = "tools-cb-test-model"
    backend = _make_backend(model)
    backend._client.chat.completions.create.side_effect = ConnectionError("timeout")

    tools = MagicMock()
    tools.schemas = []

    scope = CircuitBreakerScopeConfig(threshold=2, recovery_timeout_s=3600)
    cfg = CircuitBreakerConfig(enabled=True, per_backend=scope,
                               per_agent=scope, per_repo=scope)
    registry = CircuitBreakerRegistry(cfg)

    with patch("agents.backends.base._get_cb_registry", return_value=registry):
        # First two calls should raise the underlying ConnectionError
        for _ in range(2):
            with pytest.raises(ConnectionError):
                backend.call_with_tools([{"role": "user", "content": "hi"}], tools)

        # Third call — circuit is open, should raise CircuitOpenError
        with pytest.raises(_CircuitOpenError):
            backend.call_with_tools([{"role": "user", "content": "hi"}], tools)

        # Verify no further API calls are made when circuit is open
        call_count_before = backend._client.chat.completions.create.call_count
        with pytest.raises(_CircuitOpenError):
            backend.call_with_tools([{"role": "user", "content": "open circuit"}], tools)
        assert backend._client.chat.completions.create.call_count == call_count_before
