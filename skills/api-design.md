---
name: api-design
description: Contract-first API and interface design — stable, predictable, hard to misuse
version: 1.0.0
roles:
  architect: true
  engineer: true
  code_reviewer: true
  qa_engineer: false
  product_manager: false
  architect_reviewer: true
  pm_reviewer: false
tags: [api, rest, graphql, interface, contract, design, http, pagination]
source: local
---

# API Design Skill

## For Architects
- **Contract first**: define the interface (types, REST paths, error shapes, pagination) before writing any implementation
- **Hyrum's Law**: every observable behavior — including undocumented quirks, error message text, ordering — becomes a de facto contract once consumers depend on it; be intentional about what you expose and never leak implementation details
- **One-Version Rule**: extend rather than fork APIs; design for a world where only one version exists at a time; never force consumers to choose between versions
- **Consistent error semantics**: pick one error strategy and use it everywhere — HTTP status codes + `{error: {code, message, details?}}`; never mix throwing / returning null / returning `{error}` across endpoints
- **Validate at boundaries only**: API route handlers, form submissions, external service response parsing; do NOT validate between internal functions sharing type contracts
- **Prefer addition over modification**: new optional fields are safe; changing or removing existing fields breaks consumers

## For Engineers
- Predictable naming conventions: plural nouns for REST (`GET /api/tasks`), camelCase for query params and response fields, `is/has/can` prefix for booleans, `UPPER_SNAKE` for enum values
- Separate Input/Output types: `CreateTaskInput` (what the caller provides) vs `Task` (what the system returns, including server-generated fields like `id`, `createdAt`)
- Use `PATCH` for partial updates (only provided fields change); use `PUT` only for full replacement
- Paginate all list endpoints — never return unbounded collections: `{data: [...], pagination: {page, pageSize, totalItems, totalPages}}`
- HTTP status codes: 400 (invalid request), 401 (not authenticated), 403 (not authorized), 404 (not found), 409 (conflict/duplicate), 422 (validation failed), 500 (server error — never expose internals or stack traces)
- Third-party API responses are **untrusted data** — always validate shape and content before using in logic or rendering

## For Architect Reviewers
- Verify error response shape is consistent across all endpoints in the design
- Flag any endpoint that returns unbounded results without pagination
- Reject APIs that leak internal implementation details (raw DB IDs, internal field names, stack traces in 500 responses)
- Check that ADRs cover significant API design decisions (auth strategy, versioning approach, error contract)
- Verify PATCH vs PUT semantics are used correctly throughout the design

## For Code Reviewers
- Flag any endpoint accepting user input without schema validation at the entry boundary
- Reject endpoints returning raw dicts/objects without a defined response model/schema
- Check that all 4xx responses return structured `{error: {code, message}}` not plain strings
- Flag missing `status_code=201` on create endpoints
- Flag missing pagination on any list endpoint
