# Quick Wins Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement 6 independent reliability/security/DX improvements, each shipped as its own PR.

**Architecture:** Six self-contained changes — connection pooling in GitHubClient, a shared token sanitiser utility, tenacity retry decorator in watcher, pydantic config schema, structlog JSON logging, and a standalone check.py CLI. QW-6 depends on QW-4's config schema; all others are independent.

**Tech Stack:** Python 3.11+, `requests`, `tenacity>=8.2`, `pydantic>=2.0`, `structlog>=24.0`, `rich` (already installed), `argparse` (stdlib)

**Spec:** `docs/superpowers/specs/2026-05-07-quick-wins-design.md`

---

## File Map

| Action | File | Purpose |
|--------|------|---------|
| Modify | `github_client.py` | QW-1: add `self._session`, update `_request()`, add `__del__` |
| Create | `utils.py` | QW-2: `sanitise(text, *secrets)` shared utility |
| Modify | `github_client.py` | QW-2: sanitise token from `RuntimeError` messages |
| Modify | `agents/conflict_resolver.py` | QW-2: delegate `_sanitise()` to `utils.sanitise` |
| Modify | `orchestrator.py` | QW-2: sanitise in conflict-resolver error path |
| Modify | `watcher.py` | QW-2: sanitise in exception handlers + QW-3: tenacity retries + QW-5: structlog |
| Modify | `requirements.txt` | QW-3 + QW-4 + QW-5: add tenacity, pydantic, structlog |
| Create | `config_schema.py` | QW-4: pydantic models for config.yaml and repos.yaml |
| Modify | `orchestrator.py` | QW-4: `from_config()` uses `load_config()` |
| Create | `logging_setup.py` | QW-5: `configure_logging()` and `bind_run_id()` |
| Modify | `main.py` | QW-5: call `configure_logging()` + `bind_run_id()` |
| Create | `check.py` | QW-6: `validate-config` and `test-github` subcommands |
| Modify | `tests/test_github_client.py` | QW-1 + QW-2: update mocks, add new tests |
| Create | `tests/test_utils.py` | QW-2: sanitise unit tests |
| Create | `tests/test_config_schema.py` | QW-4: pydantic model tests |
| Create | `tests/test_logging_setup.py` | QW-5: logging configuration tests |
| Create | `tests/test_check.py` | QW-6: CLI subcommand tests |

---

## Task 1 (QW-1): `requests.Session` in `GitHubClient`

**Branch:** `qw-1-requests-session`

**Files:**
- Modify: `github_client.py` lines 54–96
- Modify: `tests/test_github_client.py`

### Context

`github_client.py` currently uses `requests.request(method, url, headers=self.headers, **kwargs)` at line 83 inside `_request()`. This opens a new TCP connection on every call. The fix stores a `requests.Session` as `self._session`, sets the default headers on the session once at `__init__` time, and replaces the bare `requests.request` call with `self._session.request`.

There is also a standalone `requests.post` at line 327 (`merge_pull_request_graphql`) that bypasses `_request()` — update that one too.

### Steps

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_github_client.py`:

```python
from unittest.mock import MagicMock, patch, call

def test_session_created_on_init():
    """GitHubClient creates a requests.Session in __init__."""
    with patch("github_client.requests.Session") as mock_session_cls:
        mock_session_cls.return_value = MagicMock()
        gc = GitHubClient("owner/repo", github_token="tok")
    mock_session_cls.assert_called_once()

def test_session_headers_set_on_init():
    """Session headers include Authorization and Accept."""
    with patch("github_client.requests.Session") as mock_session_cls:
        mock_sess = MagicMock()
        mock_session_cls.return_value = mock_sess
        gc = GitHubClient("owner/repo", github_token="mytoken")
    mock_sess.headers.update.assert_called_once()
    call_kwargs = mock_sess.headers.update.call_args[0][0]
    assert call_kwargs["Authorization"] == "Bearer mytoken"

def test_request_uses_session():
    """_request() uses self._session.request, not requests.request."""
    gc = GitHubClient("owner/repo", github_token="tok")
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.text = '{"id": 1}'
    mock_resp.json.return_value = {"id": 1}
    gc._session = MagicMock()
    gc._session.request.return_value = mock_resp
    result = gc._request("GET", "/repos/owner/repo")
    gc._session.request.assert_called_once_with("GET", "https://api.github.com/repos/owner/repo")
    assert result == {"id": 1}

def test_session_closed_on_del():
    """__del__ calls session.close()."""
    gc = GitHubClient("owner/repo", github_token="tok")
    mock_session = MagicMock()
    gc._session = mock_session
    gc.__del__()
    mock_session.close.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_github_client.py::test_session_created_on_init tests/test_github_client.py::test_request_uses_session tests/test_github_client.py::test_session_closed_on_del -v
```

Expected: FAIL — `GitHubClient has no attribute '_session'`

- [ ] **Step 3: Implement the changes in `github_client.py`**

In `__init__` (after the `self.headers = {...}` block, around line 75), add:

```python
        self._session = requests.Session()
        self._session.headers.update(self.headers)
```

After `__init__`, add `__del__`:

```python
    def __del__(self) -> None:
        try:
            self._session.close()
        except Exception:
            pass
```

In `_request()`, change line 83 from:
```python
            response = requests.request(method, url, headers=self.headers, **kwargs)
```
to:
```python
            response = self._session.request(method, url, **kwargs)
