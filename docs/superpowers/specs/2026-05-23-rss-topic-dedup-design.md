# Design: RSS Topic Deduplication

**Date:** 2026-05-23
**Status:** Approved
**Scope:** `rss_watcher.py` + new `topic_dedup.py`

---

## Problem

The RSS watcher creates one GitHub issue per article URL. When 3 different sources (e.g. The Register, Ars Technica, BleepingComputer) all report the same story, 3 separate issues are created. Each goes through intake-triage independently, producing 3 PUBLISH verdicts and 3 near-identical articles.

Follow-up coverage (a significant new development on a story from 3+ days ago) must still create a new issue — it is not a duplicate.

---

## Solution Overview

Before creating a new issue, `rss_watcher.py` fetches recent open issues from the press repo and runs a similarity check. If a match is found, it decides whether to:

1. **Merge** — add the new source as a comment on the existing issue (no new issue)
2. **Follow-up** — create a new issue with a `follow-up` label and a reference to the original
3. **Create new** — no match found; proceed as normal

```
RSS entry found (not seen in DB)
        ↓
Fetch recent open issues (news-article label, within dedup_window_hours)
        ↓
Run similarity check (fuzzy / keyword / LLM — configurable)
        ↓
    ┌───┴──────────────────────┐
No match               Match found
    ↓                      ↓
Create new issue    Is it a follow-up?
                    (time / content / both — configurable)
                       ↙          ↘
                  Yes              No
                   ↓                ↓
           Create new issue    Add source URL as
           with follow-up      comment on existing
           label + link        issue (no new issue)
```

---

## New Module: `topic_dedup.py`

### `TopicDeduplicator`

```python
class TopicDeduplicator:
    def __init__(self, cfg: dict, token: str)
    def check(self, entry: dict, open_issues: list[dict]) -> DedupeResult
```

`DedupeResult` is a dataclass:
```python
@dataclass
class DedupeResult:
    action: Literal["CREATE_NEW", "ADD_SOURCE", "CREATE_FOLLOWUP"]
    matched_issue: dict | None   # the existing issue if action != CREATE_NEW
    matched_number: int | None
```

### Similarity Methods (all configurable)

**`fuzzy`** — token-set ratio on issue titles using `difflib.SequenceMatcher` (no extra dependencies). Threshold: `fuzzy_threshold` (default 0.75).

**`keyword`** — extract named entities from title + summary using simple regex (product names, CVE IDs `CVE-\d{4}-\d+`, version strings, company names from a stopword-filtered noun list). Match if `keyword_min_overlap` (default 2) entities in common.

**`llm`** — send both titles + summaries to `similarity.llm_model`. Prompt: "Are these two news stories about the same event? Answer YES or NO with one sentence of reasoning." Parse YES/NO from response.

**`all`** — run all configured methods; a match requires **any one** to fire (OR logic). This maximises recall. False positives are kept low in practice by the specificity of keyword/CVE matching and the LLM prompt's reasoning requirement — but note that only one method needs to match, not all three.

### Follow-up Detection (configurable via `follow_up.mode`)

| Mode | Logic |
|------|-------|
| `time` | `now - issue.created_at >= min_age_hours` |
| `content` | LLM compares summaries: "Does the new article contain significant new facts not present in the original?" → YES/NO |
| `both` | Both time AND content conditions must be true |

If follow-up is detected: create a new issue with label `follow-up` and prepend the issue body with `⚡ Follow-up to #N (original: "<title>")`.

---

## Changes to `rss_watcher.py`

### New helper: `_fetch_open_issues(repo, label, token) → list[dict]`
- Calls `GET /repos/{repo}/issues?state=open&labels={label}&per_page=100&sort=created&direction=desc`
- Fetches open issues with the specified label, sorted newest-first
- Excludes pull requests
- Returns normalized dicts with keys: `number`, `title`, `body`, `created_at`, `html_url`
- Called **once per `process_feeds()` run** and cached in a local variable (not re-fetched per entry)
- Returns an empty list on any error

