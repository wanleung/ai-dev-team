# Config Override Fix - 2026-06-10

## Summary
- Reanalyzed watcher configuration override flow for `config.yaml` plus `config.local.yaml`.
- Fixed `_load_pipeline_config()` to recursively merge nested config sections with `deep_merge()`, so local overrides no longer discard sibling keys under sections like `llm`, `pipeline`, or `mcp`.
- Fixed watcher issue dispatch and PR revision paths to pass configured revision limits into `Orchestrator`.

## Config Values Covered
- `pipeline.max_revisions`
- `pipeline.max_prd_revisions`
- `pipeline.max_design_revisions`
- `pipeline.max_test_retries`
- `pipeline.max_deploy_retries`
- Nested sections such as `pipeline.chaining`, `llm.overrides`, and `llm.pools`

## Verification
- `pytest tests/test_watcher_config_validation.py tests/test_watcher_dispatch.py tests/test_watcher_prs.py -q`
- Result: `38 passed`

## Operational Note
- Restart the watcher after deployment. Existing watcher processes keep the old loaded code and config.
