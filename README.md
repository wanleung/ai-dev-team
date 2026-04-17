# 🏢 AI Software House

A team of AI agents that builds software from a plain-English requirement — creating GitHub Issues, feature branches, pull requests, tests, and deployment smoke tests automatically.

Built on the **GitHub Models API** — the same AI backbone that powers GitHub Copilot CLI.

---

## ✨ Features

- **9 specialised agent types** (10+ agents in parallel): PM → PM Reviewer → Architect → Arch Reviewer → Engineers ×N → Code Reviewer → QA Planner → QA Engineer → Deployment Tester
- **Checkpoint / resume** — interrupted runs pick up from the last successful stage
- **Multi-repo routing** — agents push to a target repo; tracking issues live in a central `ai-software-house` repo
- **Per-agent LLM config** — assign any GitHub Models model to each agent independently
- **Actual test execution** — pytest runs locally; results posted back to the PR as a comment
- **Docker smoke tests** — deployment tester generates and runs container health checks
- **GitHub Actions integration** — label an issue to trigger the full pipeline automatically; 15-minute watcher catches pre-labelled issues too
- **PR feedback loop** — humans post review comments on AI-generated PRs → Engineer + Code Reviewer + QA automatically re-run, push fixes, and update the PR (up to `max_revisions` rounds)
- **Tool calling built-in** — Code Reviewer runs `ruff`, QA Planner searches GitHub Issues; any agent can call tools via `call_with_tools()`
- **MCP server support** — connect any MCP-compatible server (stdio or SSE); tools are automatically merged and injected into tool-calling agents
- **Pluggable skill system** — skills are markdown files in `skills/` that inject domain-specific guidance into agent prompts; auto-detected from project context (issue body, repo languages) or always-loaded from config
- **Fully customisable** — add agents, skills, and tools by editing markdown role files and Python tool functions
- 🧠 **Agent memory** — tiered SQLite memory (run → monthly → quarterly), conversation history within each run, auto-summariser after every pipeline
- 🌙 **Refactor / dream mode** — `--refactor` flag analyses and cleans up workspace code, opens a cleanup PR
- 🤖 **6 LLM backends** — GitHub Models (default), Anthropic Claude, Ollama (local), OpenCode CLI, OpenCode Zen API, and OpenCode Go API; switch per-agent with a model prefix
- **Resilient checkpoints** — atomic writes prevent corruption on Ctrl+C; best-checkpoint-wins logic survives bad config runs

---

## ⚡ MVP Setup (Get Running in 5 Minutes)

The minimal setup to run the core pipeline — no Docker, no GitHub Actions, no reviewers. Just PM → Architect → Engineers → Code Reviewer → QA Engineer pushing code to a GitHub repo.

### Step 1 — Clone & install

```bash
git clone https://github.com/your-username/ai-software-house
cd ai-software-house
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

### Step 2 — GitHub classic PAT

1. Go to [github.com/settings/tokens](https://github.com/settings/tokens) → **Tokens (classic)**
2. Generate new token → tick **`repo`** scope (this also enables GitHub Models access)
3. Copy the token (`ghp_...`)

```bash
export GITHUB_TOKEN=ghp_your_token_here
```

> ⚠️ Must be a **classic** PAT, not a fine-grained token. Fine-grained tokens return `401 models permission required`.

### Step 3 — Create a target repo

Create an **empty public repo** on GitHub (e.g. `your-username/my-first-agent-app`).  
The pipeline will initialise it automatically.

### Step 4 — Minimal config

Edit `config.yaml` — change just one line:

```yaml
github:
  repo: "your-username/my-first-agent-app"   # ← your new repo
```

Disable the optional agents to keep it fast:

```yaml
team:
  num_engineers: 1        # start with 1 engineer
  agents:
    product_manager: true
    pm_reviewer: false    # skip for MVP
    architect: true
    engineer: true
    code_reviewer: true
    qa_planner: false     # skip for MVP
    qa_engineer: true
    deployment_tester: false  # skip — needs Docker
```

### Step 5 — Run

```bash
python main.py \
  --requirement "Build a simple REST API for a todo list with FastAPI" \
  --repo your-username/my-first-agent-app
```

### What you'll get

```
workspace/
  simple-todo-rest-api/       ← generated code saved locally

GitHub:
  Issue #1                    ← PRD created by Alice (PM)
  Branch: feature/agent-...  ← code pushed by Alex (Engineer)
  PR #2                       ← pull request with code review + test files
```

### MVP vs Full Pipeline

| | MVP | Full |
|---|---|---|
| Agents | 4 core agents | 9 agent types |
| Reviewers | Code Reviewer only | PM Reviewer + Arch Reviewer + Code Reviewer |
| Test planning | QA Engineer only | QA Planner → QA Engineer |
| Deployment tests | ❌ | ✅ Docker smoke tests |
| GitHub Actions | ❌ | ✅ Auto-trigger on issue labels |
| Time to first PR | ~2–3 min | ~5–10 min |

Once the MVP works, turn agents back on one by one in `config.yaml`.

---

## 🚀 Full Setup

### 1. Prerequisites

- Python 3.11+
- A GitHub **classic** PAT (not fine-grained) with scopes: `repo` + `read:org` (for GitHub Models access)
- Docker (optional — for deployment smoke tests)

### 2. Install

```bash
git clone https://github.com/your-username/ai-software-house
cd ai-software-house
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure

