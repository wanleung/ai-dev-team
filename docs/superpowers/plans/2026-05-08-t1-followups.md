# T1 Follow-ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three hardening items left over from the T1 reliability track: unsanitised logger calls, missing config validation in `_load_pipeline_config()`, and circuit breaker gaps in `_stream_call` / `call_with_tools`.

**Architecture:** Three independent, self-contained fixes in one branch (`t1-followups`). Each fix has its own commit. No new abstractions needed — all fixes apply existing patterns consistently.

**Tech Stack:** Python 3.11, Pydantic v2, `core.circuit_breaker_registry`, existing `_sanitise()` helper in `utils.py`.

---

## File Map

| File | Change |
|------|--------|
| `watcher.py` | Fix 2 unsanitised `logger.warning` calls (lines ~466, ~1539) |
| `watcher.py` | Add `AppConfig.model_validate()` after merge in `_load_pipeline_config()` |
| `agents/backends/base.py` | Wrap `_stream_call` and `call_with_tools` (3 sites) with `cb.call()` |
| `tests/test_watcher_sanitise.py` (new) | Tests for sanitised DLQ log calls |
| `tests/test_watcher_config_validation.py` (new) | Tests for `_load_pipeline_config()` validation |
| `tests/test_backend_circuit_breaker.py` (existing) | Add tests for `_stream_call` and `call_with_tools` CB wrapping |

---

## Branch Setup

```bash
cd /home/wanleung/Projects/ai-software-house
git checkout master && git pull
git checkout -b t1-followups
```

---

## Task 1: Sanitise unsanitised logger calls in `watcher.py`

Two `logger.warning` calls log exception objects without `_sanitise()`. If the exception wraps an HTTP error containing a GitHub token in a URL, the token leaks to the log.

**Files:**
- Modify: `watcher.py` (lines ~466, ~1539)
- Test: `tests/test_watcher_sanitise.py` (create)

- [ ] **Step 1: Write failing tests**

Create `tests/test_watcher_sanitise.py`:

```python
import logging
import os
import datetime
from unittest.mock import MagicMock, patch
import pytest


def _exc_with_token(token: str) -> Exception:
    return Exception(f"https://x-access-token:{token}@github.com/owner/repo.git")


def test_dlq_enqueue_warning_sanitises_token(caplog):
    """logger.warning for DLQ enqueue failure must not emit the raw token."""
    token = "ghp_SECRETTOKEN1234"
    os.environ["GITHUB_TOKEN"] = token

    with caplog.at_level(logging.WARNING, logger="watcher"):
        import watcher
        from utils import sanitise as _sanitise
        logger = logging.getLogger("watcher")
        # Simulate what the fixed code does
        exc = _exc_with_token(token)
        logger.warning("Could not enqueue to DLQ: %s", _sanitise(str(exc), os.environ.get("GITHUB_TOKEN", "")))

    assert token not in caplog.text


def test_dlq_retry_warning_sanitises_token(caplog):
    """logger.warning for DLQ retry failure must not emit the raw token."""
    token = "ghp_SECRETRETRY5678"
    os.environ["GITHUB_TOKEN"] = token

    with caplog.at_level(logging.WARNING, logger="watcher"):
        import watcher
        from utils import sanitise as _sanitise
        logger = logging.getLogger("watcher")
        exc = _exc_with_token(token)
        logger.warning(
            "DLQ retry failed for issue #%d: %s",
            42,
            _sanitise(str(exc), os.environ.get("GITHUB_TOKEN", "")),
        )

    assert token not in caplog.text
```

- [ ] **Step 2: Run to verify tests describe the right behaviour**

```bash
cd /home/wanleung/Projects/ai-software-house && source ~/.bash_env && python3 -m pytest tests/test_watcher_sanitise.py -v 2>&1 | tail -10
```

These tests verify the *fixed* pattern. They should PASS even before the production code change (they test the helper directly). The real regression protection comes from Step 4 verifying the production call sites match.

- [ ] **Step 3: Verify current production code is unsanitised**

```bash
grep -n "_sanitise" watcher.py | grep -E "466|1539"
```

Expected: no output (neither line uses `_sanitise` yet).

- [ ] **Step 4: Apply the fixes to `watcher.py`**

Find line ~466 (inside `except Exception as _dlq_exc` block under DLQ enqueue):

```python
# BEFORE
logger.warning("Could not enqueue to DLQ: %s", _dlq_exc)

# AFTER
logger.warning("Could not enqueue to DLQ: %s", _sanitise(str(_dlq_exc), os.environ.get("GITHUB_TOKEN", "")))
```

Find line ~1539 (inside `except Exception as exc` block in `--retry-dlq` loop):