```
(Headers are now on the session — remove `headers=self.headers` from the call.)

At line 327 (standalone `requests.post` in `merge_pull_request_graphql`), change:
```python
        resp = requests.post(url, headers=self.headers, json=payload)
```
to:
```python
        resp = self._session.post(url, json=payload)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_github_client.py -v
```

Expected: all tests pass (including the 4 new ones)

- [ ] **Step 5: Commit**

```bash
git checkout -b qw-1-requests-session
git add github_client.py tests/test_github_client.py
git commit -m "perf: use requests.Session in GitHubClient for connection reuse

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 2 (QW-2): Global Token Sanitisation

**Branch:** `qw-2-global-token-sanitise`

**Files:**
- Create: `utils.py`
- Create: `tests/test_utils.py`
- Modify: `github_client.py` (error message sanitisation)
- Modify: `agents/conflict_resolver.py` (delegate to utils)
- Modify: `orchestrator.py` (sanitise conflict-resolver error path)
- Modify: `watcher.py` (sanitise in exception handlers)

### Context

`ConflictResolverAgent` has a private `_sanitise()` method that replaces the token with `***`. Everywhere else the raw token can appear in error messages (e.g. in a clone URL like `https://x-access-token:<token>@github.com/...` that git may echo in stderr, or in a `RuntimeError` message from `github_client._request()`). This task moves the sanitiser to a shared `utils.py` and applies it at the four remaining unsafe sites.

### Steps

- [ ] **Step 1: Write failing tests for `utils.sanitise`**

Create `tests/test_utils.py`:

```python
from utils import sanitise

def test_sanitise_replaces_single_secret():
    assert sanitise("error: https://mytoken@host/repo", "mytoken") == "error: https://***@host/repo"

def test_sanitise_replaces_multiple_secrets():
    result = sanitise("tok1 and tok2 here", "tok1", "tok2")
    assert result == "*** and *** here"

def test_sanitise_empty_secret_is_safe():
    assert sanitise("no change", "", None) == "no change"

def test_sanitise_no_match_returns_unchanged():
    assert sanitise("hello world", "secret") == "hello world"

def test_sanitise_multiple_occurrences():
    assert sanitise("x secret x secret x", "secret") == "x *** x *** x"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_utils.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'utils'`

- [ ] **Step 3: Create `utils.py`**

```python
"""Shared utility functions for ai-software-house."""
from __future__ import annotations


def sanitise(text: str, *secrets: str | None) -> str:
    """Replace every occurrence of each secret in text with '***'.

    Safe to call with empty or None secrets — they are silently skipped.

    Example:
        sanitise("clone https://tok@host/repo failed", "tok")
        # → "clone https://***@host/repo failed"
    """
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text
```

- [ ] **Step 4: Run utils tests to verify they pass**

```bash
python -m pytest tests/test_utils.py -v
```

Expected: 5 passed

- [ ] **Step 5: Write failing test for GitHubClient error redaction**

Add to `tests/test_github_client.py`:

```python
def test_request_error_redacts_token():
    """RuntimeError from _request() must not contain the raw token."""
    gc = GitHubClient("owner/repo", github_token="supersecret")
    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 500
    mock_resp.text = "https://x-access-token:supersecret@github.com/owner/repo: error"
    mock_resp.json.return_value = {}
    gc._session = MagicMock()
    gc._session.request.return_value = mock_resp

    import pytest
    with pytest.raises(RuntimeError) as exc_info:
        gc._request("GET", "/repos/owner/repo")
    assert "supersecret" not in str(exc_info.value)
    assert "***" in str(exc_info.value)
```

- [ ] **Step 6: Run to verify it fails**

```bash
python -m pytest tests/test_github_client.py::test_request_error_redacts_token -v
```

Expected: FAIL — token appears in error message

- [ ] **Step 7: Update `github_client.py` to sanitise error messages**

At the top of `github_client.py`, add the import:
```python
from utils import sanitise
```

In `_request()`, change the `raise RuntimeError(...)` block (around line 87) from:
```python
            if response.status_code not in self._RETRYABLE or attempt == self._MAX_RETRIES - 1:
                raise RuntimeError(
                    f"GitHub API {method} {url} failed [{response.status_code}]: {response.text[:500]}"
                )
```
to:
```python
            if response.status_code not in self._RETRYABLE or attempt == self._MAX_RETRIES - 1:
                raise RuntimeError(sanitise(
                    f"GitHub API {method} {url} failed [{response.status_code}]: {response.text[:500]}",
                    self.token,
                ))
```

Also update the final fallback raise (line 96):
```python
        raise RuntimeError(sanitise(
            f"GitHub API {method} {url} failed after {self._MAX_RETRIES} attempts",
            self.token,
        ))
```

- [ ] **Step 8: Update `agents/conflict_resolver.py` to delegate to `utils.sanitise`**

In `agents/conflict_resolver.py`, find the `_sanitise` method (around line 82):
```python
    def _sanitise(self, text: str) -> str:
        token = getattr(self, "_token", None)
        if token:
            return text.replace(token, "***")
        return text
```

Replace with:
```python
    def _sanitise(self, text: str) -> str:
        from utils import sanitise
        return sanitise(text, getattr(self, "_token", None))
```

- [ ] **Step 9: Sanitise in `orchestrator.py` conflict-resolver path**

