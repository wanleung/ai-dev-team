# Copilot Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `copilot` LLM backend to `agents/base_agent.py` that routes agent calls through the GitHub Copilot Chat API (`api.githubcopilot.com`) using the two-token auth system.

**Architecture:** Module-level helpers discover the OAuth token and exchange it for a short-lived session token. A module-level cache holds the session token and its expiry. `BaseAgent` creates an OpenAI-compatible client pointing at the Copilot API; before each call the agent checks whether the session token has expired and silently refreshes it.

**Tech Stack:** Python stdlib (`urllib.request`, `json`, `datetime`, `time`, `os`), `openai` SDK (already a dependency)

---

## File Map

| File | Change |
|---|---|
| `agents/base_agent.py` | Add helpers, cache, backend block, `_ensure_copilot_session()`, refresh in `call()` |
| `tests/test_copilot_backend.py` | New — all unit tests for the copilot backend |
| `config.yaml` | Add `copilot/` model docs and example overrides |

---

### Task 1: Module-level helpers

**Files:**
- Modify: `agents/base_agent.py` (top of file, after existing `_is_nvidia_nim_model`)
- Create: `tests/test_copilot_backend.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_copilot_backend.py`:

```python
"""Unit tests for GitHub Copilot backend in ai-software-house."""
import json
import os
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, mock_open


# ── _is_copilot_model ────────────────────────────────────────────────────────

def test_is_copilot_model_with_prefix():
    from agents.base_agent import _is_copilot_model
    assert _is_copilot_model("copilot/claude-sonnet-4.6") is True
    assert _is_copilot_model("copilot/gpt-4o") is True


def test_is_copilot_model_without_prefix():
    from agents.base_agent import _is_copilot_model
    assert _is_copilot_model("ollama/llama3.2") is False
    assert _is_copilot_model("gpt-4o") is False
    assert _is_copilot_model("claude-sonnet-4.6") is False


# ── _discover_copilot_oauth_token ─────────────────────────────────────────────

def test_discover_oauth_token_from_env():
    from agents.base_agent import _discover_copilot_oauth_token
    with patch.dict(os.environ, {"COPILOT_OAUTH_TOKEN": "gho_test123"}):
        assert _discover_copilot_oauth_token() == "gho_test123"


def test_discover_oauth_token_from_config_file():
    from agents.base_agent import _discover_copilot_oauth_token
    config = {
        "copilot_tokens": {
            "https://github.com:testuser": "gho_fromfile"
        }
    }
    config_json = json.dumps(config)
    with patch.dict(os.environ, {}, clear=False):
        env = {k: v for k, v in os.environ.items() if k != "COPILOT_OAUTH_TOKEN"}
        with patch.dict(os.environ, env, clear=True):
            with patch("builtins.open", mock_open(read_data=config_json)):
                with patch("os.path.exists", return_value=True):
                    assert _discover_copilot_oauth_token() == "gho_fromfile"


def test_discover_oauth_token_raises_when_missing():
    from agents.base_agent import _discover_copilot_oauth_token
    with patch.dict(os.environ, {}, clear=True):
        with patch("os.path.exists", return_value=False):
            try:
                _discover_copilot_oauth_token()
                assert False, "Should have raised EnvironmentError"
            except EnvironmentError as exc:
                assert "COPILOT_OAUTH_TOKEN" in str(exc)


# ── _fetch_copilot_session_token ──────────────────────────────────────────────

def test_fetch_session_token_success():
    from agents.base_agent import _fetch_copilot_session_token, _COPILOT_SESSION
    expires = (datetime.now(timezone.utc) + timedelta(minutes=30)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    response_body = json.dumps({"token": "session_abc", "expires_at": expires}).encode()

    mock_resp = MagicMock()
    mock_resp.read.return_value = response_body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        token = _fetch_copilot_session_token("gho_fake")

    assert token == "session_abc"
    assert _COPILOT_SESSION["token"] == "session_abc"
    assert _COPILOT_SESSION["expires_at"] > time.time()


def test_fetch_session_token_raises_on_http_error():
    from agents.base_agent import _fetch_copilot_session_token
    import urllib.error
    with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError(
        url="", code=401, msg="Unauthorized", hdrs={}, fp=None
    )):
        try:
            _fetch_copilot_session_token("gho_bad")
            assert False, "Should have raised RuntimeError"
        except RuntimeError as exc:
            assert "401" in str(exc)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_copilot_backend.py -v 2>&1 | head -40
```

