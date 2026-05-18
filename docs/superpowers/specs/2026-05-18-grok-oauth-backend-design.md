# GrokOAuthBackend Design Spec

**Date:** 2026-05-18  
**Status:** Approved  
**Feature:** `grok-oauth/` backend prefix — xAI Grok via SuperGrok subscription (OAuth 2.0 PKCE)

---

## Overview

`GrokOAuthBackend` lets users with an active **SuperGrok subscription** call xAI's API without an `XAI_API_KEY`. Authentication uses OAuth 2.0 PKCE against `accounts.x.ai`. After a one-time browser login, tokens are persisted to `~/.ai-software-house/auth.json` and refreshed automatically. No new dependencies — stdlib only.

Model prefix: `grok-oauth/` (e.g. `grok-oauth/grok-3` → sends `grok-3` to the API).

---

## Constants

| Name | Value |
|---|---|
| `XAI_CLIENT_ID` | `os.environ.get("XAI_OAUTH_CLIENT_ID", "xai-supergrok")` — override via env var; default must be confirmed from xAI developer docs or grok-cli source |
| `XAI_AUTH_URL` | `https://accounts.x.ai/oauth/authorize` |
| `XAI_TOKEN_URL` | `https://accounts.x.ai/oauth/token` |
| `XAI_API_BASE` | `https://api.x.ai/v1` |
| `XAI_REDIRECT_URI` | `http://127.0.0.1:56121/callback` |
| `XAI_SCOPES` | `openid offline_access` (standard; confirm with xAI if API access requires additional scopes) |
| `XAI_AUTH_PATH` | `~/.ai-software-house/auth.json` |
| `LOGIN_TIMEOUT_SECS` | `120` |
| `TOKEN_EXPIRY_BUFFER_SECS` | `60` |

> **⚠️ Pre-implementation dependency:** `XAI_CLIENT_ID` and exact OAuth scopes must be confirmed from xAI's public developer docs or by inspecting grok-cli source (`https://github.com/superagent-ai/grok-cli`). The implementation should raise a clear `EnvironmentError` if `XAI_OAUTH_CLIENT_ID` is not set and the default cannot be verified.

---

## Token Storage

File: `~/.ai-software-house/auth.json`

```json
{
  "xai": {
    "access_token": "ey...",
    "refresh_token": "rt...",
    "expires_at": 1747999999.0
  }
}
```

- `expires_at` is a Unix timestamp (float) of access token expiry.
- File is created with mode `0o600` (owner read/write only).
- Keyed under `"xai"` so the file can later hold tokens for other OAuth providers.

### `_load_tokens() -> dict | None`
Reads `~/.ai-software-house/auth.json`, returns the `"xai"` sub-dict or `None` if absent/corrupt.

### `_save_tokens(access_token, refresh_token, expires_at) -> None`
Reads existing file (or empty dict), merges `"xai"` key, writes back atomically (write to `.tmp` then `os.replace`). Sets file permissions to `0o600`.

---

## PKCE Login Flow — `_do_pkce_login() -> dict`

Returns `{"access_token": ..., "refresh_token": ..., "expires_at": ...}`.

### Step 1: Generate PKCE parameters
```python
code_verifier  = base64.urlsafe_b64encode(secrets.token_bytes(96)).rstrip(b"=").decode()
code_challenge = base64.urlsafe_b64encode(
    hashlib.sha256(code_verifier.encode()).digest()
).rstrip(b"=").decode()
state = secrets.token_urlsafe(16)
```

### Step 2: Build authorization URL
```
https://accounts.x.ai/oauth/authorize
  ?response_type=code
  &client_id=<XAI_CLIENT_ID>
  &redirect_uri=http://127.0.0.1:56121/callback
  &scope=openid+offline_access
  &state=<state>
  &code_challenge=<code_challenge>
  &code_challenge_method=S256
```

### Step 3: Start loopback server with 120s timeout

```python
result: dict = {}
timed_out = [False]

class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        # parse ?code=...&state=...
        # verify state matches
        # store code in result["code"]
        # send 200 HTML "Login successful, return to terminal"
        server.shutdown()  # signal main thread

server = http.server.HTTPServer(("127.0.0.1", 56121), _Handler)
timer = threading.Timer(LOGIN_TIMEOUT_SECS, _on_timeout)

def _on_timeout():
    timed_out[0] = True
    server.shutdown()

timer.start()
server.serve_forever()  # blocks until shutdown()

if timed_out[0]:
    raise TimeoutError(
        f"xAI login timed out after {LOGIN_TIMEOUT_SECS}s. "
        "Run again to retry."
    )
if "code" not in result:
    raise RuntimeError("xAI login failed: no code received from callback.")
```

**State mismatch** in the callback handler → respond `400 Bad Request` and call `server.shutdown()` with an error flag. Raises `RuntimeError("xAI login aborted: state mismatch (possible CSRF)")`.

### Step 4: Headless / SSH detection

```python
is_headless = (not sys.stdout.isatty()) or bool(os.environ.get("SSH_TTY"))

if is_headless:
    print(f"\nOpen this URL in your browser to log in:\n\n  {auth_url}\n")
else:
    print(f"Opening browser for xAI login… (timeout: {LOGIN_TIMEOUT_SECS}s)")
    webbrowser.open(auth_url)
```

### Step 5: Token exchange

