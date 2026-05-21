# Intake Triage Scoring System — Design Spec

**Date:** 2026-05-20  
**Status:** Approved

---

## Problem

Intake triage currently produces a binary PUBLISH/SKIP verdict with no numeric signal about item quality or priority. This means:
- No way to rank published items for pipeline ordering
- Threshold decisions are implicit in the AI discussion, not inspectable or configurable
- Different repos cannot tune editorial standards without forking the discussion preset

---

## Goals

1. AI agents score each item on five qualitative dimensions (1–10 each)
2. A configurable formula combines dimension scores into a single final score
3. Score ≥ configured threshold → PUBLISH; below → SKIP
4. Published items are sorted by score descending for pipeline ordering
5. Score is written as a GitHub label and comment on approved items
6. Weights/formula/threshold are configurable globally and overrideable per-repo

---

## Architecture

```
DiscussionAgent.run()
    └─ synthesis text
         ├─ ScoreParser.parse_batch()     → list[ItemScores]
         ├─ ScoringEngine.score()         → list[float]   (applies formula)
         └─ VerdictRouter.route()         → list[(PUBLISH|SKIP, score, notes)]
              └─ on PUBLISH:
                   ├─ TrackerAdapter.approve(item)
                   ├─ TrackerAdapter.add_score_label(item, score, score_scale)
                   └─ TrackerAdapter.post_score_comment(item, score, dimension_scores, score_scale)
              └─ on SKIP:
                   └─ TrackerAdapter.skip(item)
```

New module: `intake_scoring.py` — contains `ScoreParser`, `ScoringEngine`, `VerdictRouter`.  
`intake_triage.py` imports and calls these after receiving the synthesis.

---

## Config Schema

### Global defaults (`config.yaml` under `intake_triage.verdict`)

```yaml
intake_triage:
  verdict:
    mode: score                   # binary | score
    score_threshold: 6.0          # items scoring >= this → PUBLISH
    score_formula: "(relevance*1.5 + news_value*2.0 + audience_fit*1.0 + urgency*1.5 + originality*1.0) / 7.0"
    score_dimensions:
      - relevance
      - news_value
      - audience_fit
      - urgency
      - originality
    score_scale: 10               # AI scores each dimension 1–score_scale
```

### Per-repo overrides (`repos-available/<repo>.yaml`)

```yaml
intake_triage:
  verdict:
    score_threshold: 7.0
    score_formula: "(news_value*3 + relevance*2 + urgency*2) / 7"
```

Per-repo keys are merged on top of global defaults. Any key not present falls back to the global value.

---

## AI Output Format

The discussion preset (`discussions/intake-triage.yaml`) `verdict_format` is updated to require a `SCORES:` line per item:

```
ITEM 1: PUBLISH
SCORES: relevance=8 news_value=9 audience_fit=7 urgency=6 originality=5
NOTES: Focus on the API cost implications for enterprise buyers.

ITEM 2: SKIP
SCORES: relevance=3 news_value=4 audience_fit=5 urgency=2 originality=3
NOTES: Duplicate coverage of a story covered last week.
```

### ScoreParser

- Regex: `SCORES:\s*((?:\w+=\d+\s*)+)` per item block
- Extracts `{dimension: int}` dict per item
- Missing dimension defaults to `score_scale // 2` (neutral)
- SCORES line is optional for backward compat — if absent, all dimensions default to neutral → formula produces a mid-range score

### ScoringEngine

- Receives `{dimension: value}` dict + formula string from config
- Evaluates formula using a safe expression evaluator:
  - Parses via `ast.parse()` with mode `eval`
  - Walks AST; only permits: `ast.Expression`, `ast.BinOp`, `ast.UnaryOp`, `ast.Num`/`ast.Constant`, `ast.Name` (variables only, no attributes/calls)
  - Variable names resolved from dimension dict
  - Raises `ValueError` on disallowed AST nodes
- Returns `float` clamped to `[0, score_scale]`

### VerdictRouter

- Compares `score >= score_threshold` → PUBLISH, else SKIP
- Falls back to binary PUBLISH/SKIP from existing moderator text if `mode: binary`

---

## GitHub Output

### On PUBLISH

1. `TrackerAdapter.approve(item)` — existing behaviour (add approved label, remove pending)
2. Add label: `score-{round(score)}` (e.g. `score-8`)  
   - Label is created in the repo if it doesn't exist (colour `#0075ca`)
3. Post comment:
   ```
   **Editorial Score: 8.2/10**
   relevance=8  news_value=9  audience_fit=7  urgency=6  originality=5
   ```

### On SKIP

Score is logged at DEBUG level only. No label or comment added.

---

## Pipeline Ordering

`run()` returns `approved` list sorted by score descending. This means the highest-scoring items surface first when the pipeline picks them up.

---

## Backward Compatibility

- `mode: binary` (existing default) bypasses scoring entirely — no behaviour change
- If `mode: score` but synthesis has no `SCORES:` lines, all dimensions default to neutral; item scores near `score_threshold` and likely PUBLISH (conservative)
- Config merge is additive — repos without `verdict` overrides use global defaults

---

## Files Changed

| File | Change |
|------|--------|
| `intake_scoring.py` | New — `ScoreParser`, `ScoringEngine`, `VerdictRouter` |
| `intake_triage.py` | Import and call scoring; pass score to tracker; sort approved by score |
| `tracker_adapter.py` | Add `add_label(item, label)` and `post_comment(item, text)` methods |
| `config_schema.py` | Add `score_threshold`, `score_formula`, `score_dimensions`, `score_scale` to `VerdictConfig` |
| `config.yaml` | Add score defaults under `intake_triage.verdict` |
| `discussions/intake-triage.yaml` | Update `verdict_format` to include SCORES line |
| `tests/test_intake_scoring.py` | Unit tests for parser, engine, router |