Expected: `ImportError` or `AttributeError` — `_is_copilot_model`, `_discover_copilot_oauth_token`, `_fetch_copilot_session_token` not yet defined.

- [ ] **Step 3: Add helpers to `agents/base_agent.py`**

Add the following immediately after the `_is_nvidia_nim_model` function (before the `class BaseAgent:` line). Also add `import urllib.request`, `import urllib.error` to the existing imports block at the top of the file, and `from datetime import datetime, timezone` to the imports.

First, in the imports section at the top of `agents/base_agent.py`, add:
```python
import urllib.error
import urllib.request
from datetime import datetime, timezone
```

Then, after `_is_nvidia_nim_model`, add:

```python
# ── GitHub Copilot backend helpers ────────────────────────────────────────────

_COPILOT_SESSION: dict = {"token": "", "expires_at": 0.0}
"""Module-level cache for the short-lived Copilot session token."""

_COPILOT_API_BASE = "https://api.githubcopilot.com"
_COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
_COPILOT_CONFIG_PATH = os.path.expanduser("~/.copilot/config.json")


def _is_copilot_model(model: str) -> bool:
    """Return True if the model name indicates a GitHub Copilot model."""
    return model.startswith("copilot/")


def _discover_copilot_oauth_token() -> str:
    """Return the Copilot OAuth token from env var or Copilot CLI config file.

    Discovery order:
    1. COPILOT_OAUTH_TOKEN environment variable
    2. ~/.copilot/config.json → copilot_tokens (first value)

    Raises:
        EnvironmentError: if no token is found from either source.
    """
    token = os.environ.get("COPILOT_OAUTH_TOKEN")
    if token:
        return token

    if os.path.exists(_COPILOT_CONFIG_PATH):
        with open(_COPILOT_CONFIG_PATH, encoding="utf-8") as fh:
            cfg = json.load(fh)
        tokens: dict = cfg.get("copilot_tokens", {})
        if tokens:
            return next(iter(tokens.values()))

    raise EnvironmentError(
        "No GitHub Copilot OAuth token found. Either:\n"
        "  1. Set COPILOT_OAUTH_TOKEN=<gho_...> environment variable, or\n"
        "  2. Log in to Copilot CLI (the token is then auto-discovered from\n"
        "     ~/.copilot/config.json)."
    )


def _fetch_copilot_session_token(oauth_token: str) -> str:
    """Exchange a Copilot OAuth token for a short-lived session token.

    Updates the module-level _COPILOT_SESSION cache with the new token and
    its expiry timestamp.

    Args:
        oauth_token: A GitHub OAuth token (gho_...) with Copilot access.

    Returns:
        The session token string for use as API Bearer auth.

    Raises:
        RuntimeError: on non-200 HTTP response from the token endpoint.
    """
    req = urllib.request.Request(
        _COPILOT_TOKEN_URL,
        headers={"Authorization": f"token {oauth_token}"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"Copilot token exchange failed: HTTP {exc.code} — {exc.reason}"
        ) from exc

    session_token: str = data["token"]
    expires_str: str = data["expires_at"]
    # Parse ISO 8601 expiry ("2026-04-20T15:00:00Z") to a Unix timestamp
    dt = datetime.fromisoformat(expires_str.replace("Z", "+00:00"))
    _COPILOT_SESSION["token"] = session_token
    _COPILOT_SESSION["expires_at"] = dt.timestamp()
    return session_token
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_copilot_backend.py -v
```

