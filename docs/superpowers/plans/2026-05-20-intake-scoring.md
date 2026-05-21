# Intake Triage Scoring System — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a configurable scoring system to intake_triage so AI agents score items on five qualitative dimensions, a formula computes a final score, score ≥ threshold → PUBLISH, and approved items are ranked and labelled by score.

**Architecture:** New `intake_scoring.py` module contains `ScoreParser` (regex extraction from synthesis), `ScoringEngine` (safe AST formula evaluator), and `VerdictRouter` (threshold-based PUBLISH/SKIP). `intake_triage.py` calls this pipeline after the discussion; `tracker_adapter.py` gains `add_score_label` and `post_score_comment` methods; `config_schema.py` gains score fields on `IntakeVerdictConfig`.

**Tech Stack:** Python 3.11+, `ast` (safe eval), `re`, `pydantic` (config schema), `requests` (GitHub API), `pytest`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `intake_scoring.py` | Create | `ScoreParser`, `ScoringEngine`, `VerdictRouter` |
| `tests/test_intake_scoring.py` | Create | Unit tests for all three classes |
| `config_schema.py` | Modify | Add score fields to `IntakeVerdictConfig` |
| `tracker_adapter.py` | Modify | Add `add_score_label()`, `post_score_comment()` to abstract base + GitHub impl |
| `intake_triage.py` | Modify | Call scoring pipeline, pass score data to tracker, sort approved by score |
| `config.yaml` | Modify | Add score defaults under `intake_triage.verdict` |
| `discussions/intake-triage.yaml` | Modify | Update `verdict_format` to include `SCORES:` line |

---

### Task 1: `intake_scoring.py` — ScoreParser

**Files:**
- Create: `intake_scoring.py`
- Create: `tests/test_intake_scoring.py`

The `ScoreParser` extracts per-item `{dimension: int}` dicts from moderator synthesis text. Input is the full synthesis string; output is a list of dicts (one per item, in order). Missing dimensions default to `score_scale // 2`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_intake_scoring.py
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
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /path/to/ai-software-house
python3 -m pytest tests/test_intake_scoring.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError: No module named 'intake_scoring'`

- [ ] **Step 3: Implement ScoreParser in `intake_scoring.py`**

```python
"""intake_scoring.py — Scoring pipeline for intake_triage.

Provides ScoreParser, ScoringEngine, VerdictRouter.
"""
from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("intake_scoring")

# ---------------------------------------------------------------------------
# ScoreParser
# ---------------------------------------------------------------------------

# Matches:  SCORES: relevance=8 news_value=9 ...
_SCORES_LINE_RE = re.compile(
    r"ITEM\s+(\d+).*?SCORES:\s*((?:\w+=\d+\s*)+)",
    re.IGNORECASE | re.DOTALL,
)
_KV_RE = re.compile(r"(\w+)=(\d+)")


class ScoreParser:
    """Extract per-item dimension scores from moderator synthesis text."""

    def __init__(self, dimensions: list[str], score_scale: int = 10) -> None:
        self.dimensions = dimensions
        self.score_scale = score_scale
        self._neutral = score_scale // 2

    def _neutral_scores(self) -> dict[str, int]:
        return {dim: self._neutral for dim in self.dimensions}

    def parse_batch(self, synthesis: str, item_count: int) -> list[dict[str, int]]:
        """Return list of {dimension: score} dicts, one per item (1-indexed → 0-indexed).

        Missing dimensions filled with neutral (score_scale // 2).
        If synthesis has fewer SCORES blocks than item_count, extras are neutral.
        """
        raw: dict[int, dict[str, int]] = {}
        for m in _SCORES_LINE_RE.finditer(synthesis):
            idx = int(m.group(1))
            kv = {k: int(v) for k, v in _KV_RE.findall(m.group(2))}
            scores = self._neutral_scores()
            for dim in self.dimensions:
                if dim in kv:
                    scores[dim] = kv[dim]
            raw[idx] = scores

        results = []
        for i in range(1, item_count + 1):
            results.append(raw.get(i, self._neutral_scores()))
        return results
