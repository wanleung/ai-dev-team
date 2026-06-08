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

## For Scan Stage
- Output detected stack, exact dependency versions, and official docs URLs downstream agents should rely on
- Mark any framework/library guidance `UNVERIFIED` when official docs could not be checked, and explain the risk
- Keep source URLs in scan output, design notes, ADRs, or PR notes unless a production-code comment is needed for a non-obvious constraint

## For Engineers
- **Detect stack and versions first** from dependency files; state versions before implementing: `"React 19.1.0 from package.json → fetching docs"`
- Fetch the **specific documentation page** for the feature (not the homepage, not a tutorial): `react.dev/reference/react/useActionState` not `react.dev`
- Source hierarchy (in order of authority): official docs → official blog/changelog → web standards (MDN/web.dev) → runtime compatibility (caniuse, node.green)
- **Never use as primary sources**: Stack Overflow, blog posts, tutorials, or AI-generated summaries — including your own training data
- **Cite sources in planning artifacts** for framework-specific decisions. In production code, cite only non-obvious compatibility constraints, deprecated API migrations, security-sensitive behavior, or workarounds:
  ```python
  # Compatibility: lifespan replaces deprecated on_startup/on_shutdown.
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
- Flag framework-specific decisions with no cited source in scan output, design notes, ADRs, or PR notes. In production code, request source comments only for non-obvious constraints or workarounds
- Reject usage of deprecated APIs (e.g. Flask `before_first_request`, FastAPI `on_startup`) — always use the current documented approach
- Check that library usage matches current documented API signatures, not signatures from older versions
