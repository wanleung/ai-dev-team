---
name: code-review-reception
description: Evaluate PR review feedback before implementing — verify, push back if wrong, never apply blindly
version: 1.0.0
roles:
  architect: false
  engineer: true
  code_reviewer: false
  qa_engineer: false
  product_manager: false
  architect_reviewer: false
  pm_reviewer: false
tags: [code-review, feedback, revision, pr, evaluation]
source: local
---

# Code Review Reception Skill

## Core Rule
```
UNDERSTAND AND VERIFY FEEDBACK BEFORE IMPLEMENTING ANYTHING
```

Applying feedback blindly without evaluation leads to wrong implementations.

## For Engineers
- **Read all feedback first, implement nothing yet**: get the full picture before touching any code; related items affect each other
- **Clarify before implementing unclear items**: if even one item is ambiguous, ask — partial understanding leads to wrong implementation for the whole batch
- **Verify feedback against the codebase**: before changing anything, check whether the suggestion is technically correct for *this* codebase — reviewers may lack context
- **Push back with evidence if a suggestion is wrong**: "I can't implement that because X" is correct behavior; blind agreement is not
- **Minimal diff principle**: only change what the feedback explicitly asks for; do not refactor unrelated code while applying a review comment
- **Address every item**: after implementing, list each feedback item and state what you changed (or why you didn't); never silently skip an item
- **Test each change**: after applying each feedback item, verify the relevant tests still pass before moving to the next item

## Handling Specific Feedback Types
- **"This is wrong"** — reproduce the reported bug first; verify you can see the problem before fixing it
- **"Add X"** — check if X already exists elsewhere in the codebase before adding a duplicate
- **"Remove Y"** — confirm Y is not used elsewhere before removing it; grep first
- **"Rename Z"** — check all call sites; a rename without updating callers breaks things
- **"This is a security issue"** — treat as Critical; verify the attack vector is real before claiming it's fixed

## Red Flags
- Implementing fixes faster than you can read the feedback
- Saying "you're right" without verifying the claim
- Skipping items you don't understand rather than asking
- Mixing feedback implementation with opportunistic refactoring
- Claiming all items addressed without listing them
