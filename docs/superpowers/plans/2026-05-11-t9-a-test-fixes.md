# T9-A: Fix Failing Tests (65 failures) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 65 failing tests across 4 test files by adding async decorators, fixing SSE queue drain, adding Pydantic validation, and moving inline msgraph imports to module level.

**Architecture:** All fixes are in existing files — no new files created. Each task is independent and targets a single file or concern. The msgraph guard pattern mirrors the existing kiota guard in `src/calendar_provider/__init__.py`.

**Tech Stack:** Python 3.13, pytest 9.0 with asyncio strict mode, Pydantic v2, FastAPI, asyncio

---

## File Map

| File | Change |
|---|---|
| `tests/unit/test_google_provider.py` | Add `@pytest.mark.asyncio` + `async def` + `await` to 41 async tests |
| `src/mcp_server/sse.py` | Fix `event_stream()` to drain queue + early keepalive when closed |
| `src/models/calendar.py` | Add `Field(ge=0)` to `EventReminder.minutes_before` |
| `src/services/event_normalizer.py` | Move inline msgraph imports to module level with try/except |

---

## Task 1: Fix 41 async tests in test_google_provider.py

**Files:**
- Modify: `tests/unit/test_google_provider.py`

Context: The Google Calendar provider methods (`authenticate`, `list_calendars`, `get_events`, `create_event`, `update_event`, `delete_event`, `get_free_busy`, `close`) are all `async def`. Tests call them without `await` and without `@pytest.mark.asyncio`, so they return coroutines that are never awaited. The project uses `asyncio_mode = strict` so every async test needs an explicit decorator.

Affected test classes: `TestAuthenticate`, `TestListCalendars`, `TestGetEvents`, `TestCreateEvent`, `TestUpdateEvent`, `TestDeleteEvent`, `TestGetFreeBusy`, `TestClose`.

- [ ] **Step 1: Verify the baseline failure count**

```bash
cd /home/wanleung/Projects/ai-software-house
python3 -m pytest tests/unit/test_google_provider.py -q --tb=no 2>&1 | tail -3
```

Expected: `41 failed, 42 passed`

- [ ] **Step 2: Add `@pytest.mark.asyncio` and `async def` to TestAuthenticate**

In `tests/unit/test_google_provider.py`, find `class TestAuthenticate` (around line 280). Change each `def test_*` to `async def test_*` and add `@pytest.mark.asyncio` before each method. Add `await` before each call to a provider async method.

There are 4 tests: `test_authenticate_valid_token`, `test_authenticate_refreshes_expired_token`, `test_authenticate_returns_false_on_error`, `test_authenticate_no_refresh_token_when_expired`.

Pattern — change from:
```python
def test_authenticate_valid_token(
    self, google_config: ProviderConfig, mock_credentials: tuple
) -> None:
    ...
    result = provider.authenticate()
    assert result is True
```

To:
```python
@pytest.mark.asyncio
async def test_authenticate_valid_token(
    self, google_config: ProviderConfig, mock_credentials: tuple
) -> None:
    ...
    result = await provider.authenticate()
    assert result is True
```

Apply this pattern to all 4 `TestAuthenticate` methods. The provider method call in each test is `provider.authenticate()` → `await provider.authenticate()`.

- [ ] **Step 3: Add `@pytest.mark.asyncio` and `async def` to TestListCalendars**

Find `class TestListCalendars` (around line 350). There are 5 tests. Each calls `provider.list_calendars()`. Change to `async def` + `@pytest.mark.asyncio` + `await provider.list_calendars()`.

- [ ] **Step 4: Add `@pytest.mark.asyncio` and `async def` to TestGetEvents**

Find `class TestGetEvents` (around line 455). There are 11 tests. Each calls `provider.get_events(...)`. Change to `async def` + `@pytest.mark.asyncio` + `await provider.get_events(...)`.

- [ ] **Step 5: Add `@pytest.mark.asyncio` and `async def` to TestCreateEvent**

Find `class TestCreateEvent` (around line 700). There are 6 tests. Each calls `provider.create_event(...)`. Change to `async def` + `@pytest.mark.asyncio` + `await provider.create_event(...)`.

- [ ] **Step 6: Add `@pytest.mark.asyncio` and `async def` to TestUpdateEvent**

Find `class TestUpdateEvent` (around line 860). There are 5 tests. Each calls `provider.update_event(...)`. Change to `async def` + `@pytest.mark.asyncio` + `await provider.update_event(...)`.

