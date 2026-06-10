# Playwright MCP For Source Review

## Purpose

Use Playwright MCP when a source article is rendered by JavaScript or blocked behind a cookie modal. This gives `news_reviewer` a real browser tool in addition to Google Search MCP.

## What Changed

`news_reviewer` receives the source-research MCP registry. The registry now includes MCP servers named:

- `google_search`
- `playwright`
- `browser`
- `browser_render`

Use `playwright` for the official Playwright MCP server.

## Install

Playwright MCP is provided by the official `@playwright/mcp` npm package.

No global install is required if using `npx`.

Optional first-run browser install:

```bash
npx -y @playwright/mcp@latest --help
```

## Config

Add this to `config.local.yaml` under `mcp.servers`:

```yaml
mcp:
  servers:
    - name: google_search
      type: http
      url: "http://10.100.1.8:8080/mcp"

    - name: playwright
      type: stdio
      command: npx
      args:
        - "-y"
        - "@playwright/mcp@latest"
        - "--headless"
```

If Playwright needs more capabilities, use:

```yaml
    - name: playwright
      type: stdio
      command: npx
      args:
        - "-y"
        - "@playwright/mcp@latest"
        - "--headless"
        - "--caps=vision,pdf,devtools"
```

## Expected Tools

The official Playwright MCP exposes browser tools including:

- `browser_navigate`
- `browser_snapshot`
- `browser_click`
- `browser_type`
- `browser_take_screenshot`

For source review, the most useful flow is:

1. `browser_navigate` to the source URL.
2. `browser_snapshot` to read the rendered accessibility tree.
3. Use search tools if the rendered page is still blocked.

## Reviewer Behavior

The direct source fetch still runs first because it is cheap.

If direct fetch returns:

- empty content
- very short content
- cookie-consent boilerplate
- long HTML/CSS/JavaScript cookie-modal content

then `news_reviewer` switches to tool mode and can use Google Search MCP and Playwright MCP.

## Operational Notes

- Restart the watcher after changing MCP config.
- Playwright MCP uses more tokens than plain HTTP fetch because page snapshots are injected into the model context.
- Keep it scoped to source review and browser-rendered pages.
- Use `--headless` for server/watch mode.
- If a site blocks headless browsers, Google Search MCP may still be needed as a fallback.

## Verification

Run:

```bash
pytest tests/test_orchestrator_mcp.py::TestOrchestratorMCPWiring::test_news_reviewer_gets_google_and_playwright_mcp_servers -q
pytest tests/test_news_reviewer.py tests/test_news_stages.py -q
```
