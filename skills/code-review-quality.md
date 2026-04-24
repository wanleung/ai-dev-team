---
name: code-review-quality
description: Five-axis code review — correctness, readability, architecture, security, performance
version: 1.0.0
roles:
  architect: false
  engineer: false
  code_reviewer: true
  qa_engineer: false
  product_manager: false
  architect_reviewer: true
  pm_reviewer: false
tags: [code-review, quality, review, refactoring, correctness, readability]
source: local
---

# Code Review Quality Skill

## For Code Reviewers
- **Review tests first**: tests reveal intent and coverage — check they test behavior (not implementation details), cover edge cases and error paths, have descriptive names, and would catch a regression if behavior changed
- **Five axes every review must cover**:
  1. **Correctness**: does code match spec? are edge cases handled (null/empty/boundary)? are all error paths covered?
  2. **Readability**: no vague variable names (`temp`, `data`, `result`); no nested ternaries; dead code removed; abstractions earn their complexity; could another engineer understand this without the author?
  3. **Architecture**: follows existing patterns (or justifies a new one); clean module boundaries; no circular imports; code that changes together lives together
  4. **Security**: user input validated at boundaries; no secrets in source/logs; parameterised queries; outputs encoded; external data treated as untrusted
  5. **Performance**: no N+1 query patterns; no unbounded loops; all list endpoints paginated; no missing async where I/O occurs
- **Label every comment** by severity so the author knows what's required:
  - *(no prefix)* — required change, must address before merge
  - **Critical:** — blocks merge immediately (security vulnerability, data loss, broken functionality)
  - **Nit:** — optional minor style preference; author may ignore
  - **Optional:** / **Consider:** — worth thinking about but not required
  - **FYI** — informational only, no action needed
- **Approval standard**: approve when the change clearly improves overall code health, even if imperfect; don't block because it's not how you'd write it personally
- Change sizing guide: ~100 lines = ideal; ~300 lines = acceptable for a single logical change; ~1000+ lines = too large, request a split

## For Architect Reviewers
- Verify new patterns are explicitly justified; reject silent introduction of a second way to do something already established
- Check module boundaries: dependencies must flow in one direction; flag circular imports or cross-domain coupling
- Flag any new abstraction (base class, mixin, generic handler) without at least two concrete use cases driving it
- Verify ADRs exist for significant architectural decisions introduced in the change (new major dependency, data model change, auth approach)
- Check that the change description explains *why*, not just *what* — "refactor X" is not a reason; "refactor X because Y was causing Z" is
