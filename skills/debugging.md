---
name: debugging
description: Systematic root-cause debugging — reproduce, localize, reduce, fix, guard against recurrence
version: 1.0.0
roles:
  architect: false
  engineer: true
  code_reviewer: false
  qa_engineer: true
  product_manager: false
  architect_reviewer: false
  pm_reviewer: false
tags: [debugging, bug-fix, error, triage, root-cause]
source: local
---

# Debugging Skill

## Architectural Problem Rule
```
3 OR MORE FAILED FIX ATTEMPTS = WRONG ARCHITECTURE, NOT A HARDER BUG
```
If you've tried three fixes and each one reveals a new problem in a different place, stop patching. The pattern is wrong. Discuss with a senior engineer before attempting another fix.

## For Engineers
- **Stop-the-Line rule**: when anything unexpected happens — STOP adding features, preserve evidence (error output, logs, repro steps), diagnose before resuming; errors compound
- **5-step triage in order** (do not skip steps):
  1. **Reproduce** reliably — if you can't reproduce it, you can't fix it with confidence
  2. **Localize** — which layer is failing? (UI/API/DB/build tooling/external service/the test itself)
  3. **Reduce** — create the minimal failing case; strip everything unrelated until only the bug remains
  4. **Fix the root cause**, not the symptom — "duplicate rows in UI" → fix the JOIN query, not deduplicate in the component
  5. **Guard** — write a regression test that fails without the fix and passes with it
- For non-reproducible bugs: check for timing dependence (add delays), environment differences (compare Node/Python versions, env vars), or leaked state between tests (run in isolation)
- Use `git bisect` to binary-search which commit introduced a regression
- Safe fallback under time pressure: log a warning and return a safe default rather than crashing — never silently swallow errors
- Permanent instrumentation to keep: errors with stack traces (logged, not surfaced to users), slow operations > 1s, external service failures
- Remove debug logging once the bug is fixed — never commit `print`/`console.log` debugging statements

## For QA Engineers
- Confirm a bug by writing a failing test before declaring it fixed — test must fail first (Prove-It Pattern)
- Run the specific failing test in isolation to rule out order/pollution issues: `pytest tests/test_foo.py::test_name -v`
- For flaky tests: check for shared mutable state, timing dependencies, or external service calls that should be mocked
- Build failure triage: type error → read the cited location; import error → check exports match paths; env error → check runtime version compatibility
- Runtime error triage: `NoneType has no attribute X` → trace where the value comes from upstream; network/CORS errors → check URL + headers + server config
