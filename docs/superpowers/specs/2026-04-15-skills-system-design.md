# Skills System Design

**Date:** 2026-04-15  
**Status:** Approved  
**Feature:** Pluggable skill system for ai-software-house agents

---

## Overview

A skill-aware agent protocol that allows ai-software-house agents to load domain knowledge and workflow capabilities from markdown skill files at runtime. Skills are auto-detected from project context and injected into agent prompts in a role-scoped manner. Both local skills and a remote marketplace are supported.

---

## Goals

- Agents automatically follow technology-specific or workflow-specific guidance without manual prompt editing
- Extensible: adding a new skill requires only dropping a markdown file into `skills/`
- Role-scoped: each agent role sees only the skill content relevant to it
- Graceful degradation: skill failures never block a pipeline run
- Marketplace support: skills can be shared via a GitHub repo and fetched at startup

---

## Architecture

### Components

```
ai-software-house/
├── skills/                           # local skills (committed to repo)
│   ├── flutter.md
│   ├── fastapi.md
│   ├── react.md
│   ├── security-audit.md
│   └── docker.md
├── skills_loader.py                  # NEW: SkillLoader class
├── config.yaml                       # extended: skills.always_load, skills.marketplace_repo
└── orchestrator.py                   # modified: inject skills into agent prompts
```

**Remote cache:** `~/.ai-software-house/skills/` — marketplace skills cached locally after first fetch.

### Three Layers

1. **Discovery** — `SkillLoader` scans `skills/` (local) and optionally fetches a `skills-index.json` from the configured marketplace GitHub repo. Remote skills are downloaded on first use and cached.

2. **Detection** — `SkillLoader.detect(context)` scans the issue body, PR description, and repo language hints for tag keywords. Returns a ranked list of matching skills. Explicit `skills:` override in the issue body or `always_load` in config takes precedence.

3. **Injection** — `SkillLoader.for_role(role, matched_skills)` extracts the `## For <Role>` section from each matched skill and returns content blocks ready for prompt injection.

---

## Skill File Format

Each skill is a single markdown file with YAML frontmatter.

```markdown
---
name: flutter
description: Flutter/Dart mobile development guidance for all project phases
version: 1.0.0
roles:
  architect: true
  engineer: true
  code_reviewer: true
  qa_engineer: true
  product_manager: false
  architect_reviewer: false
  pm_reviewer: false
tags: [flutter, dart, mobile, ios, android, widget]
source: local   # or: marketplace
---

# Flutter Skill

## For Architects
- Prefer feature-based folder structure (`lib/features/auth/`, `lib/features/home/`)
- Use Riverpod for state management; avoid setState in anything but leaf widgets
- Drift for local DB; always generate `.g.dart` files before committing

## For Engineers
- Run `flutter pub run build_runner build --delete-conflicting-outputs` after model changes
- Golden tests for UI components; integration tests for navigation flows

## For Code Reviewers
- Flag any `BuildContext` used across async gaps without `mounted` check
- Verify `.g.dart` files are committed alongside model changes

## For QA Engineers
- Test on both iOS Simulator and Android Emulator in CI
- Include `flutter test --coverage` in the test plan
```

**Role section names** must match exactly (case-insensitive): `For Architects`, `For Engineers`, `For Code Reviewers`, `For QA Engineers`, `For Product Managers`, `For Architect Reviewers`, `For PM Reviewers`.

A skill that omits a role section for a given role is not injected for that role (same as `roles.<role>: false`).

---

## Detection Logic

### Auto-detection

Tags are matched against a combined context string: issue title + body + PR description + detected repo languages (from GitHub Linguist via API). Matching is case-insensitive, whole-word.

Skills are ranked by number of tag matches (descending). Ties resolved alphabetically.

### Explicit override

**In issue body:**
```markdown
skills: flutter, security-audit
```
Explicit skills are always loaded (merged with auto-detected, deduplicated).

**In config.yaml:**
```yaml
skills:
  always_load: [security-audit]        # loaded for every project
  marketplace_repo: owner/ai-software-house-skills   # remote marketplace
```
`always_load` skills are loaded before detection and are not filtered by detection score.

---

## Orchestrator Integration

### Startup (`Orchestrator.from_config`)

```python
self.skill_loader = SkillLoader(config)
self.skill_loader.init()   # scan local + fetch marketplace index
```