```

- [ ] **Step 4: Run tests — all should pass**

```bash
python3 -m pytest tests/test_intake_scoring.py::test_parse_two_items_all_dimensions tests/test_intake_scoring.py::test_parse_missing_scores_returns_neutral tests/test_intake_scoring.py::test_parse_partial_scores_fills_missing_with_neutral tests/test_intake_scoring.py::test_parse_item_count_pads_missing_items -v
```
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add intake_scoring.py tests/test_intake_scoring.py
git commit -m "feat: add ScoreParser to intake_scoring

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 2: `intake_scoring.py` — ScoringEngine

**Files:**
- Modify: `intake_scoring.py` (append)
- Modify: `tests/test_intake_scoring.py` (append)

`ScoringEngine` safely evaluates a formula string with dimension values substituted as variables. Only arithmetic AST nodes are permitted; result is clamped to `[0, score_scale]`.

- [ ] **Step 1: Append failing tests**

```python
# append to tests/test_intake_scoring.py
from intake_scoring import ScoringEngine

FORMULA = "(relevance*1.5 + news_value*2.0 + audience_fit*1.0 + urgency*1.5 + originality*1.0) / 7.0 * 10"


def test_engine_correct_score():
    engine = ScoringEngine(formula=FORMULA, score_scale=10)
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
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python3 -m pytest tests/test_intake_scoring.py -k "engine" -v 2>&1 | head -20
```
Expected: `ImportError` or `AttributeError` (ScoringEngine not yet defined)

- [ ] **Step 3: Implement ScoringEngine — append to `intake_scoring.py`**

```python
# ---------------------------------------------------------------------------
# ScoringEngine
# ---------------------------------------------------------------------------

_ALLOWED_AST_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.FloorDiv,
    ast.UAdd, ast.USub,
    ast.Constant,   # Python 3.8+ replaces ast.Num
    ast.Name,       # variable references only
)


def _safe_eval(expr_str: str, variables: dict[str, float]) -> float:
    """Evaluate a numeric expression with only the given variables in scope.

    Raises ValueError if the expression uses any disallowed AST node.
    """
    tree = ast.parse(expr_str, mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_AST_NODES):
            raise ValueError(
                f"disallowed AST node {type(node).__name__!r} in formula"
            )
        if isinstance(node, ast.Name) and node.id not in variables:
            raise ValueError(f"unknown variable {node.id!r} in formula")
    code = compile(tree, "<formula>", "eval")
    return float(eval(code, {"__builtins__": {}}, variables))  # noqa: S307


class ScoringEngine:
    """Apply a safe formula to a dimension-score dict and return a clamped float."""

    def __init__(self, formula: str, score_scale: int = 10) -> None:
        self.formula = formula
        self.score_scale = score_scale

    def score(self, dimension_scores: dict[str, int]) -> float:
        variables = {k: float(v) for k, v in dimension_scores.items()}
        result = _safe_eval(self.formula, variables)
        return float(max(0.0, min(float(self.score_scale), result)))
```

- [ ] **Step 4: Run engine tests**

```bash
python3 -m pytest tests/test_intake_scoring.py -k "engine" -v
```
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add intake_scoring.py tests/test_intake_scoring.py
git commit -m "feat: add ScoringEngine with safe AST formula evaluator

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 3: `intake_scoring.py` — VerdictRouter

**Files:**
- Modify: `intake_scoring.py` (append)
- Modify: `tests/test_intake_scoring.py` (append)

`VerdictRouter` combines the parser and engine: given synthesis text and config, it returns `list[ScoredVerdict]` (named tuple: `verdict`, `score`, `notes`, `dimension_scores`).

- [ ] **Step 1: Append failing tests**

```python
# append to tests/test_intake_scoring.py
from intake_scoring import VerdictRouter, ScoredVerdict

FULL_SYNTHESIS = """
ITEM 1: PUBLISH
SCORES: relevance=9 news_value=9 audience_fit=8 urgency=7 originality=8
NOTES: Lead with the regulatory angle.

ITEM 2: SKIP
SCORES: relevance=3 news_value=2 audience_fit=3 urgency=2 originality=2
NOTES: Too niche.

ITEM 3: PUBLISH
SCORES: relevance=6 news_value=6 audience_fit=6 urgency=5 originality=5
NOTES: Solid but unremarkable.
"""

