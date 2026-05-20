# Editorial Triage Stage Design

**Date:** 2026-05-20  
**Status:** Approved  
**Repo:** ai-software-house  

---

## Problem

The ai-it-press pipeline currently processes every story that passes the RSS watcher filters. As the volume of incoming news grows, many stories waste agent cycles because they are out of scope, low-quality, or irrelevant to the target audience. There is no mechanism to filter stories before the expensive writing and translation stages run. Editors also have no way to influence the angle of a story before it is written.

---

## Goal

Add an **editorial triage stage** at the start of the press pipeline that:

1. Convenes a small editorial team to discuss whether a story is worth publishing.
2. Issues a structured `PUBLISH` or `SKIP` verdict.
3. On `SKIP`: closes the GitHub issue with an explanation comment and aborts the pipeline.
4. On `PUBLISH`: passes editorial notes (angle/focus guidance) forward to the writer.
5. Provides a tunable "net" so operators can adjust scope without touching code.

---

## Architecture

```
[RSS watcher triggers pipeline]
        ↓
news_triage                  ← new first stage (wraps discuss + verdict parsing)
  ├─ PUBLISH → editorial_notes stored in PipelineResult
  │            pipeline continues normally
  └─ SKIP    → post comment + close GitHub issue
               pipeline aborts (PipelineStage.stop_if)
        ↓ (PUBLISH only)
discuss_news_analysis
        ↓
news_writer  ← receives editorial_notes in prompt
        ↓
discuss_news_draft → news_editor → translate → news_reviewer → news_article_pr
```

The triage discussion is a standard `_stage_discuss()` call wrapped by a thin `_stage_news_triage()` method that parses the verdict and handles the SKIP path.

---

## Components

### 1. `discussions/news-triage.yaml`

```yaml
name: news_triage
description: Editorial triage — decide publish or skip
participants:
  - editorial_director
  - audience_specialist
  - news_editor
homework_round: true
max_rounds: 2
early_exit: true
context_fields:
  - article_title
  - article_draft
verdict_format: |
  End your final message with:
  VERDICT: PUBLISH|SKIP
  EDITORIAL_NOTES: <one sentence: angle for writer, or reason for skip>
```

- `homework_round: true` — each editor researches the story before discussion begins.
- `max_rounds: 2` — caps LLM cost per story.
- `early_exit: true` — stops early on unanimous consensus.
- `context_fields` — injects `article_title` and raw RSS content / initial draft into the discussion prompt.

### 2. `roles/editorial_director.md` (new)

Evaluates:
- Strategic importance of the story in the IT/tech space.
- Whether the story has enough substance to write a meaningful article.
- Topic relevance against the configured scope.

Prompt template uses `{triage_scope}` substitution.

### 3. `roles/audience_specialist.md` (new)

Evaluates:
- Cultural fit for the Hong Kong / Cantonese-speaking tech professional audience.
- Whether local readers will care enough to read it.
- Whether the story has a local angle worth highlighting.

Prompt template uses `{triage_scope}` substitution.

### 4. `roles/news_editor.md` (existing, no change)

Evaluates:
- Source credibility.
- Whether there is enough raw material to write a complete article.
- Basic editorial standards.

### 5. `config.yaml` — new `press.triage` section

```yaml
press:
  triage:
    scope: |
      Focus areas: AI, software development tools, cybersecurity, Hong Kong tech scene,
      enterprise software, open-source.
      Audience: HK Cantonese-speaking tech professionals.
    min_score: 2
```

- `scope`: injected as `{triage_scope}` into `editorial_director` and `audience_specialist` role prompts at instantiation. Edit this to shift the editorial net.
- `min_score`: minimum number of PUBLISH votes needed (out of 3 editors). Default 2.

---

## Data Model

Two new fields added to `PipelineResult`:

```python
editorial_verdict: str = ""   # "PUBLISH" or "SKIP"
editorial_notes: str = ""     # angle/focus for writer, or reason for skip
```

Both included in `to_dict()` / `from_dict()`.

---

## Stage Implementation: `_stage_news_triage()`

```
1. Run news-triage.yaml discussion via _stage_discuss()
2. Extract final moderator turn text
3. Call _parse_triage_verdict(text) → {verdict, notes}
4. Store result.editorial_verdict, result.editorial_notes
5. If verdict == "SKIP":
   a. Post comment to GitHub issue (quote discussion summary + EDITORIAL_NOTES)
   b. Close the GitHub issue
   c. (Pipeline halted via PipelineStage.stop_if=lambda r: r.editorial_verdict=="SKIP")
6. If verdict == "PUBLISH":
   a. Log editorial notes
   b. Return normally
```