Expected output:
```
tests/test_copilot_backend.py::test_is_copilot_model_with_prefix PASSED
tests/test_copilot_backend.py::test_is_copilot_model_without_prefix PASSED
tests/test_copilot_backend.py::test_discover_oauth_token_from_env PASSED
tests/test_copilot_backend.py::test_discover_oauth_token_from_config_file PASSED
tests/test_copilot_backend.py::test_discover_oauth_token_raises_when_missing PASSED
tests/test_copilot_backend.py::test_fetch_session_token_success PASSED
tests/test_copilot_backend.py::test_fetch_session_token_raises_on_http_error PASSED
```

Also verify the existing suite still passes:
```bash
python -m pytest tests/ -v --ignore=tests/integration -q 2>&1 | tail -10
```

Expected: all previously-passing tests still PASSED.

- [ ] **Step 5: Commit**

```bash
cd /home/wanleung/Projects/ai-software-house
git add agents/base_agent.py tests/test_copilot_backend.py
git commit -m "feat: add copilot backend helpers (_is_copilot_model, _discover_copilot_oauth_token, _fetch_copilot_session_token)

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 2: Backend block, `_ensure_copilot_session()`, and `call()` integration

**Files:**
- Modify: `agents/base_agent.py` (`__init__`, add `_ensure_copilot_session`, update `call`, update `call_with_tools`)
- Modify: `tests/test_copilot_backend.py` (add backend + session refresh tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_copilot_backend.py`:

