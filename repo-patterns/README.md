# Repo-Specific Codebase Patterns (Local Fallback)

This directory contains per-repo codebase pattern files used by ai-software-house agents
as a **last-resort fallback** when a target repo has none of the standard AI context files.

## Priority order checked by _build_engineer_context()

1. `.github/copilot-instructions.md` in target repo — GitHub Copilot standard (preferred)
2. `CLAUDE.md` in target repo — Claude Code standard
3. `.github/AGENTS.md` in target repo — our convention
4. `repo-patterns/{owner}-{repo}.md` in this directory — **this fallback**

## File naming
`{github-owner}-{repo-name}.md` — e.g. `wanleung-myapp.md`

## How files get here
- Automatically: BootstrapPatternsAgent (planned, M4) will create the initial file when a repo is added to repos.yaml
- Incrementally: LearningAgent (planned, M3) will append dated anti-pattern rules here when failures occur
- Manually: Create a `{owner}-{repo}.md` file by hand with patterns specific to that repo

## Recommended approach for target repos
Add `.github/copilot-instructions.md` to the repo — GitHub Copilot's coding agent, this system,
and other AI tools will all read it. Once `BootstrapPatternsAgent` (planned, M4) is available,
use it to generate the initial content automatically.
