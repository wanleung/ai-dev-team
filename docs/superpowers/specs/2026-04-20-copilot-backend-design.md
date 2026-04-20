# Copilot Backend Design

**Date:** 2026-04-20  
**Scope:** Add a `copilot` LLM backend to `ai-software-house` that routes agent calls through the GitHub Copilot Chat API.

---

## Problem

The pipeline supports seven backends (`github_models`, `anthropic`, `ollama`, `opencode`, `opencode_zen`, `opencode_go`, `nvidia_nim`). Users already authenticated with GitHub Copilot CLI have access to a rich set of models (Claude, GPT-4o, etc.) through the Copilot Chat API but no direct way to use them in the pipeline without a separate API key.

---

## Solution

A new `copilot` backend using `https://api.githubcopilot.com/chat/completions`. The API is OpenAI-compatible, so it plugs in cleanly alongside `github_models` — same SDK, different base URL and authentication.

**Model prefix:** `copilot/`  
Examples: `copilot/claude-sonnet-4.6`, `copilot/gpt-4o`, `copilot/gpt-4o-mini`

---

## Authentication

The Copilot API uses a two-token system:

| Token | Lifetime | Purpose |
|---|---|---|
| OAuth token (`gho_...`) | Long-lived | Obtained when signing in to Copilot CLI |
| Session token | ~30 minutes | Exchanged from OAuth token; used as API Bearer |

**Session token exchange:**
```
GET https://api.github.com/copilot_internal/v2/token
Authorization: token <oauth_token>
```
Response: `{ "token": "<session_token>", "expires_at": "<ISO timestamp>" }`

**OAuth token discovery order:**
1. `COPILOT_OAUTH_TOKEN` environment variable (explicit — takes precedence)
2. Auto-read from `~/.copilot/config.json` under `copilot_tokens["https://github.com:<username>"]` (convenient for users already logged in to Copilot CLI)

If neither source provides a token, raise a clear `EnvironmentError` with setup instructions.

---

## Token Refresh

A module-level cache (`_COPILOT_SESSION = {"token": "", "expires_at": 0.0}`) stores the current session token. Before each API call:

- If `time.time() < expires_at - 60` → use cached token (60s safety buffer)
- Otherwise → re-exchange for a fresh session token and recreate the OpenAI client

The refresh is transparent to callers. The `_ensure_copilot_session()` instance method handles the check and updates `self.client` in-place when needed.

---

## Required Headers

The Copilot API requires two additional headers beyond standard OpenAI:

```
Editor-Version: vscode/1.90.0
Copilot-Integration-Id: vscode-chat
```

These are set as `default_headers` on the `OpenAI` client at construction time and on each refresh — no call-site changes needed.

---

## Components

### `agents/base_agent.py`

1. **`_COPILOT_SESSION`** — module-level dict `{"token": str, "expires_at": float}` for session caching.

2. **`_is_copilot_model(model)`** — returns `model.startswith("copilot/")`.

3. **`_discover_copilot_oauth_token()`** — reads `COPILOT_OAUTH_TOKEN` env var; falls back to parsing `~/.copilot/config.json`; raises `EnvironmentError` if not found.

4. **`_fetch_copilot_session_token(oauth_token)`** — calls the exchange endpoint, updates `_COPILOT_SESSION`, returns the session token string.

5. **`_ensure_copilot_session()`** (instance method) — checks the cache; if stale, calls `_fetch_copilot_session_token` and rebuilds `self.client` with a new `OpenAI` instance using the fresh token.

6. **`copilot` backend block in `__init__`** — sets `self._backend = "copilot"`, stores `self._copilot_oauth_token`, performs the initial session token exchange, creates the `OpenAI` client with the correct base URL and headers.

7. **`_call_openai` update** — calls `self._ensure_copilot_session()` at the top of the call when `self._backend == "copilot"`.

### `config.yaml`

Add a `copilot/` section to the LLM model documentation with example model IDs and instructions for setting `COPILOT_OAUTH_TOKEN` (or relying on auto-discovery).

---

## Error Handling

| Scenario | Behaviour |
|---|---|
| No OAuth token found | `EnvironmentError` at agent init with clear setup steps |
| Token exchange fails (non-200) | `RuntimeError` with status code and response body |
| Session expired mid-run | `_ensure_copilot_session()` refreshes before each call — transparent |
| Model not available on account | Propagated as HTTP 404/403 from Copilot API with original message |

---

## Testing

- Unit test `_discover_copilot_oauth_token` — env var path, config file path, missing token error
- Unit test `_fetch_copilot_session_token` — mocked HTTP responses (success, failure, expiry parsing)
- Unit test `_ensure_copilot_session` — stale cache triggers refresh, fresh cache does not
- Existing 18-test suite must continue to pass unchanged

---

## Out of Scope

- Streaming responses (not currently used by any backend)
- Support for Copilot extensions / agents via the API
- Rotation across multiple OAuth tokens