In `orchestrator.py`, find the block where `result.reason` from `ConflictResolverAgent` is logged (inside `_update_branch_from_base()`, around line 1793). Find the line:
```python
self._log(f"conflict resolution failed: {result.reason}")
```
Change to:
```python
from utils import sanitise as _sanitise_text
# ... (put import at top of file, not inline)
self._log(f"conflict resolution failed: {_sanitise_text(result.reason or '', self._gh.token if self._gh else '')}")
```

Actually: add `from utils import sanitise as _sanitise` to the imports at the top of `orchestrator.py` (near other imports, around line 50), then change the log call to:
```python
self._log(f"conflict resolution failed: {_sanitise(result.reason or '', getattr(self._gh, 'token', ''))}")
```

- [ ] **Step 10: Sanitise in `watcher.py` exception handlers**

In `watcher.py`, add to imports:
```python
from utils import sanitise as _sanitise
```

Find the `except Exception` blocks in `run_pipeline()` (around lines 331–335) and `_run_pr_revision()` (around lines 709–711) where `post_comment()` is called with exception text. For each, wrap the exception string:

Change patterns like:
```python
post_comment(tracker_repo, issue_number, f"❌ Pipeline failed:\n```\n{exc}\n```")
```
to:
```python
_token = os.environ.get("GITHUB_TOKEN", "")
post_comment(tracker_repo, issue_number, f"❌ Pipeline failed:\n```\n{_sanitise(str(exc), _token)}\n```")
```

- [ ] **Step 11: Run full test suite**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_utils.py tests/test_github_client.py tests/test_conflict_resolver.py -v
```

Expected: all pass

- [ ] **Step 12: Commit**

```bash
git checkout -b qw-2-global-token-sanitise
git add utils.py tests/test_utils.py github_client.py agents/conflict_resolver.py orchestrator.py watcher.py
git commit -m "security: global token sanitisation via shared utils.sanitise()

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 3 (QW-3): Tenacity Retries in `watcher.py`

**Branch:** `qw-3-tenacity-retries`

**Files:**
- Modify: `requirements.txt`
- Modify: `watcher.py`
- Modify: `tests/test_watcher.py`

### Context

`watcher.py` has ~8 direct `requests.*` call sites that bypass `GitHubClient._request()` and have zero retry logic. The functions are: `ensure_label` (lines 70–77), `add_label` (79–81), `remove_label` (84–86), `post_comment` (233–235), `get_open_issues` (101 area), `get_open_prs` (121 area), `get_pr_comments` (133 area).

All these functions use `requests.get/post/delete` directly and do not call `.raise_for_status()`. For tenacity to retry on bad status codes, each call must raise on failure. The approach: add `.raise_for_status()` after each call, then wrap each function with a `@_retry_github` decorator.

### Steps

- [ ] **Step 1: Add `tenacity` to `requirements.txt`**

Open `requirements.txt` and append:
```
tenacity>=8.2
```

Then install:
```bash
pip install tenacity>=8.2
```

- [ ] **Step 2: Write failing tests**

Add to `tests/test_watcher.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
import requests

def test_ensure_label_retries_on_429(monkeypatch):
    """ensure_label retries when GitHub returns 429."""
    call_count = {"n": 0}

    def fake_get(url, **kwargs):
        call_count["n"] += 1
        resp = MagicMock()
        if call_count["n"] < 3:
            resp.ok = False
            resp.status_code = 429
            resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
        else:
            resp.ok = True
            resp.status_code = 200
            resp.json.return_value = []
            resp.raise_for_status.return_value = None
        return resp

    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    with patch("watcher.requests.get", side_effect=fake_get), \
         patch("watcher.requests.post", return_value=MagicMock(ok=True, raise_for_status=lambda: None)):
        from watcher import ensure_label
        ensure_label("owner/repo", "ai-feature", "0075ca")

    assert call_count["n"] == 3   # failed twice, succeeded on 3rd

def test_post_comment_retries_on_503(monkeypatch):
    """post_comment retries on 503."""
    call_count = {"n": 0}

    def fake_post(url, **kwargs):
        call_count["n"] += 1
        resp = MagicMock()
        if call_count["n"] < 2:
            resp.ok = False
            resp.status_code = 503
            resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
        else:
            resp.ok = True
            resp.raise_for_status.return_value = None
        return resp

    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    with patch("watcher.requests.post", side_effect=fake_post):
        from watcher import post_comment
        post_comment("owner/repo", 42, "hello")

    assert call_count["n"] == 2
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
python -m pytest tests/test_watcher.py::test_ensure_label_retries_on_429 tests/test_watcher.py::test_post_comment_retries_on_503 -v
```

Expected: FAIL — no retry occurs, raises immediately on 429/503

- [ ] **Step 4: Add tenacity imports and `_retry_github` decorator to `watcher.py`**

At the top of `watcher.py`, add after the existing imports:

```python
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

def _is_retryable_http_error(exc: BaseException) -> bool:
    """Return True if exc is an HTTPError with a retryable status code."""
    if not isinstance(exc, requests.HTTPError):
        return False
    resp = getattr(exc, "response", None)
    return resp is not None and resp.status_code in {429, 500, 502, 503, 504}

_retry_github = retry(
    retry=retry_if_exception(_is_retryable_http_error),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    stop=stop_after_attempt(5),
    before_sleep=before_sleep_log(_log, logging.WARNING),
    reraise=True,
)
```

- [ ] **Step 5: Apply `@_retry_github` and add `.raise_for_status()` to each function**