```python
# ── BaseAgent copilot backend init ────────────────────────────────────────────

def test_base_agent_copilot_backend_detected_from_prefix():
    """'copilot/' prefix auto-selects the copilot backend."""
    expires = (datetime.now(timezone.utc) + timedelta(minutes=30)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    response_body = json.dumps({"token": "sess_init", "expires_at": expires}).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = response_body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch.dict(os.environ, {"COPILOT_OAUTH_TOKEN": "gho_fake"}):
        with patch("urllib.request.urlopen", return_value=mock_resp):
            with patch("agents.base_agent.OpenAI") as mock_openai:
                mock_openai.return_value = MagicMock()
                from agents.base_agent import BaseAgent
                agent = BaseAgent(model="copilot/gpt-4o")
                assert agent._backend == "copilot"
                assert agent._api_model == "gpt-4o"


def test_base_agent_copilot_strips_prefix():
    """_api_model is the model ID with 'copilot/' stripped."""
    expires = (datetime.now(timezone.utc) + timedelta(minutes=30)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    response_body = json.dumps({"token": "sess_init", "expires_at": expires}).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = response_body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch.dict(os.environ, {"COPILOT_OAUTH_TOKEN": "gho_fake"}):
        with patch("urllib.request.urlopen", return_value=mock_resp):
            with patch("agents.base_agent.OpenAI") as mock_openai:
                mock_openai.return_value = MagicMock()
                from agents.base_agent import BaseAgent
                agent = BaseAgent(model="copilot/claude-sonnet-4.6")
                assert agent._api_model == "claude-sonnet-4.6"


def test_base_agent_copilot_openai_client_base_url():
    """OpenAI client is initialised with the Copilot API base URL."""
    expires = (datetime.now(timezone.utc) + timedelta(minutes=30)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    response_body = json.dumps({"token": "sess_tok", "expires_at": expires}).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = response_body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch.dict(os.environ, {"COPILOT_OAUTH_TOKEN": "gho_fake"}):
        with patch("urllib.request.urlopen", return_value=mock_resp):
            with patch("agents.base_agent.OpenAI") as mock_openai:
                mock_openai.return_value = MagicMock()
                from agents.base_agent import BaseAgent
                BaseAgent(model="copilot/gpt-4o")
                call_kwargs = mock_openai.call_args[1]
                assert call_kwargs["base_url"] == "https://api.githubcopilot.com"
                assert call_kwargs["api_key"] == "sess_tok"
                assert call_kwargs["default_headers"]["Copilot-Integration-Id"] == "vscode-chat"


def test_base_agent_copilot_raises_without_token():
    """EnvironmentError is raised when no OAuth token is available."""
    with patch.dict(os.environ, {}, clear=True):
        with patch("os.path.exists", return_value=False):
            from agents.base_agent import BaseAgent
            try:
                BaseAgent(model="copilot/gpt-4o")
                assert False, "Expected EnvironmentError"
            except EnvironmentError as exc:
                assert "COPILOT_OAUTH_TOKEN" in str(exc)


# ── _ensure_copilot_session ───────────────────────────────────────────────────

def test_ensure_copilot_session_skips_refresh_when_fresh():
    """No token exchange when the cached token is still valid."""
    expires = (datetime.now(timezone.utc) + timedelta(minutes=30)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    response_body = json.dumps({"token": "initial_tok", "expires_at": expires}).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = response_body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch.dict(os.environ, {"COPILOT_OAUTH_TOKEN": "gho_fake"}):
        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
            with patch("agents.base_agent.OpenAI") as mock_openai:
                mock_openai.return_value = MagicMock()
                from agents.base_agent import BaseAgent
                agent = BaseAgent(model="copilot/gpt-4o")
                call_count_after_init = mock_urlopen.call_count
                agent._ensure_copilot_session()
                # No additional urlopen call — token is still fresh
                assert mock_urlopen.call_count == call_count_after_init


def test_ensure_copilot_session_refreshes_when_stale():
    """Token exchange is triggered when cached token has expired."""
    import agents.base_agent as ba_module

    past_expiry = time.time() - 10  # already expired
    ba_module._COPILOT_SESSION["token"] = "old_tok"
    ba_module._COPILOT_SESSION["expires_at"] = past_expiry

    expires = (datetime.now(timezone.utc) + timedelta(minutes=30)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    response_body = json.dumps({"token": "new_tok", "expires_at": expires}).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = response_body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch.dict(os.environ, {"COPILOT_OAUTH_TOKEN": "gho_fake"}):
        with patch("urllib.request.urlopen", return_value=mock_resp):
            with patch("agents.base_agent.OpenAI") as mock_openai:
                mock_openai.return_value = MagicMock()
                # Init with a fresh token so __init__ succeeds
                fresh_expiry = time.time() + 1800
                ba_module._COPILOT_SESSION["expires_at"] = fresh_expiry
                ba_module._COPILOT_SESSION["token"] = "old_tok"
                agent = BaseAgent(model="copilot/gpt-4o")

                # Now force expiry
                ba_module._COPILOT_SESSION["expires_at"] = time.time() - 10
                agent._ensure_copilot_session()

                assert ba_module._COPILOT_SESSION["token"] == "new_tok"
```

- [ ] **Step 2: Run new tests to verify they fail**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_copilot_backend.py -v -k "copilot_backend or ensure_copilot" 2>&1 | tail -20
```

Expected: `AttributeError` — `copilot` backend block not yet in `__init__`.

- [ ] **Step 3: Add `use_copilot` flag and backend block to `__init__`**

In `agents/base_agent.py`, in the `__init__` method, add the `use_copilot` flag alongside the other `use_*` variables (after `use_opencode = ...`):

```python
        use_copilot = (backend == "copilot") or (
            backend is None and _is_copilot_model(model)
        )
```

Then add the `copilot` backend block **before** the `elif use_opencode:` block:

```python
        if use_copilot:
            self._backend = "copilot"
            self._api_model = model.removeprefix("copilot/")
            self._copilot_oauth_token = _discover_copilot_oauth_token()
            session_token = _fetch_copilot_session_token(self._copilot_oauth_token)
            self.client = OpenAI(
                base_url=_COPILOT_API_BASE,
                api_key=session_token,
                default_headers={
                    "Editor-Version": "vscode/1.90.0",
                    "Copilot-Integration-Id": "vscode-chat",
                },
            )
            self._anthropic_client = None
        elif use_opencode_go:
```

> **Note:** The full `if/elif` chain currently starts with `if use_opencode_go:`. Change it to start with `if use_copilot:` and push `use_opencode_go` to the first `elif`.

Also update the `backend` parameter type comment:
```python
backend: Optional[str] = None,  # "github_models" | "anthropic" | "ollama" | "opencode" | "opencode_zen" | "opencode_go" | "nvidia_nim" | "copilot" | None (auto)
```

And update the module docstring lines at the top of the file to add:
```
  backend: copilot         — GitHub Copilot Chat API (OpenAI-compatible, model prefix "copilot/",
                             uses COPILOT_OAUTH_TOKEN or auto-discovered from ~/.copilot/config.json)
```

- [ ] **Step 4: Add `_ensure_copilot_session()` method to `BaseAgent`**

Add the method after `reset_history()`:

```python
    def _ensure_copilot_session(self) -> None:
        """Refresh the Copilot session token if it is within 60s of expiry.

        Rebuilds self.client with the new token when a refresh occurs.
        No-op for non-copilot backends.
        """
        if self._backend != "copilot":
            return
        if time.time() < _COPILOT_SESSION["expires_at"] - 60:
            return
        new_token = _fetch_copilot_session_token(self._copilot_oauth_token)
        self.client = OpenAI(
            base_url=_COPILOT_API_BASE,
            api_key=new_token,
            default_headers={
                "Editor-Version": "vscode/1.90.0",
                "Copilot-Integration-Id": "vscode-chat",
            },
        )
```

- [ ] **Step 5: Call `_ensure_copilot_session()` in `call()`**

In `agents/base_agent.py`, in the `call()` method, add the refresh call just before the OpenAI-compatible branch. The current code is:

```python
        # OpenAI-compatible backends (GitHub Models, Ollama, opencode_zen/opencode_go non-Anthropic)
        messages: list[dict] = []
```

Change it to:

```python
        # Refresh Copilot session token if near expiry
        self._ensure_copilot_session()

        # OpenAI-compatible backends (GitHub Models, Ollama, opencode_zen/opencode_go non-Anthropic, Copilot)
        messages: list[dict] = []
```

- [ ] **Step 6: Update `call_with_tools` NotImplementedError check**

In `agents/base_agent.py`, the `call_with_tools` method has this guard:

```python
        if self._backend in ("opencode", "anthropic") or (
            self._backend in ("opencode_zen", "opencode_go") and self._anthropic_client is not None
        ):
```

The `copilot` backend is OpenAI-compatible and supports tool-calling, so no change is needed — it falls through to the existing tool-call loop. Verify the guard does NOT include `"copilot"`. If it does, remove it.

- [ ] **Step 7: Run all new and existing tests**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_copilot_backend.py -v
```

Expected: all 14 tests PASSED.

```bash
python -m pytest tests/ -v --ignore=tests/integration -q 2>&1 | tail -15
```

Expected: all previously-passing tests still PASSED, no new failures.

- [ ] **Step 8: Commit**

```bash
cd /home/wanleung/Projects/ai-software-house
git add agents/base_agent.py tests/test_copilot_backend.py
git commit -m "feat: add copilot backend block and _ensure_copilot_session() to BaseAgent

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 3: config.yaml docs and final verification

**Files:**
- Modify: `config.yaml`

- [ ] **Step 1: Add `copilot/` backend docs to `config.yaml`**

Find the existing NVIDIA NIM block in `config.yaml` (it ends with `# Claude models are auto-detected...`). Add the following block immediately after the NVIDIA NIM section and before the `# Claude models are auto-detected` line:

