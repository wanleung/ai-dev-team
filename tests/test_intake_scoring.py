import pytest
from intake_scoring import ScoreParser

SYNTHESIS_TWO_ITEMS = """
ITEM 1: PUBLISH
SCORES: relevance=8 news_value=9 audience_fit=7 urgency=6 originality=5
NOTES: Strong tech angle.

ITEM 2: SKIP
SCORES: relevance=3 news_value=4 audience_fit=5 urgency=2 originality=3
NOTES: Duplicate story.
"""

SYNTHESIS_MISSING_SCORES = """
ITEM 1: PUBLISH
NOTES: No scores line here.

ITEM 2: SKIP
NOTES: Also no scores.
"""

SYNTHESIS_PARTIAL_SCORES = """
ITEM 1: PUBLISH
SCORES: relevance=7 news_value=8
NOTES: Partial scores only.
"""

DIMENSIONS = ["relevance", "news_value", "audience_fit", "urgency", "originality"]
SCALE = 10


def test_parse_two_items_all_dimensions():
    parser = ScoreParser(dimensions=DIMENSIONS, score_scale=SCALE)
    result = parser.parse_batch(SYNTHESIS_TWO_ITEMS, item_count=2)
    assert len(result) == 2
    assert result[0] == {"relevance": 8, "news_value": 9, "audience_fit": 7, "urgency": 6, "originality": 5}
    assert result[1] == {"relevance": 3, "news_value": 4, "audience_fit": 5, "urgency": 2, "originality": 3}


def test_parse_missing_scores_returns_neutral():
    parser = ScoreParser(dimensions=DIMENSIONS, score_scale=SCALE)
    result = parser.parse_batch(SYNTHESIS_MISSING_SCORES, item_count=2)
    assert len(result) == 2
    # neutral = score_scale // 2 = 5
    for scores in result:
        for dim in DIMENSIONS:
            assert scores[dim] == 5


def test_parse_partial_scores_fills_missing_with_neutral():
    parser = ScoreParser(dimensions=DIMENSIONS, score_scale=SCALE)
    result = parser.parse_batch(SYNTHESIS_PARTIAL_SCORES, item_count=1)
    assert result[0]["relevance"] == 7
    assert result[0]["news_value"] == 8
    assert result[0]["audience_fit"] == 5   # neutral
    assert result[0]["urgency"] == 5        # neutral
    assert result[0]["originality"] == 5    # neutral


def test_parse_item_count_pads_missing_items():
    """If synthesis has fewer SCORES blocks than item_count, pad with neutral."""
    parser = ScoreParser(dimensions=DIMENSIONS, score_scale=SCALE)
    result = parser.parse_batch(SYNTHESIS_TWO_ITEMS, item_count=3)
    assert len(result) == 3
    for dim in DIMENSIONS:
        assert result[2][dim] == 5


SYNTHESIS_MIXED = """
ITEM 1: PUBLISH
NOTES: No scores here.

ITEM 2: SKIP
SCORES: relevance=3 news_value=4 audience_fit=5 urgency=2 originality=3
NOTES: Has scores.
"""


def test_parse_item_without_scores_does_not_steal_next_item_scores():
    """ITEM 1 missing SCORES must not consume ITEM 2's SCORES block."""
    parser = ScoreParser(dimensions=DIMENSIONS, score_scale=SCALE)
    result = parser.parse_batch(SYNTHESIS_MIXED, item_count=2)
    # ITEM 1 has no scores → all neutral
    for dim in DIMENSIONS:
        assert result[0][dim] == 5
    # ITEM 2 must retain its own scores
    assert result[1] == {"relevance": 3, "news_value": 4, "audience_fit": 5,
                         "urgency": 2, "originality": 3}


def test_parse_out_of_range_score_is_clamped():
    """Scores outside [0, score_scale] should be clamped, not silently accepted."""
    synthesis = """
ITEM 1: PUBLISH
SCORES: relevance=99 news_value=8
"""
    parser = ScoreParser(dimensions=DIMENSIONS, score_scale=SCALE)
    result = parser.parse_batch(synthesis, item_count=1)
    assert result[0]["relevance"] == 10   # clamped to scale max
    assert result[0]["news_value"] == 8