**`ensure_label` (line 70):**
```python
@_retry_github
def ensure_label(repo: str, name: str, colour: str) -> None:
    """Create a label if it doesn't already exist."""
    url = f"https://api.github.com/repos/{repo}/labels"
    existing = requests.get(url, headers=_gh_headers(), timeout=10)
    existing.raise_for_status()
    names = {l["name"] for l in existing.json()} if existing.ok else set()
    if name not in names:
        resp = requests.post(url, headers=_gh_headers(), json={"name": name, "color": colour}, timeout=10)
        resp.raise_for_status()
```

**`add_label` (line 79):**
```python
@_retry_github
def add_label(repo: str, issue_number: int, label: str) -> None:
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/labels"
    resp = requests.post(url, headers=_gh_headers(), json={"labels": [label]}, timeout=10)
    resp.raise_for_status()
```

**`remove_label` (line 84):**
```python
@_retry_github
def remove_label(repo: str, issue_number: int, label: str) -> None:
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/labels/{label}"
    resp = requests.delete(url, headers=_gh_headers(), timeout=10)
    resp.raise_for_status()
```

**`post_comment` (line 233):**
```python
@_retry_github
def post_comment(repo: str, issue_number: int, body: str) -> None:
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments"
    resp = requests.post(url, headers=_gh_headers(), json={"body": body}, timeout=10)
    resp.raise_for_status()
```

For `get_open_issues`, `get_open_prs`, `get_pr_comments` — these already raise `RuntimeError` on `not resp.ok`. Instead of `@_retry_github` (which only catches `HTTPError`), change them to call `resp.raise_for_status()` instead of the manual check, then add `@_retry_github`:

```python
@_retry_github
def get_open_issues(repo: str, label: str | list[str]) -> list[dict]:
    ...
    resp = requests.get(url, headers=_gh_headers(), params=params, timeout=10)
    resp.raise_for_status()   # replaces: if not resp.ok: raise RuntimeError(...)
    for issue in resp.json():
    ...
```

Apply the same `resp.raise_for_status()` replacement + `@_retry_github` to `get_open_prs` and `get_pr_comments`.

- [ ] **Step 6: Run tests**

```bash
python -m pytest tests/test_watcher.py -v
```

Expected: all pass including the 2 new tests

- [ ] **Step 7: Commit**

```bash
git checkout -b qw-3-tenacity-retries
git add requirements.txt watcher.py tests/test_watcher.py
git commit -m "reliability: add tenacity retry decorator to watcher GitHub API calls

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 4 (QW-4): Pydantic Config Validation

**Branch:** `qw-4-pydantic-config`

**Files:**
- Create: `config_schema.py`
- Create: `tests/test_config_schema.py`
- Modify: `requirements.txt` (add pydantic)
- Modify: `orchestrator.py` (`from_config()`)
- Modify: `watcher.py` (validate repo entries)

### Context

`Orchestrator.from_config()` at line 890 does `cfg = yaml.safe_load(f) or {}` and then accesses keys via `.get()`. A typo in `config.yaml` is silently ignored. The fix validates config at load time using a pydantic `AppConfig` model.

The model must use `extra="allow"` for the `llm.overrides` section (agent names are user-defined) but `extra="forbid"` at the top level to catch typos.

### Steps

- [ ] **Step 1: Add pydantic to `requirements.txt`**

```
pydantic>=2.0
```

Install: `pip install "pydantic>=2.0"`

- [ ] **Step 2: Write failing tests**

Create `tests/test_config_schema.py`:

```python
import pytest
from pydantic import ValidationError

def test_valid_minimal_config():
    """A config with only defaults passes validation."""
    from config_schema import load_config
    import tempfile, yaml, os
    cfg = {"llm": {"model": "gpt-4.1"}}
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        yaml.dump(cfg, f)
        path = f.name
    result = load_config(path)
    assert result.llm.model == "gpt-4.1"
    os.unlink(path)

def test_unknown_top_level_key_raises():
    """An unknown top-level key raises ValidationError."""
    from config_schema import load_config
    import tempfile, yaml, os
    cfg = {"llm": {"model": "gpt-4.1"}, "typo_key": "bad"}
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        yaml.dump(cfg, f)
        path = f.name
    with pytest.raises(ValidationError):
        load_config(path)
    os.unlink(path)

def test_missing_llm_model_uses_default():
    """Omitting llm.model gives the default 'gpt-4.1'."""
    from config_schema import AppConfig
    cfg = AppConfig.model_validate({})
    assert cfg.llm.model == "gpt-4.1"

def test_repo_config_extra_fields_allowed():
    """RepoWatcherEntry allows arbitrary extra keys for future expansion."""
    from config_schema import RepoWatcherEntry
    entry = RepoWatcherEntry.model_validate({
        "tracker_repo": "owner/repo",
        "custom_future_field": "value",
    })
    assert entry.tracker_repo == "owner/repo"

