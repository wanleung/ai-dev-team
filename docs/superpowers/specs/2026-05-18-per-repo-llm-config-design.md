# Per-Repo LLM Config Design

**Date:** 2026-05-18  
**Status:** Approved

## Problem

All repos and pipelines share a single global LLM config (`config.yaml`). There is no way for a specific project to use a different default model or per-agent overrides without editing the global config, which affects every repo.

## Goal

Allow each repo config file (`repos-available/*.yaml` or inline `repos.yaml`) to declare an optional `llm:` section that overrides the global LLM config for that repo only. Supports:
- Per-repo default model
- Per-agent model overrides
- Per-repo concurrency pool limits

## Schema

Add a top-level `llm:` key to repo config YAMLs. All keys are optional.

```yaml
# repos-available/custom-blog.yaml
tracker_repo: wanleung/custom-blog
labels:
  ai-feature: tdd
  ai-fix: ai-smart-fix

llm:
  model: "openai/gpt-4.1"          # default model for all agents in this repo
  overrides:                         # per-agent model overrides
    architect: "claude-3-5-sonnet-20241022"
    engineer: "openai/gpt-4.1-mini"
    qa_engineer: "openai/gpt-4.1-mini"
  pools:                             # per-repo concurrency pool limits
    openai: 5
    anthropic: 2
```

Omitting `llm:` entirely means the repo uses the global config unchanged.

The supported sub-keys mirror `config.yaml`'s `llm:` section:
- `model` — default model string
- `overrides` — dict of `agent_name: model_string`
- `pools` — dict of `backend_name: max_concurrency`

Other `llm:` keys from `config.yaml` (e.g. `ollama_url`, `ollama_think`, `stream`) are also merged if present, allowing full per-repo LLM tuning.

## Merge Logic

When a repo's `llm:` section is present, it is deep-merged on top of the global LLM config. **Repo values win; unspecified keys fall through to global.**

```
effective_llm = deep_merge(global_llm, repo_llm)
```

Rules:
- `model`: repo value replaces global if non-empty
- `overrides`: key-by-key merge — repo agent entry wins; agents not listed in repo keep global values
- `pools`: key-by-key merge — repo backend limit wins; other backends keep global limits
- All other scalar keys: repo value replaces global if present

The existing `settings.model` key (already supported in per-watcher `settings:`) continues to work as-is. Priority order (highest → lowest):
1. `llm.model` in repo config
2. `settings.model` in repo config
3. `llm.model` in global `config.yaml`
4. Hardcoded default `"gpt-4.1"`

## Implementation Touch Points

### `watcher.py`

1. **`load_watcher_config()`** — extract `llm:` from each repo entry (alongside `settings:`) and store as `_llm` on the watcher dict, so it survives the pop/transform step.

2. **`watch()` loop** — for each watcher entry:
   - Compute `effective_llm = deep_merge(global_llm, w.get("_llm", {}))`
   - Add `llm=effective_llm` to each task dict queued for that watcher

3. **`_dispatch()`** — accept `llm_cfg: dict | None = None` parameter. When present, use it for the LLM section instead of re-reading from `_load_pipeline_config()`. Existing behaviour unchanged when `llm_cfg` is `None`.

### `config_schema.py`

- Add `llm: Optional[LLMConfig] = None` to the per-watcher entry schema for validation. `LLMConfig` already exists; reuse it.

### Documentation

- Update the comment block in `repos.yaml` and `repos-available/` example files to document the new `llm:` key.

## Error Handling

- Invalid `llm:` values (wrong model string format, non-integer pool limit) are caught at config load time by the existing `LLMConfig` Pydantic schema. The watcher logs a warning and skips the repo entry.
- Unrecognised agent names in `overrides` are silently ignored (same as global config behaviour).

## Testing

- Unit test: `deep_merge` of two `llm:` dicts — model, overrides, and pools each merge correctly
- Unit test: repo with no `llm:` key uses global config unchanged
- Integration test: watcher task dict contains the correct `effective_llm` after merge
- Existing config tests must remain green (no regression)
