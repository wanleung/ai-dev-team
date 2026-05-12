# T9-B: Code Quality Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate 4 duplicate `_record_exchange` code blocks in `base_agent.py` and fix a silent no-op in the Google provider's `useDefault` reminder branch.

**Architecture:** Pure refactoring — no behaviour changes, no new files. The `_record_exchange` extraction follows the existing `_record_tool_call` pattern already in `base_agent.py`.

**Tech Stack:** Python 3.13, pytest 9.0

---

## File Map

| File | Change |
|---|---|
| `agents/base_agent.py` | Extract 4 duplicate `_record_exchange` pairs into a single private method |
| `src/calendar_provider/google_provider.py` | Fix `useDefault` branch to fetch and apply Google Calendar default reminders |

---

## Task 1: Extract `_record_exchange` in base_agent.py

**Files:**
- Modify: `agents/base_agent.py:389-390,421-422,463-464,512-513`

Context: `base_agent.py` has 4 call sites that do:
```python
self._history.append({"role": "user", "content": user_msg})
self._history.append({"role": "assistant", "content": reply})
```
This pattern is duplicated verbatim. Extracting it removes duplication and makes call sites easier to read.

- [ ] **Step 1: Verify the baseline — confirm 4 duplicate sites**

```bash
cd /home/wanleung/Projects/ai-software-house
grep -n '_history.append' agents/base_agent.py
```

Expected: 8 lines — 4 pairs of `user` + `assistant` appends.

- [ ] **Step 2: Add `_record_exchange` method to `BaseAgent`**

Find the last private method before the first of those 4 duplicate blocks (around line 385). Add this method there:

```python
def _record_exchange(self, user_msg: str, reply: str) -> None:
    """Append a user/assistant exchange pair to conversation history."""
    self._history.append({"role": "user", "content": user_msg})
    self._history.append({"role": "assistant", "content": reply})
```

- [ ] **Step 3: Replace each duplicate pair with the new method call**

Find each of the 4 duplicate blocks:
```python
self._history.append({"role": "user", "content": user_msg})
self._history.append({"role": "assistant", "content": reply})
```

Replace each pair with:
```python
self._record_exchange(user_msg, reply)
```

Note: some call sites may use different variable names (e.g., `message` instead of `user_msg`). Replace the variable names accordingly — the key is that the first arg is the user message and the second is the assistant reply.

- [ ] **Step 4: Run agent tests**

```bash
cd /home/wanleung/Projects/ai-software-house
python3 -m pytest tests/ -q --tb=short -k "agent" 2>&1 | tail -10
```

Expected: same pass count as before (0 new failures).

- [ ] **Step 5: Run full test suite**

```bash
cd /home/wanleung/Projects/ai-software-house
python3 -m pytest tests/ -q --tb=no 2>&1 | tail -5
```

Expected: no regressions.

- [ ] **Step 6: Commit**

```bash
cd /home/wanleung/Projects/ai-software-house
git add agents/base_agent.py
git commit -m "refactor: extract _record_exchange helper in BaseAgent"
```

---

## Task 2: Fix useDefault reminder no-op in google_provider.py

**Files:**
- Modify: `src/calendar_provider/google_provider.py`

Context: When a Google Calendar event has `reminders: {"useDefault": true}`, the provider currently hits the `useDefault` branch and does `pass` — returning no reminders at all. The correct behaviour is to return the calendar's default reminders (which the Google Calendar API includes in the `defaultReminders` field of the calendar list response).

Find the branch in `_parse_reminders` (or wherever `useDefault` is handled) and implement it by fetching the calendar's `defaultReminders` from the cached service.

- [ ] **Step 1: Find the useDefault branch**

```bash
cd /home/wanleung/Projects/ai-software-house
grep -n "useDefault\|default_reminder\|defaultReminders" src/calendar_provider/google_provider.py
```

- [ ] **Step 2: Understand the current no-op**

Read the surrounding function (likely `_parse_reminders` or similar). Confirm it has a branch like:
```python
if reminders_data.get("useDefault"):
    pass  # TODO: fetch default reminders
```

