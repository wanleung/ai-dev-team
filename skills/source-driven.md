---
name: source-driven
description: Ground every framework decision in official docs — verify versions, cite sources, never implement from memory
version: 1.0.0
roles:
  architect: true
  engineer: true
  code_reviewer: true
  qa_engineer: false
  product_manager: false
  architect_reviewer: true
  pm_reviewer: false
tags: [documentation, sources, frameworks, verification, citations, best-practices]
source: local
---

# Source-Driven Development Skill

## For Architects
- Read `pyproject.toml` / `package.json` / `requirements.txt` / `go.mod` to identify exact framework and library versions before designing; state what you found explicitly
- For architectural patterns, use official docs as the primary source — framework docs > official blog/changelog > web standards (MDN); never cite Stack Overflow or tutorials as architecture justification
- When official docs conflict with existing project code, surface the conflict explicitly — present both options and let the team decide; don't silently pick one
- ADRs must cite official documentation for library/framework choices with full URLs, not memory or blog posts

## For Engineers
- **Detect stack and versions first** from dependency files; state versions before implementing: `"React 19.1.0 from package.json → fetching docs"`
- Fetch the **specific documentation page** for the feature (not the homepage, not a tutorial): `react.dev/reference/react/useActionState` not `react.dev`
- Source hierarchy (in order of authority): official docs → official blog/changelog → web standards (MDN/web.dev) → runtime compatibility (caniuse, node.green)
- **Never use as primary sources**: Stack Overflow, blog posts, tutorials, or AI-generated summaries — including your own training data
- **Cite sources inline** for every framework-specific pattern:
  ```python
  # FastAPI lifespan pattern (replaces deprecated on_startup/on_shutdown)
  # Source: https://fastapi.tiangolo.com/advanced/events/#lifespan
  ```
- If you cannot find official documentation for a pattern, flag it explicitly:
  ```
  UNVERIFIED: No official documentation found for this pattern.
  This is based on training data and may be outdated — verify before using in production.
  ```
- Check migration guides for deprecated APIs; always use the current recommended approach

## For Architect Reviewers
- Flag framework-specific architectural decisions with no cited official source
- Reject deprecated APIs even if they appear in the existing codebase — modernisation should be noted as a separate task

## For Code Reviewers
- Flag framework-specific code without an inline source citation — request the source URL
- Reject usage of deprecated APIs (e.g. Flask `before_first_request`, FastAPI `on_startup`) — always use the current documented approach
- Check that library usage matches current documented API signatures, not signatures from older versions