### Per-agent prompt build

```python
context = SkillContext(
    issue_body=issue.body,
    explicit_skills=parse_explicit_skills(issue.body),
    repo_languages=self.target_github.get_repo_languages(),  # new GitHubClient method
)
role_skill_blocks = self.skill_loader.for_role(role_name, context)
prompt = build_prompt(base_prompt, role_skill_blocks)
```

### Injected prompt block

```
## Skills Loaded

The following skills are active for this task. Read and follow their guidance.
Note in your response which skills you applied and how.

### flutter (local)
[flutter's "## For Engineers" section content only]

### security-audit (marketplace)
[security-audit's "## For Engineers" section content only]
```

### Agent output logging

The orchestrator scans agent responses for an optional `## Skills Applied` block and logs it to the run log. Not required from agents — just captured if present.

---

## Marketplace

Remote marketplace is a GitHub repo with this structure:

```
skills-index.json          # list of available skills with names, tags, download URLs
skills/
  flutter.md
  fastapi.md
  ...
```

`skills-index.json` format:
```json
[
  {
    "name": "flutter",
    "description": "Flutter/Dart guidance",
    "tags": ["flutter", "dart", "mobile"],
    "url": "https://raw.githubusercontent.com/owner/repo/main/skills/flutter.md",
    "version": "1.0.0"
  }
]
```

**Fetch behaviour:**
- Index fetched at startup if `marketplace_repo` is configured
- Individual skill files fetched on first match and cached locally
- `--update-skills` CLI flag re-fetches index + all cached skills
- All fetches have a 5-second timeout; failures log a warning and fall back to cache
- No fetches during a pipeline run (avoid latency + network failures mid-run)

---

## CLI Flag

```
--update-skills    Re-fetch marketplace index and refresh all cached skills
```

Example:
```bash
python main.py --update-skills
```

Can be combined with any other mode (skills update happens before pipeline start).

---

## Error Handling

| Scenario | Behaviour |
|---|---|
| Local skill file missing | Warn + skip |
| Malformed YAML frontmatter | Warn + skip that skill |
| Role section not found in skill | Skip injection for that role |
| Marketplace fetch fails (no cache) | Warn + skip marketplace skills |
| Marketplace fetch fails (cache exists) | Warn + use cached version |
| No skills matched | Pipeline runs normally, no injection |
| `always_load` skill not found | Warn + skip (never fail pipeline) |

---

## Bundled Starter Skills

| File | Tags | Roles |
|---|---|---|
| `flutter.md` | flutter, dart, mobile, ios, android, widget | architect, engineer, code_reviewer, qa_engineer |
| `fastapi.md` | fastapi, python, api, rest, uvicorn, pydantic | architect, engineer, code_reviewer |
| `react.md` | react, typescript, frontend, nextjs, vite | architect, engineer, code_reviewer, qa_engineer |
| `security-audit.md` | security, auth, jwt, oauth, csrf, injection | all roles |
| `docker.md` | docker, container, kubernetes, k8s, compose | architect, engineer, qa_engineer |

---

## Testing (`tests/test_skills.py`)

- `detect()` returns correct skills for a given issue body with matching tags
- `detect()` returns empty list when no tags match
- Role scoping: engineer does not receive PM-only content
- Role section extraction: only the `## For Engineers` block is injected, not the full file
- Explicit `skills:` override in issue body is always loaded regardless of tag match
- `always_load` from config is present for every call
- Malformed frontmatter file is skipped, other skills still load
- Marketplace fetch failure (mocked) falls back to cache, logs warning
- Marketplace fetch failure with no cache: skill skipped, pipeline continues
- `--update-skills` triggers re-fetch of index and cached files

---

## Config Reference

```yaml
skills:
  always_load: []                     # skill names always injected (e.g. [security-audit])
  marketplace_repo: ""                # GitHub repo slug, e.g. owner/ai-software-house-skills
  cache_dir: "~/.ai-software-house/skills"  # local cache for marketplace skills
  fetch_timeout: 5                    # seconds; marketplace fetch timeout
```

---

## Out of Scope

- Skill versioning / pinning (future)
- Composable skills invoking other skills (future)
- User-invocable skills by name during an interactive session (future)
- Skill analytics / usage reporting dashboard (future)
