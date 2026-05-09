"""Tests for DegradationPolicy."""
from __future__ import annotations
from config_schema import DegradationConfig, LLMConfig
from core.degradation import DegradationContext, DegradationPolicy, DegradationResult
from core.events import DegradationEvent, set_emit_callback, reset_emit_callback


def _policy(reduce=True, fallback=True, skip=True, optional=None, enabled=True):
    cfg = DegradationConfig(
        enabled=enabled,
        reduce_engineers=reduce,
        fallback_model=fallback,
        skip_optional_stages=skip,
        optional_stages=optional or ["deploy_test", "documentation"],
    )
    llm = LLMConfig(model="gpt-4.1", fallback=["gpt-4.1-mini", "gpt-4o-mini"])
    return DegradationPolicy(cfg, llm)


def _ctx(reason="circuit open: gpt-4.1", engineers=2, model="gpt-4.1"):
    return DegradationContext(
        reason=reason,
        original_num_engineers=engineers,
        original_model=model,
    )


def test_disabled_policy_returns_unchanged():
    p = _policy(enabled=False)
    r = p.apply(num_engineers=3, model="gpt-4.1",
                skippable_stages=["deploy_test"], context=_ctx())
    assert r.num_engineers == 3
    assert r.model == "gpt-4.1"
    assert r.skipped_stages == []
    assert r.actions_taken == []


def test_reduce_engineers():
    p = _policy(reduce=True, fallback=False, skip=False)
    r = p.apply(num_engineers=3, model="gpt-4.1",
                skippable_stages=[], context=_ctx())
    assert r.num_engineers == 2
    assert "reduce_engineers" in " ".join(r.actions_taken)


def test_reduce_engineers_minimum_one():
    p = _policy(reduce=True, fallback=False, skip=False)
    r = p.apply(num_engineers=1, model="gpt-4.1",
                skippable_stages=[], context=_ctx())
    assert r.num_engineers == 1
    assert r.actions_taken == []  # floor reached — no action logged


def test_fallback_model_substitutes_next_in_chain():
    p = _policy(reduce=False, fallback=True, skip=False)
    r = p.apply(num_engineers=2, model="gpt-4.1",
                skippable_stages=[], context=_ctx(model="gpt-4.1"))
    assert r.model == "gpt-4.1-mini"
    assert "fallback_model" in " ".join(r.actions_taken)


def test_fallback_model_no_fallback_list():
    cfg = DegradationConfig(enabled=True, fallback_model=True,
                            reduce_engineers=False, skip_optional_stages=False)
    llm = LLMConfig(model="gpt-4.1", fallback=None)
    p = DegradationPolicy(cfg, llm)
    r = p.apply(num_engineers=2, model="gpt-4.1",
                skippable_stages=[], context=_ctx())
    assert r.model == "gpt-4.1"  # unchanged — no fallback available
    assert r.actions_taken == []  # no action logged


def test_fallback_model_advances_past_current_mid_chain():
    """Current model is mid-chain; must advance forward, not regress."""
    cfg = DegradationConfig(
        enabled=True, fallback_model=True,
        reduce_engineers=False, skip_optional_stages=False,
    )
    llm = LLMConfig(model="gpt-4.1",
                    fallback=["gpt-4.1", "gpt-4.1-mini", "gpt-4o-mini"])
    p = DegradationPolicy(cfg, llm)
    r = p.apply(num_engineers=2, model="gpt-4.1-mini",
                skippable_stages=[], context=_ctx(model="gpt-4.1-mini"))
    assert r.model == "gpt-4o-mini"  # next after gpt-4.1-mini, not gpt-4.1
    assert "fallback_model" in " ".join(r.actions_taken)


def test_fallback_model_already_at_end_of_chain():
    """When current model is the last in chain, leave model unchanged."""
    cfg = DegradationConfig(
        enabled=True, fallback_model=True,
        reduce_engineers=False, skip_optional_stages=False,
    )
    llm = LLMConfig(model="gpt-4.1", fallback=["gpt-4.1-mini", "gpt-4o-mini"])
    p = DegradationPolicy(cfg, llm)
    r = p.apply(num_engineers=2, model="gpt-4o-mini",
                skippable_stages=[], context=_ctx(model="gpt-4o-mini"))
    assert r.model == "gpt-4o-mini"  # unchanged — already at end
    assert r.actions_taken == []  # no action logged


