"""Tests that LLM backends emit token usage to the global TokenLedger."""
from __future__ import annotations
from unittest.mock import MagicMock, patch
import pytest
from agents.token_ledger import TokenLedger, set_ledger, get_ledger, current_stage


@pytest.fixture(autouse=True)
def _reset_circuit_registry():
    """Reset the global circuit breaker registry before each test.

    Orchestrator integration tests may leave the ``backend:gpt-4.1`` circuit
    breaker OPEN (TierReviewerAgent fails with a mock LLM, and a prior test
    sets threshold=1), causing ``CircuitOpenError`` in these tests.  Reinitialising
    the registry with a very high threshold ensures the circuit never trips.
    """
    from core.circuit_breaker_registry import init_registry
    from config_schema import CircuitBreakerConfig, CircuitBreakerScopeConfig

    safe_scope = CircuitBreakerScopeConfig(threshold=10_000, recovery_timeout_s=0)
    init_registry(
        CircuitBreakerConfig(
            enabled=True,
            per_backend=safe_scope,
            per_agent=safe_scope,
            per_repo=safe_scope,
        )
    )


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