```yaml
  # ── GitHub Copilot API (COPILOT_OAUTH_TOKEN or auto-discovered) ───────────
  #   copilot/<model-id>   e.g. copilot/gpt-4o
  #                             copilot/claude-sonnet-4.6
  #                             copilot/gpt-4o-mini
  #   Auth: set COPILOT_OAUTH_TOKEN=<gho_...> env var, OR the token is
  #   auto-discovered from ~/.copilot/config.json if you are logged in to
  #   GitHub Copilot CLI. The backend exchanges the OAuth token for a
  #   short-lived session token automatically (refreshed every ~30 min).
  #   OpenAI-compatible — supports tool-calling (code_reviewer, qa_engineer).
```

- [ ] **Step 2: Add example overrides for copilot models**

In the `overrides:` section of `config.yaml`, add commented-out copilot examples alongside the existing ones. Find:

```yaml
    product_manager: "openai/gpt-4.1"          # or "claude-3-5-sonnet-20241022"
```

Add a comment block above it:

```yaml
    # ── Copilot backend examples ──────────────────────────────────────────
    # product_manager: "copilot/gpt-4o"
    # architect: "copilot/claude-sonnet-4.6"
    # engineer: "copilot/gpt-4o-mini"
    # ─────────────────────────────────────────────────────────────────────
```

- [ ] **Step 3: Run full test suite**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/ --ignore=tests/integration -q 2>&1 | tail -15
```

Expected: all tests PASSED, 0 failures.

- [ ] **Step 4: Smoke-test backend detection**

```bash
cd /home/wanleung/Projects/ai-software-house
python3 -c "
from agents.base_agent import _is_copilot_model, _discover_copilot_oauth_token, _COPILOT_SESSION
print('_is_copilot_model(\"copilot/gpt-4o\"):', _is_copilot_model('copilot/gpt-4o'))
print('_is_copilot_model(\"gpt-4o\"):', _is_copilot_model('gpt-4o'))
try:
    tok = _discover_copilot_oauth_token()
    print('OAuth token discovered:', tok[:12] + '...')
except EnvironmentError as e:
    print('No token (expected if not logged in):', e)
"
```

Expected:
```
_is_copilot_model("copilot/gpt-4o"): True
_is_copilot_model("gpt-4o"): False
OAuth token discovered: gho_C4pMCfKr...    # or EnvironmentError if COPILOT_OAUTH_TOKEN not set
```

- [ ] **Step 5: Commit**

```bash
cd /home/wanleung/Projects/ai-software-house
git add config.yaml
git commit -m "docs: add copilot backend examples to config.yaml

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

- [ ] **Step 6: Push**

```bash
cd /home/wanleung/Projects/ai-software-house
git push origin master
```

---

## Self-Review

**Spec coverage check:**
- ✅ `_is_copilot_model()` — Task 1
- ✅ `_discover_copilot_oauth_token()` (env var + config file + error) — Task 1
- ✅ `_fetch_copilot_session_token()` (exchange, cache update, HTTP error) — Task 1
- ✅ `_COPILOT_SESSION` module-level cache — Task 1
- ✅ `copilot` backend block in `__init__` — Task 2
- ✅ `_ensure_copilot_session()` (fresh → no-op, stale → refresh) — Task 2
- ✅ `call()` integration — Task 2
- ✅ `call_with_tools` compatibility — Task 2 (verified, no exclusion)
- ✅ `config.yaml` docs — Task 3
- ✅ All 14 new tests + existing suite — Tasks 1–3

**No placeholders:** All steps contain complete code.

**Type consistency:**
- `_COPILOT_SESSION` dict used identically in Task 1 (`_fetch_copilot_session_token`) and Task 2 (`_ensure_copilot_session`)
- `_COPILOT_API_BASE` constant defined once (Task 1), referenced in Task 2
- `_copilot_oauth_token` stored in `__init__` (Task 2), read in `_ensure_copilot_session` (Task 2) — consistent
