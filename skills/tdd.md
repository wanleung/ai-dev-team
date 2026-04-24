---
name: tdd
description: Test-driven development — write failing tests first, then minimal implementation to pass
version: 1.0.0
roles:
  architect: false
  engineer: true
  code_reviewer: true
  qa_engineer: true
  product_manager: false
  architect_reviewer: false
  pm_reviewer: false
tags: [tdd, testing, quality, pytest, jest, vitest, unit-test, integration-test]
source: local
---

# TDD Skill

## For Engineers
- **Red→Green→Refactor**: write a failing test first → write minimal code to make it pass → refactor with tests still green
- **Prove-It Pattern (bug fixes)**: write a test that reproduces the bug BEFORE attempting the fix; the test must fail first, confirming the bug exists
- **Test pyramid**: ~80% unit (pure logic, no I/O, milliseconds), ~15% integration (API/DB boundaries), ~5% E2E (critical flows only)
- **DAMP over DRY in tests**: each test is self-contained and reads like a spec; repeating setup code is acceptable if it makes each test independently understandable
- **Test state, not interactions**: assert on what the function *does* (output/state), not on which internal methods were called; interaction-based mocks break on refactoring
- **Mock preference order**: real implementation → fake (in-memory) → stub (canned data) → mock (interaction); only mock when real implementation is too slow, non-deterministic, or has side effects you can't control
- Never apply TDD to pure configuration changes, documentation updates, or static content with no behavioral impact

## For QA Engineers
- Every bug fix requires a regression test: it must fail without the fix and pass with it — "Prove-It" is non-negotiable
- **Test sizes**: Small (single process, no I/O, milliseconds — most tests should be here), Medium (localhost/test DB only, seconds), Large (external services, minutes — limit to critical paths)
- **The Beyonce Rule**: if a regression is not caught by tests, the missing test is the real defect; infrastructure changes are not responsible for catching untested behavior
- Integration tests: test API boundaries with a real test database, not mocked DB calls — mocked DB tests don't catch query bugs
- E2E: limit to 3–5 critical user flows; more becomes a maintenance burden that teams stop trusting
- Run a specific test in isolation first to rule out test pollution: `pytest tests/test_foo.py::test_name -v`

## For Code Reviewers
- Reject tests that only verify method calls (pure interaction mocks) — they break on refactor without catching real bugs
- Flag vague test names (`test_works`, `test_success`) — names must describe the specific behavior being verified
- Verify error paths and edge cases (null, empty, boundary values) are tested, not just the happy path
- Check test isolation: no shared mutable state between tests; each test must pass when run alone
- Reject any bug fix that has no corresponding regression test