def test_parse_invalid_item_count_raises():
    """item_count < 1 must raise ValueError."""
    parser = ScoreParser(dimensions=DIMENSIONS, score_scale=SCALE)
    with pytest.raises(ValueError, match="item_count"):
        parser.parse_batch(SYNTHESIS_TWO_ITEMS, item_count=0)


SYNTHESIS_PROSE_ITEM_REF = """
ITEM 1: PUBLISH
NOTES: Compare with ITEM 2 which covers the same angle.
SCORES: relevance=8 news_value=7 audience_fit=6 urgency=5 originality=4

ITEM 2: SKIP
SCORES: relevance=3 news_value=4 audience_fit=5 urgency=2 originality=3
"""


def test_item_reference_in_notes_does_not_corrupt_scores():
    parser = ScoreParser(dimensions=DIMENSIONS, score_scale=SCALE)
    result = parser.parse_batch(SYNTHESIS_PROSE_ITEM_REF, item_count=2)
    assert result[0]["relevance"] == 8  # ITEM 1's own score
    assert result[1]["relevance"] == 3  # ITEM 2's own score


def test_parse_markdown_bold_scores():
    """MiMo thinking models often wrap output in **bold** markdown."""
    synthesis = (
        "**ITEM 1: PUBLISH**\n"
        "**SCORES:** relevance=8 news_value=9 audience_fit=7 urgency=6 originality=5\n"
        "**NOTES:** Strong tech angle.\n\n"
        "**ITEM 2: SKIP**\n"
        "**SCORES:** relevance=3 news_value=4 audience_fit=5 urgency=2 originality=3\n"
        "**NOTES:** Duplicate story.\n"
    )
    parser = ScoreParser(dimensions=DIMENSIONS, score_scale=SCALE)
    result = parser.parse_batch(synthesis, item_count=2)
    assert result[0] == {"relevance": 8, "news_value": 9, "audience_fit": 7, "urgency": 6, "originality": 5}
    assert result[1] == {"relevance": 3, "news_value": 4, "audience_fit": 5, "urgency": 2, "originality": 3}


def test_parse_markdown_header_scores():
    """Models may use ### markdown headers for ITEM lines."""
    synthesis = (
        "### ITEM 1: PUBLISH\n"
        "SCORES: relevance=8 news_value=9 audience_fit=7 urgency=6 originality=5\n"
        "NOTES: Strong tech angle.\n\n"
        "### ITEM 2: SKIP\n"
        "SCORES: relevance=3 news_value=4 audience_fit=5 urgency=2 originality=3\n"
        "NOTES: Duplicate story.\n"
    )
    parser = ScoreParser(dimensions=DIMENSIONS, score_scale=SCALE)
    result = parser.parse_batch(synthesis, item_count=2)
    assert result[0]["relevance"] == 8
    assert result[1]["relevance"] == 3


# ---------------------------------------------------------------------------
# ScoringEngine tests
# ---------------------------------------------------------------------------
from intake_scoring import ScoringEngine  # noqa: E402

FORMULA = "(relevance*1.5 + news_value*2.0 + audience_fit*1.0 + urgency*1.5 + originality*1.0) / 7.0 * 10"


def test_engine_correct_score():
    # FORMULA's natural output range is [0, 100]: it divides by the sum of
    # weights (7.0) to produce a weighted average, then ×10 to scale to
    # 0–100 when dimension scores are on a 0–10 scale.
    # score_scale=100 matches that natural range so no spurious clamping occurs.
    engine = ScoringEngine(formula=FORMULA, score_scale=100)
    scores = {"relevance": 8, "news_value": 9, "audience_fit": 7, "urgency": 6, "originality": 5}
    result = engine.score(scores)
    expected = (8*1.5 + 9*2.0 + 7*1.0 + 6*1.5 + 5*1.0) / 7.0 * 10
    assert abs(result - expected) < 0.001