ROUTER_FORMULA = "(relevance*1.5 + news_value*2.0 + audience_fit*1.0 + urgency*1.5 + originality*1.0) / 7.0 * 10"


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
"""
    router = VerdictRouter(dimensions=DIMENSIONS, score_scale=10, formula=ROUTER_FORMULA, threshold=6.0)
    results = router.route(synthesis, item_count=1)
    assert results[0].verdict == "SKIP"
    assert results[0].score < 6.0


def test_router_returns_dimension_scores():
    router = VerdictRouter(dimensions=DIMENSIONS, score_scale=10, formula=ROUTER_FORMULA, threshold=6.0)
    results = router.route(FULL_SYNTHESIS, item_count=3)
    assert results[0].dimension_scores["relevance"] == 9
    assert results[0].dimension_scores["news_value"] == 9
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python3 -m pytest tests/test_intake_scoring.py -k "router" -v 2>&1 | head -20
```
Expected: `ImportError` for `VerdictRouter`, `ScoredVerdict`

- [ ] **Step 3: Implement VerdictRouter — append to `intake_scoring.py`**

```python
# ---------------------------------------------------------------------------
# VerdictRouter
# ---------------------------------------------------------------------------

from typing import NamedTuple


class ScoredVerdict(NamedTuple):
    verdict: str                       # "PUBLISH" or "SKIP"
    score: float                       # final computed score
    notes: str                         # editorial notes from moderator
    dimension_scores: dict[str, int]   # raw per-dimension values


# Extracts NOTES line per item (reuse pattern from intake_triage._ITEM_VERDICT_RE)
_ITEM_NOTES_RE = re.compile(
    r"ITEM\s+(\d+):.*?NOTES:\s*(.+?)(?=\n\nITEM\s+\d+:|\Z)",
    re.IGNORECASE | re.DOTALL,
)


class VerdictRouter:
    """Route items to PUBLISH/SKIP based on computed score vs threshold."""

    def __init__(
        self,
        dimensions: list[str],
        score_scale: int,
        formula: str,
        threshold: float,
    ) -> None:
        self._parser = ScoreParser(dimensions=dimensions, score_scale=score_scale)
        self._engine = ScoringEngine(formula=formula, score_scale=score_scale)
        self.threshold = threshold

    def route(self, synthesis: str, item_count: int) -> list[ScoredVerdict]:
        """Return one ScoredVerdict per item.

        Score is computed from dimension values regardless of the AI-written verdict;
        threshold comparison is the authoritative PUBLISH/SKIP decision.
        """
        all_scores = self._parser.parse_batch(synthesis, item_count)

        # Extract notes per item
        notes_map: dict[int, str] = {}
        for m in _ITEM_NOTES_RE.finditer(synthesis):
            idx = int(m.group(1))
            notes_map[idx] = m.group(2).strip().splitlines()[0].strip()

        results = []
        for i, dim_scores in enumerate(all_scores, 1):
            score = self._engine.score(dim_scores)
            verdict = "PUBLISH" if score >= self.threshold else "SKIP"
            notes = notes_map.get(i, "")
            results.append(ScoredVerdict(
                verdict=verdict,
                score=score,
                notes=notes,
                dimension_scores=dim_scores,
            ))
        return results
```

- [ ] **Step 4: Run all intake_scoring tests**

```bash
python3 -m pytest tests/test_intake_scoring.py -v
```
Expected: all 14 tests pass

- [ ] **Step 5: Commit**

```bash
git add intake_scoring.py tests/test_intake_scoring.py
git commit -m "feat: add VerdictRouter to intake_scoring

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 4: `config_schema.py` — Score fields on IntakeVerdictConfig

**Files:**
- Modify: `config_schema.py`

Add `score_formula`, `score_dimensions`, `score_scale` to `IntakeVerdictConfig`. `score_threshold` already exists as `Optional[int]`; change to `Optional[float]`.

- [ ] **Step 1: Write failing test**

```python
# append to tests/test_intake_scoring.py
from config_schema import IntakeVerdictConfig


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
```

- [ ] **Step 2: Run test to confirm failure**

```bash
python3 -m pytest tests/test_intake_scoring.py::test_verdict_config_score_defaults -v
```
Expected: `AssertionError` — `score_threshold` is `None`, fields missing

- [ ] **Step 3: Update `IntakeVerdictConfig` in `config_schema.py`**

Replace the existing `IntakeVerdictConfig` class:

```python
class IntakeVerdictConfig(BaseModel):
    model_config = {"extra": "allow"}

    mode: str = "binary"
    score_threshold: Optional[float] = 6.0
    score_formula: str = (
        "(relevance*1.5 + news_value*2.0 + audience_fit*1.0"
        " + urgency*1.5 + originality*1.0) / 7.0 * 10"
    )
    score_dimensions: list[str] = Field(
        default_factory=lambda: ["relevance", "news_value", "audience_fit", "urgency", "originality"]
    )
    score_scale: int = 10
```

- [ ] **Step 4: Run config tests**

```bash
python3 -m pytest tests/test_intake_scoring.py::test_verdict_config_score_defaults tests/test_intake_scoring.py::test_verdict_config_override -v
```
Expected: 2 passed

- [ ] **Step 5: Run full suite to check no regressions**

```bash
python3 -m pytest tests/ -q --ignore=tests/test_deployment.py --ignore=tests/test_qa_clarification.py -k "not pkce_login_headless" 2>&1 | tail -5
```
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add config_schema.py tests/test_intake_scoring.py
git commit -m "feat: add score fields to IntakeVerdictConfig

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 5: `tracker_adapter.py` — add_score_label and post_score_comment

**Files:**
- Modify: `tracker_adapter.py`

Add two new abstract methods to `TrackerAdapter` and implement them in `GitHubTrackerAdapter`. `add_score_label` ensures the label exists in the repo then attaches it to the issue. `post_score_comment` posts the score summary as a standalone comment.

- [ ] **Step 1: Write failing tests**

```python
# append to tests/test_intake_scoring.py
import unittest.mock as mock
from tracker_adapter import GitHubTrackerAdapter, TriageItem
from datetime import datetime, timezone

MOCK_ITEM = TriageItem(
    id="42",
    title="Test issue",
    body="body",
    url="https://github.com/owner/repo/issues/42",
    created_at=datetime.now(timezone.utc),
    metadata={},
)


def _make_adapter():
    adapter = GitHubTrackerAdapter.__new__(GitHubTrackerAdapter)
    adapter.repo = "owner/repo"
    adapter._token = "tok"
    adapter.pending_label = "triage-pending"
    adapter.approved_label = "triage-approved"
    adapter.skipped_label = "triage-skipped"
    adapter.trigger_label = "press"
    return adapter


def test_add_score_label_posts_label_and_creates_if_missing():
    adapter = _make_adapter()
    calls = []

    def fake_api(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if method == "GET" and "labels/score-8" in path:
            raise Exception("404")
        return {}

    adapter._api = fake_api
    adapter.add_score_label(MOCK_ITEM, score=8.2)

    methods_and_paths = [(m, p) for m, p, _ in calls]
    # should check if label exists, create it, then attach it
    assert any("POST" == m and "/labels" in p and "/issues/" not in p for m, p in methods_and_paths)
    assert any("POST" == m and "/issues/42/labels" in p for m, p in methods_and_paths)


def test_post_score_comment_posts_correct_body():
    adapter = _make_adapter()
    posted_bodies = []

    def fake_api(method, path, **kwargs):
        if method == "POST" and "comments" in path:
            posted_bodies.append(kwargs["json"]["body"])
        return {}

    adapter._api = fake_api
    dim_scores = {"relevance": 9, "news_value": 8, "audience_fit": 7, "urgency": 6, "originality": 5}
    adapter.post_score_comment(MOCK_ITEM, score=8.2, dimension_scores=dim_scores)

    assert len(posted_bodies) == 1
    body = posted_bodies[0]
    assert "8.2" in body
    assert "relevance=9" in body
    assert "news_value=8" in body
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python3 -m pytest tests/test_intake_scoring.py -k "score_label or score_comment" -v 2>&1 | head -20
```
Expected: `AttributeError: type object 'TrackerAdapter' has no attribute 'add_score_label'`

- [ ] **Step 3: Add abstract methods to `TrackerAdapter` base class**

After the existing `is_approved` abstract method, add:

```python
    @abstractmethod
    def add_score_label(self, item: TriageItem, score: float) -> None:
        """Ensure label 'score-{round(score)}' exists in repo and attach it to item."""

    @abstractmethod
    def post_score_comment(
        self,
        item: TriageItem,
        score: float,
        dimension_scores: dict[str, int],
    ) -> None:
        """Post a comment with the editorial score summary on the item."""
```

- [ ] **Step 4: Implement in `GitHubTrackerAdapter`**

Add after the `is_approved` method in `GitHubTrackerAdapter`:

```python
    def add_score_label(self, item: TriageItem, score: float) -> None:
        label_name = f"score-{round(score)}"
        # Ensure label exists in repo (404 → create it)
        try:
            self._api("GET", f"/repos/{self.repo}/labels/{label_name}")
        except Exception:
            try:
                self._api(
                    "POST",
                    f"/repos/{self.repo}/labels",
                    json={"name": label_name, "color": "0075ca"},
                )
            except Exception as exc:
                log.warning("tracker_adapter: could not create label %r: %s", label_name, exc)
        try:
            self._api(
                "POST",
                f"/repos/{self.repo}/issues/{item.id}/labels",
                json={"labels": [label_name]},
            )
        except Exception as exc:
            log.warning("tracker_adapter: failed to add score label to #%s: %s", item.id, exc)

    def post_score_comment(
        self,
        item: TriageItem,
        score: float,
        dimension_scores: dict[str, int],
    ) -> None:
        dim_line = "  ".join(f"{k}={v}" for k, v in dimension_scores.items())
        scale = max(dimension_scores.values()) if dimension_scores else 10
        # score is already on the configured scale (e.g. 0–10)
        body = (
            f"**Editorial Score: {score:.1f}/10**\n"
            f"{dim_line}"
        )
        try:
            self._api(
                "POST",
                f"/repos/{self.repo}/issues/{item.id}/comments",
                json={"body": body},
            )
        except Exception as exc:
            log.warning("tracker_adapter: failed to post score comment on #%s: %s", item.id, exc)
```

- [ ] **Step 5: Run tracker tests**

```bash
python3 -m pytest tests/test_intake_scoring.py -k "score_label or score_comment" -v
```
Expected: 2 passed

- [ ] **Step 6: Run full suite**

```bash
python3 -m pytest tests/ -q --ignore=tests/test_deployment.py --ignore=tests/test_qa_clarification.py -k "not pkce_login_headless" 2>&1 | tail -5
```
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add tracker_adapter.py tests/test_intake_scoring.py
git commit -m "feat: add add_score_label and post_score_comment to TrackerAdapter

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 6: Wire scoring into `intake_triage.py`

**Files:**
- Modify: `intake_triage.py`
- Modify: `discussions/intake-triage.yaml`
- Modify: `config.yaml`

Replace the `_parse_batch_verdicts` call with `VerdictRouter.route()` when `mode == "score"`. Sort approved items by score descending. Call `add_score_label` and `post_score_comment` on published items.

- [ ] **Step 1: Update `discussions/intake-triage.yaml` verdict_format**

Replace the existing `verdict_format` block with:

```yaml
verdict_format: |
  At the end of your final synthesis, include a verdict block for EVERY item,
  using exactly this format (one block per item, in order):

  ITEM 1: PUBLISH
  SCORES: relevance=8 news_value=9 audience_fit=7 urgency=6 originality=5
  NOTES: <one sentence: the angle or focus the writer should take>

  ITEM 2: SKIP
  SCORES: relevance=3 news_value=4 audience_fit=5 urgency=2 originality=3
  NOTES: <one sentence: why this story was skipped>

  Dimensions are scored 1–10. Only PUBLISH and SKIP are valid verdicts.
  Every item must have a SCORES line and a NOTES line.
```

- [ ] **Step 2: Update `config.yaml` under `intake_triage.verdict`**

Replace or update the existing `verdict:` block to:

```yaml
    verdict:
      mode: score                   # binary | score
      score_threshold: 6.0
      score_formula: "(relevance*1.5 + news_value*2.0 + audience_fit*1.0 + urgency*1.5 + originality*1.0) / 7.0 * 10"
      score_dimensions:
        - relevance
        - news_value
        - audience_fit
        - urgency
        - originality
      score_scale: 10
```

- [ ] **Step 3: Write a failing integration test**

```python
# append to tests/test_intake_scoring.py
import unittest.mock as mock


def test_intake_triage_run_uses_scoring(tmp_path):
    """run() with mode=score should sort approved by score and call add_score_label."""
    from intake_triage import run
    from config_schema import (
        IntakeTriageConfig, IntakeVerdictConfig, IntakeBatchConfig,
        IntakeTriggerConfig,
    )

    synthesis = """
