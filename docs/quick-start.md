# Quick Start Guide

> Four real-world scenarios to get productive with AI Software House in under 10 minutes.

---

## Prerequisites (all scenarios)

- **Python 3.10+** — `python --version`
- **GitHub classic PAT** — go to [github.com/settings/tokens](https://github.com/settings/tokens) → Tokens (classic) → tick **`repo`** scope

```bash
export GITHUB_TOKEN=ghp_your_token_here
```

- **Install dependencies:**

```bash
git clone https://github.com/your-username/ai-software-house
cd ai-software-house
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

- **`config.yaml`** — copy the example and set your target repo (see each scenario below)
- For full setup detail (RAG, multi-model, deploy backends) see the main [README](../README.md)

---

## Scenario 1 — Build from Scratch (MVP)

Start with **nothing** — just a plain-English requirement — and let agents produce a working codebase in a new GitHub repo.

### Steps

1. **Create an empty repo on GitHub** (no README, no licence — completely empty)

2. **Point `config.yaml` at it:**

```yaml
github_token: "${GITHUB_TOKEN}"
model: gpt-4o
target_repo: owner/my-new-project   # ← your empty repo
tracker_repo: owner/ai-software-house
```

3. **Write your requirement** — inline or in a file:

```bash
# Inline
python main.py "Build a REST API for a task manager with CRUD endpoints, SQLite storage, and pytest tests" \
  --repo owner/my-new-project

# Or from a file
echo "Build a REST API for a task manager..." > requirements.txt
python main.py --file requirements.txt --repo owner/my-new-project
```

4. **Watch the pipeline run** — the default pipeline (`ai-feature`) kicks in:
   PM → PM Reviewer → Architect → Arch Reviewer → Engineers → Code Reviewer → QA Planner → QA Engineer → Deployment Tester

5. **Review the PR** — agents open a pull request on `owner/my-new-project` containing:
   - Full source code on a feature branch
   - `pytest` test suite
   - `Dockerfile` / `docker-compose.yml` (if requested)
   - PR description summarising what was built

### Optional: Auto-trigger from GitHub issues

Repos are configured individually under `repos-available/` and activated via symlinks in `repos-enabled/`.

**1. Create a repo config file:**

```bash
# repos-available/my-new-project.yaml
tracker_repo: owner/my-new-project
parallel_issues: 2
labels:
  ai-feature: ai-feature
  ai-fix: ai-fix
  ai-smart-fix: ai-smart-fix
  tdd: tdd
  ai-docs: ai-docs
enabled: true
```

**2. Enable it and start the watcher:**

```bash
python watcher.py repo enable my-new-project   # creates symlink in repos-enabled/
python watcher.py repo list                    # verify it's active
python watcher.py                              # polls every 15 min
```

Create a GitHub issue → apply label `ai-feature` → watcher triggers the build automatically.

> `repos-available/` is committed (source of truth). `repos-enabled/` is gitignored — each machine manages its own active set via symlinks.

### Tips

- **Restart completely fresh:** `python main.py --file requirements.txt --repo owner/repo --no-resume`
- **More engineers in parallel:** add `--engineers 4` to speed up large builds
- **Override the model:** `--model gpt-4.1` or `--model-override engineer=gpt-4o`

### ⏱ Typical runtime
~8–12 min (default 2 engineers; scales down with `--engineers 1`, up with `--engineers 4`)

### ✅ What you get
A pull request on your target repo with runnable code, tests, and a PR summary — ready for your review and merge.

---

## Scenario 2 — Bug Fix

You've found a bug and want agents to diagnose, fix, and validate it before opening a PR.

### Path A — Via GitHub label (recommended)

1. **Create a GitHub issue** on your repo describing the bug
2. **Apply label `ai-fix`** (standard) or **`ai-smart-fix`** (includes validation gate — preferred for production)
3. The watcher picks it up and runs the matching pipeline:
   - `ai-fix` → diagnose → fix engineer → code reviewer → QA → PR
   - `ai-smart-fix` → same pipeline + syntax check + ruff lint + pytest **before** the PR opens

### Path B — Direct CLI

```bash
# Inline description
python main.py --pipeline ai-fix --repo owner/repo "Bug: login endpoint returns 500 when email contains uppercase letters"

# From a file
python main.py --pipeline ai-fix --file bug-report.txt --repo owner/repo

# Smart fix (validation gate included)
python main.py --pipeline ai-smart-fix --file bug-report.txt --repo owner/repo
```

### PR Revision loop

After the fix PR opens, post a review comment on GitHub. Agents detect unresolved comments and re-run automatically. To trigger a revision manually:

```bash
python main.py --mode=revise --pr 42 --repo owner/repo
```

### Tips

- **Prefer `ai-smart-fix`** for any repo that has existing tests — the validation gate ensures nothing breaks before the PR opens
- **`--no-resume`** if a previous fix attempt was interrupted and you want a clean run

### ⏱ Typical runtime
~4–6 min for `ai-fix`; ~6–8 min for `ai-smart-fix` (includes test execution)

### ✅ What you get
A fix PR with the minimal targeted change, passing tests, and a summary of root cause + fix applied.

---

## Scenario 3 — New Features & Production Extensions

Your MVP is running. Now you want to add features the agents didn't build in the first pass: auth, rate limiting, a real database, monitoring, etc.

### Path A — Via GitHub label

1. **Create a GitHub issue** describing the feature
2. **Apply label `ai-feature`**
3. Watcher runs the full feature pipeline:
   PM → PM Reviewer → Architect → Arch Reviewer → Engineers → Code Reviewer → QA Planner → QA Engineer → Deployment Tester → PR

### Path B — Direct CLI

```bash
# Inline
python main.py --pipeline ai-feature "Add JWT authentication with refresh tokens" --repo owner/repo

# From a file
python main.py --file new-feature.txt --repo owner/repo
```

### Path C — TDD mode (test-first, production-grade)

QA writes the failing tests first; engineers implement until the tests pass:

```bash
python main.py --pipeline tdd --file feature.txt --repo owner/repo
```

Or apply label **`tdd`** on the GitHub issue and let the watcher handle it.

### Post-merge cleanup

After a feature PR merges, run refactor mode to let agents review code quality and open a cleanup PR:

```bash
python main.py --refactor --repo owner/repo
```

### Tips

- **Break large features into separate issues** (auth, DB migration, monitoring as three issues) and label each — the watcher runs them with the concurrency defined by `parallel_issues` in `repos.yaml`
- **TDD is the safest path** for production-grade work — tests define the contract before any code is written
- **List available pipelines** at any time: `python main.py --list-pipelines`
- **Build a custom pipeline** in the browser GUI: `python main.py --config-builder`

### ⏱ Typical runtime
~8–15 min per feature (TDD adds ~2–3 min for the test-writing stage)

### ✅ What you get
A feature PR with PM spec, architecture notes, implementation, tests, and deployment smoke tests — all in one pull request.

---

## Scenario 4 — Onboard an Existing Repo

You have a codebase you wrote yourself (or inherited). You want agents to start maintaining and extending it without guessing method names or patterns.

### Steps

1. **Bootstrap the repo** — agents read the actual code and generate cheatsheets:

```bash
python main.py --repo owner/existing-repo
```

> This creates `.github/copilot-instructions.md` in your target repo with real constructor signatures, method names, and patterns extracted from the existing code. Every subsequent agent run reads this file — engineers know the codebase from day one.

2. **Register the repo in `repos-available/`** (for watcher-based automation):

```bash
# Create repos-available/existing-repo.yaml
```

```yaml
tracker_repo: owner/existing-repo
parallel_issues: 2
labels:
  ai-feature: ai-feature
  ai-fix: ai-fix
  ai-smart-fix: ai-smart-fix
  tdd: tdd
  ai-docs: ai-docs
enabled: true
```

```bash
python watcher.py repo enable existing-repo   # activate it
python watcher.py repo list                   # confirm
```

3. **First agent run — start small and low-risk:**
   - Label an issue `ai-docs` → agents document what already exists
   - Review the PR carefully — this tells you how well agents understand the codebase
   - Or: add a small utility function via `ai-feature` before attempting anything structural

4. **Bug fixes via `ai-smart-fix`** — the validation gate runs the full test suite before the PR opens, so nothing breaks existing tests:

```bash
# Label the issue ai-smart-fix, or run directly:
python main.py --pipeline ai-smart-fix --file bug-report.txt --repo owner/existing-repo
```

5. **New features via `ai-feature` or `tdd`:**

```bash
# Standard feature
python main.py --pipeline ai-feature "Add pagination to the /users endpoint" --repo owner/existing-repo

# Test-first if the repo has a strong test suite
python main.py --pipeline tdd --file feature.txt --repo owner/existing-repo
```

6. **Enable RAG for large or complex repos** so agents can search the codebase instead of guessing:

```yaml
# config.yaml
rag:
  enabled: true
  auto_index: true
```

Agents then call `search_codebase("BaseController")` during engineering — no more hallucinated method names.

7. **Learning kicks in automatically** — after any validation failure, `LearningAgent` writes DO NOT rules back into the agent role files. Each run gets better because past mistakes are in the system prompt.

### Tips

- **Do `ai-docs` first** — it's read-only and gives you a sense of agent comprehension before anything is changed
- **Use `ai-smart-fix` for all bug work** on repos with existing tests — the gate prevents regressions
- **Commit `.github/copilot-instructions.md`** after the bootstrap — it's the agents' map of your repo

### ⏱ Typical runtime
Bootstrap: ~3 min · First `ai-docs` run: ~5 min · Feature/fix runs: same as Scenarios 2–3

### ✅ What you get
A bootstrapped repo where agents understand your actual code, safely patched or extended via PRs with a validation gate protecting your existing test suite.

---

## What Happens When Something Goes Wrong

| Symptom | Fix |
|---|---|
| Run interrupted mid-pipeline | Re-run the same command — checkpoint resumes from the last successful stage |
| Checkpoint is corrupt / stale | Add `--no-resume` to start completely fresh |
| Validation gate fails (lint / tests) | Agents auto-retry up to 2× with the exact error message; if still failing, check the PR comments for details |
| PR has unresolved review comments | Post the feedback on GitHub, or run `python main.py --mode=revise --pr <number> --repo owner/repo` manually |
| Agents produce wrong code for your repo | Run `python main.py --repo owner/repo` to (re)bootstrap cheatsheets, then re-run |
| Want to see all pipeline options | `python main.py --list-pipelines` |
| Want to build a custom pipeline | `python main.py --config-builder` (opens browser GUI) |