def test_engine_clamps_above_scale():
    engine = ScoringEngine(formula="relevance * 100", score_scale=10)
    result = engine.score({"relevance": 10})
    assert result == 10.0


def test_engine_clamps_below_zero():
    engine = ScoringEngine(formula="relevance - 100", score_scale=10)
    result = engine.score({"relevance": 1})
    assert result == 0.0


def test_engine_rejects_builtins():
    engine = ScoringEngine(formula="__import__('os').system('echo pwned')", score_scale=10)
    with pytest.raises(ValueError, match="disallowed"):
        engine.score({"relevance": 5})


def test_engine_rejects_attribute_access():
    engine = ScoringEngine(formula="relevance.__class__", score_scale=10)
    with pytest.raises(ValueError, match="disallowed"):
        engine.score({"relevance": 5})


def test_engine_rejects_function_calls():
    engine = ScoringEngine(formula="abs(relevance)", score_scale=10)
    with pytest.raises(ValueError, match="disallowed"):
        engine.score({"relevance": 5})


# ---------------------------------------------------------------------------
# New tests: exception interface and clamping log
# ---------------------------------------------------------------------------
from intake_scoring import _safe_eval  # noqa: E402
import logging  # noqa: E402


def test_engine_syntax_error_raises_valueerror():
    """_safe_eval must raise ValueError (not SyntaxError) for malformed expressions."""
    with pytest.raises(ValueError, match="syntax"):
        _safe_eval("x +++", {"x": 1.0})


def test_engine_zero_division_raises_valueerror():
    """_safe_eval must raise ValueError (not ZeroDivisionError) on division by zero."""
    with pytest.raises(ValueError, match="division"):
        _safe_eval("x / 0", {"x": 1.0})


def test_engine_clamp_emits_warning(caplog):
    """ScoringEngine.score() must log a WARNING when the result is clamped."""
    engine = ScoringEngine(formula="relevance * 15", score_scale=100)
    with caplog.at_level(logging.WARNING, logger="intake_scoring"):
        result = engine.score({"relevance": 10})
    assert result == 100.0  # clamped from 150
    assert any("clamp" in record.message.lower() for record in caplog.records)


# ---------------------------------------------------------------------------
# VerdictRouter tests
# ---------------------------------------------------------------------------
from intake_scoring import VerdictRouter, ScoredVerdict  # noqa: E402

FULL_SYNTHESIS = """
ITEM 1: PUBLISH
SCORES: relevance=9 news_value=9 audience_fit=8 urgency=7 originality=8
NOTES: Lead with the regulatory angle.

ITEM 2: SKIP
SCORES: relevance=3 news_value=2 audience_fit=3 urgency=2 originality=2
NOTES: Too niche.

ITEM 3: PUBLISH
SCORES: relevance=7 news_value=8 audience_fit=7 urgency=6 originality=6
NOTES: Solid but unremarkable.
"""

ROUTER_FORMULA = "(relevance*1.5 + news_value*2.0 + audience_fit*1.0 + urgency*1.5 + originality*1.0) / 7.0"


def test_router_publish_above_threshold():
    router = VerdictRouter(
        dimensions=DIMENSIONS,
        score_scale=10,
        formula=ROUTER_FORMULA,
        threshold=6.0,
    )
    results = router.route(FULL_SYNTHESIS, item_count=3)
    assert len(results) == 3
    assert results[0].verdict == "PUBLISH"
    assert results[0].score > 6.0
    assert results[1].verdict == "SKIP"
    assert results[1].score < 6.0
    assert results[2].verdict == "PUBLISH"


def test_router_preserves_notes():
    router = VerdictRouter(dimensions=DIMENSIONS, score_scale=10, formula=ROUTER_FORMULA, threshold=6.0)
    results = router.route(FULL_SYNTHESIS, item_count=3)
    assert "regulatory" in results[0].notes
    assert "niche" in results[1].notes