### Modified `process_feeds()` flow
```
for entry in feed:
    if url in seen_urls: continue
    if age > max_age_hours: continue

    if topic_dedup.enabled:
        result = deduplicator.check(entry, open_issues)
        if result.action == ADD_SOURCE:
            _post_source_comment(repo, result.matched_number, entry, token)
            _mark_seen(db, url)
            continue
        elif result.action == CREATE_FOLLOWUP:
            entry = _enrich_as_followup(entry, result.matched_issue)
            # fall through to create issue with follow-up label

    _create_github_issue(...)
    _mark_seen(db, url)
```

### New helper: `_post_source_comment(repo, issue_number, entry, token)`
Posts a comment in this format:
```
🔗 Additional source: {source_name}
**URL:** {url}
**Summary:** {summary}
```

---

## Config Schema

New optional block under `rss_watcher:` in `config.local.yaml`:

```yaml
rss_watcher:
  dedup:
    enabled: true
    method: all                    # fuzzy | keyword | llm | all
    fuzzy_threshold: 0.85          # 0.0–1.0; only used if method includes fuzzy
    keyword_min_overlap: 2         # min shared entities; only used if method includes keyword
    followup_llm_model: "dashscope/qwen3-plus"  # only used if method includes llm or followup_mode includes content
    add_source_max_age_hours: 48   # issue age below this → ADD_SOURCE; above → CREATE_FOLLOWUP
    followup_mode: time            # time | content | both
    min_age_hours: 168             # hours since issue creation before a follow-up is considered (time/both modes)
```

If `dedup` is absent or `enabled: false`, `rss_watcher.py` behaves exactly as before (no breaking change).

**Multi-target config** (each target has independent dedup settings):
```yaml
rss_watcher:
  targets:
    - press_repo: owner/security-press
      label: security
      feeds: [...]
      dedup:
        enabled: true
        method: keyword
    - press_repo: owner/software-press
      label: software
      feeds: [...]
      dedup:
        enabled: true
        method: fuzzy
        fuzzy_threshold: 0.85

---

## What the Writer Sees

The pipeline `news-article.yaml` requires **no changes**. The `discuss_news_analysis` stage receives `issue_body` + comments via the existing `context_fields` mechanism. Agents see all sources and naturally synthesise a multi-source article.

**Merged issue (3 sources, same day):**
```
Issue body:
  Source: The Register
  URL: https://theregister.com/...
  Summary: GitHub traces mass repository breach to stolen credentials...

Comment 1 (by rss-watcher):
  🔗 Additional source: Ars Technica
  URL: https://arstechnica.com/...
  Summary: ...

Comment 2 (by rss-watcher):
  🔗 Additional source: BleepingComputer
  URL: https://bleepingcomputer.com/...
  Summary: ...
```

**Follow-up issue:**
```
⚡ Follow-up to #142 (original: "GitHub traces mass repository breach...")
Source: SecurityWeek
URL: https://securityweek.com/...
Summary: GitHub has now confirmed 1.2M repositories were accessed...
```

---

## Out of Scope

- Deduplication against **already-published articles** (not open issues). This is handled downstream by RAG memory in `discuss_news_analysis`. Can be added later.
- Merging issues that were **already created** before this feature was deployed. Only new entries are checked.
- Automatic closing of duplicate issues already in the system.

---

## Testing

- Unit tests for each similarity method (`test_topic_dedup.py`)
- Test `process_feeds()` with mocked `_fetch_open_issues` returning a matching issue → assert `_post_source_comment` called, no new issue created
- Test follow-up path: matching issue older than `min_age_hours` + LLM returns YES → assert new issue created with `follow-up` label
- Test `topic_dedup.enabled: false` → assert behaviour identical to current `rss_watcher.py`