def test_invalid_num_engineers_raises():
    """Non-integer num_engineers raises ValidationError."""
    from config_schema import AppConfig
    import pytest
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"pipeline": {"num_engineers": "two"}})
```

- [ ] **Step 3: Run to verify they fail**

```bash
python -m pytest tests/test_config_schema.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'config_schema'`

- [ ] **Step 4: Create `config_schema.py`**

```python
"""Pydantic v2 schema for config.yaml and repos.yaml.

Usage:
    from config_schema import load_config, AppConfig, RepoWatcherEntry
    cfg = load_config("config.yaml")   # raises ValidationError on bad config
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field


# ── config.yaml models ──────────────────────────────────────────────────────

class LLMConfig(BaseModel):
    model_config = {"extra": "allow"}   # allow unknown agent override keys

    model: str = "gpt-4.1"
    fallback: Optional[List[str]] = None
    overrides: Optional[Dict[str, Any]] = None


class GithubConfig(BaseModel):
    model_config = {"extra": "allow"}

    repo: str = ""
    token: Optional[str] = None


class PipelineChainingConfig(BaseModel):
    model_config = {"extra": "allow"}

    on_test_failure: Optional[str] = None
    on_review_issues: Optional[str] = None


class PipelineConfig(BaseModel):
    model_config = {"extra": "allow"}

    num_engineers: int = 2
    max_revisions: int = 3
    chaining: Optional[PipelineChainingConfig] = None
    mode: str = "standard"


class OllamaConfig(BaseModel):
    model_config = {"extra": "allow"}

    url: str = "http://localhost:11434"
    api_key: Optional[str] = None
    think: bool = False
    preserve_thinking: bool = False
    stream: bool = True


class AppConfig(BaseModel):
    model_config = {"extra": "forbid"}   # unknown top-level keys are errors

    llm: LLMConfig = Field(default_factory=LLMConfig)
    github: Optional[GithubConfig] = None
    pipeline: Optional[PipelineConfig] = None
    ollama: Optional[OllamaConfig] = None
    team: Optional[Dict[str, Any]] = None
    mcp: Optional[Dict[str, Any]] = None
    repo_context: Optional[Dict[str, Any]] = None
    memory: Optional[Dict[str, Any]] = None
    skills: Optional[Dict[str, Any]] = None
    token_tracking: Optional[Dict[str, Any]] = None
    framework_docs: Optional[Dict[str, Any]] = None
    rag: Optional[Dict[str, Any]] = None


# ── repos.yaml models ────────────────────────────────────────────────────────

class RepoWatcherEntry(BaseModel):
    model_config = {"extra": "allow"}   # allow custom keys for future expansion

    tracker_repo: str
    default_target: Optional[str] = None
    parallel_issues: int = 1
    labels: Dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    senior_model: Optional[str] = None
    conflict_resolver_model: Optional[str] = None


# ── loaders ──────────────────────────────────────────────────────────────────

def load_config(path: str) -> AppConfig:
    """Load and validate config.yaml. Raises pydantic.ValidationError on schema errors."""
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return AppConfig.model_validate(raw)


def load_repo_entry(data: dict) -> RepoWatcherEntry:
    """Validate a single repos.yaml watcher entry."""
    return RepoWatcherEntry.model_validate(data)
```

- [ ] **Step 5: Run config schema tests**

```bash
python -m pytest tests/test_config_schema.py -v
```

Expected: 5 passed

- [ ] **Step 6: Update `orchestrator.py` `from_config()` to validate on load**

In `orchestrator.py`, add import near the top (around line 50, with other imports):
```python
from config_schema import load_config as _load_app_config
```

In `from_config()` (line 892), after loading the YAML but before accessing `cfg.get(...)`, add validation. Change:
```python
        with open(config_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
```
to:
```python
        with open(config_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        # Validate schema — raises pydantic.ValidationError with field-level detail on bad config
        try:
            _load_app_config(config_path)
        except Exception as exc:
            raise ValueError(f"Invalid config.yaml: {exc}") from exc
```

Note: we still use the raw `cfg` dict for the rest of `from_config()` (backward compatible); validation is additive.

- [ ] **Step 7: Update `watcher.py` to validate each repo entry on startup**

In `watcher.py`, add import near the top:
```python
from config_schema import load_repo_entry
```

In `watch()`, find where the code reads each watcher entry from `repos.yaml` (look for `for entry in watchers:` or similar, around line 1040+). After loading the raw entry dict, add validation:
```python
        from pydantic import ValidationError
        validated_watchers = []
        for entry in raw_watchers:
            try:
                load_repo_entry(entry)   # validate; raises ValidationError on bad entry
                validated_watchers.append(entry)
            except ValidationError as exc:
                log.warning(
                    "Skipping invalid watcher entry %r: %s",
                    entry.get("tracker_repo", "?"),
                    exc,
                )
```
Then use `validated_watchers` for the rest of the loop.

- [ ] **Step 8: Run orchestrator tests to confirm no regressions**

```bash
python -m pytest tests/test_revision.py tests/test_conflict_resolver_wire.py -v 2>&1 | tail -10
```

Expected: all pass

- [ ] **Step 9: Commit**

```bash
git checkout -b qw-4-pydantic-config
git add config_schema.py tests/test_config_schema.py requirements.txt orchestrator.py watcher.py
git commit -m "feat: pydantic config validation for config.yaml and repos.yaml

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 5 (QW-5): structlog JSON Logging

**Branch:** `qw-5-structlog`

**Files:**
- Create: `logging_setup.py`
- Create: `tests/test_logging_setup.py`
- Modify: `requirements.txt`
- Modify: `watcher.py` (`_setup_logging()`)
- Modify: `main.py` (call configure_logging)
- Modify: `orchestrator.py` (generate run_id)

### Context

All logging uses stdlib `logging.getLogger(__name__)`. `watcher.py` has a `_setup_logging()` function (line 1186) that sets up file + console handlers. `main.py` has no logging setup. The fix introduces `structlog` with two renderers: `ConsoleRenderer` for terminal (human-readable), `JSONRenderer` for log files. A `run_id` is bound to all log output automatically via structlog context vars — no individual log call sites need changing.

### Steps

- [ ] **Step 1: Add structlog to `requirements.txt`**

```
structlog>=24.0
```

Install: `pip install "structlog>=24.0"`

- [ ] **Step 2: Write failing tests**

Create `tests/test_logging_setup.py`:

```python
import io, json, logging

def test_configure_logging_no_crash():
    """configure_logging() runs without raising."""
    from logging_setup import configure_logging
    configure_logging(log_level="WARNING")   # use WARNING to avoid cluttering test output

def test_bind_run_id_appears_in_log_output(tmp_path):
    """After bind_run_id(), all log lines contain the run_id."""
    import structlog
    log_file = tmp_path / "test.log"
    from logging_setup import configure_logging, bind_run_id
    configure_logging(log_level="DEBUG", log_file=log_file)
    bind_run_id("abc12345")
    logger = logging.getLogger("test_logger")
    logger.info("hello from test")
    content = log_file.read_text()
    assert "abc12345" in content

def test_json_renderer_produces_valid_json(tmp_path):
    """Log file output is valid JSON lines."""
    log_file = tmp_path / "test.log"
    from logging_setup import configure_logging, bind_run_id
    configure_logging(log_level="DEBUG", log_file=log_file)
    bind_run_id("test999")
    logging.getLogger("json_test").warning("test message")
    lines = [l for l in log_file.read_text().splitlines() if l.strip()]
    assert len(lines) >= 1
    parsed = json.loads(lines[-1])
    assert "event" in parsed or "message" in parsed
```

- [ ] **Step 3: Run to verify they fail**

```bash
python -m pytest tests/test_logging_setup.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'logging_setup'`

- [ ] **Step 4: Create `logging_setup.py`**

```python
"""Structured logging setup using structlog.