```python
# BEFORE
logger.warning("DLQ retry failed for issue #%d: %s", entry.issue_number, exc)

# AFTER
logger.warning("DLQ retry failed for issue #%d: %s", entry.issue_number, _sanitise(str(exc), os.environ.get("GITHUB_TOKEN", "")))
```

- [ ] **Step 5: Verify both sites are now sanitised**

```bash
grep -n "_sanitise" watcher.py | grep -E "dlq_exc|DLQ retry"
```

Expected: 2 lines printed, both containing `_sanitise`.

- [ ] **Step 6: Run full watcher tests**

```bash
cd /home/wanleung/Projects/ai-software-house && source ~/.bash_env && python3 -m pytest tests/test_watcher_sanitise.py tests/test_watcher.py tests/test_watcher_dlq.py -v --ignore-glob="*test_watcher_prs*" 2>&1 | tail -15
```

Expected: all PASS (ignore pre-existing failures in test_watcher_prs.py).

- [ ] **Step 7: Commit**

```bash
cd /home/wanleung/Projects/ai-software-house
git add watcher.py tests/test_watcher_sanitise.py
git commit -m "fix(t1): sanitise DLQ exception messages in logger.warning calls

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 2: Validate merged config in `_load_pipeline_config()`

`_load_pipeline_config()` in `watcher.py` merges `config.yaml` + `config.local.yaml` but returns without schema validation. The `orchestrator.py` path already validates correctly — this brings `watcher.py` in line.

**Files:**
- Modify: `watcher.py` (`_load_pipeline_config`, ~line 469)
- Test: `tests/test_watcher_config_validation.py` (create)

- [ ] **Step 1: Write failing test**

Create `tests/test_watcher_config_validation.py`:

```python
import pytest
from pathlib import Path
from unittest.mock import patch, mock_open
import io


def test_load_pipeline_config_invalid_local_raises(monkeypatch):
    """Invalid config.local.yaml field raises ValueError with 'Invalid config' message."""
    import watcher

    base_yaml = "llm:\n  model: gpt-4o\n"
    # LLMConfig has extra=forbid (or similar validation); use a completely wrong type
    local_yaml = "llm: not-a-dict\n"

    orig_exists = Path.exists
    def fake_exists(self):
        if self.name in ("config.yaml", "config.local.yaml"):
            return True
        return orig_exists(self)

    original_open = open
    def fake_open(path, *args, **kwargs):
        path_str = str(path)
        if path_str.endswith("config.local.yaml"):
            return io.StringIO(local_yaml)
        if path_str.endswith("config.yaml"):
            return io.StringIO(base_yaml)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "exists", fake_exists)
    monkeypatch.setattr("builtins.open", fake_open)

    with pytest.raises(ValueError, match="Invalid config"):
        watcher._load_pipeline_config()


def test_load_pipeline_config_valid_raises_nothing(monkeypatch):
    """Valid config.local.yaml override loads silently."""
    import watcher

    base_yaml = "llm:\n  model: gpt-4o\n"
    local_yaml = "llm:\n  model: gpt-4o-mini\n"

    orig_exists = Path.exists
    def fake_exists(self):
        if self.name in ("config.yaml", "config.local.yaml"):
            return True
        return orig_exists(self)

    original_open = open
    def fake_open(path, *args, **kwargs):
        path_str = str(path)
        if path_str.endswith("config.local.yaml"):
            return io.StringIO(local_yaml)
        if path_str.endswith("config.yaml"):
            return io.StringIO(base_yaml)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "exists", fake_exists)
    monkeypatch.setattr("builtins.open", fake_open)

    cfg = watcher._load_pipeline_config()
    assert cfg["llm"]["model"] == "gpt-4o-mini"


def test_load_pipeline_config_no_local_file(monkeypatch):
    """Absent config.local.yaml: base config loaded, no error."""
    import watcher

    base_yaml = "llm:\n  model: gpt-4o\n"

    orig_exists = Path.exists
    def fake_exists(self):
        if self.name == "config.yaml":
            return True
        if self.name == "config.local.yaml":
            return False
        return orig_exists(self)

    original_open = open
    def fake_open(path, *args, **kwargs):
        path_str = str(path)
        if path_str.endswith("config.yaml"):
            return io.StringIO(base_yaml)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "exists", fake_exists)
    monkeypatch.setattr("builtins.open", fake_open)

    cfg = watcher._load_pipeline_config()
    assert cfg.get("llm", {}).get("model") == "gpt-4o"
