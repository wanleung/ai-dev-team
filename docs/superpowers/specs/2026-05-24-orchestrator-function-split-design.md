# Orchestrator Function Split — Design Spec

**Date:** 2026-05-24  
**Goal:** Split the 4 functions in `orchestrator.py` that exceed 200 lines into private helpers of ≤30 lines each, using Approach A (extract private helper methods on the same class).

---

## Scope

| Function | Lines | Lines → target |
|---|---|---|
| `__init__` | 325 | ≤30 (body only; signature stays) |
| `run` | 315 | ≤30 |
| `run_revision` | 275 | ≤30 |
| `_make_stage_registry` | 264 | ≤30 |

No behavior changes. No public API changes. All existing tests must pass unchanged.

---

## Approach

**Extract private helper methods.** Each giant function is refactored to call a sequence of small `_X()` helpers on `self`. The helper names document intent so the top-level function reads as a clean narrative.

One side-effect: the local closure `_mk(agent_name)` inside `__init__` is promoted to a regular private method `_make_agent_kwargs(agent_name, model_fallback=None) -> dict`. This makes it independently testable.

---

## `__init__` — 8 helpers

| Helper | Responsibility | Est. lines |
|---|---|---|
| `_init_core_attrs(...)` | Assign all scalar config attrs (model, num_engineers, workspace_dir, etc.) | ~28 |
| `_init_tool_registries(mcp_servers)` | Build MCP, RAG and Google Search registries; store on self | ~28 |
| `_init_llm_cfg(...)` | Build `self._llm_cfg` dict from params; deep-merge caller-supplied cfg | ~20 |
| `_make_agent_kwargs(agent_name, model_fallback) → dict` | Return `{"llm": backend}` — replaces the local `_mk` closure | ~8 |
| `_init_standard_agents(agent_kwargs, deploy_cfg)` | pm, news_writer/editor/reviewer/translator, pm_reviewer, architect, architect_reviewer, engineer, reviewer, qa_planner, qa, deployment_tester | ~22 |
| `_init_tier_agents(agent_kwargs)` | Resolve junior/senior/tier_reviewer fallback models; create JuniorEngineerAgent, SeniorEngineerAgent, TierReviewerAgent; snapshot original prompts | ~28 |
| `_init_support_agents(agent_kwargs)` | summariser, refactor_agent, memory store | ~8 |
| `_init_github(github_repo, github_token, target_repo)` | Build GitHub clients, call `_ensure_github_labels` | ~15 |
| `_init_pipeline_config(...)` | pipeline_mode, stage_skips, yaml_stages, cost_tracking, timeouts | ~25 |
| `_init_health_and_signals()` | AgentHealthMonitor + SIGTERM/SIGINT handlers + shutdown event | ~15 |

`__init__` body becomes ~22 lines of helper calls.

---

## `run` — 5 helpers

| Helper | Responsibility | Est. lines |
|---|---|---|
| `_resolve_target_repo(trigger_issue_body)` | Parse "Target repo:" directive; create GitHubClient if needed | ~10 |
| `_inject_repo_context(result)` | Load repo file tree; prepend to agent system prompts | ~20 |
| `_inject_memory(result)` | Load long-term memory; prepend to agent system prompts | ~15 |
| `_inject_skills(trigger_issue_body, requirement)` | Detect + inject skill blocks into each agent's system prompt | ~25 |
| `_load_or_init_result(requirement, resume, issue_number, trigger_issue_body) → PipelineResult` | Load checkpoint or create fresh result; extract prior context | ~20 |
| `_setup_progress_tracker(result)` | Build ProgressTracker; restore if resuming; call set_stages | ~15 |
| `_run_revision_loops(result, requirement) → bool` | Call `_prd_revision_loop` and `_design_revision_loop`; return False if aborted | ~15 |
| `_run_pipeline_loop(result, start_time) → PipelineResult` | Main stage-list loop: calls `_advance_stage_batch` per iteration; handles shutdown/budget exceptions | ~28 |
| `_advance_stage_batch(stage_list, i, result, start_time) → tuple[int, Optional[PipelineResult]]` | Process one batch (parallel or sequential); return next index and early-exit result if any | ~30 |

`run` body becomes ~20 lines of setup calls + the try/except wrapper.

---

## `run_revision` — 7 helpers

| Helper | Responsibility | Est. lines |
|---|---|---|
| `_revision_fetch_pr_context(pr_number) → dict` | Fetch PR metadata, head_branch, labels, issue_number | ~15 |
| `_revision_inject_skills(pr_body)` | Inject skill blocks for engineer/reviewer/qa agents | ~15 |
| `_revision_check_cap(pr_number, current_rev) → bool` | Check revision cap; post comment and return True if capped | ~10 |
| `_revision_maybe_update_branch(pr_number, pr, head_branch) → Optional[dict]` | Check update directive; call `_update_branch_from_base` if needed | ~15 |
| `_revision_collect_context(pr_number, issue_number, head_branch) → tuple` | Collect feedback, design, current files, merge branches | ~25 |
| `_revision_build_augmented_design(design, head_branch, current_files, feedback_md, merge_branch_files) → str` | Build augmented design string | ~20 |
| `_revision_run_and_commit(pr_number, head_branch, augmented_design, revision_modules, project_name, new_revision, ...) → Optional[dict]` | Run engineer → commit → reviewer → QA; return error dict on failure | ~30 |
| `_revision_post_summary(pr_number, new_revision, feedback, revised_files, rev_result, test_files, merge_branch_files, current_rev)` | Update label; post PR comment summary | ~25 |

`run_revision` body becomes ~28 lines of orchestrated helper calls.

---

## `_make_stage_registry` — 5 helpers

| Helper | Responsibility | Est. lines |
|---|---|---|
| `_build_product_stages() → dict` | pm, pm_reviewer, architect, architect_reviewer, tier_review | ~28 |
| `_build_engineering_stages() → dict` | junior/senior/engineer, reviewer, qa_planner, qa_engineer, qa_write, test_fix, deploy_tester, deploy_fix | ~30 |
| `_build_content_stages() → dict` | news_triage, news_writer, news_editor, translate_*, news_reviewer, news_article_pr | ~28 |
| `_build_utility_stages() → dict` | diagnose, bug_fix, doc_generate, doc_commit_pr, pr_analyst, pr_creative, pr_proposal, validation_gate, bootstrap_patterns | ~30 |
| `_build_discussion_stages() → dict` | Auto-discover discussions/*.yaml and create discuss_* stages | ~20 |

`_make_stage_registry` becomes: combine 5 dicts + wire timeouts (~15 lines).

---

## Testing strategy

- All existing tests must pass unchanged (no public API change).
- Add 4 smoke tests to verify the extracted helpers set expected attrs:
  - `test_init_core_attrs_sets_model`
  - `test_init_tool_registries_none_mcp`
  - `test_make_agent_kwargs_no_model_fallback`
  - `test_build_product_stages_keys`

---

## Constraints

- No public method signatures change.
- No imports added or removed (helpers are methods, not modules).
- All helpers are `_private` (leading underscore).
- `_make_agent_kwargs` replaces the `_mk` closure — identical logic.
- fn_map.py `--no-html` must report 0 violations for all 4 functions after the refactor.