Usage:
    from logging_setup import configure_logging, bind_run_id
    configure_logging(log_level="INFO", log_file=Path("logs/app.log"))
    bind_run_id("abc12345")   # all subsequent log calls include run_id=abc12345
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

import structlog


def configure_logging(
    log_level: str = "INFO",
    log_file: Optional[Path] = None,
) -> None:
    """Configure stdlib logging to use structlog processors.

    Console output uses human-readable ConsoleRenderer.
    File output (if log_file given) uses JSONRenderer (one JSON object per line).

    This function is idempotent — calling it multiple times only adds handlers
    if they don't already exist. To reset, call logging.root.handlers.clear() first.
    """
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    structlog.configure(
        processors=shared_processors
        + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    root = logging.getLogger()
    level = getattr(logging, log_level.upper(), logging.INFO)
    root.setLevel(level)

    # Console handler — human-readable
    if not any(isinstance(h, logging.StreamHandler) and h.stream is sys.stderr
               for h in root.handlers):
        console_fmt = structlog.stdlib.ProcessorFormatter(
            processor=structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty()),
            foreign_pre_chain=shared_processors,
        )
        ch = logging.StreamHandler(sys.stderr)
        ch.setFormatter(console_fmt)
        root.addHandler(ch)

    # File handler — JSON lines
    if log_file:
        log_file = Path(log_file)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        json_fmt = structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(),
            foreign_pre_chain=shared_processors,
        )
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(json_fmt)
        root.addHandler(fh)


def bind_run_id(run_id: str) -> None:
    """Bind run_id to all log calls in the current thread via structlog context vars."""
    structlog.contextvars.bind_contextvars(run_id=run_id)


def clear_run_id() -> None:
    """Remove run_id binding (call between test runs or pipeline resets)."""
    structlog.contextvars.unbind_contextvars("run_id")
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_logging_setup.py -v
```

Expected: 3 passed

- [ ] **Step 6: Update `watcher.py` to use `configure_logging`**

Add import to top of `watcher.py`:
```python
import uuid
from logging_setup import configure_logging, bind_run_id
```

Replace `_setup_logging()` body (lines 1186–1201):
```python
def _setup_logging(log_dir: Path) -> logging.Logger:
    ts = datetime.now().strftime("%Y%m%d")
    log_file = log_dir / f"watcher-{ts}.log"
    configure_logging(log_level="INFO", log_file=log_file)
    return logging.getLogger("watcher")
```

In `watch()` (around line 1028), after `logger = _setup_logging(...)`, add:
```python
    run_id = uuid.uuid4().hex[:8]
    bind_run_id(run_id)
    logger.info("Watcher starting", extra={"run_id": run_id})
```

- [ ] **Step 7: Update `main.py` to call `configure_logging`**

At the top of `main.py`, add:
```python
import uuid
from logging_setup import configure_logging, bind_run_id
```

In the `main()` function, after argument parsing and before the orchestrator is created, add:
```python
    run_id = uuid.uuid4().hex[:8]
    configure_logging(log_level="INFO")
    bind_run_id(run_id)
```

- [ ] **Step 8: Run full test suite to confirm no regressions**

```bash
python -m pytest tests/test_logging_setup.py tests/test_watcher.py tests/test_revision.py -v 2>&1 | tail -15
```

Expected: all pass

- [ ] **Step 9: Commit**

```bash
git checkout -b qw-5-structlog
git add logging_setup.py tests/test_logging_setup.py requirements.txt watcher.py main.py
git commit -m "feat: structlog JSON logging with run_id context binding

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 6 (QW-6): `check.py` CLI

