# Press Team Design

**Date:** 2026-05-18  
**Status:** Approved  
**Repos involved:** `ai-software-house`, `ai-it-press`, `hklug-sitegen`

---

## Overview

Build a fully automated AI press team using ai-software-house as the engine. The system monitors RSS feeds and manual GitHub issues, researches and writes news articles, and publishes them to a static site via PR-based human review.

**Design principle (Option B):** ai-software-house stays generic. All press-specific configuration (pipeline, roles, discussions) lives in ai-it-press.

---

## Repository Responsibilities

| Repo | Owns |
|------|------|
| **ai-software-house** | Engine: `news_writer` + `news_editor` agents, `fetch_url` tool, `rss_watcher.py` script, `pipeline_file:` watcher feature, orchestrator wiring for new stages |
| **ai-it-press** | Press config: pipeline YAML, role files, discussion presets, articles as PRs, GitHub Action to publish |
| **hklug-sitegen** | Receives converted `.txt` article files in `data/news/` via GitHub Action from ai-it-press |

---

## Pipeline Flow

```
[RSS feeds / manual issue]
        ↓
rss_watcher.py (cron every 15 min on ai-software-house host)
  → reads feed list from config.local.yaml
  → deduplicates by URL (sqlite cache: rss_seen.db)
  → creates GitHub Issue in ai-it-press:
      title: "Article: <headline>"
      body:  source_url, source_name, summary snippet
      labels: news-article
        ↓
ai-software-house watcher picks up issue (label: news-article)
  → reads repos-available/ai-it-press.yaml
  → reads pipeline from ai-it-press/pipelines/news-article.yaml
  → Pipeline stages:
      1. discuss_news_analysis   (research + angle debate, homework_llm = web search)
      2. news_writer             (writes markdown article, uses discussion_synthesis)
      3. discuss_news_draft      (writer/editor back-and-forth on draft quality)
      4. news_editor             (final polish, accuracy check, frontmatter)
  → Opens PR in ai-it-press:
      branch: article/YYYYMMDD-HHmm-<slug>
      file:   articles/YYYYMMDD-HHmm-<slug>.md
        ↓
Human editor reviews PR → merges
        ↓
GitHub Action (ai-it-press .github/workflows/publish.yml)
  → detects new files in articles/
  → converts markdown + frontmatter → hklug-sitegen .txt format
  → commits to wanleung/hklug-sitegen/data/news/YYYYMMDD-HHMMSS.txt
  → hklug-sitegen CI regenerates static site
```

---

## Article Format

Articles in `ai-it-press/articles/` use standard markdown with YAML frontmatter:

```markdown
---
title: "OpenAI Releases GPT-5"
date: 2025-07-01T14:30:00
author: AI Press Team
source_url: https://example.com/original-article
tags: [ai, llm, openai]
---

Article body in markdown...
```

The GitHub Action converts this to hklug-sitegen `.txt` format:

```
Date: 2025-07-01 14:30:00
Author: AI Press Team
Title: OpenAI Releases GPT-5

<article body as HTML converted from markdown>
```

---

## New Code in ai-software-house

### A. `fetch_url` tool (`tools/fetch_url.py`)

Simple HTTP GET returning page text. Used by `news_writer` during its homework round for deep research on source articles. Falls back to plain requests if Playwright is unavailable.

```python
@tool
def fetch_url(url: str) -> str:
    """Fetch the text content of a web page."""
```

### B. `agents/news_writer.py`

Generic writer agent. Reads its role from the calling repo's `roles/news_writer.md`.

- Accepts `discussion_synthesis` from `discuss_news_analysis` output
- Uses `homework_llm` for web research before writing (MCP web search)
- Outputs clean markdown article with frontmatter

### C. `agents/news_editor.py`

Generic editor agent. Reads its role from the calling repo's `roles/news_editor.md`.

- Accepts article draft (from `news_writer` output or `discuss_news_draft` synthesis)
- Checks for factual accuracy, clarity, and tone
- Finalises frontmatter (tags, date, author)
- Outputs final markdown ready to commit as a PR file

### D. `rss_watcher.py`

Standalone script, run as a cron job every 15 minutes.

- Reads `rss_feeds:` list from `config.local.yaml`
- Fetches each feed, parses entries
- Deduplicates by URL using `rss_seen.db` (sqlite)
- For new entries: creates GitHub Issue in the configured press repo
- Skips entries older than configurable `max_age_hours` (default: 48)

Config in `config.local.yaml`:

```yaml
rss_watcher:
  press_repo: wanleung/ai-it-press
  label: news-article
  max_age_hours: 48
  feeds:
    - url: https://feeds.feedburner.com/oreilly/radar
      source: O'Reilly Radar
    - url: https://www.linux.com/feed/
      source: Linux.com
    # add more feeds here
```

### E. Orchestrator: `pipeline_file:` feature

When a repo config has `pipeline_file:`, the watcher reads the pipeline YAML from the cloned target repo at dispatch time rather than looking for a built-in orchestrator stage name.

```yaml
# repos-available/ai-it-press.yaml
tracker_repo: wanleung/ai-it-press
pipeline_file: pipelines/news-article.yaml   # read from cloned repo
labels:
  news-article: news_article_pipeline        # label → trigger name (logs only; pipeline comes from pipeline_file)
```

