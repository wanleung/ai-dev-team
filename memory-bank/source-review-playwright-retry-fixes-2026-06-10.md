# Source Review, Playwright MCP, And Retry Fixes — 2026-06-10

## What Changed

- Hardened `NewsReviewerAgent` source classification so long cookie-consent modal HTML/CSS/JavaScript is treated as unusable source content.
- Kept valid article-like fetched source content flowing into the reviewer prompt.
- Ensured unusable source content triggers `call_with_tools(...)`, allowing Google Search MCP and browser tools to verify the original article or corroborating references.
- Wired source-review MCP registry to include servers named `google_search`, `playwright`, `browser`, and `browser_render`.
- Added `roles/news_reviewer.md` guidance to use rendered browser tools such as `browser_navigate` and `browser_snapshot` before declaring claims unverifiable.
- Added `docs/playwright-mcp-source-review.md` with the `config.local.yaml` snippet for official `@playwright/mcp`.
- Fixed PR watcher revision runs so `max_test_retries` and `max_deploy_retries` from merged config are forwarded into `Orchestrator`.

## Diagnosis

- `ai-fix` issue dispatch and PR watcher revision are different paths.
- Issue dispatch already forwarded `max_test_retries` after the prior fix.
- PR watcher revision (`_run_pr_revision`) still dropped `max_test_retries` / `max_deploy_retries`, so PR-triggered fixes could still behave as if retry limits were defaults.
- News reviewer direct fetch sometimes returned large cookie-modal HTML; because it was non-empty and long, the old classifier treated it as source article text and never called Google Search MCP.

## Verification

- `pytest tests/test_watcher_prs.py tests/test_watcher_dispatch.py -q` → `32 passed`
- `pytest tests/test_orchestrator_mcp.py::TestOrchestratorMCPWiring::test_news_reviewer_gets_google_and_playwright_mcp_servers tests/test_news_reviewer.py tests/test_news_stages.py -q` → `62 passed`
- `ruff check tests/test_orchestrator_mcp.py agents/news_reviewer.py tests/test_news_reviewer.py` → passed

## Notes

- Restart the watcher after deploying these changes.
- Existing in-flight watcher runs keep using the old loaded code.
- `ruff check orchestrator.py` still has pre-existing unrelated lint issues; full orchestrator lint was not claimed clean.
