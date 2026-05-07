---
name: verification
description: Verify before claiming done — run the test suite and confirm output before marking any task complete
version: 1.0.0
roles:
  architect: false
  engineer: true
  code_reviewer: false
  qa_engineer: true
  product_manager: false
  architect_reviewer: false
  pm_reviewer: false
tags: [verification, testing, quality, done, complete, evidence]
source: local
---

# Verification Skill

## Core Rule
```
NO COMPLETION CLAIMS WITHOUT RUNNING VERIFICATION FIRST
```

Never say "done", "fixed", "passing", or "complete" without evidence from a fresh test run.

## For Engineers
- **Run tests before claiming done**: always execute the test command and read the output; a claim without a run is a lie
- **Evidence before assertions**: "tests pass" = you ran them and saw `0 failures`; never infer from code changes alone
- **Fresh run required**: a test run from 10 minutes ago doesn't count — code may have changed; always run again
- **Check exit code AND output**: exit 0 with warnings is not clean; read the full output, not just the last line
- **Verify the right tests**: run tests covering the code you changed, not a random subset; if in doubt, run the full suite
- **Regression test red-green cycle**: when adding a regression test, you must watch it **fail** before the fix and **pass** after — a test that passes immediately proves nothing
- **"Should work" is not verification**: never substitute reasoning about correctness for actually running the code
- When running tests would require environment setup you cannot complete, say so explicitly instead of assuming they pass

## For QA Engineers
- **Confirm every bug fix with a failing test first**: write the test, watch it fail (Prove-It), apply the fix, watch it pass — skip any step and the fix is unverified
- **Isolate before reporting**: before declaring a test suite clean, run the specific failing test in isolation to rule out ordering pollution: `pytest tests/test_foo.py::test_name -v`
- **Count failures explicitly**: "all tests pass" means you saw `X passed, 0 failed` in the output — not that you ran them and they "seemed fine"
- **Do not trust agent success reports**: when an agent says "tests pass", verify independently by checking the test output directly

## Common Rationalizations to Reject
| Claim | Why It's Wrong |
|-------|----------------|
| "Code looks correct" | Looking ≠ running |
| "Tests passed earlier" | Code changed since then |
| "Only a minor change" | Minor changes break things |
| "I'm confident" | Confidence ≠ evidence |
| "Should be fine" | "Should" is not verification |
| "Agent reported success" | Verify independently |
