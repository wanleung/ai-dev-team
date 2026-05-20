# AI Software House — Operations Guide

## Table of Contents

1. [Connecting to Local Ollama](#1-connecting-to-local-ollama)
2. [Multi-Ollama Pool Setup](#2-multi-ollama-pool-setup)
3. [LiteLLM Proxy for Multi-Host Isolation](#3-litellm-proxy-for-multi-host-isolation)
4. [RAG MCP — Moving to a New Machine or Rebuilding](#4-rag-mcp--moving-to-a-new-machine-or-rebuilding)
5. [Reading GitHub Issues, PRs and Comments](#5-reading-github-issues-prs-and-comments)
6. [Pipeline Self-Chaining (Auto Re-Label)](#6-pipeline-self-chaining-auto-re-label)
7. [Token Usage & Cost Tracking](#7-token-usage--cost-tracking)
8. [Repo Watcher Config (repos-available / repos-enabled)](#8-repo-watcher-config-repos-available--repos-enabled)
9. [PR Watcher](#9-pr-watcher)
10. [Multi-Agent Discussion Stages](#10-multi-agent-discussion-stages)
11. [Cantonese & Traditional Chinese Translation Stages](#11-cantonese--traditional-chinese-translation-stages)
12. [News Reviewer Agent](#12-news-reviewer-agent)
13. [Editorial Triage Stage](#13-editorial-triage-stage)
14. [Batch Intake Triage Module](#14-batch-intake-triage-module)

---

## 1. Connecting to Local Ollama

The Ollama backend uses the OpenAI-compatible API exposed by Ollama at `/v1`.

### Localhost

```yaml
# config.yaml or config.local.yaml
llm:
  model: "ollama/llama3.2"         # any model pulled in Ollama
  ollama_url: "http://localhost:11434"
  ollama_think: false              # disable CoT — faster responses
  ollama_stream: true
```

### Remote Ollama on LAN

```yaml
llm:
  model: "ollama/qwen3.6"
  ollama_url: "http://10.100.1.30:11434"
  ollama_stream: true              # REQUIRED for remote — prevents TCP idle timeout
```

### Per-Agent Override (mixed cloud + local)

Route specific agents to Ollama while keeping cloud for others:

```yaml
llm:
  model: "openai/gpt-4.1"         # default = cloud
  overrides:
    engineer: "ollama/qwen2.5-coder"
    qa_engineer: "ollama/qwen2.5-coder"
    # cloud agents (architect, PM, etc.) use the default model above
```

### Verify Ollama is Running

```bash
curl http://localhost:11434/api/tags   # list available models
ollama pull qwen2.5-coder              # pull a model if needed
```

### Useful Environment Variables

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_TIMEOUT` | none (infinite) | Request timeout in seconds. Set to `300` if you see timeouts on large models. |

### Run the Pipeline with Ollama

```bash
python main.py "Build a REST API" --model ollama/qwen2.5-coder --no-github
```

---

## 2. Multi-Ollama Pool Setup

### Scenario

- **Fast machine**: 1 thread, powerful/smart model (e.g. qwen3.6)
- **Low-end cluster**: multiple threads, cheaper model (e.g. qwen2.5-coder)

### How Pools Work

The `llm.pools` setting in `config.yaml` controls a per-backend semaphore. All `ollama/*` models share a single `"ollama"` semaphore — there is no per-host distinction natively.

### Option A: Native Per-Agent Routing (simple, limited isolation)

Route smart agents to the fast machine and bulk agents to the cluster via `ollama_url` in dict-form overrides. The semaphore is shared, but routing is correct:

```yaml
# config.local.yaml
llm:
  # Default → low-end cluster (cheap, multi-threaded)
  model: "ollama/qwen2.5-coder"
  ollama_url: "http://10.100.1.50:11434"   # low-end cluster
  ollama_stream: true

  pools:
    ollama: 4    # allow up to 4 concurrent across ALL ollama hosts

  overrides:
    # Reasoning-heavy agents → fast smart machine (1 thread only)
    architect:
      model: "ollama/qwen3.6"
      ollama_url: "http://10.100.1.30:11434"
      ollama_think: true
      ollama_stream: true

    architect_reviewer:
      model: "ollama/qwen3.6"
      ollama_url: "http://10.100.1.30:11434"
      ollama_stream: true

    tier_reviewer:
      model: "ollama/qwen3.6"
      ollama_url: "http://10.100.1.30:11434"
      ollama_think: true
      ollama_stream: true

    # Bulk agents → low-end cluster
    engineer:
      model: "ollama/qwen2.5-coder"
      ollama_url: "http://10.100.1.50:11434"
      ollama_think: false
      ollama_stream: true

    junior_engineer:
      model: "ollama/qwen2.5-coder"
      ollama_url: "http://10.100.1.50:11434"
      ollama_think: false
      ollama_stream: true

    qa_engineer:
      model: "ollama/qwen2.5-coder"
      ollama_url: "http://10.100.1.50:11434"
      ollama_think: false
      ollama_stream: true
```

**Limitation**: The shared `ollama` semaphore does not enforce per-host concurrency. Use Option B (LiteLLM) for proper isolation.

---

## 3. LiteLLM Proxy for Multi-Host Isolation

LiteLLM proxy sits in front of both Ollama servers, exposes a single OpenAI-compatible endpoint, and enforces per-model RPM limits independently. No code changes to ai-software-house are needed.

### Step 1 — Install LiteLLM

```bash
pip install litellm[proxy]
```

### Step 2 — Configure LiteLLM

Create `litellm_config.yaml` (on the machine running ai-software-house, or any reachable host):

```yaml
model_list:
  # Smart machine — 1 concurrent request max
  - model_name: smart-llm
    litellm_params:
      model: ollama/qwen3.6
      api_base: http://10.100.1.30:11434
    model_info:
      rpm: 1        # enforces serial access to this host

  # Low-end cluster — 4 concurrent requests
  - model_name: cheap-llm
    litellm_params:
      model: ollama/qwen2.5-coder
      api_base: http://10.100.1.50:11434
    model_info:
      rpm: 4

general_settings:
  master_key: "sk-local"   # remove this line to disable auth
```

### Step 3 — Start the Proxy

```bash
litellm --config litellm_config.yaml --port 4000
```

### Step 4 — Point ai-software-house at LiteLLM

```yaml
# config.local.yaml
llm:
  model: "ollama/cheap-llm"
  ollama_url: "http://localhost:4000"   # LiteLLM proxy
  ollama_stream: true

  # Relax local semaphore — LiteLLM handles rate limiting per host
  pools:
    ollama: 10

  overrides:
    architect:
      model: "ollama/smart-llm"
      ollama_url: "http://localhost:4000"
      ollama_think: true
      ollama_stream: true

    architect_reviewer:
      model: "ollama/smart-llm"
      ollama_url: "http://localhost:4000"
      ollama_stream: true

    tier_reviewer:
      model: "ollama/smart-llm"
      ollama_url: "http://localhost:4000"
      ollama_think: true
      ollama_stream: true

    engineer:
      model: "ollama/cheap-llm"
      ollama_url: "http://localhost:4000"
      ollama_think: false

    junior_engineer:
      model: "ollama/cheap-llm"
      ollama_url: "http://localhost:4000"
      ollama_think: false

    qa_engineer:
      model: "ollama/cheap-llm"
      ollama_url: "http://localhost:4000"
      ollama_think: false
```

### Comparison: Native vs LiteLLM

| | Native (Option A) | LiteLLM Proxy (Option B) |
|---|---|---|
| Per-agent URL routing | ✅ | ✅ |
| Per-host concurrency control | ❌ shared semaphore | ✅ per-model RPM |
| Load balancing across cluster nodes | ❌ | ✅ |
| Setup complexity | Low | Medium |
| Code changes required | None | None |

**Recommendation**: Use LiteLLM if the low-end cluster has 3+ machines or if you need strict isolation of the smart machine's single thread.

---

## 4. RAG MCP — Moving to a New Machine or Rebuilding

The RAG service has two data stores with different migration strategies:

| Store | File | What it contains | Migratable? |
|---|---|---|---|
| **SQLite memory** | `workspace/memory.db` | Tiered run summaries (run/monthly/quarterly) | ✅ Copy directly — this is the source of truth |
| **pgvector embeddings** | Docker volume `rag-mcp_pgdata` | Vector index over memory + codebase + docs | ✅ Rebuild from memory.db + sources, or pg_dump |

> **Most important:** `workspace/memory.db` holds all accumulated pipeline memory. Copy this first. The pgvector index is derived data — it can always be regenerated from `memory.db` and your source repos.

### Step 0: Back up memory.db (always do this first)

```bash
# On old machine — copy memory.db to new machine
scp /path/to/ai-software-house/workspace/memory.db user@new-machine:~/memory.db
```

### Check disk usage

```bash
docker system df              # overall Docker disk usage
docker volume ls              # list volumes
docker volume inspect rag-mcp_pgdata   # see mountpoint and size
```

### Option A: Rebuild from Source (Recommended)

The RAG index is fully regeneratable from your codebase and docs. Use this unless re-indexing would take many hours.

```bash
# On the new machine
cd ai-software-house/rag-mcp

# Configure environment
cp .env.example .env
nano .env    # set POSTGRES_USER, POSTGRES_PASSWORD, OLLAMA_BASE_URL, etc.

# Start services
docker compose up -d

# Apply schema migration
docker exec $(docker compose ps -q postgres) \
  psql -U rag -d rag -f /dev/stdin < migrations/001_create_rag_embeddings.sql

# 1. Re-index memory from the copied memory.db (run this first)
docker compose exec rag-mcp python indexer.py \
  --source memory --db /path/to/memory.db

# 2. Re-index codebase repos (repeat per repo)
docker compose exec rag-mcp python indexer.py \
  --source codebase --path /path/to/your/repo --ext py,ts,go,dart --clean

# 3. Re-index docs / URLs if you had them
docker compose exec rag-mcp python indexer.py \
  --source docs --path /path/to/docs --ext md,txt,rst --clean
docker compose exec rag-mcp python indexer.py \
  --source url --url https://docs.example.com --depth 3
```

> **Note:** Run the indexer via `docker compose exec rag-mcp` so it picks up the correct `DATABASE_URL` and embed backend environment variables defined in `docker-compose.yml`.

### Option B: Migrate Docker Volume (preserve existing index)

Use this to avoid re-indexing large amounts of crawled URL content.

**On the old machine:**
```bash
cd ai-software-house/rag-mcp

# Dump the database to a file
docker compose exec postgres \
  pg_dump -U rag -d rag --no-owner --no-acl -F c -f /tmp/rag_backup.dump

# Copy dump out of container
docker compose cp postgres:/tmp/rag_backup.dump ./rag_backup.dump

# Transfer to new machine
scp ./rag_backup.dump user@new-machine:~/rag_backup.dump
```

**On the new machine:**
```bash
cd ai-software-house/rag-mcp
cp .env.example .env && nano .env

# Start postgres only first (wait for healthy)
docker compose up -d postgres

# Restore the dump
docker compose cp ~/rag_backup.dump postgres:/tmp/rag_backup.dump
docker compose exec postgres \
  pg_restore -U rag -d rag --no-owner --clean /tmp/rag_backup.dump

# Start the full stack
docker compose up -d
```

### Embed Backend for the RAG Indexer

The indexer needs an embed model to generate vectors. Configure via `.env` in `rag-mcp/`:

**Option A — Direct Ollama** (default):
```bash
EMBED_BACKEND=ollama
OLLAMA_BASE_URL=http://10.100.1.30:11434
OLLAMA_MODEL=nomic-embed-text
```

**Option B — Via LiteLLM proxy** (uses your `embed`/`embed-fast` pool):
```bash
EMBED_BACKEND=ollama
OLLAMA_BASE_URL=http://10.100.1.30:4000    # LiteLLM proxy
OLLAMA_MODEL=embed                          # matches model_name in LiteLLM config
```

> LiteLLM's `embed` alias (1024 dims) and `embed-fast` alias (768 dims) both work. Use `embed` for best quality RAG retrieval.

### Free Space on the Old Machine

After migrating or rebuilding on the new machine, clean up the old one:

```bash
cd ai-software-house/rag-mcp

docker compose down                    # stop the RAG stack
docker volume rm rag-mcp_pgdata        # delete the volume data
docker image prune -a                  # remove unused images
docker system prune                    # clean build cache and dangling resources
```

### Update config.yaml After Moving

Point the MCP server config at the new host:

```yaml
# config.yaml or config.local.yaml
mcp:
  servers:
    - name: rag
      type: http
      url: "http://<new-machine-ip>:8001/mcp"
```

---

## 5. Reading GitHub Issues, PRs and Comments

### What Works Automatically Today

| Source | Agents that see it | How |
|---|---|---|
| **Issue body** | All (PM first) | `watcher.py` passes it as `requirement` + `trigger_issue_body` |
| **Issue comments** | Architect only | `_fetch_design_from_issue()` scans comments for `🏗️ System Design` |
| **PR body** | Engineer (revision loop) | `run_revision()` reads it for context |
| **PR review comments** | Engineer (revision loop) | `_collect_pr_feedback()` reads inline + review-level comments |

> **Note**: Issue comments are NOT passed to PM/Engineer on the initial pipeline run — only the issue body is. Human comments added after the issue was created are ignored unless it's a revision loop.

---

### Method 1: GitHub MCP Server (agents actively query GitHub)

This is the cleanest approach. Agents that support tool-calling (Code Reviewer, QA Planner, Senior Engineer) get live GitHub tools: `get_issue`, `list_issue_comments`, `get_pull_request`, `list_pull_request_comments`, `list_issues`, etc.

**Step 1 — Install the official GitHub MCP server:**
```bash
npm install -g @modelcontextprotocol/server-github
```

**Step 2 — Add to `config.yaml`:**
```yaml
mcp:
  servers:
    - name: github
      type: stdio
      command: npx
      args: ["-y", "@modelcontextprotocol/server-github"]
      env:
        GITHUB_TOKEN: "${GITHUB_TOKEN}"

    # Keep your existing servers
    - name: google_search
      type: http
      url: "http://10.100.1.8:8000/mcp"

    - name: rag
      type: http
      url: "http://localhost:8001/mcp"
```

**Step 3 — Enable MCP for engineers if needed (`config.yaml`):**
```yaml
team:
  senior_engineer_use_mcp: true   # give senior engineers GitHub tools
  junior_engineer_use_mcp: false  # keep junior fast (no tool overhead)
```

**Available GitHub MCP tools agents can call:**
- `get_issue` — read issue body + metadata
- `list_issue_comments` — read all comments on an issue
- `get_pull_request` — read PR body + status
- `list_pull_request_comments` — read PR review comments
- `list_issues` — query issues by label/state

> ⚠️ Only agents with tool-calling support use MCP. Code Reviewer and QA Planner always have MCP. Engineer requires `senior_engineer_use_mcp: true`.

---

### Method 2: Pass Issue Comments into the Requirement (all agents see them)

Modify `watcher.py` `_dispatch()` to fetch comments and append them to the requirement before the pipeline runs. All agents (PM, Architect, Engineer) will see the full discussion thread.

Find this block in `watcher.py` (around line 254):
```python
tracker_gh = GitHubClient(tracker_repo, token)
issue = tracker_gh.get_issue(issue_number)
issue_body = issue.get("body") or ""
requirement = (issue_body or issue.get("title") or "").strip()
```

Replace with:
```python
tracker_gh = GitHubClient(tracker_repo, token)
issue = tracker_gh.get_issue(issue_number)
issue_body = issue.get("body") or ""

# Fetch human comments and append to requirement
issue_comments = tracker_gh.get_issue_comments(issue_number)
human_comments = [
    c["body"] for c in issue_comments
    if not c.get("user", {}).get("login", "").endswith("[bot]")
]
if human_comments:
    comments_block = (
        "\n\n---\n\n## Additional Context (Issue Comments)\n\n"
        + "\n\n---\n\n".join(human_comments)
    )
    issue_body = issue_body + comments_block

requirement = (issue_body or issue.get("title") or "").strip()
```

---

### Method 3: Write Full Context in the Issue Body (no code changes)

The simplest approach. When creating a GitHub issue, include all context, constraints, and references in the body. The watcher already passes the full body to PM.

**Recommended issue template:**
```markdown
## Requirement
Build a booking API with calendar integration.

## Context / Constraints
- Must integrate with the existing `UserService`
- See PR #42 for the data model we agreed on
- Authentication: use JWT (see issue #38 for spec)

**Target repo:** wanleung/mybooking

## Acceptance Criteria
- [ ] POST /bookings creates a booking
- [ ] GET /bookings/:id returns booking details
- [ ] Booking conflicts return HTTP 409
```

---

### How the Revision Loop Reads PR Comments

When a human leaves review comments on a generated PR, the watcher detects the `agent-waiting` label and triggers `run_revision()` automatically. It reads:

1. **PR review comments** (`get_pr_review_comments`) — inline code annotations
2. **PR review submissions** (`get_pr_reviews`) — APPROVED / CHANGES_REQUESTED bodies
3. **PR body** — original spec and linked issue number
4. **Linked issue comments** — fetches architect's system design from the issue thread

The engineer then re-implements using the feedback and pushes a new commit to the same branch. Labels track revision rounds (`ai-revision-1`, `ai-revision-2`, etc.) up to `max_revisions` in `config.yaml`.

---

### Summary: Which Method to Use

| Goal | Method |
|---|---|
| Agents actively query any issue/PR during pipeline | MCP GitHub server (Method 1) |
| PM + all agents get full discussion thread | Patch `watcher.py` (Method 2) |
| Simple one-off requirements | Write full context in issue body (Method 3) |
| PR human review triggers code revision | Already built-in — leave review comments on the PR |

**Recommended combination**: Method 3 for structured issue bodies + Method 1 (MCP) for Code Reviewer and QA Planner to look up related issues/PRs at review time.

---

### GitHub Token Scopes Required

```
repo → contents      (read/write — for branch/file operations)
       issues        (read/write — for creating/labelling issues)
       pull_requests (read/write — for creating PRs and reading reviews)
```

Create or update token at: https://github.com/settings/personal-access-tokens/new

```bash
export GITHUB_TOKEN=ghp_your_token_here
```

---

## 6. Pipeline Self-Chaining (Auto Re-Label)

### Problem

After a pipeline completes, the watcher adds `agent-complete` and skips the issue on future cycles. If tests failed or the code reviewer requested changes, a human had to manually remove `agent-complete` and re-add a trigger label (e.g. `ai-fix`) before the agent could continue.

### Solution

The watcher now inspects `PipelineResult` after each run and automatically applies a follow-up trigger label when conditions are met — no human intervention needed.

**Flow:**
```
Issue #42 (ai-feature)
  → watcher picks up → agent-running
  → pipeline runs → tests fail
  → watcher sees tests_passed=False
  → removes agent-running, adds ai-fix        ← chaining
  → posts comment explaining why
  → next watcher cycle picks up ai-fix label
  → ai-fix pipeline runs → fixes failing tests
  → tests pass → adds agent-complete          ← done
```

---

### Configuration (`config.yaml`)

```yaml
pipeline:
  chaining:
    # Apply this label when unit tests or deploy tests fail after max retries
    on_test_failure: "ai-fix"

    # Apply this label when code reviewer verdict is CHANGES REQUESTED
    on_review_issues: "ai-fix"

    # Set to null (or omit) to disable a rule
    # on_test_failure: ~
```

The chained label must be one of the trigger labels already configured in `repos.yaml` (under `feature_label` / `bug_label`).

To **disable chaining entirely**, set all rules to null or remove the `chaining` block:
```yaml
pipeline:
  chaining: {}
```

---

### Priority Order

When deciding the next label, the system uses this priority:

| Priority | Source | When |
|---|---|---|
| 1 (highest) | `result.next_label` set by an agent | Agent explicitly requests a follow-up |
| 2 | `chaining.on_test_failure` | `tests_passed=False` or `deploy_tests_passed=False` |
| 3 | `chaining.on_review_issues` | `verdict` contains "CHANGES" |
| — | None → `agent-complete` | All conditions clean |

---

### Setting `next_label` Explicitly from an Agent/Stage

Any stage in the orchestrator can set `result.next_label` to override config rules. For example, in a custom pipeline YAML stage or by editing a role:

```python
# In a custom stage function in orchestrator.py:
def _stage_my_check(self, result: PipelineResult) -> None:
    # ... run some check ...
    if some_condition:
        result.next_label = "ai-review"   # watcher will chain to this
```

Or in `pipelines/ai-feature.yaml`, after the reviewer stage, if you want to always queue a human review:
```yaml
# The orchestrator's stage can set next_label = "needs-human-review"
# and the watcher will apply it after completion.
```

---

### What the Watcher Posts to the Issue

When chaining is triggered, the watcher automatically posts a comment:

```
🔁 Pipeline Chaining → `ai-fix`

The pipeline completed but follow-up work was detected
(verdict: `CHANGES REQUESTED`, tests_passed: `False`, deploy_tests_passed: `None`).

Automatically re-queued with label `ai-fix`.
The watcher will pick this up on the next cycle.

To stop chaining, remove the `ai-fix` label.
```

---

### Files Changed

| File | Change |
|---|---|
| `orchestrator.py` | Added `next_label: Optional[str]` field to `PipelineResult` |
| `watcher.py` | `_dispatch()` now returns `PipelineResult`; added `_resolve_next_label()`; `run_pipeline()` applies chaining |
| `config.yaml` | Added `pipeline.chaining` section with `on_test_failure` and `on_review_issues` rules |

---

## 7. Token Usage & Cost Tracking

Token usage and cost tracking records how many tokens each pipeline stage consumed and estimates the USD cost, then flushes results to a local SQLite database. Optionally it posts a Markdown breakdown table as a comment on the GitHub issue.

### What it does

- Counts input and output tokens for every LLM call, grouped by stage and by model
- Calculates USD cost using a configurable per-model pricing table (input/output per 1M tokens)
- Stores every run as a row in `token_usage.db` (SQLite, local to your project)
- Optionally posts a per-stage cost breakdown table to the GitHub issue when the run finishes

### How to enable

Set `cost_tracking.enabled: true` in `config.yaml` (or `config.local.yaml`):

```yaml
cost_tracking:
  enabled: true
  db_path: "./token_usage.db"     # SQLite file path (relative to project root)
  post_to_github: false           # set true to post cost comment to the GitHub issue

  # Pricing per 1M tokens: [input_price_usd, output_price_usd]
  # Set to [0.00, 0.00] for local/free models (Ollama, etc.)
  # Unlisted models fall back to "default".
  pricing:
    gpt-4.1:           [2.00, 8.00]
    gpt-4.1-mini:      [0.40, 1.60]
    gpt-4o:            [2.50, 10.00]
    qwen3.6-plus:      [0.50, 1.50]
    qwen3.5-plus:      [0.30, 1.20]
    thinker:           [0.00, 0.00]
    thinker-best:      [0.00, 0.00]
    coder:             [0.00, 0.00]
    fast:              [0.00, 0.00]
    chat:              [0.00, 0.00]
    default:           [2.00, 8.00]   # fallback for any unlisted model
```

Add your own model entries to `pricing:` as needed. Models with `[0.00, 0.00]` (e.g. local Ollama models) are tracked for token counts but report $0.00 cost.

### Reading the SQLite database

The database is written to `db_path` (default `./token_usage.db`). Query it with the standard `sqlite3` CLI:

```bash
# Show all runs with total cost
sqlite3 token_usage.db "SELECT run_id, created_at, total_cost_usd FROM runs ORDER BY created_at DESC LIMIT 20;"

# Show per-model breakdown for the most recent run
sqlite3 token_usage.db "
  SELECT model, sum(input_tokens) as in_tok, sum(output_tokens) as out_tok, sum(cost_usd) as cost
  FROM token_usage
  WHERE run_id = (SELECT run_id FROM runs ORDER BY created_at DESC LIMIT 1)
  GROUP BY model
  ORDER BY cost DESC;
"

# Show per-stage breakdown for a specific run
sqlite3 token_usage.db "
  SELECT stage, model, input_tokens, output_tokens, cost_usd
  FROM token_usage
  WHERE run_id = 'YOUR-RUN-UUID'
  ORDER BY cost_usd DESC;
"
```

### GitHub issue comment format

When `post_to_github: true`, the pipeline posts a comment to the issue after the run completes. The comment contains a Markdown table with one row per stage:

```
## 💰 Token Usage & Cost — run abc123

| Stage | Model | In (tokens) | Out (tokens) | Cost (USD) |
|---|---|---|---|---|
| architect | gpt-4.1 | 4,210 | 1,840 | $0.0242 |
| engineer | gpt-4.1-mini | 12,500 | 6,100 | $0.0147 |
| qa_engineer | gpt-4.1-mini | 8,300 | 3,200 | $0.0085 |
| … | … | … | … | … |
| **Total** | | **31,400** | **14,200** | **$0.0612** |
```

### `PipelineResult` fields

The `PipelineResult` object returned by `orch.run()` exposes three new fields when cost tracking is enabled:

| Field | Type | Description |
|---|---|---|
| `run_id` | `str` | UUID identifying this pipeline run (also used as the DB key) |
| `total_cost_usd` | `float` | Estimated total USD cost across all stages |
| `token_usage` | `dict` | Full breakdown: `by_stage` and `by_model` sub-dicts, each mapping names to `{input_tokens, output_tokens, cost_usd}` |

```python
result = orch.run("Build a REST API for patient questionnaires")

print(result.run_id)            # e.g. "a3f9c2d1-..."
print(result.total_cost_usd)    # e.g. 0.0612
print(result.token_usage)       # {"by_stage": {...}, "by_model": {...}}
```

These fields are `None` / `0.0` / `{}` when `cost_tracking.enabled` is `false`.

---

## 8. Repo Watcher Config (repos-available / repos-enabled)

Watcher entries are stored individually in `repos-available/<name>.yaml` (one file per
tracked repository). Activate a repo by symlinking it into `repos-enabled/`:

```bash
# Enable a repo
python watcher.py repo enable mcp-tfl

# Disable a repo
python watcher.py repo disable mcp-tfl

# List all repos with enabled/disabled status
python watcher.py repo list
```

**File format** (`repos-available/<name>.yaml`):

```yaml
tracker_repo: owner/repo-name
default_target: ~          # null = same repo as tracker
feature_label:
  - feature-request
  - ai-feature
bug_label: bug
doc_label: documentation
enabled: true              # optional; defaults to true

settings:                  # optional — overrides global settings for this repo only
  model: gpt-4.1-mini
  num_engineers: 1
```

**Global settings** in `repos.yaml` apply to all repos unless overridden per-repo.

**`repos-enabled/`** is gitignored — each deployment manages its own symlinks.
**`repos-available/`** is committed — it's the source of truth for all available configs.

---

## 9. PR Watcher

The watcher can also monitor open pull requests for failures and automatically
run `run_revision()` to push fixes.

### Enable per repo

In `repos-available/<repo>.yaml`, add under `settings:`:

```yaml
settings:
  watch_prs: true              # enable PR watching for this repo
  pr_fix_label: "ai-fix"      # label on PR that triggers a fix run
  pr_failure_pattern: "❌|FAILED|tests? failed"  # regex matched against comments
  max_pr_retries: 3           # stop after this many fix attempts
  watch_draft_prs: false      # set true to also watch draft PRs
```

### How it works

On each watcher cycle, for repos with `watch_prs: true`, the watcher:

1. Fetches all open PRs in the target repo
2. For each PR, checks:
   - Does it have the `pr_fix_label` (e.g. `ai-fix`)? **OR**
   - Does any comment body match `pr_failure_pattern`?
3. Skips PRs that have `agent-running`, `agent-failed`, or have exhausted `max_pr_retries`
4. Runs `run_revision()` — re-runs engineer → reviewer → QA, pushes commits to the PR branch
5. Labels the PR `agent-complete` on success, or `agent-failed` if the orchestrator returns an error status or throws an exception.

### Retry tracking

Each fix attempt adds an `ai-pr-fix-N` label to the PR. When N reaches `max_pr_retries`,
the watcher stops and adds `agent-failed`.

To reset and retry: remove all `ai-pr-fix-N` labels and `agent-failed` from the PR.

## 7. Per-repo deploy backends

Each repo can independently choose how its deployment smoke tests run. Configure via a `deploy:` block at the top level of `repos-available/<repo>.yaml` (or `repos-enabled/<repo>.yaml`).

### Mode: `docker` (default)

Runs local docker-compose smoke tests. If no `deploy:` block is present, this is the default.

```yaml
deploy:
  mode: docker
  compose_file: docker-compose.test.yml  # default
  timeout_s: 300                          # default
```

Prefers `scripts/deploy_test.sh` if present; otherwise looks for `docker-compose.test.yml` + `tests/test_deployment.py`. Skips (returns `passed=None`) if neither exists.

### Mode: `libvirt` — remote VM via SSH + CoW overlay

Provisions a fresh VM on a remote libvirt host from a copy-on-write overlay of a read-only base image. Each run gets its own isolated overlay; the base image is never modified. Multiple repos can share the same base image safely.

```yaml
deploy:
  mode: libvirt
  virt_host: ubuntu@192.168.1.10         # required: SSH address of the libvirt host
  base_image: /var/lib/libvirt/images/ubuntu-24.04.qcow2  # required
  vm_user: ubuntu                        # default: ubuntu
  ssh_key: ~/.ssh/id_ed25519             # default: SSH agent
  vcpus: 2                               # default: 2
  ram_mb: 2048                           # default: 2048
  teardown: always                       # always | on_pass | keep  (default: always)
  timeout_s: 600                         # default: 600
```

**Steps performed:**
1. Create CoW overlay from `base_image` on the libvirt host
2. Start VM with `virt-install --import`
3. Wait for SSH reachability (polls via `virt_host` as jump proxy)
4. `rsync` the project into `/opt/app/` on the VM
5. Run `tests/test_deployment.py` via `pytest` over SSH
6. Post result + duration + VM info as a PR comment
7. Tear down based on `teardown` mode

**Teardown modes:**
- `always` — destroy VM after every run (default; safest for CI)
- `on_pass` — keep VM alive when tests **fail** (lets you SSH in for debugging)
- `keep` — never destroy (manual cleanup with `virsh destroy` / `virsh undefine`)

**SSH key setup:** The libvirt host needs the orchestrator's public key in `~/.ssh/authorized_keys`. The VM base image should also trust the same key (or one derived from it via `ssh_key`). Set `ssh_key` to the private key path to specify which key to use.

**VM name collision:** Each run derives a unique VM name from `{repo}-{issue_number}` (template configurable via `vm_name` in the deploy block). Concurrent runs for the same repo on different issues use different overlay paths and VM names.

### Mode: `none`

Skip deployment testing entirely. Useful for library-only repos or repos that have their own CI.

```yaml
deploy:
  mode: none
```

### Checking the result

The orchestrator posts a PR comment after every deploy run:
- 🐳 Docker: `Deploy tests passed in X.Xs` / `Deploy tests FAILED`
- 🚀 Libvirt: same + VM name and libvirt host info on failure
- ⏭️ None / skipped: no comment posted

---

## 8. Agent Accuracy System

The accuracy system is a four-layer defence against structural agent mistakes — hallucinated APIs, wiped config files, missing registry wiring, and similar failures that produce code which looks right but cannot run.

### Layer 1 — Prevention

Before the engineer agent runs, the orchestrator:

1. Reads the role file (`roles/<agent>.md`) and injects any `## API Cheatsheet` block found there directly into the system prompt
2. Attaches the source files listed in the role file's `## Context Files` block to the prompt
3. Ensures `tool_registry` is passed so the agent can query the codebase via RAG

To add a cheatsheet manually:

```markdown
<!-- roles/engineer.md -->
## API Cheatsheet

- Call the LLM: `self.call(user_message)` — NOT `self.llm.generate()`
- Load system prompt: already in BaseAgent — do NOT re-implement `_load_system_prompt()`
- GitHubClient requires: `GitHubClient(repo="owner/repo", token="...")`
```

The `BootstrapPatternsAgent` generates these cheatsheets automatically when onboarding a new repo (see Layer 4).

### Layer 2 — Detection (Validation Gate)

The `validation_gate` pipeline stage runs three checks in order before any PR is opened:

1. **Syntax** — `python -m py_compile` on all `.py` files in the PR
2. **Lint** — `ruff check` on changed files
3. **Tests** — `pytest` on the full test suite

On failure, the exact error is injected back into the engineer agent's prompt and the engineer re-runs (up to `max_retries: 2`, configurable per pipeline YAML). After max retries, the gate posts a failure comment on the issue and stops — a human reviews.

To check gate results:

```bash
# In pipeline logs
grep "validation_gate" logs/pipeline-*.log

# Gate result in PipelineResult
result.stage_outputs["validation_gate"]
```

### Layer 3 — Learning

`LearningAgent` runs after a `validation_gate` failure. It:

1. Reads the error that caused the failure
2. Identifies the agent role responsible
3. Appends a `## DO NOT` rule to that role file

Example rules written automatically:

```markdown
<!-- roles/engineer.md — appended by LearningAgent -->
## DO NOT

- DO NOT call `self.llm.generate()` — use `self.call(user_message)`
- DO NOT rewrite `repos.yaml` from scratch — read it first, add only the new entry
- DO NOT instantiate `GitHubClient()` with no arguments — it requires `repo` and `token`
```

These rules appear in the system prompt of every future agent run for that role. The more failures the system sees, the stronger the protection.

### Layer 4 — Bootstrap

`BootstrapPatternsAgent` generates Layer 1 cheatsheets automatically when a new repo is onboarded.

**Automatic trigger** — runs when `validation_gate` detects that no `## API Cheatsheet` block exists in the engineer role file for a given repo.

**Manual trigger:**

```bash
python main.py --bootstrap --repo owner/new-repo
```

The agent:
1. Clones the target repo
2. Reads key source files (`base_agent.py`, config schemas, constructor signatures)
3. Writes `.github/copilot-instructions.md` with real method names, constructor signatures, and common patterns
4. Optionally writes `## API Cheatsheet` blocks back to the relevant role files

New repos start with Layer 1 protection before any failures have ever occurred.

### Disabling layers

Individual layers can be disabled in `config.yaml`:

```yaml
accuracy:
  prevention: true      # Layer 1 — context injection
  validation_gate: true # Layer 2 — syntax/lint/test gate
  learning: true        # Layer 3 — LearningAgent rule writes
  bootstrap: true       # Layer 4 — BootstrapPatternsAgent
  max_retries: 2        # Gate retry limit before human escalation
```

---

## 10. Multi-Agent Discussion Stages

Discussion stages let multiple AI personas debate a topic before downstream agents act. The synthesis is injected into all following stages so engineers, architects, and QA understand the reasoning without re-deriving it.

### How it works

1. Each participant independently writes a **homework** analysis (optional)
2. Participants debate in up to N **rounds**, `@mention`-ing each other to respond directly
3. A **moderator** persona summarises and can signal `CONSENSUS_REACHED` to exit early
4. `discussion_transcript` and `discussion_synthesis` are written to `PipelineResult` and injected into every downstream stage

### Auto-discovery

Any YAML file placed in `discussions/` is automatically registered as a pipeline stage named `discuss_<stem>`. For example:

| File | Stage name |
|------|-----------|
| `discussions/brainstorm.yaml` | `discuss_brainstorm` |
| `discussions/spec_brief.yaml` | `discuss_spec_brief` |
| `discussions/news-analysis.yaml` | `discuss_news-analysis` |

Add the stage name to any `pipelines/*.yaml` to use it.

---

### Built-in presets

#### `discuss_brainstorm` — architecture / feature brainstorm

Three personas (Analyst, Skeptic, Optimist) debate a feature or architecture decision **before** the engineers write any code. Best for high-stakes or ambiguous requirements.

```yaml
# pipelines/ai-feature-brainstorm.yaml
stages:
  - pm
  - architect
  - discuss_brainstorm   # debate before engineers touch code
  - reviewer
  - junior_engineer
  - senior_engineer
  - qa_planner
  - qa_engineer
```

#### `discuss_spec_brief` — pre-PM requirements debate

PM, PM Reviewer, and Architect debate the raw requirement **before** the PM writes the PRD. The synthesis is automatically injected into `PM.run()` so the PM produces a better first draft, reducing or eliminating revision rounds.

```yaml
# pipelines/ai-feature-careful.yaml
stages:
  - discuss_spec_brief   # debate requirements first
  - pm                   # writes PRD informed by synthesis (automatic)
  - pm_reviewer          # likely approves first time
  - architect
  - junior_engineer
  - senior_engineer
  - qa_planner
  - qa_engineer
```

**No `homework_llm` needed** for spec discussions — participants only reason about the requirement text, no codebase searching required.

---

### Writing a custom preset

Create `discussions/my-preset.yaml`:

```yaml
participants:
  - role: analyst
    persona_file: roles/analyst.md
    llm: "opencode-go/qwen3.6-plus"

  - role: skeptic
    persona_file: roles/skeptic.md
    llm: "opencode-go/qwen3.6-plus"

homework_round: true      # independent analysis before group debate
max_rounds: 2
early_exit: CONSENSUS_REACHED

moderator:
  persona_file: roles/moderator.md

output_mode: both         # inject both transcript and synthesis downstream

context_fields:
  - issue_body            # fields from PipelineResult to inject as context
```

The stage name becomes `discuss_my-preset` automatically.

---

### Participant configuration

#### Option 1 — Role file (recommended)

```yaml
participants:
  - role: analyst
    persona_file: roles/analyst.md
    llm: "opencode-go/qwen3.6-plus"
```

Any `roles/*.md` file can be a participant — existing agent roles (e.g. `roles/architect.md`, `roles/code_reviewer.md`) or dedicated debater roles.

#### Option 2 — Inline persona

```yaml
participants:
  - role: security-expert
    persona: "You are a security expert. Challenge every design for vulnerabilities."
    llm: "opencode-go/qwen3.6-plus"
```

#### Option 3 — Auto-selected from pool

```yaml
auto_participants:
  pool:
    - analyst
    - skeptic
    - optimist
    - architect
    - security-expert
  count: 3              # LLM picks the 3 most relevant for this issue
```

---

### Two-model split: fast debate + slow research (`homework_llm`)

Discussion rounds (debate) need fast reasoning, not tools. But the **homework round** may benefit from codebase search — especially for architecture or code-related topics.

Set `homework_llm` on any participant to give them a different (capable, tool-enabled) model for homework only:

```yaml
participants:
  - role: analyst
    persona_file: roles/analyst.md
    llm: "fast-model"           # debate rounds — no tools needed
    homework_llm: "slow-model"  # homework round — has RAG tool access
```

| Phase | Model | Tools |
|-------|-------|-------|
| Homework (round 0) | `homework_llm` | ✅ `search_codebase`, `search_memory`, `search_docs` |
| Discussion rounds (1+) | `llm` | ❌ pure reasoning |

**When to use `homework_llm`:**
- ✅ Architecture / feature brainstorm touching existing code
- ✅ Any case where participants need to know what's already in the codebase
- ❌ Spec/requirements discussions (reasoning only, no search needed)
- ❌ Greenfield projects with no existing codebase

If `homework_llm` is set but the model doesn't support tool calling, it falls back to a plain call automatically.

---

### `context_fields` — what gets injected

`context_fields` lists `PipelineResult` string fields to inject as context for all participants:

| Field | When available | Typical use |
|-------|---------------|-------------|
| `issue_body` | Always | Raw requirement text |
| `prd` | After `pm` stage | PRD for spec review discussions |
| `design` | After `architect` stage | Architecture for code brainstorm |
| `review` | After `code_reviewer` stage | Review findings |
| `discussion_synthesis` | After any prior discussion | Chain discussions |

**Note:** `all_files` (dict) and other non-string fields cannot be used in `context_fields` directly. Summarise them in a prior stage if needed.

---

### Where to place a discussion in a pipeline

| Placement | Use case | `context_fields` |
|-----------|----------|-----------------|
| Before `pm` | Align on requirements before writing the spec | `issue_body` |
| Between `architect` and engineers | Debate design before writing code | `design`, `prd` |
| After `code_reviewer`, before fixes | Reviewer + engineer debate the review findings | `review`, `design` |
| After `pm`, before `pm_reviewer` | Debate the written spec quality | `prd` |

Multiple discussion stages can be chained in one pipeline — each adds its synthesis to `PipelineResult` (the last one wins for `discussion_synthesis`).

---

### Per-agent model override in `config.local.yaml`

The discussion stage respects the `discussion` key in `model_overrides`:

```yaml
model_overrides:
  discussion:
    primary: "opencode-go/qwen3.6-plus"
    fallbacks:
      - "opencode-go/qwen3.5-plus"
      - "ollama/qwen3.5"
```

Individual participant `llm:` fields in the preset YAML take precedence over this override.

---

## 11. Cantonese & Traditional Chinese Translation Stages

Two pipeline stages translate the finished English article into Hong Kong–style Written Cantonese and Taiwan/HK-style Traditional Chinese, committing both as separate `.md` files in the same PR.

| Stage | Output field | Target locale | Style |
|---|---|---|---|
| `translate_cantonese` | `article_zh_hk` | `zh-hk` | Informal 口語書面語, HK press |
| `translate_zh_traditional` | `article_zh_tw` | `zh-tw` | Formal 正式繁體中文, broadsheet |

Both stages share a single `TranslatorAgent` class — the `target_language` parameter selects the output style. No extra LLM configuration is needed beyond the global `llm:` settings.

The agent is driven by `roles/translator.md`.

### Pipeline configuration

Add the two stages after `news_editor` and before `news_reviewer` in `pipeline.yaml`:

```yaml
stages:
  - ...
  - news_editor
  - translate_cantonese
  - translate_zh_traditional
  - news_reviewer
  - news_article_pr
```

### PipelineResult fields

| Field | Type | Description |
|---|---|---|
| `article_zh_hk` | `str` | Written Cantonese article body (Traditional characters) |
| `article_zh_tw` | `str` | Traditional Chinese article body (Taiwan/HK Mandarin) |

Both fields are `None` when the translation stages are not included in the pipeline.

---

## 12. News Reviewer Agent

The `news_reviewer` stage runs one LLM call that checks all three language versions of the article before the PR is opened. It must appear **after all translation stages** and **before `news_article_pr`**.

### Checks performed

**English article:**
- Fact plausibility against source (version numbers, dates, product names)
- No invented quotes or statistics
- No agent commentary in the article body
- Grammar and headline–body consistency

**zh-hk (Written Cantonese):**
- All characters are Traditional (no Simplified — e.g. `國` not `国`)
- Uses Cantonese vocabulary (`係`, `唔係`, `喺`, `咁`, `嘅`, `咗`, …)

**zh-tw (Traditional Chinese):**
- All characters Traditional
- Uses Taiwanese Mandarin vocabulary (`軟體` not `软件`, `網路` not `网络`, …)
- No Cantonese colloquialisms

### Output and pipeline behaviour

The reviewer emits a verdict line followed by an issues list:

```
VERDICT: PASS
```

or

```
VERDICT: NEEDS_REVISION
ISSUES:
- zh-hk: "国" (Simplified) found in paragraph 2 — should be "國"
- en: Version number "3.1" contradicts source ("3.2")
```

On `NEEDS_REVISION` the pipeline **halts** and posts the issues list as a GitHub comment on the issue. The PR is not opened.

### Pipeline configuration

```yaml
stages:
  - ...
  - translate_cantonese
  - translate_zh_traditional
  - news_reviewer
  - news_article_pr
```

No additional `config.yaml` keys are required.

---

## 13. Editorial Triage Stage

`news_triage` is the first stage in the press pipeline. Three AI editors convene to vote **PUBLISH** or **SKIP** before any writing or translation runs — avoiding wasted LLM calls on stories that are out of scope or too thin.

### Pipeline position

```
RSS watcher → news_triage → discuss_news_analysis → news_writer → ...
```

### Participants

| Persona | Evaluates |
|---|---|
| `editorial_director` | Strategic importance, substance, scope fit |
| `audience_specialist` | Relevance to HK/Cantonese tech professionals |
| `news_editor` | Source credibility, sufficient material to write from |

### On SKIP

The pipeline posts a comment to the GitHub issue with the reason and **closes the issue**. No downstream stages run.

### On PUBLISH

`editorial_notes` (angle guidance agreed in the triage discussion) is written to `PipelineResult` and automatically injected into the writer's prompt.

### Configuration

```yaml
# config.yaml
triage_scope: "Tech news relevant to HK Cantonese-speaking tech professionals."
```

```yaml
# pipelines/press.yaml
stages:
  - news_triage
  - discuss_news_analysis
  - news_writer
  - news_editor
  - translate_cantonese
  - translate_zh_traditional
  - news_reviewer
  - news_article_pr
```

---

## 14. Batch Intake Triage Module

A generic, reusable pre-pipeline triage layer. Items accumulate in a `triage-pending` state; an AI editorial team evaluates them **together** (with relative ranking), then approves or skips each one.

Opt-in per repo — zero impact on repos that do not enable it.

### Key properties

- **Tracker-agnostic**: `GitHubTrackerAdapter` ships today; a JIRA interface is defined for future use.
- **Standalone**: `intake_triage.py` can be run from cron or manually — no watcher changes required.
- **Orchestrator integration**: `orchestrator.py`'s `news_triage` stage fast-passes items that have already been batch-triaged (skips the per-item LLM triage call).

### Trigger logic

Triggers are evaluated in order; the first that fires runs the batch:

| Priority | Trigger | Default |
|---|---|---|
| 1 | `--run` flag | Manual override |
| 2 | `min_count` | Fire when ≥ N items are pending (default: 5) |
| 3 | `max_age_hours` | Fire when oldest pending item ≥ N hours old (default: 6) |
| 4 | `schedule` | Cron expression (default: null / off) |

### Flow

1. `list_pending()` — fetches all issues labelled `triage-pending`
2. AI batch discussion — editors see all N items together, rank and discuss
3. Per-item verdict:
   - **APPROVE** → removes `triage-pending`, adds `triage-approved` + trigger label, posts editorial notes as a comment
   - **SKIP** → adds `triage-skipped`, closes issue, posts reason
4. `orchestrator.py` `news_triage` fast-passes items already batch-triaged

### Configuration

```yaml
# config.yaml
intake_triage:
  enabled: false              # flip to true to activate
  tracker: github
  scope: "Tech news relevant to HK Cantonese-speaking professionals."

  labels:
    pending:  triage-pending
    approved: triage-approved
    skipped:  triage-skipped
    trigger:  press            # label the watcher watches for (added on approve)

  trigger:
    min_count: 5
    max_age_hours: 6
    schedule: null             # cron e.g. "0 9 * * *"

  batch:
    max_size: 10
    body_preview_chars: 300

  discussion:
    preset: discussions/intake-triage.yaml
```

### Running the triage

```bash
# Manual one-shot run
python intake_triage.py

# Force run regardless of trigger conditions
python intake_triage.py --run
```

**Cron example** (every 6 hours):

```bash
0 */6 * * * python /path/to/ai-software-house/intake_triage.py
```

### Human override

Manually add the `triage-approved` label to any GitHub issue. The system respects it automatically — that item will be fast-passed by `news_triage` without re-running the batch discussion.