def test_router_score_overrides_ai_verdict():
    """A PUBLISH in synthesis but low score → SKIP; SKIP in synthesis but high score → PUBLISH."""
    synthesis = """
ITEM 1: PUBLISH
SCORES: relevance=1 news_value=1 audience_fit=1 urgency=1 originality=1
NOTES: Should be skipped by score.

ITEM 2: SKIP
SCORES: relevance=9 news_value=9 audience_fit=9 urgency=9 originality=9
NOTES: Should be published by score.
"""
    router = VerdictRouter(dimensions=DIMENSIONS, score_scale=10, formula=ROUTER_FORMULA, threshold=6.0)
    results = router.route(synthesis, item_count=2)
    assert results[0].verdict == "SKIP"
    assert results[0].score < 6.0
    assert results[1].verdict == "PUBLISH"
    assert results[1].score > 6.0


def test_router_returns_dimension_scores():
    router = VerdictRouter(dimensions=DIMENSIONS, score_scale=10, formula=ROUTER_FORMULA, threshold=6.0)
    results = router.route(FULL_SYNTHESIS, item_count=3)
    assert results[0].dimension_scores["relevance"] == 9
    assert results[0].dimension_scores["news_value"] == 9


def test_router_missing_notes_returns_empty_string():
    synthesis = """
ITEM 1: PUBLISH
SCORES: relevance=9 news_value=9 audience_fit=8 urgency=7 originality=8

ITEM 2: SKIP
SCORES: relevance=3 news_value=2 audience_fit=3 urgency=2 originality=2
NOTES: Too niche.
"""
    router = VerdictRouter(dimensions=DIMENSIONS, score_scale=10,
                           formula=ROUTER_FORMULA, threshold=6.0)
    results = router.route(synthesis, item_count=2)
    assert results[0].notes == ""          # no NOTES line → empty, not stolen
    assert results[1].notes == "Too niche."


# ── Task 4: IntakeVerdictConfig score fields ──────────────────────────────────

from config_schema import IntakeVerdictConfig  # noqa: E402


def test_verdict_config_score_defaults():
    cfg = IntakeVerdictConfig(mode="score")
    assert cfg.score_threshold == 6.0
    assert "news_value" in cfg.score_dimensions
    assert cfg.score_scale == 10
    assert "news_value" in cfg.score_formula


def test_verdict_config_override():
    cfg = IntakeVerdictConfig(
        mode="score",
        score_threshold=7.5,
        score_formula="news_value * 10",
        score_dimensions=["news_value"],
        score_scale=10,
    )
    assert cfg.score_threshold == 7.5
    assert cfg.score_formula == "news_value * 10"
    assert cfg.score_dimensions == ["news_value"]


# --- Task 5: TrackerAdapter ---
import unittest.mock as mock  # noqa: E402
import requests  # noqa: E402
from tracker_adapter import GitHubTrackerAdapter, TriageItem  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

MOCK_ITEM = TriageItem(
    id="42",
    title="Test issue",
    body="body",
    url="https://github.com/owner/repo/issues/42",
    created_at=datetime.now(timezone.utc),
    metadata={},
)


def _make_adapter():
    return GitHubTrackerAdapter(repo="owner/repo", token="tok")