**Fail-open**: any parse error or LLM failure → defaults to `PUBLISH`. Pipeline is never silently dropped.

### `_parse_triage_verdict(text) → dict`

Regex extracts:
- `VERDICT: (PUBLISH|SKIP)` — case-insensitive
- `EDITORIAL_NOTES: (.+)` — rest of line

Returns `{"verdict": "PUBLISH", "notes": ""}` on any failure.

---

## Pipeline Abort Mechanism

Pipeline abort uses the existing `PipelineStage.stop_if` mechanism — no new `pipeline_abort` field on `PipelineResult`. The `news_triage` stage is registered with:

```python
stop_if=lambda r: r.editorial_verdict == "SKIP",
stop_message="🚫 Editorial triage: story skipped — pipeline aborted.",
```

The `run()` loop checks `stop_if` after each stage and halts if it returns `True`. No code changes to `run()` were needed.

---

## Editorial Notes Flow

`news_writer` receives `result.editorial_notes` in its prompt:

```python
if result.editorial_notes:
    prompt = f"[EDITORIAL NOTES]\n{result.editorial_notes}\n\n" + prompt
```

This gives the writer the angle/focus decided by the triage team without changing the writer's role prompt.

---

## Pipeline YAML Change

```yaml
# pipelines/news-article.yaml
stages:
  - news_triage             # ← new first stage (wraps discussion + SKIP/PUBLISH logic)
  - discuss_news_analysis
  - news_writer
  - discuss_news_draft
  - news_editor
  - translate_cantonese
  - translate_zh_traditional
  - news_reviewer
  - news_article_pr
```

---

## Tuning the Net

Operators tune editorial scope by editing `config.yaml`:

```yaml
press:
  triage:
    scope: |
      <edit this block>
    min_score: 2  # lower to 1 for more permissive, keep at 3 for strict
```

Role-level tuning: edit `roles/editorial_director.md` or `roles/audience_specialist.md` to change evaluation criteria. No code changes needed.

---

## Error Handling

| Situation | Behaviour |
|-----------|-----------|
| LLM returns no VERDICT line | Fail-open → PUBLISH |
| Discussion stage times out | Fail-open → PUBLISH |
| GitHub issue close fails | Log warning, do NOT abort the abort — story is still skipped |
| `article_draft` empty | Triage still runs with title only; editors may recommend SKIP |

---

## Testing

### Unit tests (`tests/test_news_triage.py`)

- `test_parse_verdict_publish` — standard PUBLISH output
- `test_parse_verdict_skip` — standard SKIP output
- `test_parse_verdict_malformed` — no VERDICT line → PUBLISH (fail-open)
- `test_parse_verdict_llm_failure` — exception input → PUBLISH (fail-open)
- `test_parse_verdict_case_insensitive` — `publish` lowercase accepted

### Stage tests (`tests/test_news_stages.py`)

- `test_stage_triage_publish_path` — editorial_notes stored, no abort
- `test_stage_triage_skip_path` — pipeline_abort set, GitHub issue closed
- `test_stage_triage_fail_open` — discussion crashes → PUBLISH, no abort

### Integration tests

- `test_pipeline_aborts_on_skip` — full run() returns after triage, no subsequent stage called
- `test_pipeline_continues_on_publish` — run() proceeds to news_writer with editorial_notes

### Discussion YAML test

- `test_news_triage_yaml_valid` — YAML loads, required fields present, participants exist as role files

---

## Files Changed

| File | Change |
|------|--------|
| `discussions/news-triage.yaml` | Create |
| `roles/editorial_director.md` | Create |
| `roles/audience_specialist.md` | Create |
| `orchestrator.py` | `PipelineResult` fields, `pipeline_abort` check in `run()`, `_stage_news_triage()`, `_parse_triage_verdict()`, stage registry, `news_writer` editorial notes injection |
| `config.yaml` | Add `press.triage` section |
| `config_schema.py` | Add `TriageConfig`, `PressConfig` dataclasses |
| `pipelines/news-article.yaml` | Prepend `discuss_news_triage` |
| `tests/test_news_triage.py` | Create |
| `tests/test_news_stages.py` | Add triage stage tests |

---

## Out of Scope

- UI or dashboard for triage decisions.
- Human-in-the-loop approval (all decisions are AI-only).
- Retroactive re-triage of already-published articles.
- Per-repo triage config (global config only for now).
