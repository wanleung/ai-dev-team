# 🏢 AI Software House

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
- **Same AI as Copilot CLI**: uses `GITHUB_TOKEN` and GitHub Models API — no extra API keys
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
export GITHUB_TOKEN=ghp_your_token_here
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

**2. Add `GITHUB_TOKEN` as a repository secret:**  
Go to: **Settings → Secrets and variables → Actions → New repository secret**
- Name: `GITHUB_TOKEN` ← GitHub provides this *automatically* in Actions (no manual secret needed!)
  
> `GITHUB_TOKEN` is auto-injected by GitHub Actions. You only need to ensure the workflow has the right **permissions** (already set in the workflow files).

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

> **Token permissions**: The `GITHUB_TOKEN` in GitHub Actions only has access to the `ai-software-house` repo. To commit code to a *different* project repo, you must create a **Personal Access Token (PAT)** with `Contents` write access to that repo, and add it as a repository secret named `TARGET_GITHUB_TOKEN`. Then pass it via `--token ${{ secrets.TARGET_GITHUB_TOKEN }}` in the workflow.

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
| Authentication | `GITHUB_TOKEN` | `GITHUB_TOKEN` |
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