def test_add_score_label_posts_label_and_creates_if_missing():
    adapter = _make_adapter()
    calls = []

    def fake_api(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if method == "GET" and "labels/score-8" in path:
            resp = mock.Mock()
            resp.status_code = 404
            raise requests.HTTPError(response=resp)
        return {}

    adapter._api = fake_api
    adapter.add_score_label(MOCK_ITEM, score=8.2)

    methods_and_paths = [(m, p) for m, p, _ in calls]
    # should check if label exists, create it, then attach it
    assert any("POST" == m and "/labels" in p and "/issues/" not in p for m, p in methods_and_paths)
    assert any("POST" == m and "/issues/42/labels" in p for m, p in methods_and_paths)


def test_add_score_label_does_not_attach_on_non_404_error():
    """A non-404 HTTP error on the GET should propagate and NOT trigger label attachment."""
    adapter = _make_adapter()
    attached = []

    def fake_api(method, path, **kwargs):
        if method == "GET" and "labels/score-8" in path:
            resp = mock.Mock()
            resp.status_code = 403
            raise requests.HTTPError(response=resp)
        if method == "POST" and "/issues/" in path:
            attached.append(path)
        return {}

    adapter._api = fake_api
    with pytest.raises(requests.HTTPError):
        adapter.add_score_label(MOCK_ITEM, score=8.2)
    assert attached == []  # must NOT attach if label existence unconfirmed


def test_add_score_label_attaches_existing_label_without_creating():
    """When GET returns 200 (label exists), no POST to /labels and label IS attached to issue."""
    adapter = _make_adapter()
    created = []
    attached = []

    def fake_api(method, path, **kwargs):
        if method == "POST" and "/labels" in path and "/issues/" not in path:
            created.append(path)
        if method == "POST" and "/issues/" in path:
            attached.append(path)
        return {}

    adapter._api = fake_api
    adapter.add_score_label(MOCK_ITEM, score=8.2)

    assert created == []   # label already exists — must NOT create
    assert any("/issues/42/labels" in p for p in attached)  # must attach to issue


def test_post_score_comment_posts_correct_body():
    adapter = _make_adapter()
    posted_bodies = []

    def fake_api(method, path, **kwargs):
        if method == "POST" and "comments" in path:
            posted_bodies.append(kwargs["json"]["body"])
        return {}

    adapter._api = fake_api
    dim_scores = {"relevance": 9, "news_value": 8, "audience_fit": 7, "urgency": 6, "originality": 5}
    adapter.post_score_comment(MOCK_ITEM, score=8.2, dimension_scores=dim_scores, score_scale=5)

    assert len(posted_bodies) == 1
    body = posted_bodies[0]
    assert "8.2" in body
    assert "/5" in body
    for k, v in dim_scores.items():
        assert f"{k}={v}" in body


# ---------------------------------------------------------------------------
# Task 6: Integration test — VerdictRouter wired into intake_triage.run()
# ---------------------------------------------------------------------------
from unittest.mock import MagicMock, patch  # noqa: E402
from pathlib import Path  # noqa: E402
import sys  # noqa: E402
import os  # noqa: E402
from datetime import datetime, timezone  # noqa: E402 (already imported above but harmless)


def _make_triage_item(n: int, created_at=None) -> "TriageItem":
    return TriageItem(
        id=str(n),
        title=f"Story {n}",
        body="Body content here",
        url=f"https://github.com/org/repo/issues/{n}",
        created_at=created_at or datetime(2026, 5, 20, 10, 0, 0, tzinfo=timezone.utc),
        metadata={"number": n},
    )


# Synthesis where ITEM 1 scores high (PUBLISH) and ITEM 2 scores low (SKIP)
_SCORE_SYNTHESIS = """
ITEM 1: PUBLISH
SCORES: relevance=9 news_value=9 audience_fit=8 urgency=8 originality=8
NOTES: Strong regulatory angle worth covering.

ITEM 2: SKIP
SCORES: relevance=2 news_value=2 audience_fit=2 urgency=2 originality=2
NOTES: Too niche for our audience.
"""


def test_intake_triage_score_mode_wires_correctly():
    """Verify that in score mode:
    - approve + add_score_label called for the high-scoring item (PUBLISH)
    - skip called for the low-scoring item (SKIP)
    - tracker.add_score_label receives the computed score
    """
    from config_schema import IntakeTriageConfig, IntakeVerdictConfig
    import intake_triage

    # Build a score-mode config
    verdict_cfg = IntakeVerdictConfig(
        mode="score",
        score_threshold=6.0,
        score_formula=(
            "(relevance*1.5 + news_value*2.0 + audience_fit*1.0"
            " + urgency*1.5 + originality*1.0) / 7.0"
        ),
        score_dimensions=["relevance", "news_value", "audience_fit", "urgency", "originality"],
        score_scale=10,
    )
    cfg = IntakeTriageConfig(
        enabled=True,
        tracker="github",
        scope="Tech news for HK professionals.",
        verdict=verdict_cfg.model_dump(),
        trigger={"min_count": 1},
        batch={"max_size": 10, "body_preview_chars": 300},
        discussion={"preset": "discussions/intake-triage.yaml"},
    )

    item1 = _make_triage_item(1, datetime(2026, 5, 20, 9, 0, 0, tzinfo=timezone.utc))
    item2 = _make_triage_item(2, datetime(2026, 5, 20, 10, 0, 0, tzinfo=timezone.utc))

    # Mock adapter
    mock_adapter = MagicMock()
    mock_adapter.list_pending.return_value = [item1, item2]

    # Mock DiscussionAgent to return our canned synthesis
    mock_disc_result = MagicMock()
    mock_disc_result.synthesis = _SCORE_SYNTHESIS
    mock_agent = MagicMock()
    mock_agent.run.return_value = mock_disc_result
    mock_agent_cls = MagicMock(return_value=mock_agent)

    # Patch the deferred import inside run()
    import agents.discussion_agent as da_mod
    original_cls = da_mod.DiscussionAgent
    da_mod.DiscussionAgent = MagicMock()
    da_mod.DiscussionAgent.from_file = MagicMock(return_value=mock_agent)
    try:
        with patch.object(intake_triage, "_make_adapter", return_value=mock_adapter):
            result = intake_triage.run(
                cfg=cfg,
                repo="owner/repo",
                force=True,
                dry_run=False,
                script_dir=Path(__file__).parent.parent,
            )
    finally:
        da_mod.DiscussionAgent = original_cls

    # item1 should be approved (high score > 6.0)
    approve_calls = [call.args[0] for call in mock_adapter.approve.call_args_list]
    assert item1 in approve_calls, "item1 (high score) must be approved"

    # add_score_label called for item1 with a score > threshold
    add_label_calls = mock_adapter.add_score_label.call_args_list
    assert len(add_label_calls) >= 1, "add_score_label must be called for PUBLISH items"
    label_item, label_score = add_label_calls[0].args
    assert label_item == item1
    assert label_score > 6.0, f"Expected score > 6.0, got {label_score}"

    # item2 should be skipped (low score < 6.0)
    skip_calls = [call.args[0] for call in mock_adapter.skip.call_args_list]
    assert item2 in skip_calls, "item2 (low score) must be skipped"

    # post_score_comment must be called for item1
    comment_calls = mock_adapter.post_score_comment.call_args_list
    assert len(comment_calls) >= 1, "post_score_comment must be called for PUBLISH items"

    assert result["fired"] is True
    assert item1.id in result["approved"]
    assert item2.id in result["skipped"]


# Synthesis where both items PUBLISH but item2 scores higher than item1
_SCORE_SYNTHESIS_BOTH_PUBLISH = """
ITEM 1: PUBLISH
SCORES: relevance=7 news_value=7 audience_fit=7 urgency=7 originality=7
NOTES: Decent coverage, above threshold.

ITEM 2: PUBLISH
SCORES: relevance=9 news_value=9 audience_fit=9 urgency=9 originality=9
NOTES: Excellent — top story of the day.
"""


def test_intake_triage_score_mode_sorts_by_score_descending():
    """Verify that PUBLISH items are returned in descending score order.

    item2 scores (9,9,9,9,9) > item1 scores (7,7,7,7,7); both are above threshold.
    The first entry in result["approved"] must be item2.id.
    """
    from config_schema import IntakeTriageConfig, IntakeVerdictConfig
    import intake_triage

    verdict_cfg = IntakeVerdictConfig(
        mode="score",
        score_threshold=6.0,
        score_formula=(
            "(relevance*1.5 + news_value*2.0 + audience_fit*1.0"
            " + urgency*1.5 + originality*1.0) / 7.0"
        ),
        score_dimensions=["relevance", "news_value", "audience_fit", "urgency", "originality"],
        score_scale=10,
    )
    cfg = IntakeTriageConfig(
        enabled=True,
        tracker="github",
        scope="Tech news for HK professionals.",
        verdict=verdict_cfg.model_dump(),
        trigger={"min_count": 1},
        batch={"max_size": 10, "body_preview_chars": 300},
        discussion={"preset": "discussions/intake-triage.yaml"},
    )

    item1 = _make_triage_item(1, datetime(2026, 5, 20, 9, 0, 0, tzinfo=timezone.utc))
    item2 = _make_triage_item(2, datetime(2026, 5, 20, 10, 0, 0, tzinfo=timezone.utc))

    mock_adapter = MagicMock()
    mock_adapter.list_pending.return_value = [item1, item2]

    mock_disc_result = MagicMock()
    mock_disc_result.synthesis = _SCORE_SYNTHESIS_BOTH_PUBLISH
    mock_agent = MagicMock()
    mock_agent.run.return_value = mock_disc_result

    import agents.discussion_agent as da_mod
    original_cls = da_mod.DiscussionAgent
    da_mod.DiscussionAgent = MagicMock()
    da_mod.DiscussionAgent.from_file = MagicMock(return_value=mock_agent)
    try:
        with patch.object(intake_triage, "_make_adapter", return_value=mock_adapter):
            result = intake_triage.run(
                cfg=cfg,
                repo="owner/repo",
                force=True,
                dry_run=False,
                script_dir=Path(__file__).parent.parent,
            )
    finally:
        da_mod.DiscussionAgent = original_cls

    assert result["fired"] is True
    assert item1.id in result["approved"]
    assert item2.id in result["approved"]
    # Higher-scoring item2 must appear before item1 in approved list
    assert result["approved"][0] == item2.id, (
        f"Expected item2 first (higher score), got {result['approved']}"
    )


# ---------------------------------------------------------------------------
# Task 7: Per-repo IntakeVerdictConfig merge test
# ---------------------------------------------------------------------------
from config_schema import IntakeTriageConfig  # noqa: E402
from intake_triage import _merge_intake_cfg   # noqa: E402


def test_intake_verdict_config_per_repo_merge():
    """Per-repo verdict overrides correctly shadow global IntakeVerdictConfig defaults.

    The system resolves per-repo vs global config via ``_merge_intake_cfg``, which
    deep-merges the per-repo override dict into a base ``IntakeTriageConfig`` — nested
    dicts (including ``verdict``) are merged key-by-key so partial overrides work.

    This test verifies that all four scoring fields are individually overridable.
    """
    # 1. Global config — all defaults
    global_cfg = IntakeTriageConfig()
    assert global_cfg.verdict.score_threshold == 6.0
    assert global_cfg.verdict.score_scale == 10

    # 2. Per-repo override dict (only the verdict sub-keys we want to change)
    per_repo_override = {
        "verdict": {
            "score_threshold": 7.5,
            "score_formula": "relevance",
            "score_dimensions": ["relevance"],
            "score_scale": 5,
        }
    }

    # 3. Simulate the merge exactly as intake_triage does at runtime
    merged_cfg = _merge_intake_cfg(global_cfg, per_repo_override)

    # 4. Assert every overridden field carries the per-repo value
    assert merged_cfg.verdict.score_threshold == 7.5, (
        f"Expected score_threshold=7.5, got {merged_cfg.verdict.score_threshold}"
    )
    assert merged_cfg.verdict.score_formula == "relevance", (
        f"Expected score_formula='relevance', got {merged_cfg.verdict.score_formula}"
    )
    assert merged_cfg.verdict.score_dimensions == ["relevance"], (
        f"Expected score_dimensions=['relevance'], got {merged_cfg.verdict.score_dimensions}"
    )
    assert merged_cfg.verdict.score_scale == 5, (
        f"Expected score_scale=5, got {merged_cfg.verdict.score_scale}"
    )
    # 5. Non-overridden fields must retain global defaults
    assert merged_cfg.verdict.mode == global_cfg.verdict.mode, (
        f"Expected mode to be unchanged '{global_cfg.verdict.mode}', got '{merged_cfg.verdict.mode}'"
    )