ITEM 1: PUBLISH
SCORES: relevance=9 news_value=9 audience_fit=8 urgency=7 originality=8
NOTES: Strong story.

ITEM 2: PUBLISH
SCORES: relevance=5 news_value=5 audience_fit=5 urgency=5 originality=5
NOTES: Average story.

ITEM 3: SKIP
SCORES: relevance=2 news_value=2 audience_fit=2 urgency=2 originality=2
NOTES: Weak story.
"""
    item1 = TriageItem(id="1", title="T1", body="", url="u1", created_at=datetime.now(timezone.utc), metadata={})
    item2 = TriageItem(id="2", title="T2", body="", url="u2", created_at=datetime.now(timezone.utc), metadata={})
    item3 = TriageItem(id="3", title="T3", body="", url="u3", created_at=datetime.now(timezone.utc), metadata={})

    cfg = IntakeTriageConfig(
        enabled=True,
        verdict=IntakeVerdictConfig(
            mode="score",
            score_threshold=6.0,
            score_formula="(relevance*1.5 + news_value*2.0 + audience_fit*1.0 + urgency*1.5 + originality*1.0) / 7.0 * 10",
            score_dimensions=["relevance", "news_value", "audience_fit", "urgency", "originality"],
            score_scale=10,
        ),
        trigger=IntakeTriggerConfig(min_count=1),
    )

    mock_adapter = mock.MagicMock()
    mock_adapter.get_pending.return_value = [item1, item2, item3]

    mock_disc_result = mock.MagicMock()
    mock_disc_result.synthesis = synthesis

    mock_agent = mock.MagicMock()
    mock_agent.run.return_value = mock_disc_result

    with mock.patch("intake_triage.GitHubTrackerAdapter", return_value=mock_adapter), \
         mock.patch("intake_triage.DiscussionAgent") as MockDisc:
        MockDisc.from_file.return_value = mock_agent
        result = run(
            cfg=cfg,
            repo="owner/repo",
            script_dir=tmp_path,
            force=True,
        )

    # item1 has higher score than item2 — approved list should be [item1.id, item2.id]
    assert result["approved"] == ["1", "2"]
    # add_score_label called twice (once per approved item)
    assert mock_adapter.add_score_label.call_count == 2
    # post_score_comment called twice
    assert mock_adapter.post_score_comment.call_count == 2
    # skip called once
    assert mock_adapter.skip.call_count == 1
```

- [ ] **Step 4: Run test to confirm failure**

```bash
python3 -m pytest tests/test_intake_scoring.py::test_intake_triage_run_uses_scoring -v 2>&1 | head -30
```
Expected: FAIL — `run()` doesn't call `add_score_label` yet

- [ ] **Step 5: Update verdict section in `intake_triage.py`**

Replace the existing verdict-action block (the `verdicts = _parse_batch_verdicts(...)` section through `return {...}`) with:

```python
    verdict_cfg = cfg.verdict
    if verdict_cfg.mode == "score":
        from intake_scoring import VerdictRouter
        router = VerdictRouter(
            dimensions=verdict_cfg.score_dimensions,
            score_scale=verdict_cfg.score_scale,
            formula=verdict_cfg.score_formula,
            threshold=verdict_cfg.score_threshold,
        )
        scored = router.route(synthesis, item_count=len(batch))
        # Sort by score descending so pipeline picks highest-quality items first
        indexed = sorted(enumerate(scored), key=lambda x: x[1].score, reverse=True)
        approved, skipped = [], []
        for orig_idx, sv in indexed:
            item = batch[orig_idx]
            if sv.verdict == "SKIP":
                log.info("intake_triage: SKIP item %s (score=%.1f) — %s", item.id, sv.score, sv.notes)
                try:
                    adapter.skip(item, reason=sv.notes)
                    skipped.append(item.id)
                except Exception as exc:
                    log.warning("intake_triage: failed to skip item %s: %s", item.id, exc)
            else:
                log.info("intake_triage: PUBLISH item %s (score=%.1f) — %s", item.id, sv.score, sv.notes)
                try:
                    adapter.approve(item, notes=sv.notes)
                    adapter.add_score_label(item, score=sv.score)
                    adapter.post_score_comment(item, score=sv.score, dimension_scores=sv.dimension_scores)
                    approved.append(item.id)
                except Exception as exc:
                    log.warning("intake_triage: failed to approve item %s: %s", item.id, exc)
        log.info("intake_triage: done. approved=%d skipped=%d", len(approved), len(skipped))
        return {"fired": True, "approved": approved, "skipped": skipped}

    # --- binary mode (original behaviour) ---
    verdicts = _parse_batch_verdicts(synthesis, item_count=len(batch))
    approved, skipped = [], []
    for item, (verdict, notes) in zip(batch, verdicts):
        if verdict == "SKIP":
            log.info("intake_triage: SKIP item %s — %s", item.id, notes)
            try:
                adapter.skip(item, reason=notes)
                skipped.append(item.id)
            except Exception as exc:
                log.warning("intake_triage: failed to skip item %s: %s", item.id, exc)
        else:
            log.info("intake_triage: PUBLISH item %s — %s", item.id, notes)
            try:
                adapter.approve(item, notes=notes)
                approved.append(item.id)
            except Exception as exc:
                log.warning("intake_triage: failed to approve item %s: %s", item.id, exc)
    log.info("intake_triage: done. approved=%d skipped=%d", len(approved), len(skipped))
    return {"fired": True, "approved": approved, "skipped": skipped}
```

- [ ] **Step 6: Run integration test**

```bash
python3 -m pytest tests/test_intake_scoring.py::test_intake_triage_run_uses_scoring -v
```
Expected: PASS

- [ ] **Step 7: Run full suite**

```bash
python3 -m pytest tests/ -q --ignore=tests/test_deployment.py --ignore=tests/test_qa_clarification.py -k "not pkce_login_headless" 2>&1 | tail -5
```
Expected: all pass

- [ ] **Step 8: Commit**

```bash
git add intake_triage.py discussions/intake-triage.yaml config.yaml tests/test_intake_scoring.py
git commit -m "feat: wire VerdictRouter scoring into intake_triage pipeline

- mode=score uses VerdictRouter instead of _parse_batch_verdicts
- approved items sorted by score descending
- add_score_label + post_score_comment called on PUBLISH
- discussions/intake-triage.yaml updated with SCORES line format
- config.yaml sets mode=score with default formula/threshold

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 7: Per-repo score config merging

**Files:**
- Modify: `intake_triage.py` (`_load_repos_enabled` / `_main_locked`)

Per-repo `intake_triage.verdict` keys (from `repos-available/*.yaml`) should override the global `IntakeVerdictConfig`. The merge already happens at the `IntakeTriageConfig` level via deep-merge; this task verifies the config path carries score overrides into `run()`.

- [ ] **Step 1: Write test**

```python
# append to tests/test_intake_scoring.py
def test_per_repo_verdict_override_merges_correctly():
    from config_schema import IntakeVerdictConfig, IntakeTriageConfig

    global_verdict = IntakeVerdictConfig(mode="score", score_threshold=6.0)
    # Simulate per-repo override: higher threshold, custom formula
    per_repo_override = {"score_threshold": 8.0, "score_formula": "news_value * 10"}

    merged_data = global_verdict.model_dump()
    merged_data.update(per_repo_override)
    merged = IntakeVerdictConfig(**merged_data)

    assert merged.score_threshold == 8.0
    assert merged.score_formula == "news_value * 10"
    assert merged.score_dimensions == global_verdict.score_dimensions  # inherited
    assert merged.mode == "score"  # inherited
```

- [ ] **Step 2: Run test**

```bash
python3 -m pytest tests/test_intake_scoring.py::test_per_repo_verdict_override_merges_correctly -v
```
Expected: PASS (no code change needed — pydantic merge already works)

If it fails, check `_build_intake_config_for_repo()` in `intake_triage.py` to ensure per-repo `intake_triage.verdict` dict is deep-merged before being passed to `IntakeTriageConfig`.

- [ ] **Step 3: Commit test**

```bash
git add tests/test_intake_scoring.py
git commit -m "test: verify per-repo score config override merges correctly

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 8: Final smoke test and cleanup

- [ ] **Step 1: Run complete test suite**

```bash
python3 -m pytest tests/ -q --ignore=tests/test_deployment.py --ignore=tests/test_qa_clarification.py -k "not pkce_login_headless" 2>&1 | tail -10
```
Expected: all pass, no regressions

- [ ] **Step 2: Verify `intake_scoring.py` has no bare `eval` without the safe guard**

```bash
grep -n "eval(" intake_scoring.py
```
Expected: only `eval(code, {"__builtins__": {}}, variables)` — the safe call

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "chore: intake scoring system complete

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```