POST to `XAI_TOKEN_URL`:
```
grant_type=authorization_code
&code=<code>
&redirect_uri=http://127.0.0.1:56121/callback
&client_id=<XAI_CLIENT_ID>
&code_verifier=<code_verifier>
```

Response JSON expected: `{ "access_token", "refresh_token", "expires_in" }`.
`expires_at = time.time() + expires_in`.

**HTTP errors:**
- `400/401` → `RuntimeError("xAI token exchange failed: HTTP <code> — <body[:200]>")`
- Network error → `RuntimeError("xAI token exchange failed: network error — <reason>")`
- Missing fields → `RuntimeError("xAI token exchange failed: unexpected response format")`

---

## Token Refresh — `_refresh_access_token(refresh_token: str) -> dict`

POST to `XAI_TOKEN_URL`:
```
grant_type=refresh_token
&refresh_token=<refresh_token>
&client_id=<XAI_CLIENT_ID>
```

Returns `{"access_token", "refresh_token", "expires_at"}`.

**On `HTTP 400` or `401`**: the refresh token has expired. Caller (`_ensure_valid_token`) will trigger re-login.

**On network error**: raises `RuntimeError` immediately (no silent swallow).

---

## `_ensure_valid_token() -> str`

Returns a valid access token. Called at `__init__` and inside `_pre_call()` (under lock).

```
tokens = _load_tokens()
if tokens is None or no access_token:
    → _do_pkce_login() → _save_tokens() → return access_token

if time.time() >= tokens["expires_at"] - TOKEN_EXPIRY_BUFFER_SECS:
    try:
        new = _refresh_access_token(tokens["refresh_token"])
        _save_tokens(...)
        return new["access_token"]
    except RuntimeError as exc:
        if "HTTP 400" or "HTTP 401" in str(exc):
            → _do_pkce_login() → _save_tokens() → return access_token
        raise  # propagate network errors

return tokens["access_token"]  # still valid
```

---

## `GrokOAuthBackend(OpenAICompatibleBackend)`

```python
_XAI_SESSION_LOCK = threading.RLock()

class GrokOAuthBackend(OpenAICompatibleBackend):
    def __init__(self, model: str, max_retries: int = _DEFAULT_MAX_RETRIES, ...) -> None:
        with _XAI_SESSION_LOCK:
            token = _ensure_valid_token()
            client = OpenAI(base_url=XAI_API_BASE, api_key=token)
        super().__init__(model=model.removeprefix("grok-oauth/"), client=client, ...)

    def _pre_call(self) -> None:
        """Proactively refresh token 60s before expiry; rebuild OpenAI client if refreshed."""
        with _XAI_SESSION_LOCK:
            tokens = _load_tokens()
            if tokens and time.time() < tokens["expires_at"] - TOKEN_EXPIRY_BUFFER_SECS:
                return  # still valid
            new_token = _ensure_valid_token()
            self._client = OpenAI(base_url=XAI_API_BASE, api_key=new_token)
```

---

## Factory Registration

In `agents/backends/factory.py`, add after the `grok/` block:

```python
if model.startswith("grok-oauth/"):
    from agents.backends.grok_oauth import GrokOAuthBackend
    return GrokOAuthBackend(model=model, **kwargs)
```

Update the `ValueError` message to include `'grok-oauth/'`.

---

## Error Taxonomy

| Situation | Exception | Message |
|---|---|---|
| Browser login times out | `TimeoutError` | `"xAI login timed out after 120s. Run again to retry."` |
| State mismatch in callback | `RuntimeError` | `"xAI login aborted: state mismatch (possible CSRF)"` |
| Token exchange HTTP 4xx | `RuntimeError` | `"xAI token exchange failed: HTTP <N> — <body>"` |
| Token exchange network error | `RuntimeError` | `"xAI token exchange failed: network error — <reason>"` |
| Refresh token expired → re-login | *(triggers re-login, no raise)* | — |
| Refresh network error | `RuntimeError` | `"xAI token refresh failed: network error — <reason>"` |
| Port 56121 already in use | `OSError` | propagated as-is from `HTTPServer` bind |

---

## Testing

All tests mock network and browser calls — no real HTTP.

| Test | Covers |
|---|---|
| `test_pkce_login_success` | Full flow: loopback callback received, tokens saved |
| `test_pkce_login_timeout` | `threading.Timer` fires → `TimeoutError` raised |
| `test_pkce_login_state_mismatch` | Wrong `state` in callback → `RuntimeError` |
| `test_pkce_login_headless` | No TTY → URL printed, `webbrowser.open` NOT called |
| `test_refresh_token_success` | Proactive refresh on `_pre_call()`, client rebuilt |
| `test_refresh_token_expired` | Refresh returns 401 → re-login triggered automatically |
| `test_refresh_network_error` | Network error during refresh → `RuntimeError` propagated |
| `test_load_save_tokens` | Round-trip: save then load, verify `0o600` permissions |
| `test_factory_grok_oauth` | `create_backend({"model": "grok-oauth/grok-3"})` returns `GrokOAuthBackend` |

---

## Files

| File | Action |
|---|---|
| `agents/backends/grok_oauth.py` | **New** — full implementation |
| `agents/backends/factory.py` | **Edit** — add `grok-oauth/` block |
| `tests/test_grok_oauth_backend.py` | **New** — 9 tests |
