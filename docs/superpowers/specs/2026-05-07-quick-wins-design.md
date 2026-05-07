# Quick Wins — Reliability, Security & DX Improvements

**Date:** 2026-05-07  
**Status:** Approved  
**Delivery:** 6 separate PRs, one per quick win

---

## Overview

Six targeted improvements addressing the highest-impact, lowest-effort issues found in the codebase analysis. Each is independently shippable as its own PR with no dependencies between them (except QW-4 pydantic schema is used by QW-6 `check.py`).

| # | Title | Files | PR |
|---|-------|-------|----|
| QW-1 | `requests.Session` in `GitHubClient` | `github_client.py` | PR-1 |
| QW-2 | Global token sanitisation | `utils.py` (new), `github_client.py`, `orchestrator.py`, `watcher.py`, `agents/conflict_resolver.py` | PR-2 |
| QW-3 | Tenacity retries in `watcher.py` | `requirements.txt`, `watcher.py` | PR-3 |
| QW-4 | Pydantic config validation | `config_schema.py` (new), `orchestrator.py`, `watcher.py` | PR-4 |
| QW-5 | structlog JSON logging | `logging_setup.py` (new), `requirements.txt`, `watcher.py`, `orchestrator.py`, `main.py` | PR-5 |
| QW-6 | `check.py` CLI | `check.py` (new) | PR-6 |

**Dependency:** QW-6 depends on QW-4 (uses pydantic schemas). All others are independent.

---

## QW-1: `requests.Session` in `GitHubClient`

### Problem

Every `_request()` call invokes `requests.request(method, url, ...)` which opens a new TCP connection. A full pipeline makes 50–150 GitHub API calls — each paying the TCP + TLS handshake overhead (~50–200ms per call).

### Design

Store a `requests.Session` as `self._session` on `GitHubClient`. Set default `Authorization` and `Accept` headers once on the session. Replace `requests.request(...)` with `self._session.request(...)` inside `_request()`.

```python
class GitHubClient:
    def __init__(self, repo: str, github_token: Optional[str] = None) -> None:
        ...
        self._session = requests.Session()
        self._session.headers.update(self.headers)   # set once

    def __del__(self) -> None:
        self._session.close()
```

The existing `self.headers` dict is kept for backward compatibility (some code reads it directly). Retry logic in `_request()` is unchanged. No public API changes.

### Files
- `github_client.py` — add `self._session`, update `_request()`, add `__del__`
- `tests/test_github_client.py` — update request mocks from `requests.request` to `session.request`

### Tests
- `test_session_reused_across_requests` — make two calls, assert session.request called twice (not requests.request)
- `test_session_closed_on_del` — verify `__del__` calls `session.close()`

---

## QW-2: Global Token Sanitisation

### Problem

`_sanitise()` exists only in `ConflictResolverAgent`. All other components — `github_client.py`, `orchestrator.py`, `watcher.py` — may emit the raw GitHub token in error messages, log lines, or PR comments if it appears in a URL (e.g. `https://x-access-token:<token>@github.com/...`) or API error response.

### Design

**New module `utils.py`** (project root):

```python
def sanitise(text: str, *secrets: str) -> str:
    """Replace all occurrences of each secret in text with '***'."""
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return text
```

**Apply at 4 sites:**

1. **`github_client.py` `_request()`** — sanitise the `RuntimeError` message:
   ```python
   raise RuntimeError(sanitise(
       f"GitHub API {method} {url} failed [{status}]: {response.text[:500]}",
       self.token
   ))
   ```

2. **`orchestrator.py`** — sanitise in `_update_branch_from_base()` conflict-resolver error path where `result.reason` is logged/commented.

3. **`watcher.py`** — sanitise in `except` blocks that call `post_comment()` or `_log()` with exception text.

4. **`agents/conflict_resolver.py`** — `_sanitise()` now delegates to `utils.sanitise`:
   ```python
   def _sanitise(self, text: str) -> str:
       from utils import sanitise
       return sanitise(text, getattr(self, "_token", None) or "")
   ```
   No behaviour change; just removes duplication.

### Files
- `utils.py` (new)
- `github_client.py`
- `orchestrator.py`
- `watcher.py`
- `agents/conflict_resolver.py`

### Tests
- `test_sanitise_replaces_token` — basic unit test
- `test_sanitise_empty_secret_safe` — empty/None secret doesn't crash
- `test_github_client_error_redacts_token` — mock a 500 response whose URL contains token; assert RuntimeError message shows `***`

---

## QW-3: Tenacity Retries in `watcher.py`

### Problem

`watcher.py` has ~8 direct `requests.get/post` call sites (in `ensure_label`, `add_label`, `post_comment`, and PR polling) with no retry. A transient 429 or 503 causes the entire PR cycle to fail and posts `agent-failed` on the issue unnecessarily.

