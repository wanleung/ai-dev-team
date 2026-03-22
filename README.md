# 🏢 AI Software House

A team of AI agents that builds software from a plain-English requirement — powered by the **GitHub Models API** (the same AI backend as GitHub Copilot CLI) and integrated with **GitHub** for issue tracking, code management, and pull requests.

```
Requirement → PM → Architect → Engineers ×N → Code Reviewer → QA → Test Runner → Deployment Tester → PR
```

## ✨ Features

- **7 specialized agents**: Product Manager, Architect, N Engineers, Code Reviewer, QA Engineer, Deployment Tester
- **GitHub-native**: creates Issues (PRD), feature branches, Pull Requests, and review comments
- **Auto-trigger on Issues**: label any issue `ai-fix` or `ai-feature` → pipeline runs automatically via GitHub Actions
- **Two pipelines**: full feature build **and** focused bug-fix (diagnosis → fix → review → regression tests)
- **Test execution**: unit tests + deployment smoke tests run automatically, results posted to PR
- **Parallel engineering**: N engineer agents implement modules simultaneously
- **Per-agent LLM**: each agent can use a different model (powerful for PM/Architect, fast/cheap for Engineer)
- **Checkpoint/resume**: pipeline saves progress — re-run after a failure to continue from where it stopped
- **Same AI as Copilot CLI**: uses your PAT (`GH_TOKEN` secret) and GitHub Models API — no extra API keys
- **Local workspace**: all generated files saved to `./workspace/` for inspection
- **Configurable**: YAML config for model selection, team size, and GitHub settings

---

## 🚀 Quick Start

### 1. Prerequisites