**Branch:** `qw-6-check-cli`

**Depends on:** Task 4 (QW-4) — `config_schema.py` must exist

**Files:**
- Create: `check.py`
- Create: `tests/test_check.py`

### Context

No way currently to validate config or credentials without running a full pipeline. `check.py` is a standalone script with two subcommands: `validate-config` (uses pydantic schema from QW-4) and `test-github` (calls `GET /user` and `GET /repos/{repo}`).

### Steps

- [ ] **Step 1: Write failing tests**

Create `tests/test_check.py`:

```python
import subprocess, sys, json
from unittest.mock import patch, MagicMock
import pytest

def _run_check(*args):
    """Run check.py as subprocess and return (returncode, stdout)."""
    result = subprocess.run(
        [sys.executable, "check.py"] + list(args),
        capture_output=True, text=True,
        cwd="/home/wanleung/Projects/ai-software-house"
    )
    return result.returncode, result.stdout + result.stderr

def test_validate_config_valid(tmp_path):
    """Valid config.yaml exits 0."""
    import yaml
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump({"llm": {"model": "gpt-4.1"}}))
    code, out = _run_check("validate-config", "--config", str(cfg_file))
    assert code == 0
    assert "✅" in out or "valid" in out.lower()

def test_validate_config_invalid(tmp_path):
    """Invalid config.yaml exits 1 with error details."""
    import yaml
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump({"unknown_top_level": "bad"}))
    code, out = _run_check("validate-config", "--config", str(cfg_file))
    assert code == 1
    assert "❌" in out or "error" in out.lower()

def test_test_github_success(monkeypatch):
    """test-github subcommand exits 0 when token and repo are valid."""
    import importlib
    monkeypatch.setenv("GITHUB_TOKEN", "faketoken")

    user_resp = MagicMock()
    user_resp.ok = True
    user_resp.status_code = 200
    user_resp.json.return_value = {"login": "testuser"}
    user_resp.headers = {"X-OAuth-Scopes": "repo", "X-RateLimit-Remaining": "4999", "X-RateLimit-Reset": "9999999999"}

    repo_resp = MagicMock()
    repo_resp.ok = True
    repo_resp.status_code = 200
    repo_resp.json.return_value = {"full_name": "owner/repo", "permissions": {"push": True}}

    with patch("requests.get", side_effect=[user_resp, repo_resp]):
        import check
        import importlib; importlib.reload(check)
        code = check.cmd_test_github(repo="owner/repo", token="faketoken")
    assert code == 0

def test_test_github_bad_token(monkeypatch):
    """test-github exits 1 when token is invalid (401)."""
    monkeypatch.setenv("GITHUB_TOKEN", "badtoken")
    resp = MagicMock()
    resp.ok = False
    resp.status_code = 401
    resp.json.return_value = {"message": "Bad credentials"}

    with patch("requests.get", return_value=resp):
        import check
        import importlib; importlib.reload(check)
        code = check.cmd_test_github(repo="owner/repo", token="badtoken")
    assert code == 1
```

- [ ] **Step 2: Run to verify they fail**

```bash
python -m pytest tests/test_check.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'check'`

- [ ] **Step 3: Create `check.py`**

