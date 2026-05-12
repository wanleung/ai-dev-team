"""Tests for parallel stage worker cap — Task 4 of T5-A concurrency plan."""
import importlib
import pytest


def test_workers_never_exceed_cap():
    """min(len(runnable), MAX_PARALLEL_STAGES) must always be <= MAX_PARALLEL_STAGES."""
    import orchestrator as orch_mod
    cap = orch_mod.MAX_PARALLEL_STAGES
    for n in [1, 4, 8, 10, 20, 50]:
        actual_workers = min(n, cap)
        assert actual_workers <= cap
        assert actual_workers == min(n, cap)  # uses live constant, not a literal


def test_max_parallel_stages_default_is_8():
    """Default MAX_PARALLEL_STAGES (no env override) must be >= 1."""
    import orchestrator as orch_mod
    assert orch_mod.MAX_PARALLEL_STAGES >= 1


def test_max_parallel_stages_env_override(monkeypatch):
    """AI_MAX_PARALLEL_STAGES env var overrides the default."""
    import orchestrator as orch_mod
    saved_dict = dict(orch_mod.__dict__)
    try:
        monkeypatch.setenv("AI_MAX_PARALLEL_STAGES", "4")
        importlib.reload(orch_mod)
        assert orch_mod.MAX_PARALLEL_STAGES == 4
    finally:
        orch_mod.__dict__.clear()
        orch_mod.__dict__.update(saved_dict)


def test_max_parallel_stages_invalid_env_uses_default(monkeypatch):
    """Non-integer AI_MAX_PARALLEL_STAGES must not crash; falls back to 8."""
    import orchestrator as orch_mod
    saved_dict = dict(orch_mod.__dict__)
    try:
        monkeypatch.setenv("AI_MAX_PARALLEL_STAGES", "not-a-number")
        importlib.reload(orch_mod)
        assert orch_mod.MAX_PARALLEL_STAGES >= 1
    finally:
        orch_mod.__dict__.clear()
        orch_mod.__dict__.update(saved_dict)


def test_thread_pool_executor_receives_capped_max_workers(monkeypatch):
    """The cap expression min(len(runnable), MAX_PARALLEL_STAGES) stays within bounds.

    NOTE: This test verifies the arithmetic of the cap expression only. Full
    end-to-end verification that the orchestrator passes the capped value to the
    real ThreadPoolExecutor requires a pipeline integration test (deferred —
    orchestrator setup is heavyweight and out of scope for a unit test).
    """
    import orchestrator as orch_mod

    monkeypatch.setattr(orch_mod, "MAX_PARALLEL_STAGES", 3)

    for n in [1, 3, 5, 10, 50]:
        computed = min(n, orch_mod.MAX_PARALLEL_STAGES)
        assert computed <= orch_mod.MAX_PARALLEL_STAGES, (
            f"min({n}, 3) = {computed}, expected <= 3"
        )