- Python 3.9+
- A GitHub account with a [Personal Access Token](https://github.com/settings/tokens/new) (classic, not fine-grained)

**Token permissions required (classic PAT):**
| Permission | Why |
|---|---|
| **`repo`** (full) | Commit code, open PRs, create branches |
| **`read:org`** | Required if repo is under an org |

> ⚠️ Must be a **classic** token (`ghp_...`). Fine-grained PATs (`github_pat_...`) do NOT work with the GitHub Models API.

### 2. Install

```bash
git clone https://github.com/YOUR_USERNAME/ai-software-house
cd ai-software-house
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure

```bash
export GITHUB_TOKEN=ghp_your_token_here
```

Edit `config.yaml` to set your target GitHub repo:
```yaml
github:
  repo: "your-username/your-project-repo"
```

### 4. Run

```bash
# With requirement inline
python main.py "Build a REST API for a task management app with user authentication"

# Load requirement from a text file
python main.py --file requirements.txt --repo myuser/myrepo

# Local only (no GitHub) — files saved to ./workspace/
python main.py --file requirements.txt --no-github

# Start fresh (ignore saved checkpoint)
python main.py --file requirements.txt --repo myuser/myrepo --no-resume
```

---

## 📋 All CLI Options

```
python main.py [requirement] [options]

Positional:
  requirement               Plain-English description of what to build

Options:
  --file PATH               Read requirement from a text/markdown file
  --repo OWNER/REPO         GitHub repo for integration (overrides config.yaml)
  --model MODEL             Default LLM for all agents  (e.g. gpt-4.1)
  --model-override          Per-agent model, repeatable  (e.g. engineer=gpt-4.1-mini)
    AGENT=MODEL
  --engineers N             Number of parallel engineer agents (default: 2)
  --no-github               Disable GitHub integration, save files locally only
  --no-resume               Ignore checkpoint, start pipeline from scratch
  --workspace DIR           Local output directory (default: ./workspace)
  --token TOKEN             GitHub token (overrides GITHUB_TOKEN env var)
  --config FILE             Config YAML file (default: config.yaml)
```

**Example `requirements.txt`:**
```
Build a task management REST API.

## Features
- User registration and JWT authentication
- CRUD for tasks (title, description, due date, status)
- Filter tasks by status: todo / in-progress / done
- PostgreSQL with SQLAlchemy ORM
- Pytest test suite

## Constraints
- Python 3.11+, FastAPI framework
- Return JSON errors with meaningful messages
```

---

## 🔧 Using the Orchestrators Directly

The project has **two orchestrators** — choose based on what you need:

### `orchestrator.py` — Full Feature Build

Runs the complete 8-stage pipeline from requirement to PR.

**Via CLI (`main.py`):**
```bash
# Build from a file
python main.py --file requirements.txt --repo wanleung/my-project

# Use specific models per agent
python main.py --file req.txt --repo wanleung/my-project \
  --model-override architect=claude-3.5-sonnet \
  --model-override engineer=gpt-4.1-mini

# More parallel engineers for large projects
python main.py --file req.txt --repo wanleung/my-project --engineers 4
```

**Via Python:**
```python
from orchestrator import Orchestrator

orch = Orchestrator.from_config("config.yaml", github_token="ghp_...")
result = orch.run("Build a REST API for patient records")

print(result.pr_url)           # https://github.com/owner/repo/pull/3
print(result.project_name)     # "Patient Records REST API"
print(len(result.all_files))   # 24
print(result.tests_passed)     # True
print(result.deploy_tests_passed)  # True / False / None (skipped)
```

**Pipeline stages:**
```
1. 📋 Product Manager   — requirement → PRD + GitHub Issue
2. 🏗️  Architect         — PRD → system design + modules
3. 💻 Engineers ×N      — parallel code generation → feature branch + PR
4. 🔍 Code Reviewer     — reviews code → PR comment
5. 🧪 QA Engineer       — writes tests + conftest.py + requirements-test.txt → PR
6. 🏃 Test Runner       — runs pytest locally → PR comment with results
7. 🚀 Deployment Tester — generates docker-compose.test.yml + smoke tests → PR
8. 🐳 Deploy Test Runner— runs docker smoke tests → PR comment (skips if no Docker)
```

---

### `bug_fix_orchestrator.py` — Bug Fix Pipeline

Targeted pipeline for fixing bugs reported in GitHub Issues. Skips PM — the issue IS the requirement.

**Via CLI (`fix_issue.py`):**
```bash
# Fix bug from issue #7 in the tracker repo
# (code changes go to the repo in the issue body's "Target repo:" line)
python fix_issue.py --issue-number 7 --repo wanleung/ai-software-house

# Fix directly in a specific project repo
python fix_issue.py --issue-number 3 --repo wanleung/test-mobile-01

# With a custom model
python fix_issue.py --issue-number 7 --repo wanleung/ai-software-house --model gpt-4.1
```

**Via Python:**
```python
from bug_fix_orchestrator import BugFixOrchestrator

orch = BugFixOrchestrator.from_config("config.yaml", github_token="ghp_...")
result = orch.run(
    issue_number=7,
    tracker_repo="wanleung/ai-software-house"
)
print(result.pr_url)   # PR with the targeted fix
```

**Pipeline stages:**
```
1. 🔬 Diagnosis (Architect) — reads issue + existing code → root cause analysis
2. 🔧 Fix (Engineer)        — patches only the affected files → branch + PR
3. 🔍 Code Reviewer         — reviews the fix → PR comment
4. 🧪 Regression Tests (QA) — writes tests to prevent regression → PR
```

---

### `build_feature.py` — Feature from Issue (GitHub Actions entry point)

Same as `main.py` but reads the requirement from a GitHub Issue. Used by `feature-build.yml`.

```bash
# Manually invoke (same as triggering via label)
python build_feature.py --issue-number 5 --tracker-repo wanleung/ai-software-house
```

---

## 🤖 GitHub Actions — Auto-Trigger

The pipelines run **automatically** when you label a GitHub Issue. No manual command needed.

### Setup (one time)

**1. Push this repo to GitHub:**
```bash
git remote add origin https://github.com/YOUR_USERNAME/ai-software-house
git push -u origin master
```

**2. Add your PAT as a repository secret:**  
Go to: **Settings → Secrets and variables → Actions → New repository secret**
- Name: `GH_TOKEN`
- Value: your classic Personal Access Token

> **Why `GH_TOKEN` not `GITHUB_TOKEN`?** GitHub blocks secret names starting with `GITHUB_`. Also the auto-injected `GITHUB_TOKEN` represents `github-actions[bot]` which has no Copilot subscription — it can't call the AI API. Your PAT (stored as `GH_TOKEN`) is tied to your account which has Copilot access.

**3. Create the required labels:**  
Go to: **Actions → 🏷️ Setup AI Labels → Run workflow**

This creates: `ai-fix`, `ai-feature`, `prd`, `ai-generated`

---

### Triggering a bug fix

```
1. Open a GitHub Issue reporting the bug
2. Add the label:  ai-fix
3. GitHub Actions triggers automatically

Pipeline:  Issue → Diagnosis → Fix → Review → Regression Tests → PR
```

**Example issue body:**
```
Title: Login fails with uppercase email addresses

Steps to reproduce:
1. Enter email with uppercase (e.g. User@Example.com)
2. Click login
Expected: logs in successfully
Actual: nothing happens, no error shown
```

---

### Triggering a new feature build

```
1. Open a GitHub Issue describing the feature
2. Add the label:  ai-feature
3. The full 8-stage pipeline runs

Pipeline:  Issue → PM → Architect → Engineers → Review → QA → Tests → Deploy Tests → PR
```

---

### 🏢 Central agency — targeting a different project repo

Add a `Target repo:` line to the issue body and the agents will push code to that repo instead:

```markdown
Title: Add patient questionnaire API

Target repo: wanleung/my-medical-app

## Description
Add a REST API for managing patient questionnaires.
Patients can fill in forms, doctors can review responses.

## Acceptance Criteria
- POST /questionnaires — create a new questionnaire
- GET /questionnaires/{id}/responses — list all patient responses
- JWT auth required
```

When labeled `ai-feature`, the code goes to `wanleung/my-medical-app`, not to `ai-software-house`.

**Multiple projects, one AI team:**
```
ai-software-house (your hub)
├── Issue #5  [ai-feature]  Target repo: me/react-dashboard  → PR in react-dashboard
├── Issue #6  [ai-fix]      Target repo: me/node-api         → fix PR in node-api
└── Issue #7  [ai-feature]  (no Target repo)                 → PR in ai-software-house itself
```

---

### Workflows overview

| Workflow | Trigger | Pipeline |
|---|---|---|
| `bug-fix.yml` | Issue labeled `ai-fix` | Diagnosis → Fix → Review → Tests |
| `feature-build.yml` | Issue labeled `ai-feature` | PM → Architect → Engineers → Review → QA → Tests |
| `run-tests.yml` | PR opened/updated | Unit tests + Docker smoke tests → PR comments |
| `setup-labels.yml` | Manual (run once) | Creates required labels |

---

## ⚙️ Configuration Reference (`config.yaml`)

```yaml
llm:
  # Default model for all agents
  # GitHub Models options:
  #   OpenAI:     gpt-4.1, gpt-4.1-mini, gpt-4.1-nano, gpt-4o, o4-mini, o3
  #   Anthropic:  claude-3.7-sonnet, claude-3.5-sonnet, claude-3-haiku
  #   Meta:       meta-llama-3.3-70b-instruct, meta-llama-3.1-405b-instruct
  #   Mistral:    mistral-large-2411, mistral-small-2503
  #   DeepSeek:   deepseek-r1, deepseek-v3
  model: "gpt-4.1"

  # Per-agent overrides — each agent can use a different LLM
  # Tip: powerful model for PM/Architect (reasoning), cheap/fast for Engineer (repetitive)
  overrides:
    product_manager: "gpt-4.1"
    architect: "gpt-4.1"
    engineer: "gpt-4.1-mini"       # runs N times — use cheaper model
    code_reviewer: "gpt-4.1"
    qa_engineer: "gpt-4.1-mini"
    deployment_tester: "gpt-4.1-mini"

github:
  repo: "owner/repo"               # Where code PRs are created
  branch_prefix: "feature/agent"

team:
  num_engineers: 2                 # Parallel engineer agents
  agents:
    product_manager: true
    architect: true
    engineer: true
    code_reviewer: true
    qa_engineer: true
    deployment_tester: true

pipeline:
  workspace_dir: "./workspace"     # Local output directory
  stop_on_review_issues: false     # Stop if reviewer requests changes
```

**CLI override** (takes precedence over config.yaml):
```bash
python main.py --file req.txt \
  --model gpt-4.1 \
  --model-override engineer=gpt-4.1-mini \
  --model-override architect=claude-3.5-sonnet
```

---

## 📁 Project Structure

```
ai-software-house/
├── main.py                      # CLI entry point for feature builds
├── fix_issue.py                 # CLI entry point for bug fixes
├── build_feature.py             # GitHub Actions entry point (reads from Issue)
├── orchestrator.py              # Full 8-stage feature pipeline
├── bug_fix_orchestrator.py      # Focused bug-fix pipeline
├── github_client.py             # GitHub REST API wrapper
├── config.yaml                  # Configuration
├── requirements.txt
│
├── .github/workflows/
│   ├── bug-fix.yml              # Auto-runs on "ai-fix" label
│   ├── feature-build.yml        # Auto-runs on "ai-feature" label
│   ├── run-tests.yml            # Auto-runs unit + docker tests on PRs
│   └── setup-labels.yml         # One-time label setup
│
├── agents/
│   ├── base_agent.py            # BaseAgent (GitHub Models API, retry logic)
│   ├── product_manager.py
│   ├── architect.py
│   ├── engineer.py              # Parallel N-worker, rate-limit aware
│   ├── code_reviewer.py
│   ├── qa_engineer.py
│   └── deployment_tester.py    # Docker smoke test generator
│
└── roles/                       # Agent system prompts (markdown)
    ├── product_manager.md
    ├── architect.md
    ├── engineer.md
    ├── code_reviewer.md
    ├── qa_engineer.md
    └── deployment_tester.md
```

---

## 🤖 Agent Roles

| Agent | Name | Input | Output | GitHub Artifact |
|---|---|---|---|---|
| **Product Manager** | Alice | Raw requirement | PRD markdown | GitHub Issue |
| **Architect** | Bob | PRD | System design + modules | Issue comment |
| **Engineer ×N** | Alex (×N) | System design | Code files | Feature branch + PR |
| **Code Reviewer** | Carol | Code files + PRD | Review + verdict | PR review comment |
| **QA Engineer** | Edward | Code + PRD | Test files + conftest + requirements-test.txt | PR comment + tests on branch |
| **Deployment Tester** | Diana | Code + Dockerfile | docker-compose.test.yml + smoke tests + deploy script | PR comment + files on branch |

---

## 🧩 How It Connects to Copilot CLI

This project uses the **same AI backend** as GitHub Copilot CLI:

| | GitHub Copilot CLI | AI Software House |
|---|---|---|
| AI Model | GitHub Models API | GitHub Models API |
| Authentication | `GITHUB_TOKEN` (PAT) | `GH_TOKEN` secret |
| API Endpoint | `models.inference.ai.azure.com` | `models.inference.ai.azure.com` |
| Usage | Interactive terminal | Python orchestration pipeline |

---

## 🔧 Extending the Team

Add a new agent role by:

1. Creating `roles/your_role.md` with the agent's system prompt
2. Creating `agents/your_role.py` extending `BaseAgent`
3. Adding it to `agents/__init__.py`
4. Wiring it into `orchestrator.py` as a new stage

---

## 📚 Background

Inspired by:
- **[MetaGPT](https://github.com/FoundationAgents/MetaGPT)** — "The Multi-Agent Framework: First AI Software Company" (ICLR 2024)
- **[ChatDev](https://github.com/OpenBMB/ChatDev)** — "Communicative Agents for Software Development" (ACL 2024)

The key insight: encoding **Standard Operating Procedures (SOPs)** into LLM agent workflows reduces hallucination cascades and produces more coherent, structured outputs than naive LLM chaining.

---

## 📄 License

MIT


A team of AI agents that builds software from a plain-English requirement — powered by the **GitHub Models API** (the same AI backend as GitHub Copilot CLI) and integrated with **GitHub** for issue tracking, code management, and pull requests.

```
Requirement → PM → Architect → Engineers ×N → Code Reviewer → QA → PR on GitHub
```

## ✨ Features

- **6 specialized agents**: Product Manager, Architect, N Engineers, Code Reviewer, QA
- **GitHub-native**: creates Issues (PRD), feature branches, Pull Requests, and review comments
- **Auto-trigger on Issues**: label any issue `ai-fix` → pipeline runs automatically via GitHub Actions
- **Two pipelines**: full feature build **and** focused bug-fix (diagnosis → fix → review → regression tests)
- **Parallel engineering**: N engineer agents implement modules simultaneously
- **Same AI as Copilot CLI**: uses your PAT (`GH_TOKEN` secret) and GitHub Models API — no extra API keys
- **Local workspace**: all generated files saved to `./workspace/` for inspection
- **Configurable**: YAML config for model selection, team size, and GitHub settings

---

## 🚀 Quick Start

### 1. Prerequisites

- Python 3.9+
- A GitHub account with a [Personal Access Token](https://github.com/settings/personal-access-tokens/new)

**Token permissions required:**
| Permission | Why |
|---|---|
| **Copilot Requests** | LLM calls via GitHub Models API |
| **Contents** (read/write) | Commit generated code |
| **Issues** (read/write) | Create PRD issues |
| **Pull requests** (read/write) | Open PRs and add reviews |

### 2. Install

```bash
git clone https://github.com/YOUR_USERNAME/ai-software-house
cd ai-software-house
python3 -m pip install -r requirements.txt
```

### 3. Configure

```bash
export GITHUB_TOKEN=ghp_your_token_here  # your PAT (used locally and as GH_TOKEN secret in Actions)
```

Edit `config.yaml` to set your target GitHub repo:
```yaml
github:
  repo: "your-username/your-project-repo"
```

### 4. Run

```bash
# Interactive mode (prompts for requirement)
python main.py

# With requirement inline
python main.py "Build a REST API for a task management app with user authentication"

# Load requirement from a text file
python main.py --file requirements.txt

# With GitHub integration (creates Issues + PR)
python main.py "Build a blog platform with markdown support" --repo myuser/myrepo
python main.py --file requirements.txt --repo myuser/myrepo

# Local only (no GitHub) — files saved to ./workspace/
python main.py --file requirements.txt --no-github

# Use a faster/cheaper model
python main.py "Build a calculator" --model gpt-4.1-mini --engineers 1
```

**Example `requirements.txt`:**
```
Build a task management REST API.

## Features
- User registration and JWT authentication
- CRUD for tasks (title, description, due date, status)
- Filter tasks by status: todo / in-progress / done
- PostgreSQL with SQLAlchemy ORM
- Pytest test suite

## Constraints
- Python 3.11+, FastAPI framework
- Return JSON errors with meaningful messages
```

> **Tip:** The requirements file can be plain text or Markdown — headings, bullet points, and acceptance criteria all help the agents produce better output.

---

## 🤖 GitHub Actions — Auto-Trigger

The pipelines run **automatically** when you label a GitHub Issue. No manual command needed.

### Setup (one time)

**1. Push this repo to GitHub:**
```bash
git remote add origin https://github.com/YOUR_USERNAME/ai-software-house
git push -u origin master
```

**2. Add your PAT as a repository secret:**  
Go to: **Settings → Secrets and variables → Actions → New repository secret**
- Name: `GH_TOKEN`
- Value: your Personal Access Token from step 1

> **Why not `GITHUB_TOKEN`?** GitHub blocks secret names starting with `GITHUB_`. Also, the auto-injected `GITHUB_TOKEN` represents the `github-actions[bot]` which has no Copilot subscription and can't call the AI API. Your PAT (stored as `GH_TOKEN`) is tied to your account which has Copilot access.

**3. Create the required labels:**  
Go to: **Actions → 🏷️ Setup AI Labels → Run workflow**

This creates: `ai-fix`, `ai-feature`, `prd`, `ai-generated`

---

### Triggering a bug fix automatically

```
1. Someone opens a GitHub Issue reporting a bug
2. You (or a maintainer) add the label:  ai-fix
3. GitHub Actions triggers automatically
4. The AI pipeline runs:
   Issue → Diagnosis → Fix → Code Review → Regression Tests → PR
5. A PR is opened with the fix within ~2 minutes
6. The issue gets comments at each stage
```

**Example issue that would trigger it:**
```
Title: Login button does nothing when clicking with email that has capital letters
Body:  Steps to reproduce:
       1. Enter email with uppercase letters (e.g. User@Example.com)
       2. Click login
       Expected: should log in
       Actual: nothing happens, no error shown
```

After adding label `ai-fix`:
- 🔬 Architect diagnoses root cause (case sensitivity bug in email comparison)
- 🔧 Engineer patches the affected files
- 🔍 Code Reviewer reviews the fix
- 🧪 QA adds a regression test case
- A PR is opened: `fix/agent/issue-42-login-button-does-nothing...`

---

### Triggering a new feature build

```
1. Open a GitHub Issue describing a feature
2. Add the label:  ai-feature
3. The full pipeline runs:
   Issue → PM (PRD) → Architect → Engineers ×N → Reviewer → QA → PR
```

---

### 🏢 Central agency — targeting any project repo

`ai-software-house` can work as a **central AI team hub** that builds code in a *separate* project repo. Just add a `Target repo:` line to any issue body:

```markdown
Title: Add dark mode toggle to the settings page

**Target repo:** myusername/my-webapp

## Description
Add a dark mode toggle in the Settings page. It should persist in localStorage
and apply a `dark` CSS class to the document root.

## Acceptance Criteria
- Toggle appears in Settings
- State persists across page reloads
- Works with existing Tailwind CSS setup
```

When this issue is labeled `ai-fix` or `ai-feature`:

```
ai-software-house repo           my-webapp repo
       │                                │
       ├── Issue #12 filed here         │
       │   └── label: ai-feature        │
       │                                │
       ├── Pipeline runs (Actions)      │
       │   PM creates tracker issue ─── │
       │                                ├── feature/agent/... branch
       │   Engineers commit code ──────▶│
       │   PR opened ─────────────────▶│
       │   PR review posted ──────────▶│
       │   QA tests committed ────────▶│
       │                                │
       └── Issue #12 closed with link ──┘
```

**Multiple projects, one AI team:**
```
ai-software-house
├── Issue #5  [ai-feature]  Target repo: me/react-dashboard   → PR in react-dashboard
├── Issue #6  [ai-fix]      Target repo: me/node-api          → fix PR in node-api
└── Issue #7  [ai-feature]  (no Target repo)                  → PR in ai-software-house itself
```

> **Token permissions**: The auto-injected `GITHUB_TOKEN` in Actions can't call the GitHub Models API (no Copilot access). To commit code to a *different* project repo, create a PAT with `Contents` write access to that repo and add it as a secret named `GH_TOKEN` (same secret, just ensure it also has access to the target repo).

---

### Workflows overview

| Workflow | Trigger | Pipeline |
|---|---|---|
| `bug-fix.yml` | Issue labeled `ai-fix` | Diagnosis → Fix → Review → Tests |
| `feature-build.yml` | Issue labeled `ai-feature` | PM → Architect → Engineers → Review → QA |
| `setup-labels.yml` | Manual (run once) | Creates required labels |

---

## 📁 Project Structure

```
ai-software-house/
├── main.py                      # CLI: python main.py "Build a todo app"
├── orchestrator.py              # Full feature pipeline
├── bug_fix_orchestrator.py      # Bug-fix pipeline (triggered by GitHub Issues)
├── fix_issue.py                 # Entry point for GitHub Actions bug-fix workflow
├── build_feature.py             # Entry point for GitHub Actions feature workflow
├── github_client.py             # GitHub REST API wrapper
├── config.yaml                  # Configuration
├── requirements.txt
│
├── .github/
│   └── workflows/
│       ├── bug-fix.yml          # Auto-runs on "ai-fix" label
│       ├── feature-build.yml    # Auto-runs on "ai-feature" label
│       └── setup-labels.yml    # One-time label setup
│
├── agents/
│   ├── base_agent.py            # BaseAgent (calls GitHub Models API)
│   ├── product_manager.py
│   ├── architect.py
│   ├── engineer.py              # Parallel N-worker engineer
│   ├── code_reviewer.py
│   └── qa_engineer.py
│
└── roles/                       # Agent role instructions (system prompts)
    ├── product_manager.md
    ├── architect.md
    ├── engineer.md
    ├── code_reviewer.md
    └── qa_engineer.md
```

---

## 🤖 Agent Roles

| Agent | Name | Input | Output | GitHub Artifact |
|---|---|---|---|---|
| **Product Manager** | Alice | Raw requirement | PRD markdown | GitHub Issue |
| **Architect** | Bob | PRD | System design + modules | Issue comment |
| **Engineer ×N** | Alex (×N) | System design | Code files | Feature branch + PR |
| **Code Reviewer** | Carol | Code files | Review + verdict | PR review |
| **QA Engineer** | Edward | Code + PRD | Test files + report | PR comment + close issue |

---

## ⚙️ Configuration Reference

```yaml
# config.yaml
llm:
  model: "gpt-4.1"              # Default model for all agents
  overrides:
    engineer: "gpt-4.1-mini"   # Use faster model for engineers

github:
  repo: "owner/repo"           # Target GitHub repo
  branch_prefix: "feature/agent"

team:
  num_engineers: 2              # Parallel engineer agents

pipeline:
  workspace_dir: "./workspace"  # Local output directory
  stop_on_review_issues: false  # Stop if reviewer requests changes
```

---

## 🧩 How It Connects to Copilot CLI

This project uses the **same AI backend** as GitHub Copilot CLI:

| | GitHub Copilot CLI | AI Software House |
|---|---|---|
| AI Model | GitHub Models API | GitHub Models API |
| Authentication | `GITHUB_TOKEN` (PAT) | `GH_TOKEN` secret |
| API Endpoint | `models.inference.ai.azure.com` | `models.inference.ai.azure.com` |
| Usage | Interactive terminal | Python orchestration |

You can use the Copilot CLI's `/fleet` command to run multiple independent agent sessions in parallel — this project provides the Python-level equivalent for programmatic pipelines.

---

## 📖 Example Output

Running `python main.py "Build a task manager REST API"` produces:

```
🏢 AI Software House Pipeline
Build a task manager REST API...

  ✅ 📋 Product Manager complete
  ✅ 🏗️  Architect complete
  ✅ 💻 Engineers (×2) complete
  ✅ 🔍 Code Reviewer complete
  ✅ 🧪 QA Engineer complete

┌─────────────────────────────────────────────┐
│              Pipeline Summary               │
├────────────────┬────────────────────────────┤
│ Project        │ Task Manager REST API      │
│ PRD            │ 1842 chars                 │
│ Modules        │ 4                          │
│ Code files     │ 8                          │
│ Test files     │ 3                          │
│ Review verdict │ APPROVED WITH MINOR COMMENTS│
│ GitHub Issue   │ https://github.com/...     │
│ Pull Request   │ https://github.com/...     │
│ Duration       │ 47.3s                      │
└────────────────┴────────────────────────────┘
```

---

## 🔧 Extending the Team

Add a new agent role by:

1. Creating `roles/your_role.md` with the agent's system prompt
2. Creating `agents/your_role.py` extending `BaseAgent`
3. Adding it to `agents/__init__.py`
4. Wiring it into `orchestrator.py`

---

## 📚 Background

This project is inspired by the academic research behind:
- **[MetaGPT](https://github.com/FoundationAgents/MetaGPT)** — "The Multi-Agent Framework: First AI Software Company" (ICLR 2024)
- **[ChatDev](https://github.com/OpenBMB/ChatDev)** — "Communicative Agents for Software Development" (ACL 2024)

The key insight: encoding **Standard Operating Procedures (SOPs)** into LLM agent workflows reduces hallucination cascades and produces more coherent, structured outputs than naive LLM chaining.

---

## 📄 License

MIT