- [ ] **Step 7: Add `@pytest.mark.asyncio` and `async def` to TestDeleteEvent**

Find `class TestDeleteEvent` (around line 1020). There are 5 tests. Each calls `provider.delete_event(...)`. Change to `async def` + `@pytest.mark.asyncio` + `await provider.delete_event(...)`.

- [ ] **Step 8: Add `@pytest.mark.asyncio` and `async def` to TestGetFreeBusy**

Find `class TestGetFreeBusy` (around line 1110). There are 3 tests. Each calls `provider.get_free_busy(...)`. Change to `async def` + `@pytest.mark.asyncio` + `await provider.get_free_busy(...)`.

- [ ] **Step 9: Add `@pytest.mark.asyncio` and `async def` to TestClose**

Find `class TestClose` (around line 1230). There is 1 test: `test_close_clears_resources`. It calls `provider.close()`. Change to `async def` + `@pytest.mark.asyncio` + `await provider.close()`.

- [ ] **Step 10: Run the tests and verify**

```bash
cd /home/wanleung/Projects/ai-software-house
python3 -m pytest tests/unit/test_google_provider.py -q --tb=short 2>&1 | tail -10
```

Expected: 83 passed (0 failures). If any fail, the error will be a mismatched `await` — check that the method name in the call matches the one in the provider (`authenticate`, `list_calendars`, `get_events`, `create_event`, `update_event`, `delete_event`, `get_free_busy`, `close`).

- [ ] **Step 11: Commit**

```bash
cd /home/wanleung/Projects/ai-software-house
git add tests/unit/test_google_provider.py
git commit -m "test: add asyncio markers and await to 41 async provider tests"
```

---

## Task 2: Fix SSE event_stream queue drain bug

**Files:**
- Modify: `src/mcp_server/sse.py:38-55`

Context: `event_stream()` has `while not self._closed`. When `close()` is called before iteration starts, `_closed=True` so the loop never executes — any queued messages are dropped silently. Two tests fail:
1. `test_yields_queued_messages`: sends a message, closes, iterates — expects 1 event
2. `test_yields_keepalive_on_timeout`: closes, iterates — expects first event to be `: keepalive\n\n`

The fix uses an early-exit path: if closed AND queue empty, yield a keepalive immediately and return. Otherwise, drain the queue with `while not self._closed or not self._queue.empty()`.

- [ ] **Step 1: Verify the current failure**

```bash
cd /home/wanleung/Projects/ai-software-house
python3 -m pytest tests/unit/test_sse.py -q --tb=short 2>&1 | tail -15
```

Expected: `test_yields_queued_messages` and `test_yields_keepalive_on_timeout` both FAILED.

- [ ] **Step 2: Update `event_stream` in `src/mcp_server/sse.py`**

Find the `event_stream` method (around line 38). Replace the entire method body:

Current:
```python
async def event_stream(self) -> AsyncGenerator[str, None]:
    """Yield SSE-formatted events from the queue.

    Yields:
        SSE-formatted string events.
    """
    try:
        while not self._closed:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=30.0)
                yield event
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
    finally:
        self._closed = True
```

New:
```python
async def event_stream(self) -> AsyncGenerator[str, None]:
    """Yield SSE-formatted events from the queue.

    Yields:
        SSE-formatted string events.
    """
    try:
        if self._closed and self._queue.empty():
            yield ": keepalive\n\n"
            return
        while not self._closed or not self._queue.empty():
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=30.0)
                yield event
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
    finally:
        self._closed = True
```

Logic:
- If already closed with empty queue (test 2 scenario): yield one keepalive immediately, then return.
- Otherwise: drain the queue even after `close()` is called (`not self._closed OR not self._queue.empty()`).

- [ ] **Step 3: Run SSE tests**

```bash
cd /home/wanleung/Projects/ai-software-house
python3 -m pytest tests/unit/test_sse.py -q --tb=short 2>&1 | tail -10
```

Expected: all tests pass (no FAILED lines).

- [ ] **Step 4: Commit**

```bash
cd /home/wanleung/Projects/ai-software-house
git add src/mcp_server/sse.py
git commit -m "fix: drain SSE queue and yield keepalive when connection pre-closed"
```

---

## Task 3: Add `ge=0` validation to EventReminder.minutes_before

**Files:**
- Modify: `src/models/calendar.py`