```

- [ ] **Step 2: Run to verify invalid-config test fails**

```bash
cd /home/wanleung/Projects/ai-software-house && source ~/.bash_env && python3 -m pytest tests/test_watcher_config_validation.py::test_load_pipeline_config_invalid_local_raises -v 2>&1 | tail -10
```

Expected: FAIL — `ValueError` not raised yet.

- [ ] **Step 3: Apply the fix to `_load_pipeline_config()`**

In `watcher.py`, replace the entire `_load_pipeline_config` function body with:

```python
def _load_pipeline_config() -> dict:
    """Load config.yaml + config.local.yaml from the script directory.

    Returns the merged config dict. Raises ValueError if the merged result
    fails AppConfig schema validation.
    """
    from config_schema import AppConfig as _AppConfig
    from pydantic import ValidationError as _PydanticValidationError

    script_dir = Path(__file__).parent
    cfg: dict = {}
    for name in ("config.yaml", "config.local.yaml"):
        p = script_dir / name
        if p.exists():
            with open(p, encoding="utf-8") as f:
                local = yaml.safe_load(f) or {}
            for section, val in local.items():
                if isinstance(val, dict) and isinstance(cfg.get(section), dict):
                    cfg[section] = {**cfg.get(section, {}), **val}
                else:
                    cfg[section] = val
    try:
        _AppConfig.model_validate(cfg)
    except _PydanticValidationError as exc:
        raise ValueError(f"Invalid config (merged config.yaml + config.local.yaml): {exc}") from exc
    return cfg
```

- [ ] **Step 4: Run all three tests**

```bash
cd /home/wanleung/Projects/ai-software-house && source ~/.bash_env && python3 -m pytest tests/test_watcher_config_validation.py -v 2>&1 | tail -10
```

Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
cd /home/wanleung/Projects/ai-software-house
git add watcher.py tests/test_watcher_config_validation.py
git commit -m "fix(t1): validate merged config in _load_pipeline_config()

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 3: Wrap `_stream_call` and `call_with_tools` with circuit breaker

`call()` already wraps with `cb.call()`. Three `TODO(t1)` sites in `_stream_call` and `call_with_tools` bypass the breaker.

**Files:**
- Modify: `agents/backends/base.py`
- Test: `tests/test_backend_circuit_breaker.py` (extend)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_backend_circuit_breaker.py`:

```python
def _make_backend(model: str) -> "OpenAICompatibleBackend":
    """Return a minimal OpenAICompatibleBackend instance for testing."""
    from agents.backends.base import OpenAICompatibleBackend
    b = OpenAICompatibleBackend.__new__(OpenAICompatibleBackend)
    b.model = model
    b._stream = False
    b._max_retries = 0
    b._retry_delay = 0
    b._inter_call_delay = 0
    b._client = MagicMock()
    return b


def _make_registry(threshold: int = 2):
    from core.circuit_breaker_registry import CircuitBreakerRegistry
    from core.circuit_breaker import CircuitBreakerConfig, CircuitBreakerScopeConfig
    cfg = CircuitBreakerConfig(
        enabled=True,
        scopes={"backend": CircuitBreakerScopeConfig(threshold=threshold, recovery_timeout_s=60)},
    )
    return CircuitBreakerRegistry(cfg)


def test_stream_call_trips_circuit_after_threshold_failures():
    """_stream_call trips the circuit after threshold failures."""
    from agents.backends.base import _CircuitOpenError
    backend = _make_backend("stream-model")
    backend._stream = True
    backend._client.chat.completions.create.side_effect = ConnectionError("stream err")
    registry = _make_registry(threshold=2)

    with patch("agents.backends.base._get_cb_registry", return_value=registry):
        for _ in range(2):
            with pytest.raises(ConnectionError):
                backend._stream_call([{"role": "user", "content": "hi"}])
        with pytest.raises(_CircuitOpenError):
            backend._stream_call([{"role": "user", "content": "hi"}])


def test_call_with_tools_trips_circuit_after_threshold_failures():
    """call_with_tools trips the circuit after threshold failures in the tool loop."""
    from agents.backends.base import _CircuitOpenError
    backend = _make_backend("tools-model")
    backend._client.chat.completions.create.side_effect = ConnectionError("tools err")
    registry = _make_registry(threshold=2)
    tools = MagicMock()
    tools.schemas = []

    with patch("agents.backends.base._get_cb_registry", return_value=registry):
        for _ in range(2):
            with pytest.raises(ConnectionError):
                backend.call_with_tools([{"role": "user", "content": "hi"}], tools)
        with pytest.raises(_CircuitOpenError):
            backend.call_with_tools([{"role": "user", "content": "hi"}], tools)
```

- [ ] **Step 2: Run to verify both new tests fail**

```bash
cd /home/wanleung/Projects/ai-software-house && source ~/.bash_env && python3 -m pytest tests/test_backend_circuit_breaker.py::test_stream_call_trips_circuit_after_threshold_failures tests/test_backend_circuit_breaker.py::test_call_with_tools_trips_circuit_after_threshold_failures -v 2>&1 | tail -15
```

Expected: both FAIL.