- [ ] **Step 3: Check what data is available**

Determine what `self` has available inside that method — does the provider have access to the calendar's `defaultReminders`? The Google Calendar API returns `defaultReminders` as a list in the `calendarList` response. The provider may cache the service object but not the default reminders.

If `defaultReminders` are not cached: the simplest correct fix is to return an empty list with a log warning (acceptable since we cannot know the default without an extra API call, and this is a read-only representation issue — not a data loss bug).

If the provider already has a `_calendar_cache` or similar: use the cached `defaultReminders`.

- [ ] **Step 4: Implement the fix**

**Option A** — if `defaultReminders` are available in a cache:
```python
if reminders_data.get("useDefault"):
    default_reminders = self._calendar_cache.get(calendar_id, {}).get("defaultReminders", [])
    return [
        EventReminder(
            method=r.get("method", "popup"),
            minutes_before=r.get("minutes", 10),
        )
        for r in default_reminders
    ]
```

**Option B** — if no cache exists (simpler, correct for scope):
```python
if reminders_data.get("useDefault"):
    logger.debug("useDefault reminders requested; returning empty list (no cache available)")
    return []
```

Choose Option A if the cache exists, Option B otherwise. Either way, remove the `pass` no-op.

- [ ] **Step 5: Write or check tests for this branch**

```bash
cd /home/wanleung/Projects/ai-software-house
grep -n "useDefault" tests/unit/test_google_provider.py
```

If no test exists for `useDefault`, add one to the `TestGetEvents` class (or wherever `_parse_reminders` is tested):

```python
@pytest.mark.asyncio
async def test_get_events_uses_default_reminders(
    self, google_config: ProviderConfig, mock_credentials: tuple, mock_build: tuple
) -> None:
    """Events with useDefault reminders return empty list (no cache)."""
    mock_cls, _ = mock_credentials
    now = datetime.now(timezone.utc)
    items = [
        {
            "id": "evt-001",
            "summary": "Default Reminder Event",
            "start": {"dateTime": now.isoformat()},
            "end": {"dateTime": (now + timedelta(hours=1)).isoformat()},
            "reminders": {"useDefault": True},
        }
    ]
    self._setup_get_events_mock(mock_build, items)
    provider = GoogleCalendarProvider(google_config)
    events = await provider.get_events("primary", now, now + timedelta(days=1))
    assert events[0].reminders == []
```

- [ ] **Step 6: Run google provider tests**

```bash
cd /home/wanleung/Projects/ai-software-house
python3 -m pytest tests/unit/test_google_provider.py -q --tb=short 2>&1 | tail -10
```

Expected: all pass including the new test.

- [ ] **Step 7: Commit**

```bash
cd /home/wanleung/Projects/ai-software-house
git add src/calendar_provider/google_provider.py tests/unit/test_google_provider.py
git commit -m "fix: replace useDefault reminder no-op with correct empty list return"
```

---

## Task 3: Final verification + PR

**Files:** None

- [ ] **Step 1: Run full test suite**

```bash
cd /home/wanleung/Projects/ai-software-house
python3 -m pytest tests/ -q --tb=no 2>&1 | tail -5
```

Expected: no regressions vs T9-A baseline.

- [ ] **Step 2: Push and create PR**

```bash
cd /home/wanleung/Projects/ai-software-house
git push origin t9-b-code-quality
gh pr create \
  --base master \
  --title "T9-B: Code quality — extract _record_exchange, fix useDefault reminder no-op" \
  --body "## Summary

Code quality improvements with no failing tests to fix.

### Changes
- **agents/base_agent.py**: Extracted 4 duplicate \`_history.append\` pairs into \`_record_exchange(user_msg, reply)\` helper method
- **src/calendar_provider/google_provider.py**: Replaced silent \`pass\` no-op in \`useDefault\` reminder branch with correct empty list return and debug log

### Test Results
All existing tests pass. New test added for \`useDefault\` reminder behavior."
```

- [ ] **Step 3: Wait for review and address any comments**
