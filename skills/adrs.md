---
name: adrs
description: Architecture Decision Records — document the why, alternatives considered, and consequences of significant decisions
version: 1.0.0
roles:
  architect: true
  engineer: false
  code_reviewer: false
  qa_engineer: false
  product_manager: false
  architect_reviewer: true
  pm_reviewer: false
tags: [adr, architecture, decisions, documentation, why, trade-offs]
source: local
---

# Architecture Decision Records Skill

## For Architects
- **Write an ADR when**: choosing a framework or major library, designing a data model or schema, selecting an auth strategy, deciding on API architecture, any decision that would be expensive to reverse
- **ADR template** — store in the repo's established decision-doc location. Default to `docs/decisions/ADR-NNN-title.md` with sequential numbering when no convention exists:
  ```markdown
  # ADR-001: [Decision title]

  ## Status
  Accepted | Proposed | Superseded by ADR-XXX

  ## Date
  YYYY-MM-DD

  ## Context
  [Requirements and constraints that drove this decision]

  ## Decision
  [What was decided]

  ## Alternatives Considered
  ### [Option A]
  - Pros: ...
  - Cons: ...
  - Rejected because: ...

  ## Consequences
  [What this enables, what it rules out, what skills/tooling are now required]
  ```
- **Never delete old ADRs** — they capture historical context that prevents re-litigating the same decisions; when a decision changes, write a new ADR that references and supersedes the old one
- **Inline comments: document WHY, not what** — explain non-obvious constraints, known gotchas, and design intent:
  ```python
  # IMPORTANT: must be called before the first request — initialises the
  # connection pool; calling after startup causes a race condition under load.
  # See ADR-004 for the full design rationale.
  ```
- **Never comment what the code already says** — no `# increment counter` before `counter += 1`; no commented-out dead code (git has history)
- Document known traps that future engineers (or agents) would fall into if not warned

## For Architect Reviewers
- Flag significant decisions (new major dependency, data model change, auth strategy, API architecture) without a corresponding ADR
- Verify ADRs include rejected alternatives with documented rejection reasons — "we considered X and rejected it because Y" is the most valuable part
- Check that ADR `Status` is set and accurate (not left blank or as `Proposed` after being implemented)
- Verify ADRs cite official documentation or benchmarks for claims, not opinions
