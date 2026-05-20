# News Reviewer Agent — Design Spec

**Date:** 2026-05-20  
**Status:** Approved  
**Scope:** ai-software-house pipeline — press team (`news-article.yaml`)

---

## Problem

The current news article pipeline generates English articles and translates them to Written
Cantonese (zh-hk) and Formal Traditional Chinese (zh-tw), but has no automated quality gate.
Issues that can slip through:

- Hallucinated facts (wrong version numbers, dates, product names not in the source)
- Awkward phrasing or LLM artefacts in the final article
- Simplified Chinese characters in zh-hk or zh-tw articles
- Cantonese colloquialisms in zh-tw, or Mandarin patterns in zh-hk
- Agent commentary accidentally included in the article body

---

## Design

### Pipeline Position

The `news_reviewer` stage runs **after all translations** and **before the PR stage**, so it
can check English quality and translation character correctness in one pass.

```
discuss_news_analysis
  → news_writer
  → discuss_news_draft
  → news_editor
  → translate_cantonese
  → translate_zh_traditional
  → news_reviewer            ← NEW
  → news_article_pr
```

### Agent: `news_reviewer`

**Input:**
- Polished English article (markdown + frontmatter, including `source_url`)
- zh-hk translation
- zh-tw translation
- Original source content (fetched from `source_url` at runtime)

**One LLM call** performs all checks and returns a structured verdict.

**Checks performed:**

#### English — Fact Plausibility
- Version numbers, dates, product names match the source
- No invented quotes or statistics absent from the source
- Technical claims consistent with the source
- No agent commentary in the article body

#### English — Wording QA
- No awkward phrasing or grammar issues
- Headline matches article content
- Article stays on topic

#### zh-hk — Written Cantonese
- All characters are Traditional Chinese (no Simplified: 国→國, 软→軟, 网→網, etc.)
- Uses Cantonese vocabulary and particles (係, 唔係, 喺, 咁, 嘅, 咗…)
- No Mainland Mandarin-only vocabulary patterns

#### zh-tw — Formal Traditional Chinese
- All characters are Traditional Chinese (no Simplified)
- Uses Taiwanese Mandarin vocabulary (軟體 not 软件, 影片 not 视频, 網路 not 网络…)
- No Cantonese colloquialisms
- No Mainland Mandarin vocabulary patterns

### Output Format

```
VERDICT: PASS | NEEDS_REVISION
ISSUES:
- [FACT] ...
- [WORDING] ...
- [ZH_HK] Simplified character found: "软" should be "軟"
- [ZH_TW] Mainland vocabulary: "软件" should be "軟體"
CONFIDENCE: high | medium | low
```

`PASS` with `low` confidence still passes — the reviewer is not certain enough to block.
Only `NEEDS_REVISION` triggers the retry loop.

---

## Retry Logic

### English issues (`[FACT]` or `[WORDING]` in issues list)

Since translations are derived from the English article, English issues cascade:

```
news_reviewer (NEEDS_REVISION, English issues)
  → news_editor  (reviewer notes injected into prompt)
  → translate_cantonese   (redo)
  → translate_zh_traditional  (redo)
  → news_reviewer
```

### Translation-only issues

Only the affected language is retried:

```
news_reviewer (NEEDS_REVISION, ZH_HK only)
  → translate_cantonese  (reviewer notes injected)
  → news_reviewer
```

```
news_reviewer (NEEDS_REVISION, ZH_TW only)
  → translate_zh_traditional  (reviewer notes injected)
  → news_reviewer
```

### Max retries

Default: **2 retries** per loop (English loop and each translation loop independently).
After max retries, accept the article and continue to PR regardless.

Configurable in `config.yaml` per repo:

```yaml
press:
  reviewer_max_retries: 2   # default
```

---

## Implementation

### New files

| File | Purpose |
|------|---------|
| `agents/news_reviewer.py` | `NewsReviewerAgent` — single LLM call, structured verdict output |
| `roles/news_reviewer.md` | Role prompt: fact check + wording QA + character set rules |

### Pipeline change

`pipelines/news-article.yaml` — insert `news_reviewer` before `news_article_pr`:

```yaml
stages:
  - discuss_news_analysis
  - news_writer
  - discuss_news_draft
  - news_editor
  - translate_cantonese
  - translate_zh_traditional
  - news_reviewer             # ← add
  - news_article_pr
```

### Orchestrator change

`orchestrator.py` — handle `news_reviewer` stage result:
- Parse `VERDICT` and `ISSUES` from output
- If `NEEDS_REVISION` with English issues → re-run `news_editor` + both translations + reviewer
- If `NEEDS_REVISION` with translation-only issues → re-run specific translator + reviewer
- Track retry count per loop; skip reviewer after max retries

### Config change

`config.yaml` — add model assignment and retry knob:

```yaml
model_overrides:
  news_reviewer: "openai/gpt-4.1"   # or fast model

press:
  reviewer_max_retries: 2
```

---

## Error Handling

- If `source_url` is missing or fetch fails: skip fact check, still run wording + character checks
- If reviewer LLM output is unparseable: treat as `PASS` with a logged warning (never block on bad reviewer output)
- If reviewer itself errors: log warning, skip reviewer, continue to PR

---

## Out of Scope

- Human-in-the-loop review (future work)
- Checking image captions or metadata beyond frontmatter
- Cross-article consistency (duplicate detection)
