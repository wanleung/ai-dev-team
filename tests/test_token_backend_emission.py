"""Tests that LLM backends emit token usage to the global TokenLedger."""
from __future__ import annotations
from unittest.mock import MagicMock, patch
import pytest
from agents.token_ledger import TokenLedger, set_ledger, get_ledger, current_stage


@pytest.fixture(autouse=True)
def _reset_circuit_registry():
    """Reset the global circuit breaker registry before each test and restore after.

    Prior tests (notably test_backend_circuit_breaker.py) leave the global
    _REGISTRY with threshold=1. Orchestrator integration tests then trip the
    backend:gpt-4.1 circuit via TierReviewerAgent failures. This fixture
    ensures a clean high-threshold registry for each token backend test
    and restores the original after to avoid outgoing contamination.
    """
    import core.circuit_breaker_registry as _cb_mod
    from core.circuit_breaker_registry import init_registry
    from config_schema import CircuitBreakerConfig, CircuitBreakerScopeConfig

    # Save original registry
    with _cb_mod._REGISTRY_LOCK:
        _original = _cb_mod._REGISTRY

    # Install a safe high-threshold registry
    safe_scope = CircuitBreakerScopeConfig(threshold=10_000, recovery_timeout_s=60)
    init_registry(
        CircuitBreakerConfig(
            enabled=True,
            per_backend=safe_scope,
            per_agent=safe_scope,
            per_repo=safe_scope,
        )
    )

    yield  # run the test

    # Restore original registry
    with _cb_mod._REGISTRY_LOCK:
        _cb_mod._REGISTRY = _original


def _make_response(prompt_tokens: int, completion_tokens: int, content: str) -> MagicMock:
    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=content), finish_reason="stop")]
    resp.usage = usage
    return resp


def test_non_stream_call_emits_usage():
    from agents.backends.base import OpenAICompatibleBackend
    pricing = {"gpt-4.1": [2.00, 8.00], "default": [2.00, 8.00]}
    ledger = TokenLedger(pricing=pricing)
    ledger.start_run("r1", "P", "repo")
    set_ledger(ledger)

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _make_response(100, 50, "hello")
    backend = OpenAICompatibleBackend(model="gpt-4.1", client=mock_client, stream=False)

    token = current_stage.set("pm")
    try:
        result = backend.call([{"role": "user", "content": "hi"}], run_id="r1")
    finally:
        current_stage.reset(token)

    summary = ledger.summary("r1")
    assert summary["total_prompt_tokens"] == 100
    assert summary["total_completion_tokens"] == 50
    assert summary["total_cost_usd"] > 0


def test_stream_call_emits_estimated_usage():
    from agents.backends.base import OpenAICompatibleBackend
    pricing = {"gpt-4.1": [2.00, 8.00], "default": [2.00, 8.00]}
    ledger = TokenLedger(pricing=pricing)
    ledger.start_run("r2", "P", "repo")
    set_ledger(ledger)

    chunk = MagicMock(choices=[MagicMock(delta=MagicMock(content="hello world"))])
    empty_chunk = MagicMock(choices=[])
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = iter([chunk, empty_chunk])
    backend = OpenAICompatibleBackend(model="gpt-4.1", client=mock_client, stream=True)

    token = current_stage.set("architect")
    try:
        backend.call([{"role": "user", "content": "what is 2+2?"}], run_id="r2")
    finally:
        current_stage.reset(token)

    summary = ledger.summary("r2")
    assert summary["total_prompt_tokens"] > 0
    assert summary["total_completion_tokens"] > 0


def test_no_emission_without_run_id():
    """call() without run_id should not crash and should not add records."""
    from agents.backends.base import OpenAICompatibleBackend
    pricing = {"default": [2.00, 8.00]}
    ledger = TokenLedger(pricing=pricing)
    set_ledger(ledger)

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _make_response(10, 5, "hi")
    backend = OpenAICompatibleBackend(model="gpt-4.1", client=mock_client, stream=False)
    # no run_id passed — should not raise
    backend.call([{"role": "user", "content": "hi"}])
    # ledger has no runs registered, so no events
    assert ledger._events == {}