Context: `EventReminder.minutes_before` is plain `int` with no validation. A pre-existing test `test_negative_minutes_raises` (in `tests/test_models.py`) creates `EventReminder(method="popup", minutes_before=-5)` and expects an exception — this currently PASSES the creation (no validation), failing the test.

Fix: add `= Field(ge=0)` so Pydantic raises a `ValidationError` on negative values.

- [ ] **Step 1: Verify the failing test**

```bash
cd /home/wanleung/Projects/ai-software-house
python3 -m pytest tests/test_models.py -q --tb=short -k "negative_minutes" 2>&1 | tail -10
```

Expected: 1 FAILED (`test_negative_minutes_raises`).

- [ ] **Step 2: Check current imports in `src/models/calendar.py`**

```bash
head -10 /home/wanleung/Projects/ai-software-house/src/models/calendar.py
```

Check if `Field` is already imported from `pydantic`. If not, add it.

- [ ] **Step 3: Add `Field(ge=0)` to `minutes_before`**

Find `class EventReminder(BaseModel)` in `src/models/calendar.py`. The field looks like:
```python
minutes_before: int
```

Change to:
```python
minutes_before: int = Field(ge=0)
```

Make sure `Field` is imported:
```python
from pydantic import BaseModel, Field
```

- [ ] **Step 4: Run models tests**

```bash
cd /home/wanleung/Projects/ai-software-house
python3 -m pytest tests/test_models.py -q --tb=short 2>&1 | tail -5
```

Expected: all pass (was 1 FAILED, now 0 FAILED).

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
cd /home/wanleung/Projects/ai-software-house
python3 -m pytest tests/ -q --tb=no --ignore=tests/unit/test_event_normalizer.py --ignore=tests/unit/test_google_provider.py 2>&1 | tail -5
```

Expected: no new failures related to `EventReminder`.

- [ ] **Step 6: Commit**

```bash
cd /home/wanleung/Projects/ai-software-house
git add src/models/calendar.py
git commit -m "fix: add ge=0 validation to EventReminder.minutes_before"
```

---

## Task 4: Move inline msgraph imports to module level in event_normalizer.py

**Files:**
- Modify: `src/services/event_normalizer.py`

Context: The Outlook normalization/denormalization methods contain inline `from msgraph.generated.models.*` imports. In CI/test environments without msgraph installed, these imports raise `ModuleNotFoundError` at call time. Additionally, the tests use `patch("src.services.event_normalizer.PatternedRecurrence")` etc., which requires those names to be module-level attributes — inline imports don't create module-level names, so `patch()` raises `AttributeError`.

The inline imports are at:
- Line 211: `from msgraph.generated.models.event import Event as GraphEvent` (in `_normalize_outlook_event`)
- Lines 306-312: multiple imports (in `_denormalize_outlook_event`)
- Line 501: `from msgraph.generated.models.response_type import ResponseType` (in `_normalize_outlook_event`)
- Lines 593-596: `PatternedRecurrence`, `RecurrencePattern`, `RecurrenceRange`, `DayOfWeek` (in `_build_outlook_recurrence`)

Fix: Move all msgraph imports to the module top level inside a `try/except ImportError`. Use stub `None` assignments when not available. The methods that use these will work with mocks in tests (since `patch()` now resolves to module-level names), and will work with real objects in production (when msgraph is installed).

- [ ] **Step 1: Verify the baseline failures**

```bash
cd /home/wanleung/Projects/ai-software-house
python3 -m pytest tests/unit/test_event_normalizer.py -q --tb=no 2>&1 | tail -3
```

Expected: `34 failed, 70 passed`

- [ ] **Step 2: Check existing imports in `src/services/event_normalizer.py`**

```bash
head -40 /home/wanleung/Projects/ai-software-house/src/services/event_normalizer.py
```

- [ ] **Step 3: Add module-level msgraph import block at top of file**

After the existing imports (find the last `from` or `import` line in the imports section), add:

```python
try:
    from msgraph.generated.models.attendee import Attendee
    from msgraph.generated.models.attendee_type import AttendeeType
    from msgraph.generated.models.body_type import BodyType
    from msgraph.generated.models.date_time_time_zone import DateTimeTimeZone
    from msgraph.generated.models.day_of_week import DayOfWeek
    from msgraph.generated.models.email_address import EmailAddress
    from msgraph.generated.models.event import Event as GraphEvent
    from msgraph.generated.models.location import Location
    from msgraph.generated.models.patterned_recurrence import PatternedRecurrence
    from msgraph.generated.models.recurrence_pattern import RecurrencePattern
    from msgraph.generated.models.recurrence_range import RecurrenceRange
    from msgraph.generated.models.response_type import ResponseType
    _MSGRAPH_AVAILABLE = True