```python
#!/usr/bin/env python3
"""
AI Software House — setup validation CLI.

Usage:
    python check.py validate-config [--config config.yaml] [--repos repos.yaml]
    python check.py test-github [--repo owner/repo] [--token TOKEN]
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

import requests
from rich.console import Console
from rich.table import Table

console = Console()


# ── validate-config ──────────────────────────────────────────────────────────

def cmd_validate_config(config: str, repos: str) -> int:
    """Validate config.yaml and repos.yaml. Returns exit code."""
    from config_schema import load_config, load_repo_entry
    import yaml
    from pydantic import ValidationError

    errors = 0

    # Validate config.yaml
    console.print(f"\n[bold]Validating {config}...[/bold]")
    if not os.path.exists(config):
        console.print(f"  [red]❌ File not found: {config}[/red]")
        errors += 1
    else:
        try:
            cfg = load_config(config)
            console.print(f"  [green]✅ llm.model:[/green] {cfg.llm.model}")
            if cfg.github:
                console.print(f"  [green]✅ github.repo:[/green] {cfg.github.repo or '(not set)'}")
            if cfg.pipeline:
                console.print(f"  [green]✅ pipeline.num_engineers:[/green] {cfg.pipeline.num_engineers}")
            console.print(f"  [green]✅ config.yaml is valid[/green]")
        except ValidationError as exc:
            for err in exc.errors():
                loc = " → ".join(str(x) for x in err["loc"])
                console.print(f"  [red]❌ {loc}:[/red] {err['msg']}")
            errors += len(exc.errors())
        except Exception as exc:
            console.print(f"  [red]❌ Failed to load: {exc}[/red]")
            errors += 1

    # Validate repos.yaml
    console.print(f"\n[bold]Validating {repos}...[/bold]")
    if not os.path.exists(repos):
        console.print(f"  [yellow]⚠️  File not found: {repos} (optional)[/yellow]")
    else:
        try:
            with open(repos) as f:
                raw = yaml.safe_load(f) or {}
            watchers = raw.get("watchers", [])
            if not watchers:
                console.print("  [yellow]⚠️  No watchers defined[/yellow]")
            for entry in watchers:
                try:
                    r = load_repo_entry(entry)
                    status = "enabled" if r.enabled else "disabled"
                    console.print(f"  [green]✅[/green] {r.tracker_repo} ({status}, {r.parallel_issues} parallel)")
                except ValidationError as exc:
                    for err in exc.errors():
                        loc = " → ".join(str(x) for x in err["loc"])
                        console.print(f"  [red]❌ {entry.get('tracker_repo', '?')} {loc}:[/red] {err['msg']}")
                        errors += 1
        except Exception as exc:
            console.print(f"  [red]❌ Failed to load: {exc}[/red]")
            errors += 1

    if errors:
        console.print(f"\n[red]{errors} error(s) found. Fix before running the pipeline.[/red]")
    else:
        console.print("\n[green]All configuration is valid.[/green]")

    return 1 if errors else 0


# ── test-github ───────────────────────────────────────────────────────────────

def cmd_test_github(repo: str, token: str | None) -> int:
    """Test GitHub credentials. Returns exit code."""
    token = token or os.environ.get("GITHUB_TOKEN", "")
    if not token:
        console.print("[red]❌ No token provided. Set GITHUB_TOKEN or pass --token.[/red]")
        return 1

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    errors = 0

    console.print("\n[bold]Testing GitHub credentials...[/bold]")

    # Check token identity
    resp = requests.get("https://api.github.com/user", headers=headers, timeout=10)
    if resp.ok:
        user = resp.json().get("login", "unknown")
        scopes = resp.headers.get("X-OAuth-Scopes", "(none)")
        remaining = resp.headers.get("X-RateLimit-Remaining", "?")
        reset_ts = resp.headers.get("X-RateLimit-Reset")
        reset_str = ""
        if reset_ts:
            reset_dt = datetime.fromtimestamp(int(reset_ts), tz=timezone.utc)
            mins = max(0, int((reset_dt - datetime.now(tz=timezone.utc)).total_seconds() / 60))
            reset_str = f" (resets in {mins} min)"
        console.print(f"  [green]✅ Token valid[/green] — authenticated as: [bold]{user}[/bold]")
        console.print(f"  [green]✅ Token scopes:[/green] {scopes}")
        console.print(f"  [green]✅ Rate limit:[/green] {remaining}/5000 remaining{reset_str}")
    else:
        console.print(f"  [red]❌ Token invalid — HTTP {resp.status_code}: {resp.json().get('message', '')}[/red]")
        errors += 1

    # Check repo access
    if repo:
        console.print(f"\n[bold]Testing repo access: {repo}[/bold]")
        resp2 = requests.get(f"https://api.github.com/repos/{repo}", headers=headers, timeout=10)
        if resp2.ok:
            data = resp2.json()
            perms = data.get("permissions", {})
            push = "✅" if perms.get("push") else "❌"
            default_branch = data.get("default_branch", "?")
            console.print(f"  [green]✅ Repo {repo}[/green] — read access ✓, push access {push}")
            console.print(f"  [green]✅ Default branch:[/green] {default_branch}")
            if not perms.get("push"):
                console.print("  [yellow]⚠️  No push access — pipeline will fail when committing code[/yellow]")
                errors += 1
        else:
            console.print(f"  [red]❌ Cannot access repo {repo} — HTTP {resp2.status_code}[/red]")
            errors += 1

    if errors == 0:
        console.print("\n[green]All checks passed.[/green]")
    else:
        console.print(f"\n[red]{errors} check(s) failed.[/red]")

    return 1 if errors else 0


# ── CLI entry point ───────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check",
        description="AI Software House — setup validation",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # validate-config
    vc = sub.add_parser("validate-config", help="Validate config.yaml and repos.yaml")
    vc.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    vc.add_argument("--repos", default="repos.yaml", help="Path to repos.yaml")

    # test-github
    tg = sub.add_parser("test-github", help="Test GitHub token and repo access")
    tg.add_argument("--repo", default=os.environ.get("GITHUB_REPO", ""), help="owner/repo to test")
    tg.add_argument("--token", default=None, help="GitHub token (default: GITHUB_TOKEN env)")

    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    if args.command == "validate-config":
        return cmd_validate_config(config=args.config, repos=args.repos)
    elif args.command == "test-github":
        return cmd_test_github(repo=args.repo, token=args.token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_check.py -v
```

Expected: 4 passed

- [ ] **Step 5: Smoke test manually**

```bash
cd /home/wanleung/Projects/ai-software-house
python check.py validate-config
python check.py test-github --repo wanleung/ai-software-house
```

Expected: coloured output with ✅ / ❌ per check, exit 0 if config and token are valid.

- [ ] **Step 6: Commit**

```bash
git checkout -b qw-6-check-cli
git add check.py tests/test_check.py
git commit -m "feat: add check.py CLI for config validation and GitHub credential testing

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Delivery Order

```
QW-1 (session)    → PR-1 (independent)
QW-2 (sanitise)   → PR-2 (independent, but QW-1 should merge first so github_client.py diff is clean)
QW-3 (tenacity)   → PR-3 (independent)
QW-4 (pydantic)   → PR-4 (independent)
QW-5 (structlog)  → PR-5 (independent)
QW-6 (check.py)   → PR-6 (depends on QW-4 merged first)
```

Recommended merge order: QW-1, QW-2, QW-3, QW-4, QW-5, QW-6.

## Final Verification

After all 6 PRs merged, run the full test suite:

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/ -v --ignore=tests/unit --ignore=tests/integration 2>&1 | tail -20
```

Expected: all tests pass with no regressions.
