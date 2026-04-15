---
name: react
description: React/TypeScript frontend development guidance
version: 1.0.0
roles:
  architect: true
  engineer: true
  code_reviewer: true
  qa_engineer: true
  product_manager: false
  architect_reviewer: false
  pm_reviewer: false
tags: [react, typescript, frontend, nextjs, vite, tailwind, tanstack]
source: local
---

# React Skill

## For Architects
- Feature-based structure: `src/features/<name>/components/`, `hooks/`, `api/`, `types/`
- Use TanStack Query for server state; Zustand or Jotai for client-only state; avoid Redux unless justified
- Next.js App Router for new projects; Vite + React Router for SPAs
- Co-locate CSS with components (CSS Modules or Tailwind); no global stylesheet spaghetti
- All API calls go through a typed client layer (`src/api/`) — no `fetch` calls in components

## For Engineers
- Prefer server components (Next.js) for data-fetching; `"use client"` only where needed
- All props must be typed with TypeScript interfaces — no `any`
- Use `React.memo` only when profiling shows a real problem — not by default
- Forms: React Hook Form + Zod for validation
- Never store sensitive data in `localStorage`; use `httpOnly` cookies for auth tokens

## For Code Reviewers
- Reject `any` types — use `unknown` and narrow, or define the interface
- Flag inline `fetch` calls in components — must use the API client layer
- Check that all async effects have cleanup functions to prevent memory leaks
- Verify accessible markup: `<button>` not `<div onClick>`, aria labels where needed
- Flag missing `key` props in list renders

## For QA Engineers
- Unit tests with Vitest + React Testing Library; test behaviour not implementation
- Mock API calls at the network layer with MSW (Mock Service Worker)
- Accessibility tests: `@testing-library/jest-dom` + `axe-core`
- E2E tests with Playwright for critical user journeys
- Test responsive breakpoints: mobile (375px), tablet (768px), desktop (1280px)