```bash
cp config.yaml config.local.yaml   # optional — edit as needed
export GITHUB_TOKEN=ghp_your_classic_pat
```

> **Using Anthropic Claude models?** Add your Anthropic key alongside `GITHUB_TOKEN`:
> ```bash
> # For Anthropic Claude models (claude-sonnet-4.6, claude-opus-4.5, etc.)
> export ANTHROPIC_API_KEY=sk-ant-your-key-here
> ```
> Model names starting with `claude-` are automatically routed to the Anthropic API.
> `GITHUB_TOKEN` is still required for all GitHub operations.

> **Using OpenCode Zen or Go models?** Export the OpenCode API key:
> ```bash
> export OPENCODE_ZEN_API_KEY=your-opencode-api-key
> ```
> Both `opencode-zen/` and `opencode-go/` model prefixes share this key.
> Get one at <https://opencode.ai/auth>.

Edit `config.yaml`:
```yaml
github:
  repo: "your-username/your-repo"   # where code will be pushed
```

#### Using Ollama (Local LLM)

To use a local [Ollama](https://ollama.com) server instead of GitHub Models or Anthropic:

1. Set any agent's model to an `ollama/` prefixed name in `config.yaml`:
   ```yaml
   llm:
     model: "ollama/llama3.2"
     overrides:
       engineer: "ollama/qwen2.5-coder"
   ```

2. Create `config.local.yaml` alongside `config.yaml` to set your Ollama server URL (this file is gitignored — never committed):
   ```yaml
   llm:
     ollama_url: "http://your-ollama-host:11434"
   ```
   If omitted, defaults to `http://localhost:11434`.

3. Pull the required model on your Ollama server:
   ```bash
   ollama pull llama3.2
   ```

#### Using OpenCode CLI

Run models through the [OpenCode](https://opencode.ai) CLI instead of a direct API:

1. Install and authenticate OpenCode:
   ```bash
   npm install -g opencode-ai   # or follow opencode.ai instructions
   opencode auth login
   ```

2. Set model names with the `opencode/<provider>/<model>` prefix:
   ```yaml
   llm:
     model: "opencode/anthropic/claude-sonnet-4-5"
     overrides:
       engineer: "opencode/openai/gpt-4o"
   ```

   OpenCode resolves the provider from its own auth config.
   Override the binary path with `OPENCODE_BIN` if needed.

> ⚠️ OpenCode CLI does **not** support tool-calling. The Code Reviewer agent will fail if assigned an `opencode/` model. Use `opencode-go/` or `opencode-zen/` for tool-calling agents.

#### Using OpenCode Zen API

Direct HTTP access to OpenCode Zen (Claude, GPT, Gemini, and more):

1. Get an API key at <https://opencode.ai/auth> and export it:
   ```bash
   export OPENCODE_ZEN_API_KEY=your-key-here
   ```

2. Use the `opencode-zen/<model-id>` prefix:
   ```yaml
   llm:
     model: "opencode-zen/claude-sonnet-4-6"
     overrides:
       engineer: "opencode-zen/gpt-5.3-codex"
   ```

   Claude models route to the Anthropic Messages endpoint; all others use the OpenAI-compatible endpoint and **support tool-calling**.

#### Using OpenCode Go API

Access the OpenCode Go plan models (Kimi, Qwen, GLM, MiMo, MiniMax):

1. Same API key as Zen — `OPENCODE_ZEN_API_KEY`.

2. Use the `opencode-go/<model-id>` prefix:
   ```yaml
   llm:
     model: "opencode-go/kimi-k2.5"
     overrides:
       engineer: "opencode-go/qwen3.6-plus"
   ```

   | Model ID | Endpoint | Tool-calling |
   |---|---|---|
   | `kimi-k2.5`, `qwen3.6-plus`, `qwen3.5-plus`, `glm-5.1`, `glm-5`, `mimo-v2-pro`, `mimo-v2-omni` | `/chat/completions` | ✅ |
   | `minimax-m2.7`, `minimax-m2.5` | Anthropic `/messages` | ❌ |

   Override the base URL with `OPENCODE_GO_BASE_URL` if needed.

### 4. Run

```bash
# From a requirement file
python main.py --file requirements/my-app.txt --repo owner/target-repo

# From a string
python main.py --requirement "Build a REST API for a todo app" --repo owner/target-repo

# Resume an interrupted run (default — checkpoint auto-detected)
python main.py --file requirements/my-app.txt --repo owner/target-repo

# Start fresh (ignore checkpoint)
python main.py --file requirements/my-app.txt --repo owner/target-repo --no-resume
```

> **Resume behaviour:** checkpoints are written atomically after each stage completes, so a Ctrl+C or crash mid-stage never corrupts the saved state. If the same requirement has been run before with different config (e.g. a wrong model name), the pipeline automatically picks up the checkpoint with the **most completed stages** — a failed partial run can never roll back progress.

---

## 🤖 Pipeline Stages

```
1.  📋 Product Manager    — requirement → PRD + GitHub Issue
2.  📝 PM Reviewer        — reviews PRD; optionally revises before architecture
3.  🏗️  Architect          — PRD → system design + module list
4.  🔎 Arch Reviewer      — reviews design; optionally revises before engineering
5.  💻 Engineers ×N       — parallel code generation → feature branch + PR
6.  🔍 Code Reviewer      — reviews code → PR comment with verdict
7.  📋 QA Planner         — PRD + design + code → structured test plan + acceptance criteria
8.  🧪 QA Engineer        — implements tests guided by QA Planner's test plan → PR
9.  🏃 Test Runner        — runs pytest locally → PR comment with results
10. 🚀 Deployment Tester  — generates docker-compose.test.yml + smoke tests → PR
11. 🐳 Deploy Test Runner — runs docker smoke tests → PR comment (skips if Docker unavailable)
12. 🧠 Summariser         — writes compact memory entry (what was built, decisions, feedback, tech debt)
```

---

## 🧠 Agent Memory

Every pipeline run contributes to a tiered, persistent memory store so the system learns from past work on a repo.

### How it works

```
Each run  →  run summary  (SummaryAgent writes after pipeline)
                │
                ▼  (after 10 run entries)
           monthly snapshot  (MemoryConsolidatorAgent)
                │
                ▼  (after 3 monthly entries)
           quarterly index  (MemoryConsolidatorAgent)
```

`recall()` always returns: **all quarterly entries + all monthly entries + last 3 run summaries** — capped at ~2 200 words regardless of total run count.

### Storage

| File | Location | Purpose |
|---|---|---|
| `memory.db` | `workspace/<repo>/memory.db` | SQLite store (all tiers) |
| `memory.md` | `workspace/<repo>/memory.md` | Human-readable log of all entries |

Long-term memory is loaded at the start of each run and injected as a `## 📚 Memory` block into every agent's system prompt.

### Python API

```python
from orchestrator import Orchestrator

orch = Orchestrator(model="gpt-4.1", github_token="ghp_...", target_repo="owner/repo")

# View stats for a repo
stats = orch.memory.stats("owner/repo")
# → {"runs": 7, "monthly": 1, "quarterly": 0}

# Keyword search across memory entries
results = orch.memory.search("owner/repo", ["auth", "JWT"])
# → list of matching memory entries
```

---

### 🌙 Refactor / Dream Mode

A standalone cleanup pass that scans existing workspace code, identifies code smells and tech debt, rewrites flagged files, and opens a cleanup PR. It does **not** run the normal build pipeline.

**CLI:**
```bash
python main.py --refactor --repo owner/target-repo
```

**Python API:**
```python
result = orch.refactor()
# Returns:
# {
#   "plan":    "...",          # identified smells & refactor plan
#   "changes": {"file.py": "new content", ...},  # rewritten files
#   "pr_url":  "https://github.com/..."
# }
```

---

## 🗂️ Memory Bank

The Memory Bank gives Copilot CLI persistent context across sessions. Six structured Markdown files are committed to each target repo and auto-read by Copilot at session start.

### File hierarchy

| File | Updated | Purpose |
|------|---------|---------|
| `memory-bank/projectbrief.md` | Rarely | Goals, scope, core requirements |
| `memory-bank/productContext.md` | Rarely | Why it exists, user problems, UX goals |
| `memory-bank/systemPatterns.md` | On design change | Architecture, patterns, conventions |
| `memory-bank/techContext.md` | On stack change | Tech stack, dependencies, environment |
| `memory-bank/activeContext.md` | Every run | Current focus, recent changes, next steps |
| `memory-bank/progress.md` | Every run | Done / in-progress / blockers |

### Automatic updates

After every successful pipeline run, the `MemoryBankUpdaterAgent` reads the current bank files via the GitHub API and commits updated `activeContext.md` and `progress.md` (and optionally `systemPatterns.md` / `techContext.md`) to the feature branch. No manual action required.

### Deploy to a target repo

To add a Memory Bank to any project, use the templates from `copilot-agent-setting`:

```bash
cd /path/to/copilot-agent-setting
./deploy-memory-bank.sh /path/to/your-project
```

Then fill in `memory-bank/projectbrief.md` and `memory-bank/productContext.md`. The pipeline will keep the other files up to date automatically.

### Update modes

| Mode | How |
|------|-----|
| **Fully automatic** | Pipeline updates bank after every run — no action needed |
| **Semi-automatic** | `./install-memory-bank-hook.sh /path/to/project` — git post-commit hook updates bank after every commit |
| **Manual** | `./update-memory-bank.sh "summary"` — run from inside the project |

---

## 🧑‍💼 Agent Roster

| Agent | Name | Input | Output | GitHub Artifact |
|---|---|---|---|---|
| **Product Manager** | Alice | Raw requirement | PRD markdown | GitHub Issue |
| **PM Reviewer** | Grace | PRD + requirement | Review + revised PRD (if needed) | Issue comment |
| **Architect** | Bob | PRD | System design + modules | Issue comment |
| **Arch Reviewer** | Frank | Design + PRD | Review + revised design (if needed) | Issue comment |
| **Engineer ×N** | Alex ×N | System design | Source code files | Feature branch + PR |
| **Code Reviewer** | Carol | Code + PRD | Review verdict | PR comment |
| **QA Planner** | Henry | PRD + design + code | Test plan + acceptance criteria | Issue/PR comment |
| **QA Engineer** | Edward | Code + PRD + test plan | Test files + conftest + requirements-test.txt | PR comment + branch |
| **Deployment Tester** | Diana | Code + Dockerfile | docker-compose.test.yml + smoke tests + deploy script | PR comment + branch |

---

## 📋 All CLI Options (`main.py`)

```
python main.py [options]

Input (one required):
  --file PATH            Path to a .txt file containing the requirement
  --requirement TEXT     Requirement as a command-line string

Routing:
  --repo OWNER/REPO      Target repository for code (overrides config.yaml)

Model:
  --model MODEL          Override model for ALL agents
  --model-override AGENT=MODEL   Override model for one agent (repeatable)
                         Agent names: product_manager, pm_reviewer, architect,
                         architect_reviewer, engineer, code_reviewer,
                         qa_planner, qa_engineer, deployment_tester

Team:
  --engineers N          Number of parallel Engineer agents (default: 2)

Pipeline:
  --no-resume            Ignore checkpoint and start from scratch
  --stop-on-review       Halt pipeline if Code Reviewer requests changes
  --refactor             Dream mode: analyse workspace code and open a cleanup PR
  --mode {build,revise}  'build' (default) runs full pipeline; 'revise' processes PR feedback
  --pr PR_NUMBER         PR number to revise — required when --mode=revise
```

---

## 🎛️ Using the Orchestrators Directly (Python API)

### `orchestrator.py` — Full Feature Build

```python
from orchestrator import Orchestrator

orch = Orchestrator(
    model="gpt-4.1",
    github_token="ghp_...",
    target_repo="owner/my-app",
    num_engineers=3,
)

result = orch.run("Build a REST API for patient questionnaires")

print(result.prd)               # PRD markdown
print(result.prd_verdict)       # PRD APPROVED / NEEDS REVISION
print(result.design)            # System design markdown
print(result.design_verdict)    # DESIGN APPROVED / NEEDS REVISION
print(result.qa_plan)           # Full test plan from QA Planner
print(result.qa_acceptance_criteria)  # ['AC-01', 'AC-02', ...]
print(result.pr_url)            # GitHub PR URL
print(result.tests_passed)      # True / False / None
```

### `orchestrator.py` — PR Revision (`run_revision`)

Process human review feedback on an AI-generated PR and push an updated commit.

```python
from orchestrator import Orchestrator

orch = Orchestrator.from_config("config.yaml")
result = orch.run_revision(pr_number=42)
# result["status"] → "approved" | "changes_requested" | "max_revisions_reached" | "error"
```

**Via CLI:**
```bash
python main.py --mode revise --pr 42 --repo owner/target-repo
```

---

### `bug_fix_orchestrator.py` — Bug Fix Pipeline

Targeted pipeline for GitHub Issues. Skips PM — the issue body IS the requirement.

```python
from bug_fix_orchestrator import BugFixOrchestrator

orch = BugFixOrchestrator(
    model="gpt-4.1",
    github_token="ghp_...",
    tracker_repo="owner/ai-software-house",
    target_repo="owner/my-app",
)

result = orch.run(issue_number=42)
print(result.pr_url)
```

**Via CLI (`fix_issue.py`):**
```bash
python fix_issue.py --issue 42 --repo owner/ai-software-house --target owner/my-app
```

---

## ⚙️ Configuration Reference (`config.yaml`)

```yaml
llm:
  # Default model for all agents
  # ── GitHub Models (default) ─────────────────────────────────────────────
  #   gpt-4.1, gpt-4.1-mini, gpt-4.1-nano, gpt-4o, gpt-4o-mini, o4-mini, o3
  #   claude-3.5-sonnet, claude-3.7-sonnet, claude-3-haiku
  #   meta-llama-3.3-70b-instruct, mistral-large-2411
  #   deepseek-r1, deepseek-v3, cohere-command-r-plus
  #
  # ── Anthropic Claude API (ANTHROPIC_API_KEY required) ──────────────────
  #   claude-sonnet-4-6, claude-opus-4-5, claude-3-5-sonnet-20241022, ...
  #   Any model starting with "claude-" is auto-routed to Anthropic.
  #
  # ── Ollama (local, ollama_url below) ───────────────────────────────────
  #   ollama/llama3.2, ollama/qwen2.5-coder, ollama/mistral, ...
  #
  # ── OpenCode CLI (opencode must be installed + authenticated) ───────────
  #   opencode/<provider>/<model>
  #     e.g. opencode/anthropic/claude-sonnet-4-5
  #          opencode/openai/gpt-4o
  #   ⚠️  Does NOT support tool-calling (Code Reviewer will fail).
  #
  # ── OpenCode Zen API (OPENCODE_ZEN_API_KEY required) ───────────────────
  #   opencode-zen/<model-id>
  #     e.g. opencode-zen/claude-sonnet-4-6   → Anthropic endpoint
  #          opencode-zen/gpt-5.3-codex        → OpenAI endpoint (tool-calling ✅)
  #
  # ── OpenCode Go API (OPENCODE_ZEN_API_KEY required) ────────────────────
  #   opencode-go/<model-id>
  #     e.g. opencode-go/kimi-k2.5, opencode-go/qwen3.6-plus (tool-calling ✅)
  #          opencode-go/minimax-m2.7           → Anthropic endpoint (no tool-calling)
  model: "gpt-4.1"

  # Per-agent model overrides
  overrides:
    product_manager: "gpt-4.1"       # reasoning-heavy
    pm_reviewer: "gpt-4.1"
    architect: "gpt-4.1"
    architect_reviewer: "gpt-4.1"
    engineer: "gpt-4.1-mini"         # runs many times — use cheaper model
    code_reviewer: "gpt-4.1"
    qa_planner: "gpt-4.1"            # test planning needs strong reasoning
    qa_engineer: "gpt-4.1-mini"      # repetitive test writing — cheaper
    deployment_tester: "gpt-4.1-mini"

github:
  repo: "owner/repo"                 # default target repo
  branch_prefix: "feature/agent"

team:
  num_engineers: 2
  agents:                            # enable / disable individual agents
    product_manager: true
    pm_reviewer: true
    architect: true
    engineer: true
    code_reviewer: true
    qa_planner: true
    qa_engineer: true
    deployment_tester: true

pipeline:
  workspace_dir: "./workspace"
  stop_on_review_issues: false
  max_retries: 2
  max_revisions: 3        # max automated PR revision rounds (0 = disabled)

skills:
  always_load: []          # e.g. [security-audit] to always apply
  marketplace_repo: ""     # e.g. "myorg/ai-software-house-skills"
  cache_dir: ""            # defaults to ~/.ai-software-house/skills/
  fetch_timeout: 5

mcp:
  servers: []              # see "Using MCP Servers" section below
```

---

## 🎨 Defining Agent Skills & Guides

Every agent's behaviour is controlled entirely by its **role file** (`roles/<agent>.md`). This file becomes the LLM's system prompt — change the markdown, change the agent.

### Role File Structure

```markdown
# Agent Name

## Role
One or two sentences: who this agent is and what their job is.
Give them a name and a personality.

## Responsibilities
- Bullet list of what this agent does — these are the agent's "skills"
- Be specific: "Write a conftest.py with shared pytest fixtures"
- Not vague: "Write tests"

## Critical Rules
- Hard constraints that must never be violated
- e.g. "Never hardcode credentials — use environment variables"
- e.g. "Always use Given/When/Then format for acceptance tests"
- e.g. "Do NOT write test code — that is Edward's job"

## Output Format
The exact markdown/code structure the agent must produce.
Downstream parsers in the Python agent class look for specific markers.
Use code blocks showing the exact template.

## Quality Rules
- What makes a good output vs a bad one
- End with: `MY KEYWORD COMPLETE`   ← used by the parser to detect success
```

### Agents and Their Role Files

| Agent | Role File | Key Skills Defined |
|---|---|---|
| Product Manager | `roles/product_manager.md` | Requirements analysis, user story writing, PRD structure |
| PM Reviewer | `roles/pm_reviewer.md` | PRD completeness check, acceptance criteria quality, revision |
| Architect | `roles/architect.md` | System design, module decomposition, tech stack selection |
| Arch Reviewer | `roles/architect_reviewer.md` | Design critique, scalability review, revision |
| Engineer | `roles/engineer.md` | Code generation, PEP 8, type hints, error handling |
| Code Reviewer | `roles/code_reviewer.md` | Code quality, security, performance, verdict |
| QA Planner | `roles/qa_planner.md` | Acceptance criteria, test strategy, module scenarios, Given/When/Then |
| QA Engineer | `roles/qa_engineer.md` | pytest writing, mocking, conftest, runnable tests |
| Deployment Tester | `roles/deployment_tester.md` | Docker compose, health checks, smoke tests |

### Adding a Skill to an Existing Agent

Edit the role file — no code changes needed:

```bash
# Add security skills to the Engineer
nano roles/engineer.md
```

```markdown
## Security Skills
- Never hardcode credentials — always use environment variables
- Validate and sanitise all user input before processing
- Use parameterised queries — never concatenate SQL strings
- Set secure cookie flags; prefer HTTPS-only endpoints
- Flag any third-party packages with known CVEs in a comment
```

### Adding a Brand-New Agent

**Step 1 — Create the role file:**
```bash
cat > roles/security_reviewer.md << 'EOF'
# Security Reviewer Agent

## Role
You are **Sam**, a Security Reviewer specialising in OWASP Top 10 vulnerabilities.

## Skills
- OWASP Top 10 vulnerability detection
- Secrets / credential leak detection
- SQL injection and XSS pattern recognition
- Dependency audit (flag known-vulnerable packages)

## Output Format
### SECURITY VERDICT: [PASS | WARN | FAIL]
#### Findings
| Severity | File | Line | Issue | Recommendation |
...
End with: `SECURITY REVIEW COMPLETE`
EOF
```

**Step 2 — Create the agent class:**
```python
# agents/security_reviewer.py
from .base_agent import BaseAgent

class SecurityReviewerAgent(BaseAgent):
    role_name = "security_reviewer"   # maps to roles/security_reviewer.md

    def run(self, files: dict[str, str], prd: str) -> dict:
        truncated = self.truncate_files(files, max_chars=10_000)
        code = "\n\n".join(
            f"### {path}\n```\n{content}\n```"
            for path, content in truncated.items()
        )
        response = self.call(f"Review this code for security issues:\n\n{code}")
        verdict = "FAIL" if "FAIL" in response else "WARN" if "WARN" in response else "PASS"
        return {"review": response, "verdict": verdict}
```

**Step 3 — Register & wire in:**
- `agents/__init__.py` — add import and `__all__` entry
- `orchestrator.py` — instantiate, add stage, add field to `PipelineResult`
- `config.yaml` — add to `agents.overrides`
- `main.py` — add to `agent_map`

### Tuning Without Code Changes

| Goal | Where |
|---|---|
| Change personality / tone | `roles/*.md` — Role section |
| Add a new skill or check | `roles/*.md` — Responsibilities section |
| Make a rule stricter | `roles/*.md` — Critical Rules section |
| Change output structure | `roles/*.md` — Output Format section |
| Use a smarter/cheaper model | `config.yaml` → `llm.overrides.<agent>` |
| Change LLM temperature | `agents/base_agent.py` → `temperature=0.3` in `call()` |

---

## ⏰ Cron Watcher — Hourly Auto-Dispatch

Run the pipeline automatically on this machine — no GitHub Actions required.  
`watcher.py` polls GitHub hourly, finds unprocessed issues, and dispatches pipelines in parallel.

### How it works

```
Every hour:
  For each repo in repos.yaml
    → Find open issues labelled feature-request or bug
         (that don't already have an agent-* state label)
    → Label issue agent-queued
    → Run the appropriate pipeline in a thread
    → On success: label agent-complete
    → On failure: label agent-failed + post error comment
```

**State labels** (auto-created in your repo):

| Label | Meaning |
|---|---|
| `agent-queued` | Picked up this run, pipeline starting |
| `agent-running` | Pipeline actively running |
| `agent-complete` | ✅ Pipeline finished successfully |
| `agent-failed` | ❌ Pipeline failed — remove label to retry |

### Configure repos.yaml

```yaml
watchers:
  - tracker_repo: wanleung/ai-software-house   # where issues are filed
    default_target: wanleung/my-app            # default target repo for code
    feature_label: feature-request
    bug_label: bug
    enabled: true

  - tracker_repo: wanleung/another-project     # watch a second repo
    default_target: ~                          # null = same repo as tracker
    enabled: true

settings:
  max_parallel: 3       # max simultaneous pipeline runs
  num_engineers: 2
  model: "gpt-4.1"
  log_dir: ./logs/watcher
```

> Use `**Target repo:** owner/repo` in the issue body to route code to a different repo than `default_target`.

### Install cron job (runs every hour at :00)

```bash
chmod +x setup_cron.sh
./setup_cron.sh
```

Or manually:
```bash
crontab -e
# Add this line:
0 * * * * cd /home/you/ai-software-house && source venv/bin/activate && python watcher.py >> logs/watcher/cron.log 2>&1
```

### Manual / test runs

```bash
# Dry run — shows what would run, makes no GitHub changes
python watcher.py --dry-run

# Run once immediately
python watcher.py

# Use a different config file
python watcher.py --config my-other-repos.yaml
```

### Logs

```
logs/watcher/
  cron.log                      ← all cron runs (appended)
  watcher-YYYYMMDD.log          ← daily watcher log
  issue-42-20260322-140000.log  ← per-issue pipeline output
```

### Prevent overlapping runs

A lock file (`.watcher.lock`) is created at startup and removed on exit.  
If a run is still active when the next cron fires, the new run exits immediately.  
Stale locks (>1 hour old) are cleared automatically.

---

## 🔄 GitHub Actions — Auto-Trigger

The pipeline runs automatically when you label a GitHub Issue.

### One-Time Setup

```bash
# 1. Add GH_TOKEN secret (classic PAT, NOT fine-grained, NOT GITHUB_TOKEN)
#    Go to: Settings → Secrets → Actions → New repository secret
#    Name: GH_TOKEN    Value: ghp_your_classic_pat

# 2. Set up labels
gh workflow run setup-labels.yml

# 3. (Optional) Set target repo for cross-repo builds
#    Add secret: TARGET_REPO = owner/target-repo-name
```

### Triggering a Feature Build

Create a GitHub Issue, then add the **`ai-feature`** label:

```markdown
Title: Patient questionnaire mobile app

## Description
Build iOS and Android apps for rectal cancer patient questionnaires.

**Target repo:** wanleung/my-mobile-app

## Acceptance Criteria
- Patient can complete a questionnaire offline
- Data syncs when connectivity is restored
- Clinician dashboard shows aggregated results
```

> The `**Target repo:** owner/repo` line routes the code to a different repository.
> Tracking issues (PRD, reviews) stay in the `ai-software-house` repo.

### Triggering a Bug Fix

Create an issue with the **`ai-fix`** label:

```markdown
Title: Login fails for users with special characters in email

Steps to reproduce:
1. Register with email: user+test@example.com
2. Attempt to login
3. Error: 500 Internal Server Error

Expected: Successful login
```

### Triggering a PR Revision

After humans post review comments on an AI-generated PR, trigger the revision pipeline:

**Option A — GitHub UI:**  
Go to **Actions → 🔄 AI PR Feedback Loop → Run workflow**, enter the PR number and target repo.

**Option B — CLI:**
```bash
python main.py --mode revise --pr 42 --repo owner/target-repo
```

**Option C — API (`repository_dispatch`):**
```bash
gh api repos/owner/ai-software-house/dispatches \
  --method POST \
  -f event_type=ai-pr-revise \
  -f client_payload[pr_number]=42 \
  -f client_payload[target_repo]=owner/target-repo
```

The pipeline reads all non-bot review comments, re-runs Engineer → Code Reviewer → QA, commits the updated code to the same branch, and posts a `✅ Revision N complete` comment on the PR.  
Maximum revision rounds is controlled by `pipeline.max_revisions` in `config.yaml` (default: 3).

### Issue Watcher (15-minute fallback)

`issue-watcher.yml` runs every 15 minutes and picks up any open issues with `ai-feature` or `ai-fix` labels that haven't been queued yet (lack the `ai-queued` label). This catches issues created programmatically with labels already attached, where the native label-trigger doesn't fire.

**Deduplication:** once an issue is picked up, the watcher adds the `ai-queued` label — preventing double-triggering by both the watcher and the native trigger.

### Workflows

| Workflow | Trigger | What it does |
|---|---|---|
| `feature-build.yml` | Issue labelled `ai-feature` | Full 11-stage pipeline |
| `bug-fix.yml` | Issue labelled `ai-fix` | Bug fix pipeline (no PM) |
| `pr-feedback.yml` | Manual / `repository_dispatch` | Engineer → Code Reviewer → QA revision loop |
| `issue-watcher.yml` | Cron every 15 min | Finds unqueued issues and triggers the above |
| `run-tests.yml` | PR opened/updated | Runs pytest + docker smoke tests |
| `setup-labels.yml` | Manual dispatch | Creates required labels |

---

## 📁 Project Structure

```
ai-software-house/
├── main.py                    # CLI entry point for full pipeline
├── fix_issue.py               # CLI entry point for bug fix pipeline
├── build_feature.py           # GitHub Actions entry point
├── orchestrator.py            # Full pipeline (12 stages)
├── bug_fix_orchestrator.py    # Bug fix pipeline
├── github_client.py           # GitHub API wrapper (Issues, PRs, commits)
├── memory_store.py            # Tiered SQLite memory store (run/monthly/quarterly)
├── watcher.py                 # Hourly cron poller — dispatches pipelines for new issues
├── repos.yaml                 # Repos to watch + parallel/model settings
├── setup_cron.sh              # One-command cron job installer
├── config.yaml                # LLM models, team size, pipeline settings
├── requirements.txt
│
├── agents/
│   ├── base_agent.py          # BaseAgent: call(), call_with_tools(), retry, truncation
│   ├── product_manager.py     # Alice — PRD writer
│   ├── pm_reviewer.py         # Grace — PRD reviewer
│   ├── architect.py           # Bob — system designer
│   ├── architect_reviewer.py  # Frank — design reviewer
│   ├── engineer.py            # Alex — code writer (parallel)
│   ├── code_reviewer.py       # Carol — code reviewer  [tools: run_linter]
│   ├── qa_planner.py          # Henry — test planner   [tools: search_github_issues]
│   ├── qa_engineer.py         # Edward — test writer
│   ├── deployment_tester.py   # Diana — deployment tester
│   ├── summariser.py          # Writes compact memory entries after each run
│   ├── refactor_agent.py      # Analyses and rewrites code in dream mode
│   └── memory_consolidator.py # Consolidates N run summaries into snapshots
│
├── roles/                     # Agent skills & guides (system prompts)
│   ├── product_manager.md
│   ├── pm_reviewer.md
│   ├── architect.md
│   ├── architect_reviewer.md
│   ├── engineer.md
│   ├── code_reviewer.md
│   ├── qa_planner.md
│   ├── qa_engineer.md
│   ├── deployment_tester.md
│   ├── summariser.md
│   ├── refactor_agent.md
│   └── memory_consolidator.md
│
├── tools/                     # Tool calling — Option A (MCP-ready)
│   ├── registry.py            # ToolRegistry ABC + LocalToolRegistry (@tool decorator)
│   ├── builtin.py             # Built-in tools: run_linter, run_shell_command,
│   │                          #   search_github_issues, get_github_file
│   └── __init__.py
│
├── .github/workflows/
│   ├── feature-build.yml      # Auto-trigger on 'feature-request' label
│   ├── bug-fix.yml            # Auto-trigger on 'bug' label
│   ├── run-tests.yml          # Run pytest + docker on PRs
│   └── setup-labels.yml       # Create required issue labels
│
└── workspace/                 # Generated code written here locally
    └── <project-name>/
        ├── checkpoint.json    # Resume state
        ├── memory.db          # SQLite memory store (run/monthly/quarterly tiers)
        ├── memory.md          # Human-readable memory log
        ├── src/               # Generated source files
        └── tests/             # Generated test files
```

---

## 🎯 Skills System

Skills are markdown files in `skills/` that inject domain-specific guidance into agent prompts at runtime. Each skill targets specific roles (e.g. Architect gets architecture guidance, Engineer gets implementation rules) and is auto-detected from context or always-loaded from config.

### How it works

1. **Detection** — At the start of each run, `SkillLoader` scans the issue body and repo languages for tag matches (e.g. issue mentions "flutter" → `skills/flutter.md` is loaded)
2. **Role scoping** — Each skill file has a section per role: `## For Engineers`, `## For Architects`, etc. Only the relevant section is injected per agent
3. **Injection** — Matched skill blocks are prepended to each agent's system prompt as a `## Skills Loaded` block

### Bundled starter skills

| Skill | File | Auto-detects on |
|---|---|---|
| Flutter | `skills/flutter.md` | `flutter`, `dart`, `mobile`, `riverpod`, `drift` |
| FastAPI | `skills/fastapi.md` | `fastapi`, `python`, `api`, `pydantic`, `sqlalchemy` |
| React | `skills/react.md` | `react`, `typescript`, `frontend`, `nextjs`, `vite` |
| Security Audit | `skills/security-audit.md` | `security`, `auth`, `jwt`, `oauth` |
| Docker | `skills/docker.md` | `docker`, `container`, `kubernetes`, `helm` |

### Writing a custom skill

```markdown
---
name: my-skill
description: Brief description
version: 1.0.0
roles:
  architect: true
  engineer: true
  code_reviewer: true
  qa_engineer: true
  product_manager: false
  architect_reviewer: false
  pm_reviewer: false
tags: [my-tag, another-tag]   # matched against issue body + repo languages
source: local
---

# My Skill

## For Architects
Architecture-level guidance here.

## For Engineers
Implementation rules here.

## For Code Reviewers
What to look for in code reviews.

## For QA Engineers
What to test.
```

Save it as `skills/my-skill.md`. It will be auto-detected whenever `my-tag` appears in the issue body.

### Configuration

```yaml
skills:
  # Always load these skills regardless of project context
  always_load: [security-audit]

  # Remote marketplace repo (leave empty to use local only)
  marketplace_repo: ""

  # Marketplace cache dir (defaults to ~/.ai-software-house/skills/)
  cache_dir: ""

  fetch_timeout: 5
```

### Force-load a skill from the issue body

Add a line in the GitHub issue:
```
skills: docker, security-audit
```

### Update marketplace skills

```bash
python main.py --update-skills
```

---

## 🛠️ Tool Calling (Option A) & MCP (Option B)

Agents can call **tools** during their reasoning — not just produce text. The tool-call loop runs automatically inside `BaseAgent.call_with_tools()`.

### How it works

```
Agent prompt
    ↓
LLM decides to call a tool  →  tool executes  →  result appended to messages
    ↓ (repeat until no more tool calls)
Final text response
```

### Built-in tools (`tools/builtin.py`)

| Tool | Used by | What it does |
|---|---|---|
| `run_linter` | Code Reviewer | Runs `ruff` on Python files — concrete lint errors in the review |
| `run_shell_command` | Any agent | Runs a safe shell command (pytest, syntax check, etc.) |
| `search_github_issues` | QA Planner | Searches GitHub issues for existing ACs / related bugs |
| `get_github_file` | Any agent | Reads a file from a GitHub repo at runtime |

### Adding a custom tool

```python
from tools import LocalToolRegistry

my_tools = LocalToolRegistry()

@my_tools.tool(
    name="check_dependencies",
    description="Check if a Python package exists on PyPI",
    parameters={
        "type": "object",
        "properties": {
            "package": {"type": "string", "description": "Package name"},
        },
        "required": ["package"],
    },
)
def check_dependencies(package: str) -> str:
    import requests
    r = requests.get(f"https://pypi.org/pypi/{package}/json", timeout=5)
    return f"Found: {r.json()['info']['version']}" if r.ok else "Not found"

# Use in any agent
response = agent.call_with_tools("Check if fastapi exists", tools=my_tools)
```

### Using MCP Servers

Configure MCP servers in `config.yaml` under the `mcp.servers` key. Tools from all configured servers are automatically merged with the built-in tools and passed to the Code Reviewer and QA Planner agents.

```yaml
mcp:
  servers:
    - name: github
      type: stdio
      command: npx
      args: ["-y", "@modelcontextprotocol/server-github"]
      env:
        GITHUB_TOKEN: "${GITHUB_TOKEN}"   # expanded from env at runtime

    - name: my-search
      type: sse
      url: "https://mcp.example.com/sse"
      headers:
        Authorization: "Bearer ${MCP_API_KEY}"
```

**Server types:**

| Type | Key fields | Notes |
|---|---|---|
| `stdio` | `command`, `args`, `env` | Spawns a local subprocess (e.g. `npx`, `python`) |
| `sse` | `url`, `headers` | Connects to a remote HTTP/SSE endpoint |

**`${VAR}` expansion** — any value in `env` or `headers` can reference an environment variable as `${MY_VAR}`. Unknown variables are left unexpanded.

**Name collisions** — if two servers expose a tool with the same name, the second is prefixed: `servername__toolname`.

**Install:** `pip install mcp` (or add `mcp>=1.0.0` to `requirements.txt` — already included).

> ⚠️ MCP tool-calling requires a tool-calling-capable backend. The `opencode` CLI backend does **not** support tool calls. Use `github_models`, `anthropic`, `opencode-zen/` (non-Claude), or `opencode-go/` (non-MiniMax) backends.

---

## 🔗 How It Connects to GitHub Copilot CLI

This project uses the **same AI backend** as GitHub Copilot CLI:

| | GitHub Copilot CLI | AI Software House |
|---|---|---|
| AI Model | GitHub Models API | GitHub Models API |
| Authentication | Classic PAT (`ghp_…`) | Classic PAT (`ghp_…`) |
| API Endpoint | `models.inference.ai.azure.com` | `models.inference.ai.azure.com` |
| Usage | Interactive terminal assistant | Automated multi-agent pipeline |
| Token scope | `copilot` | `repo` (classic PAT) |

---

## 📚 Background

This project demonstrates how GitHub's infrastructure — Models API, Issues, Pull Requests, Actions — can be wired together into a fully automated software development team. Each agent is a thin Python wrapper around a single LLM call; the orchestrator handles sequencing, checkpointing, and GitHub integration.

The role files (`roles/*.md`) are the heart of the system. They encode domain knowledge, output contracts, and quality rules — making it easy to specialise, tune, or extend any agent without touching Python code.

---

## 📄 License

MIT