def test_skip_optional_stages():
    p = _policy(reduce=False, fallback=False, skip=True,
                optional=["deploy_test", "documentation"])
    r = p.apply(num_engineers=2, model="gpt-4.1",
                skippable_stages=["deploy_test", "documentation"],
                context=_ctx())
    assert "deploy_test" in r.skipped_stages
    assert "documentation" in r.skipped_stages
    assert "skip_optional_stages" in " ".join(r.actions_taken)


def test_skip_only_intersects_with_skippable():
    p = _policy(reduce=False, fallback=False, skip=True, optional=["deploy_test"])
    r = p.apply(num_engineers=2, model="gpt-4.1",
                skippable_stages=["documentation"],  # deploy_test not in skippable
                context=_ctx())
    assert r.skipped_stages == []


def test_all_three_strategies_combined():
    p = _policy(reduce=True, fallback=True, skip=True)
    r = p.apply(num_engineers=2, model="gpt-4.1",
                skippable_stages=["deploy_test"],
                context=_ctx())
    assert r.num_engineers == 1
    assert r.model == "gpt-4.1-mini"
    assert "deploy_test" in r.skipped_stages
    assert len(r.actions_taken) == 3


def test_apply_raises_on_zero_engineers():
    """Verify apply() raises ValueError when num_engineers=0."""
    p = _policy()
    try:
        p.apply(num_engineers=0, model="gpt-4.1",
                skippable_stages=[], context=_ctx())
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "num_engineers must be >= 1" in str(e)


def test_skip_stages_no_op_when_skippable_empty():
    """Verify no action logged when skippable_stages=[] even if skip_optional_stages=True."""
    p = _policy(reduce=False, fallback=False, skip=True, optional=["deploy_test"])
    r = p.apply(num_engineers=2, model="gpt-4.1",
                skippable_stages=[],  # empty, so nothing can be skipped
                context=_ctx())
    assert r.skipped_stages == []
    assert r.actions_taken == []


# ── DegradationSnapshot / restore tests (T2-C Task 4) ────────────────────

def test_restore_returns_snapshot_values():
    from core.degradation import DegradationSnapshot
    p = _policy()
    snap = DegradationSnapshot(num_engineers=4, model="gpt-4.1")
    result = p.restore(snap)
    assert result.num_engineers == 4
    assert result.model == "gpt-4.1"
    assert result.skipped_stages == []


def test_restore_includes_auto_recovery_action():
    from core.degradation import DegradationSnapshot
    p = _policy()
    snap = DegradationSnapshot(num_engineers=2, model="gpt-4-mini")
    result = p.restore(snap)
    assert any("auto_recovery" in a for a in result.actions_taken)


def test_degradation_emits_event_when_actions_taken():
    events = []
    set_emit_callback(events.append)
    try:
        cfg = DegradationConfig(enabled=True, reduce_engineers=True, fallback_model=False,
                                skip_optional_stages=False, optional_stages=[])
        policy = DegradationPolicy(cfg, LLMConfig(model="gpt-4o"))
        ctx = DegradationContext(reason="circuit_open", original_num_engineers=2,
                                 original_model="gpt-4o")
        policy.apply(num_engineers=2, model="gpt-4o", skippable_stages=[], context=ctx)
        assert any(isinstance(e, DegradationEvent) and e.trigger == "circuit_open"
                   for e in events)
    finally:
        reset_emit_callback()


def test_degradation_no_event_when_disabled():
    events = []
    set_emit_callback(events.append)
    try:
        cfg = DegradationConfig(enabled=False, reduce_engineers=True, fallback_model=False,
                                skip_optional_stages=False, optional_stages=[])
        policy = DegradationPolicy(cfg, LLMConfig(model="gpt-4o"))
        ctx = DegradationContext(reason="test", original_num_engineers=2, original_model="gpt-4o")
        policy.apply(num_engineers=2, model="gpt-4o", skippable_stages=[], context=ctx)
        assert not any(isinstance(e, DegradationEvent) for e in events)
    finally:
        reset_emit_callback()
