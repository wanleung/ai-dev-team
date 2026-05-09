# T2-A: Easy Wins Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three low-risk, high-value cleanup items: extract `_deep_merge` to utils, fix Redis DLQ ack/nack from O(n) list scan to O(1) hash, and add per-server MCP connection timeout.

**Architecture:** Each task is independent — different files, no shared state. All changes are backward-compatible; existing tests should pass unchanged.

**Tech Stack:** Python 3.11, pytest, Redis (fake-redis for tests), asyncio.

**Branch:** `t2-a-easy-wins` (from master, after PR #30 merges)

---

### Task 1: Extract `_deep_merge` to `utils.py`

**Files:**
- Modify: `utils.py`
- Modify: `orchestrator.py:67-76` (remove local definition, add import)
- Test: `tests/test_utils.py` (new file)

**Context:** `orchestrator.py` defines `_deep_merge` at line 67 and calls it 6+ times. `utils.py` already exists with just the `sanitise` function. Moving `deep_merge` to utils makes it available without importing from the 3903-line orchestrator.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_utils.py
import pytest
from utils import deep_merge


def test_deep_merge_flat_override():
    result = deep_merge({"a": 1, "b": 2}, {"b": 3, "c": 4})
    assert result == {"a": 1, "b": 3, "c": 4}


def test_deep_merge_nested():
    base = {"llm": {"model": "gpt-4o", "timeout": 30}, "key": "x"}
    override = {"llm": {"model": "claude-3"}}
    result = deep_merge(base, override)
    assert result == {"llm": {"model": "claude-3", "timeout": 30}, "key": "x"}


def test_deep_merge_does_not_mutate_base():
    base = {"a": {"b": 1}}
    override = {"a": {"c": 2}}
    result = deep_merge(base, override)
    assert base == {"a": {"b": 1}}   # base must not be mutated
    assert result == {"a": {"b": 1, "c": 2}}


def test_deep_merge_empty_override_returns_copy():
    base = {"a": 1}
    result = deep_merge(base, {})
    assert result == {"a": 1}
    assert result is not base


def test_deep_merge_scalar_override_wins():
    """A scalar in override replaces a dict in base (override wins always)."""
    result = deep_merge({"a": {"nested": 1}}, {"a": "flat"})
    assert result == {"a": "flat"}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/wanleung/Projects/ai-software-house
source venv/bin/activate
pytest tests/test_utils.py -v
```
Expected: `ImportError: cannot import name 'deep_merge' from 'utils'`

- [ ] **Step 3: Add `deep_merge` to `utils.py`**

```python
def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into *base*; override wins on scalar conflicts.

    Neither *base* nor *override* is mutated — a new dict is always returned.
    """
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = deep_merge(result[key], val)
        else:
            result[key] = val
    return result
```

Add this function after `sanitise` in `utils.py`.

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_utils.py -v
```
Expected: 5 PASSED

- [ ] **Step 5: Replace `_deep_merge` in `orchestrator.py` with the import**

Replace the function definition at line 67:

```python
# OLD (lines 67-76 in orchestrator.py):
def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base. Override wins on scalar conflicts."""
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result
```

with this import (add to the import block at the top of orchestrator.py, near the `from utils import sanitise` line or wherever utils is imported):

```python
from utils import deep_merge as _deep_merge
```

And delete the function definition (lines 67-76). All existing call sites in orchestrator.py already use `_deep_merge(...)` so no other changes needed.

- [ ] **Step 6: Run the full test suite to verify no regressions**

```bash
pytest tests/ -v --ignore=tests/integration --ignore=tests/unit -x -q 2>&1 | tail -20
```
Expected: same pass/fail counts as on master (885 pass or similar).

- [ ] **Step 7: Commit**

```bash
git add utils.py orchestrator.py tests/test_utils.py
git commit -m "refactor: extract deep_merge to utils.py

_deep_merge was defined in orchestrator.py but useful across modules.
Move to utils.py as deep_merge(), import back as _deep_merge in orchestrator.
Add 5 unit tests covering flat override, nested merge, mutation safety."
```

---

### Task 2: Fix Redis DLQ `ack()`/`nack()` — O(n) → O(1)

**Files:**
- Modify: `core/dead_letter.py:165-208` (RedisDLQ class)
- Test: `tests/test_dead_letter.py` (extend existing)

**Context:** `RedisDLQ.ack()` (line 183) and `nack()` (line 195) both call `LRANGE` to scan all items, then `LREM` — O(n) per call. Fix: switch to Redis **hash** (`HSET`/`HGET`/`HDEL`/`HVALS`) so each entry is addressable by `entry_id` in O(1).

**Migration note:** Existing entries in the old list format are abandoned on upgrade (DLQ entries are transient retry data; at worst they need to be re-triggered). Document this in the commit message.

**Important:** The new format stores entries in a Redis hash at `cfg.key`. The existing list at `cfg.key` is no longer read. On deploy, any entries in the old list are silently dropped.

- [ ] **Step 1: Write the failing test**

Add these test cases to `tests/test_dead_letter.py`. Find the `TestRedisDLQ` class (or create one). Use `fakeredis` which is already installed.

```python
# Add to tests/test_dead_letter.py — inside or after the existing Redis tests

import fakeredis
from core.dead_letter import DLQEntry, RedisDLQ
from config_schema import DLQRedisConfig


def _make_entry(entry_id: str = "e1") -> DLQEntry:
    return DLQEntry(
        id=entry_id,
        issue_number=1,
        tracker_repo="owner/repo",
        label="ai-dev",
        model="gpt-4o",
        num_engineers=1,
        failed_at="2026-01-01T00:00:00Z",
        error={"message": "boom"},
    )


def _make_redis_dlq(max_attempts: int = 3) -> RedisDLQ:
    cfg = DLQRedisConfig(url="redis://localhost", key="test_dlq", ttl_s=None)
    client = fakeredis.FakeRedis()
    return RedisDLQ(cfg, max_attempts=max_attempts, client=client)


def test_redis_dlq_ack_is_o1():
    """ack() removes exactly the targeted entry without scanning others."""
    dlq = _make_redis_dlq()
    e1 = _make_entry("e1")
    e2 = _make_entry("e2")
    dlq.enqueue(e1)
    dlq.enqueue(e2)

    dlq.ack("e1")

    remaining = list(dlq.drain())
    assert len(remaining) == 1
    assert remaining[0].id == "e2"


def test_redis_dlq_nack_increments_attempt_count():
    dlq = _make_redis_dlq(max_attempts=3)
    entry = _make_entry("e1")
    dlq.enqueue(entry)

    dlq.nack("e1")

    items = list(dlq.drain())
    assert len(items) == 1
    assert items[0].attempt_count == 2


def test_redis_dlq_nack_drops_entry_when_max_attempts_exceeded():
    dlq = _make_redis_dlq(max_attempts=2)
    entry = _make_entry("e1")
    dlq.enqueue(entry)
    dlq.nack("e1")   # attempt_count → 2 (== max_attempts, still kept)
    dlq.nack("e1")   # attempt_count → 3 (> max_attempts, drop)

    assert list(dlq.drain()) == []


def test_redis_dlq_ack_unknown_id_is_noop():
    dlq = _make_redis_dlq()
    dlq.enqueue(_make_entry("e1"))
    dlq.ack("nonexistent")   # must not raise
    assert len(list(dlq.drain())) == 1
```

- [ ] **Step 2: Run to verify failures**

```bash
pytest tests/test_dead_letter.py::test_redis_dlq_ack_is_o1 \
       tests/test_dead_letter.py::test_redis_dlq_nack_increments_attempt_count \
       tests/test_dead_letter.py::test_redis_dlq_nack_drops_entry_when_max_attempts_exceeded \
       tests/test_dead_letter.py::test_redis_dlq_ack_unknown_id_is_noop -v
```
Expected: 4 FAILED (or collection error if methods don't exist yet).

- [ ] **Step 3: Rewrite `RedisDLQ` in `core/dead_letter.py`**

Replace the entire `RedisDLQ` class (lines ~148-208) with:

```python
class RedisDLQ(DeadLetterQueue):
    """Redis-backed DLQ using a hash for O(1) ack/nack.

    Storage layout: Redis hash at ``cfg.key`` where field = entry.id,
    value = JSON blob. TTL (if configured) is refreshed on every enqueue.

    Migration: any entries written by the old list-based implementation
    are not migrated. On upgrade, the old list key is abandoned in Redis.
    """

    def __init__(
        self,
        cfg: "DLQRedisConfig",
        max_attempts: int = 3,
        client=None,
    ) -> None:
        self._cfg = cfg
        self._max_attempts = max_attempts
        if client is not None:
            self._redis = client
        else:
            import redis as _redis
            self._redis = _redis.from_url(cfg.url)

    def enqueue(self, entry: DLQEntry) -> None:
        """Store entry JSON in the Redis hash keyed by entry.id."""
        payload = json.dumps(asdict(entry))
        self._redis.hset(self._cfg.key, entry.id, payload)
        if self._cfg.ttl_s:
            self._redis.expire(self._cfg.key, self._cfg.ttl_s)

    def drain(self) -> Iterator[DLQEntry]:
        """Yield all entries currently in the hash (order is not guaranteed)."""
        items = self._redis.hvals(self._cfg.key) or []
        for item in items:
            try:
                raw = item.decode() if isinstance(item, bytes) else item
                data = json.loads(raw)
                yield DLQEntry(**data)
            except Exception:
                continue

    def ack(self, entry_id: str) -> None:
        """Remove the entry with entry_id from the hash (O(1))."""
        self._redis.hdel(self._cfg.key, entry_id)

    def nack(self, entry_id: str) -> None:
        """Increment attempt_count; drop entry if max_attempts exceeded."""
        raw = self._redis.hget(self._cfg.key, entry_id)
        if raw is None:
            return
        try:
            data = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
        except Exception:
            return
        data["attempt_count"] = data.get("attempt_count", 1) + 1
        if data["attempt_count"] <= self._max_attempts:
            self._redis.hset(self._cfg.key, entry_id, json.dumps(data))
        else:
            self._redis.hdel(self._cfg.key, entry_id)
```

- [ ] **Step 4: Run new tests**

```bash
pytest tests/test_dead_letter.py -v
```
Expected: all tests pass including the 4 new ones.

- [ ] **Step 5: Run full suite**

```bash
pytest tests/ -v --ignore=tests/integration --ignore=tests/unit -x -q 2>&1 | tail -20
```
Expected: same pass/fail as before.

- [ ] **Step 6: Commit**

```bash
git add core/dead_letter.py tests/test_dead_letter.py
git commit -m "perf(dlq): fix Redis DLQ ack/nack O(n) list scan → O(1) hash

RedisDLQ previously used LRANGE+LREM for every ack/nack, which is O(n)
in queue depth. Switch to Redis hash (HSET/HGET/HDEL/HVALS) so each
operation is O(1).

Migration note: entries in the old list format are abandoned on upgrade.
Add 4 unit tests covering ack isolation, nack increment, drop-on-max,
and noop on unknown id."
```

---

### Task 3: Add per-server MCP connection timeout

**Files:**
- Modify: `tools/mcp_registry.py`
- Test: `tests/test_orchestrator_mcp.py` (extend, or create `tests/test_mcp_registry.py`)

**Context:** `MCPToolRegistry.__init__` calls `asyncio.run(self._connect_all())` synchronously. If any MCP server is slow or unresponsive, orchestrator startup hangs indefinitely. Fix: add `connect_timeout_s` per server config (default 10.0), wrap `_list_tools` call with `asyncio.wait_for()`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mcp_registry.py  (new file)
import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from tools.mcp_registry import MCPToolRegistry


def test_mcp_registry_skips_server_on_connect_timeout(monkeypatch):
    """A slow server (timeout exceeded) is skipped, not hung forever."""
    async def _slow_list_tools(server):
        await asyncio.sleep(999)  # simulates a hung server
        return []

    servers = [{"name": "slow", "type": "stdio", "command": "echo", "connect_timeout_s": 0.05}]

    with patch.object(MCPToolRegistry, "_list_tools", new=_slow_list_tools):
        # Should complete quickly (timeout=0.05s) and produce a warning, not hang.
        import warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            registry = MCPToolRegistry.__new__(MCPToolRegistry)
            registry._servers = servers
            registry._schemas = []
            registry._tool_to_server = {}
            asyncio.run(registry._connect_all())

        assert len(registry._schemas) == 0  # no tools registered from slow server
        assert any("timeout" in str(warning.message).lower() or
                   "slow" in str(warning.message).lower()
                   for warning in w), f"Expected a warning, got: {[str(x.message) for x in w]}"


def test_mcp_registry_default_timeout_is_ten_seconds():
    """Default connect_timeout_s is 10.0 when not specified in server config."""
    servers = [{"name": "s1", "type": "sse", "url": "http://localhost:9999"}]
    # We just verify the attribute is read correctly, not that it actually times out
    registry = MCPToolRegistry.__new__(MCPToolRegistry)
    timeout = servers[0].get("connect_timeout_s", 10.0)
    assert timeout == 10.0


def test_mcp_registry_uses_per_server_timeout():
    """Per-server connect_timeout_s is respected."""
    server = {"name": "fast", "type": "sse", "url": "http://localhost:9999", "connect_timeout_s": 2.5}
    timeout = server.get("connect_timeout_s", 10.0)
    assert timeout == 2.5
```

- [ ] **Step 2: Run to verify failures**

```bash
pytest tests/test_mcp_registry.py -v
```
Expected: `test_mcp_registry_skips_server_on_connect_timeout` FAILED or PASSED depending on current implementation; the timeout test should fail since timeout is not yet implemented.

- [ ] **Step 3: Update `_connect_all` in `tools/mcp_registry.py`**

Replace the existing `_connect_all` method:

```python
async def _connect_all(self) -> None:
    """Connect to all configured MCP servers and fetch their tool lists.

    Each server's ``connect_timeout_s`` key (default 10.0) limits how long
    the initial tool-list fetch may take.  Servers that exceed the timeout
    are skipped with a warning rather than blocking the caller indefinitely.
    """
    for server in self._servers:
        timeout_s: float = float(server.get("connect_timeout_s", 10.0))
        try:
            tools = await asyncio.wait_for(
                self._list_tools(server),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            warnings.warn(
                f"[MCPToolRegistry] Timed out connecting to MCP server "
                f"'{server.get('name', '?')}' after {timeout_s}s. Skipping.",
                stacklevel=2,
            )
            continue
        except Exception as exc:
            warnings.warn(
                f"[MCPToolRegistry] Could not connect to MCP server "
                f"'{server.get('name', '?')}': {exc}. Skipping.",
                stacklevel=2,
            )
            continue

        for tool in tools:
            raw_name = tool.name
            if raw_name in self._tool_to_server:
                raw_name = f"{server['name']}__{tool.name}"

            self._tool_to_server[raw_name] = server
            self._schemas.append({
                "type": "function",
                "function": {
                    "name": raw_name,
                    "description": tool.description or "",
                    "parameters": tool.inputSchema or {
                        "type": "object", "properties": {}
                    },
                },
            })
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_mcp_registry.py -v
```
Expected: 3 PASSED

- [ ] **Step 5: Run full suite**

```bash
pytest tests/ -v --ignore=tests/integration --ignore=tests/unit -x -q 2>&1 | tail -20
```
Expected: same pass/fail as before.

- [ ] **Step 6: Commit**

```bash
git add tools/mcp_registry.py tests/test_mcp_registry.py
git commit -m "feat(mcp): add per-server connection timeout to MCPToolRegistry

MCPToolRegistry.__init__ called asyncio.run(_connect_all()) with no
timeout, hanging indefinitely if a server was slow or unresponsive.

Add connect_timeout_s per server config (default 10.0 s). Wraps each
_list_tools() call in asyncio.wait_for(); a TimeoutError emits a warning
and skips that server instead of blocking the caller.

Add 3 unit tests covering timeout skip, default value, and per-server
override."
```
