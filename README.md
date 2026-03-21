# 🏢 AI Software House

A team of AI agents that builds software from a plain-English requirement — powered by the **GitHub Models API** (the same AI backend as GitHub Copilot CLI) and integrated with **GitHub** for issue tracking, code management, and pull requests.

```
Requirement → PM → Architect → Engineers ×N → Code Reviewer → QA → PR on GitHub
```

## ✨ Features

- **6 specialized agents**: Product Manager, Architect, N Engineers, Code Reviewer, QA
- **GitHub-native**: creates Issues (PRD), feature branches, Pull Requests, and review comments
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

# With GitHub integration
python main.py "Build a blog platform with markdown support" --repo myuser/myrepo

# Local only (no GitHub)
python main.py "Build a weather CLI app" --no-github

# Use a faster/cheaper model
python main.py "Build a calculator" --model gpt-4.1-mini --engineers 1
```

---

## 📁 Project Structure

```
ai-software-house/
├── main.py                  # CLI entry point
├── orchestrator.py          # Pipeline manager
├── github_client.py         # GitHub REST API wrapper
├── config.yaml              # Configuration
├── requirements.txt
│
├── agents/
│   ├── __init__.py
│   ├── base_agent.py        # BaseAgent (calls GitHub Models API)
│   ├── product_manager.py   # PM: requirement → PRD
│   ├── architect.py         # Architect: PRD → system design
│   ├── engineer.py          # Engineer: design → code (parallel)
│   ├── code_reviewer.py     # Reviewer: code → review feedback
│   └── qa_engineer.py       # QA: code → tests + test plan
│
└── roles/                   # Agent role instructions (system prompts)
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