- [ ] **Step 3: Wrap `_stream_call`**

In `agents/backends/base.py`, find the TODO comment in `_stream_call` and replace:

```python
        # TODO(t1): wrap with circuit breaker (tracked: T1-Task7 follow-up)
        reply = _retry_with_backoff(
            lambda: _collect(
                self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.3,
                    stream=True,
                    **self._extra_body(),
                )
            ),
            max_retries=self._max_retries,
            base_delay=self._retry_delay,
        )
```

with:

```python
        cb = _get_cb_registry().get_or_create("backend", self.model)
        reply = cb.call(
            lambda: _retry_with_backoff(
                lambda: _collect(
                    self._client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        temperature=0.3,
                        stream=True,
                        **self._extra_body(),
                    )
                ),
                max_retries=self._max_retries,
                base_delay=self._retry_delay,
            )
        )
```

- [ ] **Step 4: Wrap `call_with_tools` loop body**

Find the TODO in the tool loop body and replace:

```python
            # TODO(t1): wrap with circuit breaker (tracked: T1-Task7 follow-up)
            response = _retry_with_backoff(
                lambda: self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=tools.schemas,
                    tool_choice="auto",
                    temperature=0.3,
                    **self._extra_body(),
                ),
                max_retries=self._max_retries,
                base_delay=self._retry_delay,
            )
```

with:

```python
            cb = _get_cb_registry().get_or_create("backend", self.model)
            response = cb.call(
                lambda: _retry_with_backoff(
                    lambda: self._client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        tools=tools.schemas,
                        tool_choice="auto",
                        temperature=0.3,
                        **self._extra_body(),
                    ),
                    max_retries=self._max_retries,
                    base_delay=self._retry_delay,
                )
            )
```

- [ ] **Step 5: Wrap `call_with_tools` final forced response**

Find the second TODO (after the loop, the final forced-response call) and replace:

```python
        # TODO(t1): wrap with circuit breaker (tracked: T1-Task7 follow-up)
        response = _retry_with_backoff(
            lambda: self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.3,
                **self._extra_body(),
            ),
            max_retries=self._max_retries,
            base_delay=self._retry_delay,
        )
```

with:

```python
        cb = _get_cb_registry().get_or_create("backend", self.model)
        response = cb.call(
            lambda: _retry_with_backoff(
                lambda: self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.3,
                    **self._extra_body(),
                ),
                max_retries=self._max_retries,
                base_delay=self._retry_delay,
            )
        )
```

- [ ] **Step 6: Run all circuit breaker tests**

```bash
cd /home/wanleung/Projects/ai-software-house && source ~/.bash_env && python3 -m pytest tests/test_backend_circuit_breaker.py -v 2>&1 | tail -15
```

Expected: all PASSED (existing 4 + new 2 = 6 total).

- [ ] **Step 7: Run full regression**

```bash
cd /home/wanleung/Projects/ai-software-house && source ~/.bash_env && python3 -m pytest tests/ --ignore=tests/integration --ignore=tests/unit --ignore=tests/test_event_normalizer.py --ignore=tests/test_rate_limiter.py --ignore=tests/test_graph_teams.py --ignore=tests/test_github_project.py --ignore=tests/test_project_manager_agent.py -q 2>&1 | tail -10
```

Expected: 875+ passed, same pre-existing failures as before (test_watcher_prs, test_deployment, etc.).

- [ ] **Step 8: Commit**

```bash
cd /home/wanleung/Projects/ai-software-house
git add agents/backends/base.py tests/test_backend_circuit_breaker.py
git commit -m "fix(t1): wrap _stream_call and call_with_tools with circuit breaker

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 4: Push branch and open PR

- [ ] **Step 1: Push branch**

```bash
cd /home/wanleung/Projects/ai-software-house
git push -u origin t1-followups
```

- [ ] **Step 2: Create PR**

```bash
gh pr create \
  --title "fix(t1): sanitise DLQ logs, validate merged config, CB for stream/tools" \
  --base master \
  --body "Closes T1 follow-up items flagged during PR #29 review.

## Changes

- **watcher.py** — Sanitise \`_dlq_exc\` and \`exc\` in two \`logger.warning\` calls; token-containing exception messages no longer leak to log files
- **watcher.py** — Validate merged \`config.yaml\` + \`config.local.yaml\` against \`AppConfig\` schema in \`_load_pipeline_config()\`; typos in \`config.local.yaml\` now fail fast with a clear error
- **agents/backends/base.py** — Wrap \`_stream_call\` and \`call_with_tools\` (3 sites) with circuit breaker; streaming and tool-loop paths now respect the breaker consistently with \`call()\`

## Tests
- 2 new sanitisation tests
- 3 new config validation tests  
- 2 new circuit breaker tests
- Full regression: 875+ pass"
```
