---
name: incremental-implementation
description: Build in thin vertical slices — implement, test, verify, commit, then move to next slice
version: 1.0.0
roles:
  architect: false
  engineer: true
  code_reviewer: true
  qa_engineer: false
  product_manager: false
  architect_reviewer: false
  pm_reviewer: false
tags: [implementation, slicing, incremental, scope, commits, feature-flags]
source: local
---

# Incremental Implementation Skill

## For Engineers
- **Implement→Test→Verify→Commit cycle**: work in small logical slices and run relevant tests after each slice; large generated scaffolds are acceptable only when immediately verified
- **Vertical slices preferred**: each slice delivers working end-to-end functionality — DB + API + basic behavior complete and passing; do not build an entire layer before wiring it
- **Simplicity first**: before writing code, ask "what is the simplest thing that could work?" — implement the naive, obviously-correct version first; optimize only after correctness is proven with tests
- **Scope discipline**: touch ONLY what the task requires; if you notice something worth improving outside your scope, note it but do not fix it — "noticed but not touching"
- Each commit changes **one logical thing**; never mix feature work + refactoring in a single commit; separate them
- Keep the codebase compilable and all tests passing between every increment — never leave it broken mid-slice
- **Feature flags for incomplete work**: if a feature isn't ready for users but needs to be merged, wrap it in a flag (`if FEATURE_X_ENABLED`) — merge small increments without exposing incomplete behavior
- New code defaults to **safe, conservative behavior** (opt-in, not opt-out); default values should be the safest choice

## For Code Reviewers
- Flag PRs > ~300 lines — suggest splitting: vertical slice (smaller full-stack pieces), stack (sequential), or horizontal (shared code first then consumers)
- Reject PRs that mix feature work with unrelated refactoring — they must be separate submissions
- Flag scope creep: changes to files not mentioned in the task description
- Flag premature abstractions: generic solutions, base classes, or plugin systems built for a single current use case
- Check that each commit message describes one self-contained change, not "WIP" or "various fixes"