`GitHubClient._request()` already has its own retry loop; this change only covers the watcher's direct `requests.*` calls that bypass `GitHubClient`.

### Design

Add `tenacity` to `requirements.txt`.

Define a shared retry decorator in `watcher.py`:

```python
from tenacity import (
    retry, retry_if_exception, stop_after_attempt,
    wait_exponential, before_sleep_log
)

def _is_retryable_response(exc: Exception) -> bool:
    return (
        isinstance(exc, requests.HTTPError)
        and exc.response is not None
        and exc.response.status_code in {429, 500, 502, 503, 504}
    )

_retry_github = retry(
    retry=retry_if_exception(_is_retryable_response),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    stop=stop_after_attempt(5),
    before_sleep=before_sleep_log(_log, logging.WARNING),
    reraise=True,
)
```

Wrap each retryable call site. Calls must raise `HTTPError` on bad status — add `.raise_for_status()` where missing.

**Retryable call sites** (to be confirmed by reading watcher.py during implementation):
- `ensure_label()` GET + POST
- `add_label()` POST
- `remove_label()` DELETE
- `post_comment()` POST
- PR list fetch GET

**Not retried:** calls inside `_run_pr_revision()` that delegate to `GitHubClient` (already retried there).

### Files
- `requirements.txt` — add `tenacity>=8.2`
- `watcher.py` — import tenacity, define `_retry_github`, wrap call sites

### Tests
- `test_ensure_label_retries_on_429` — mock 429 then 201; assert called twice
- `test_post_comment_retries_on_503` — mock 503 then 200; assert retried

---

## QW-4: Pydantic Config Validation

### Problem

`config.yaml` is loaded with `yaml.safe_load()` and accessed with dict `.get()`. Typos in agent override keys (e.g. `architeckt`) silently become `None` — discovered only when an agent produces wrong output deep in a pipeline run.

### Design

**New file `config_schema.py`:**

```python
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

class LLMOverridesConfig(BaseModel):
    model_config = {"extra": "allow"}   # allow any agent name as override key
    # common known keys documented but not enforced (agents are user-extendable)

class LLMConfig(BaseModel):
    model: str = "gpt-4.1"
    overrides: Optional[LLMOverridesConfig] = None
    fallback: Optional[list[str]] = None

class GithubConfig(BaseModel):
    repo: str
    token: Optional[str] = None   # falls back to env var

class PipelineChainingConfig(BaseModel):
    on_test_failure: Optional[str] = None
    on_review_issues: Optional[str] = None

class PipelineConfig(BaseModel):
    num_engineers: int = 2
    max_revisions: int = 3
    chaining: Optional[PipelineChainingConfig] = None

class OllamaConfig(BaseModel):
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

def load_config(path: str) -> AppConfig:
    """Load and validate config.yaml. Raises pydantic.ValidationError on schema errors."""
    import yaml
    with open(path) as f:
        raw = yaml.safe_load(f)
    return AppConfig.model_validate(raw or {})
```

**`RepoWatcherConfig`** (for `repos.yaml`) — simpler model:

```python
class RepoWatcherEntry(BaseModel):
    tracker_repo: str
    default_target: Optional[str] = None
    parallel_issues: int = 1
    labels: Dict[str, str] = {}
    enabled: bool = True
    senior_model: Optional[str] = None
    conflict_resolver_model: Optional[str] = None
    model_config = {"extra": "allow"}   # allow custom keys for future expansion
```

**Integration:**
- `Orchestrator.from_config(path)` calls `load_config(path)` — if validation fails, prints the pydantic error with field path and stops before any GitHub API calls
- `watcher.py` `watch()` validates `repos.yaml` entries on load

**Backward compatibility:** All fields have defaults matching current runtime behaviour. Existing `config.yaml` files continue to work without changes.

### Files
- `config_schema.py` (new)
- `requirements.txt` — add `pydantic>=2.0`
- `orchestrator.py` — `from_config()` uses `load_config()`
- `watcher.py` — validates repo entries

### Tests
- `test_valid_config_loads` — minimal valid config passes
- `test_unknown_top_level_key_raises` — `extra_key: true` raises `ValidationError`
- `test_missing_model_uses_default` — omitting `llm.model` gives `"gpt-4.1"`
- `test_repo_config_extra_fields_allowed` — custom keys don't raise

---

## QW-5: structlog JSON Logging

### Problem

All log calls use stdlib `logging` with `%s`-style string formatting. No request IDs, no JSON output, no machine-parseable structure. Debugging multi-stage failures requires manual log grep.

### Design

**New file `logging_setup.py`:**