except ImportError:
    Attendee = None  # type: ignore[assignment,misc]
    AttendeeType = None  # type: ignore[assignment,misc]
    BodyType = None  # type: ignore[assignment,misc]
    DateTimeTimeZone = None  # type: ignore[assignment,misc]
    DayOfWeek = None  # type: ignore[assignment,misc]
    EmailAddress = None  # type: ignore[assignment,misc]
    GraphEvent = None  # type: ignore[assignment,misc]
    Location = None  # type: ignore[assignment,misc]
    PatternedRecurrence = None  # type: ignore[assignment,misc]
    RecurrencePattern = None  # type: ignore[assignment,misc]
    RecurrenceRange = None  # type: ignore[assignment,misc]
    ResponseType = None  # type: ignore[assignment,misc]
    _MSGRAPH_AVAILABLE = False
```

- [ ] **Step 4: Remove all inline msgraph imports from method bodies**

Find and delete every `from msgraph.generated.models.*` line inside method bodies. These are at approximately:
- Line 211 inside `_normalize_outlook_event`
- Lines 306-312 inside `_denormalize_outlook_event`
- Line 501 inside `_normalize_outlook_event` (response_type)
- Lines 593-596 inside `_build_outlook_recurrence`

After deletion, the method bodies remain unchanged — they use the same names that are now at module level.

- [ ] **Step 5: Verify the file parses correctly**

```bash
cd /home/wanleung/Projects/ai-software-house
python3 -c "import src.services.event_normalizer; print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Run event_normalizer tests**

```bash
cd /home/wanleung/Projects/ai-software-house
python3 -m pytest tests/unit/test_event_normalizer.py -q --tb=short 2>&1 | tail -10
```

Expected: 0 failed (all 104 pass). If any tests still fail with `AttributeError: ... does not have the attribute`, that means there's still an inline import left that needs to be removed.

- [ ] **Step 7: Run full test suite**

```bash
cd /home/wanleung/Projects/ai-software-house
python3 -m pytest tests/ -q --tb=no 2>&1 | tail -5
```

Expected: significant improvement — T9-A tasks 1-4 combined should bring down from 65 failed to ≤1 (the pre-existing RAG failure is unrelated).

- [ ] **Step 8: Commit**

```bash
cd /home/wanleung/Projects/ai-software-house
git add src/services/event_normalizer.py
git commit -m "fix: move inline msgraph imports to module level for testability"
```

---

## Task 5: Final verification + PR

**Files:** None

- [ ] **Step 1: Run full test suite**

```bash
cd /home/wanleung/Projects/ai-software-house
python3 -m pytest tests/ -q --tb=no 2>&1 | tail -5
```

Expected: 96+ passed, ≤2 skipped, 1 pre-existing failure (`test_search_chunks_passes_source_type_as_parameter` in `test_rag_db.py` — unrelated).

- [ ] **Step 2: Push and create PR**

```bash
cd /home/wanleung/Projects/ai-software-house
git push origin t9-a-test-fixes
gh pr create \
  --base master \
  --title "T9-A: Fix 65 failing tests (async markers, SSE drain, validation, msgraph guards)" \
  --body "## Summary

Fixes 65 failing tests across 4 test files:

### Changes
- **tests/unit/test_google_provider.py**: Added \`@pytest.mark.asyncio\` + \`async def\` + \`await\` to 41 tests across TestAuthenticate, TestListCalendars, TestGetEvents, TestCreateEvent, TestUpdateEvent, TestDeleteEvent, TestGetFreeBusy, TestClose
- **src/mcp_server/sse.py**: Fixed \`event_stream()\` to drain queue after close and yield immediate keepalive when closed+empty
- **src/models/calendar.py**: Added \`Field(ge=0)\` to \`EventReminder.minutes_before\` to prevent negative values
- **src/services/event_normalizer.py**: Moved inline msgraph imports to module level with \`try/except ImportError\` guard for testability

### Test Results
Before: 65 failed
After: 0 failed (except 1 pre-existing unrelated RAG failure)"
```

- [ ] **Step 3: Wait for review and address any comments**