The pipeline YAML in the target repo specifies stages by name:

```yaml
# ai-it-press/pipelines/news-article.yaml
stages:
  - discuss_news_analysis
  - news_writer
  - discuss_news_draft
  - news_editor
```

Stages are resolved against the orchestrator's stage registry. Only registered stage names are accepted (no arbitrary code execution from the pipeline YAML).

---

## ai-it-press File Layout

```
ai-it-press/
├── .github/
│   └── workflows/
│       └── publish.yml          # convert + push to hklug-sitegen on PR merge
├── articles/                    # merged articles (markdown with frontmatter)
├── discussions/
│   ├── news-analysis.yaml       # pre-write: angle + research debate
│   └── news-draft.yaml          # post-draft: writer/editor quality review
├── pipelines/
│   └── news-article.yaml        # stage list
└── roles/
    ├── news_writer.md            # writer role prompt
    └── news_editor.md            # editor role prompt
```

### `discussions/news-analysis.yaml`

Pre-write discussion. Participants debate the story angle, key facts to verify, and scope before the writer starts. Uses `homework_llm` for web research round.

```yaml
topic: "News story analysis: angle, scope, key facts to verify"
rounds: 2
participants:
  - role: news_writer
    llm: "opencode-go/qwen3.6-plus"
    homework_llm: "ollama/qwen3:8b"    # research round
  - role: news_editor
    llm: "opencode-go/qwen3.6-plus"
    homework_llm: "ollama/qwen3:8b"
context_fields:
  - issue_body
```

### `discussions/news-draft.yaml`

Post-draft discussion. Editor critiques the draft; writer revises. Uses no homework round (pure reasoning on the draft text).

```yaml
topic: "Draft review: accuracy, clarity, completeness"
rounds: 2
participants:
  - role: news_writer
    llm: "opencode-go/qwen3.6-plus"
  - role: news_editor
    llm: "opencode-go/qwen3.6-plus"
context_fields:
  - issue_body
  - previous_stage_output    # news_writer's draft (new context field, see Implementation step 3)
```

Note: `previous_stage_output` is a new context field to be added in implementation step 3 (orchestrator `pipeline_file:` feature). It injects the previous pipeline stage's output into discussion context.

---

## ai-software-house Repo Config

```yaml
# repos-available/ai-it-press.yaml
tracker_repo: wanleung/ai-it-press
pipeline_file: pipelines/news-article.yaml
labels:
  news-article: news_article_pipeline

llm:
  overrides:
    news_writer: "opencode-go/qwen3.6-plus"
    news_editor: "opencode-go/qwen3.6-plus"
    discussion: "opencode-go/qwen3.6-plus"
  homework_llm: "ollama/qwen3:8b"
```

Activate by symlinking: `ln -s ../repos-available/ai-it-press.yaml repos-enabled/`

---

## MCP Web Search

The `news_writer` uses the existing Google Search MCP server during its homework round. No new setup required — add the tool to the `news_writer` agent's tool registry.

If Google Search MCP is unavailable, the agent falls back to `fetch_url` only (direct URL fetching from issue body).

---

## GitHub Action: publish.yml

Triggered on PR merge to `main` in ai-it-press. Converts articles and pushes to hklug-sitegen.

```yaml
name: Publish articles to hklug-sitegen
on:
  pull_request:
    types: [closed]
    branches: [main]

jobs:
  publish:
    if: github.event.pull_request.merged == true
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 2

      - name: Find new articles
        id: articles
        run: |
          git diff --name-only HEAD~1 HEAD -- articles/ > new_articles.txt
          cat new_articles.txt

      - name: Convert and push to hklug-sitegen
        env:
          SITEGEN_PAT: ${{ secrets.SITEGEN_PAT }}
        run: |
          python3 scripts/convert_articles.py new_articles.txt
          # script clones hklug-sitegen, copies .txt files, commits, pushes
```

The `scripts/convert_articles.py` script:
1. Parses YAML frontmatter from each article
2. Converts markdown body to HTML (via `markdown` library)
3. Formats as `Date/Author/Title/Content` `.txt`
4. Filename: `YYYYMMDD-HHMMSS.txt` from article `date` field
5. Commits to `wanleung/hklug-sitegen` using `SITEGEN_PAT` secret

---

## What Is Not in Scope (Deferred)

| Feature | Reason |
|---------|---------|
| Auto-merge rules | Human editor reviews all PRs initially |
| RSS feed auto-discovery | Feed list curated manually in config |
| Multi-language articles | Future extension |
| Duplicate article detection across issues | RSS dedup covers most cases |
| Editor-in-chief agent | Manual human review covers this |

---

## Implementation Order

1. `fetch_url` tool (small, unblocks writer agent)
2. `news_writer` agent + `news_editor` agent
3. Orchestrator `pipeline_file:` feature + watcher wiring
4. `rss_watcher.py` script
5. `repos-available/ai-it-press.yaml` config
6. ai-it-press: role files, discussion YAMLs, pipeline YAML
7. ai-it-press: `scripts/convert_articles.py` + `publish.yml` GitHub Action
8. End-to-end smoke test with a manual issue