```python
import structlog
import logging
import sys
from pathlib import Path

def configure_logging(
    log_level: str = "INFO",
    run_id: str | None = None,
    log_file: Path | None = None,
) -> None:
    """Configure structlog with JSON file output and human-readable console output."""

    shared_processors = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
    ]
    if run_id:
        shared_processors.append(structlog.contextvars.merge_contextvars)

    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Console handler — human-readable
    console_formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.dev.ConsoleRenderer(),
        foreign_pre_chain=shared_processors,
    )
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(console_formatter)

    handlers = [console_handler]

    # File handler — JSON lines
    if log_file:
        json_formatter = structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(),
            foreign_pre_chain=shared_processors,
        )
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(json_formatter)
        handlers.append(file_handler)

    root = logging.getLogger()
    root.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    for h in handlers:
        root.addHandler(h)

def bind_run_id(run_id: str) -> None:
    """Bind run_id to all subsequent log calls in this thread."""
    structlog.contextvars.bind_contextvars(run_id=run_id)
```

**`run_id` generation:** `uuid.uuid4().hex[:8]` — short enough to type, unique enough for a session. Generated in `Orchestrator.__init__` and `watch()`.

**Integration:**
- `watcher.py` `_setup_logging()` replaced with `configure_logging(log_file=log_dir/...)` + `bind_run_id(run_id)`
- `main.py` `main()` calls `configure_logging()` + `bind_run_id(run_id)`
- No changes to individual `log.info(...)` call sites — structlog injects `run_id` automatically via context vars

**No changes to log call sites** — all existing `log.info(...)`, `log.warning(...)` etc. continue to work unchanged because structlog wraps the stdlib logger. This is the key advantage of the structlog approach.

### Files
- `logging_setup.py` (new)
- `requirements.txt` — add `structlog>=24.0`
- `watcher.py` — replace `_setup_logging()` body
- `main.py` — call `configure_logging()` + `bind_run_id()`
- `orchestrator.py` — generate and pass `run_id`

### Tests
- `test_configure_logging_no_crash` — call configure_logging with in-memory StringIO; no exceptions
- `test_bind_run_id_appears_in_output` — bind run_id, emit log, assert run_id in output
- `test_json_renderer_produces_valid_json` — file handler output is valid JSON lines

---

## QW-6: `check.py` CLI

### Problem

No way to validate GitHub credentials or config files without running a full pipeline. Developers discover typos or expired tokens only after a 5-minute pipeline run fails.

### Design

**New file `check.py`** (project root, standalone script):

```
python check.py validate-config [--config config.yaml] [--repos repos.yaml]
python check.py test-github [--repo owner/repo] [--token TOKEN]
```

**`validate-config` subcommand:**
1. Load `config.yaml` via `load_config()` from `config_schema.py` (QW-4)
2. Load `repos.yaml` entries via `RepoWatcherEntry` models
3. Print ✅ / ❌ per section with pydantic field-level error detail
4. Exit 0 if valid, 1 if any error

```
Validating config.yaml...
  ✅ llm.model: gpt-4.1
  ✅ github.repo: wanleung/my-app
  ❌ pipeline.num_engineers: value is not a valid integer (got "two")

Validating repos.yaml...
  ✅ wanleung/ai-software-house (enabled, 2 parallel issues)
  ❌ wanleung/broken-repo: tracker_repo is required

1 error found. Fix before running the pipeline.
```

**`test-github` subcommand:**
1. Resolve token (arg → `GITHUB_TOKEN` env)
2. `GET /user` — reports token identity and scopes from `X-OAuth-Scopes` header
3. `GET /repos/{repo}` — reports read access, push access, default branch
4. Reports rate limit remaining from `X-RateLimit-Remaining` header
5. Exit 0 if all pass, 1 if any fail

```
Testing GitHub credentials...
  ✅ Token valid — authenticated as: wanleung
  ✅ Token scopes: repo, read:org
  ✅ Repo wanleung/my-app — read access ✓, push access ✓
  ✅ Rate limit: 4823/5000 remaining (resets in 42 min)
```

Uses `rich` for formatted output (already in requirements). Depends on `config_schema.py` from QW-4 for `validate-config`. `test-github` has no dependency on QW-4.

### Files
- `check.py` (new — ~150 lines)

### Tests
- `test_validate_config_valid` — valid config.yaml → exit 0
- `test_validate_config_invalid` — bad field → exit 1 + error in output
- `test_test_github_success` — mock `/user` + `/repos/{repo}` → exit 0
- `test_test_github_bad_token` — mock 401 → exit 1

---

## Delivery Order

Because QW-6 depends on QW-4's pydantic schemas, the recommended PR order is:

```
QW-1 → QW-2 → QW-3 → QW-4 → QW-6
                    ↘ QW-5 (independent, can be parallel)
```

QW-1, QW-2, QW-3, QW-5 are fully independent and can be merged in any order.

---

## Non-Goals

- No changes to `config.yaml` or `repos.yaml` format
- No changes to individual `log.info()` call sites (structlog wraps stdlib)
- No changes to `GitHubClient` public API
- No pydantic model for `pipeline.yaml` (custom pipeline files — out of scope)
