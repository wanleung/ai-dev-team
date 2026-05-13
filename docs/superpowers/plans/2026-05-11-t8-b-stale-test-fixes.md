# T8-B: Stale Test Fixes + Code Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 4 categories of broken/stale tests (2 collection errors, 7 fixture errors, 6 live-server failures) and silence swallowed exceptions in documentation_agent.py, bringing the main test suite to fully green on all previously-excluded files.

**Architecture:** Pure test infrastructure + one conditional import fix + one logging improvement. No production logic changes. The kiota fix uses lazy import in `src/calendar_provider/__init__.py` to avoid pulling in the optional MS Graph SDK at collection time. TestClient conversion replaces live-socket tests with in-process FastAPI tests backed by an async SQLite database.

**Tech Stack:** Python 3.11, pytest, FastAPI TestClient, SQLAlchemy async + aiosqlite (SQLite in-memory for tests), pydantic-settings env override.

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `src/calendar_provider/__init__.py` | Modify | Make `OutlookCalendarProvider` import conditional so `kiota_abstractions` is not required at collection time |
| `tests/conftest.py` | Modify | Add 4 missing fixtures: `utc_now`, `future_time`, `sample_calendar`, `sample_event` |
| `tests/test_deployment.py` | Modify | Replace `httpx.Client(localhost)` fixture with FastAPI `TestClient(app)` + SQLite override |
| `agents/documentation_agent.py` | Modify | Add `logger.warning(...)` to the 4 bare `except Exception:` blocks |

---

## Task 1: Fix kiota_abstractions import (unblocks test_event_normalizer + test_rate_limiter)

**Root cause:** `src/calendar_provider/__init__.py` imports `OutlookCalendarProvider` unconditionally at module load, which pulls in `kiota_abstractions` (not installed). This cascades through `src/services/__init__.py` → `error_handler.py` → `google_provider.py` → `calendar_provider/__init__.py`, causing *any* test that imports `src.services.*` to fail at collection time.

**Files:**
- Modify: `src/calendar_provider/__init__.py`

- [ ] **Step 1: Confirm the 2 files fail to collect**

```bash
python3 -m pytest tests/test_event_normalizer.py tests/test_rate_limiter.py --collect-only -q 2>&1 | tail -10
```
Expected: `ERROR` with `ModuleNotFoundError: No module named 'kiota_abstractions'`

- [ ] **Step 2: Make OutlookCalendarProvider a lazy import**

Replace the direct import with a `try/except ImportError` guard so `kiota_abstractions` is only required when actually used:

Current `src/calendar_provider/__init__.py`:
```python
from src.calendar_provider.outlook_provider import OutlookCalendarProvider
```

Replace with:
```python
try:
    from src.calendar_provider.outlook_provider import OutlookCalendarProvider
    _outlook_available = True
except ImportError:
    _outlook_available = False
    OutlookCalendarProvider = None  # type: ignore[assignment,misc]
```

- [ ] **Step 3: Run the 2 previously-broken files**

```bash
python3 -m pytest tests/test_event_normalizer.py tests/test_rate_limiter.py -q --tb=short 2>&1
```
Expected: all tests PASS (no collection errors)

- [ ] **Step 4: Verify existing calendar provider tests still pass**

```bash
python3 -m pytest tests/ -k "calendar or provider or event_normalizer or rate_limiter" -q --tb=short 2>&1 | tail -5
```
Expected: PASS (no regressions)

- [ ] **Step 5: Commit**

```bash
git add src/calendar_provider/__init__.py
git commit -m "fix(calendar_provider): make OutlookCalendarProvider import conditional

kiota_abstractions (MS Graph SDK) is an optional dependency. Guard the
import so tests that don't use Outlook can still collect and run without
it installed."
```

---

## Task 2: Add missing pytest fixtures (unblocks 7 errors in test_models.py)

**Root cause:** `tests/test_models.py` uses `utc_now`, `future_time`, `sample_calendar`, and `sample_event` fixtures that are not defined anywhere — not in `tests/conftest.py` and not locally in the test file.

**Files:**
- Modify: `tests/conftest.py`

- [ ] **Step 1: Confirm the 7 fixture errors**

```bash
python3 -m pytest tests/test_models.py -q --tb=line 2>&1 | tail -15
```
Expected: 7× `fixture 'utc_now' not found` / `fixture 'sample_calendar' not found` etc.

- [ ] **Step 2: Add the 4 missing fixtures to tests/conftest.py**

Open `tests/conftest.py` and add these fixtures at the top of the file, after the existing imports:

```python
from datetime import datetime, timedelta, timezone

import pytest
from src.models.calendar import Calendar, Event, EventAttendee, EventReminder


# ---------------------------------------------------------------------------
# Calendar model fixtures (required by test_models.py)
# ---------------------------------------------------------------------------

@pytest.fixture
def utc_now() -> datetime:
    """Current time in UTC, frozen for the duration of a test."""
    return datetime.now(tz=timezone.utc)


@pytest.fixture
def future_time(utc_now: datetime) -> datetime:
    """One hour after utc_now."""
    return utc_now + timedelta(hours=1)


@pytest.fixture
def sample_calendar(utc_now: datetime) -> Calendar:
    """A fully-populated Calendar instance for model snapshot tests."""
    return Calendar(
        id="cal_123",
        name="Test Calendar",
        description="A sample calendar for tests",
        timezone="America/New_York",
        is_primary=True,
        access_role="owner",
        color="#4285F4",
    )


@pytest.fixture
def sample_event(utc_now: datetime, future_time: datetime) -> Event:
    """A fully-populated Event instance for model snapshot tests."""
    return Event(
        id="evt_123",
        calendar_id="cal_123",
        title="Test Event",
        description="A test event",
        location="Test Location",
        start=utc_now,
        end=future_time,
        timezone="America/New_York",
        created_at=utc_now,
        updated_at=utc_now,
        attendees=[
            EventAttendee(
                email="attendee@example.com",
                name="Test Attendee",
                response_status="accepted",
            )
        ],
        reminders=[EventReminder(method="popup", minutes_before=15)],
        status="confirmed",
        etag='"abc123"',
    )
```

- [ ] **Step 3: Verify test_models.py passes**

```bash
python3 -m pytest tests/test_models.py -q --tb=short 2>&1
```
Expected: all tests PASS (0 errors, 0 failures)

- [ ] **Step 4: Verify no regressions from the new fixtures**

```bash
python3 -m pytest tests/ --ignore=tests/test_deployment.py --ignore=tests/integration --ignore=tests/unit -q --tb=short 2>&1 | tail -5
```
Expected: same pass/fail as before (no new failures)

- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py
git commit -m "test(conftest): add missing utc_now, future_time, sample_calendar, sample_event fixtures

These fixtures are referenced in test_models.py but were never defined,
causing 7 fixture-not-found errors. Add them to conftest.py so all
calendar model tests can run."
```

---

## Task 3: Convert test_deployment.py to FastAPI TestClient (fixes 6 failures)

**Root cause:** `tests/test_deployment.py` hits a live `localhost:8000` socket. Nothing starts the server during `pytest`, so all tests requiring data (health, list_groups, create_group, list_notifications, create_notification) return 404 from httpx connection. The app is at `backend/main.py` and already supports SQLite via `settings.is_sqlite`. We override `DATABASE_URL` to SQLite in-memory for tests.

**Files:**
- Modify: `tests/test_deployment.py`

- [ ] **Step 1: Confirm current failures**

```bash
python3 -m pytest tests/test_deployment.py -q --tb=line 2>&1 | tail -10
```
Expected: 6 failed (health, list_groups, create_group, create_and_get_group, list_notifications, create_notification)

- [ ] **Step 2: Verify aiosqlite is installed**

```bash
python3 -c "import aiosqlite; print('aiosqlite OK')" 2>&1
```
Expected: `aiosqlite OK`

If not installed: `pip install aiosqlite`

- [ ] **Step 3: Replace test_deployment.py client fixture with TestClient**

Replace the entire file header (imports + `BASE_URL` + `client` fixture) with:

```python
"""Deployment smoke tests for Multi-Business Booking System."""

import sys
import os

import pytest

# Add backend/ to path so 'app.*' imports resolve
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

# Override DATABASE_URL before importing the app so SQLite is used in tests
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_deployment.db")

from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    """In-process FastAPI test client backed by a temporary SQLite database."""
    with TestClient(app) as c:
        yield c
```

Remove the line:
```python
BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")
```

Update all method signatures from `client: httpx.Client` to `client: TestClient`:
```python
def test_health_endpoint(self, client: TestClient):
def test_get_nonexistent_user_returns_404(self, client: TestClient):
# ... etc for all test methods
```

- [ ] **Step 4: Run test_deployment.py**

```bash
python3 -m pytest tests/test_deployment.py -q --tb=short 2>&1
```
Expected: all 11 tests PASS

- [ ] **Step 5: Clean up test database file**

```bash
rm -f test_deployment.db
echo "test_deployment.db" >> .gitignore
```

- [ ] **Step 6: Commit**

```bash
git add tests/test_deployment.py .gitignore
git commit -m "test(deployment): convert from live-server httpx to FastAPI TestClient

Replace httpx.Client(localhost:8000) with FastAPI TestClient(app) backed
by an in-process SQLite database. Tests now run in any environment
without needing a running server."
```

---

## Task 4: Fix silent exception swallowing in documentation_agent.py

**Root cause:** `agents/documentation_agent.py` has 4 `except Exception:` blocks that silently discard errors with a bare `pass`. This hides bugs in production and makes debugging impossible. Add structured logging to each.

**Files:**
- Modify: `agents/documentation_agent.py`

- [ ] **Step 1: Find all bare except Exception blocks**

```bash
grep -n "except Exception:" agents/documentation_agent.py
```
Expected: lines ~31, ~49, ~59, ~70

- [ ] **Step 2: Fix each except block to log the exception**

For each `except Exception:` block that currently has `pass`, replace with:

```python
except Exception as exc:
    logger.warning("operation skipped due to error", error=str(exc), exc_info=True)
```

**Block at line ~31** (`_detect_ref` fallback):
```python
        except Exception as exc:
            logger.warning("could not detect default branch", error=str(exc))
            return "main"
```

**Block at line ~49** (`_build_file_context` root listing fallback):
```python
        except Exception as exc:
            logger.warning("could not list repository root", error=str(exc))
```

**Block at line ~59** (`_build_file_context` auto-discover fallback):
```python
        except Exception as exc:
            logger.warning("could not auto-discover markdown files", error=str(exc))
            paths_to_read = []
```

**Block at line ~70** (`_build_file_context` per-file read fallback):
```python
            except Exception as exc:
                logger.warning("could not read file", path=path, error=str(exc))
```

- [ ] **Step 3: Verify logger is available in the file**

```bash
grep -n "^logger" agents/documentation_agent.py | head -3
```
Expected: `logger = structlog.get_logger()` or `logger = logging.getLogger(__name__)` already present.

If not present, add at module top (after imports):
```python
import structlog
logger = structlog.get_logger(__name__)
```

- [ ] **Step 4: Run documentation agent tests**

```bash
python3 -m pytest tests/ -k "documentation" -q --tb=short 2>&1 | tail -5
```
Expected: PASS (no regressions)

- [ ] **Step 5: Commit**

```bash
git add agents/documentation_agent.py
git commit -m "fix(documentation_agent): log swallowed exceptions instead of silencing them

Replace bare 'except Exception: pass' with structured logger.warning() calls
so errors in branch detection and file fetching are visible in logs without
crashing the agent."
```

---

## Task 5: Final verification

- [ ] **Step 1: Run all previously-excluded test files**

```bash
python3 -m pytest tests/test_event_normalizer.py tests/test_rate_limiter.py tests/test_models.py tests/test_deployment.py -q --tb=short 2>&1
```
Expected: all PASS, 0 failures

- [ ] **Step 2: Run full suite regression check**

```bash
python3 -m pytest tests/ --ignore=tests/integration --ignore=tests/unit -q --tb=short 2>&1 | tail -10
```
Expected: ≥1130 passing, only the pre-existing `test_qa_clarification.py` flakiness may appear (2 tests, order-dependent, not caused by T8-B)

- [ ] **Step 3: Clean up any stale test artifacts**

```bash
rm -f test_deployment.db
```

- [ ] **Step 4: Push branch and create PR**

```bash
git push -u origin t8-b-stale-test-fixes
gh pr create \
  --title "test(t8-b): fix stale test infrastructure (collection errors, missing fixtures, live-server tests)" \
  --body "## Summary
Fixes 4 categories of broken tests that were excluded from the CI run.

## Changes
- **src/calendar_provider/__init__.py**: Guard OutlookCalendarProvider import with try/except so kiota_abstractions (MS Graph SDK) is optional — unblocks test_event_normalizer.py and test_rate_limiter.py
- **tests/conftest.py**: Add utc_now, future_time, sample_calendar, sample_event fixtures — fixes 7 fixture-not-found errors in test_models.py
- **tests/test_deployment.py**: Replace live httpx.Client(localhost:8000) with FastAPI TestClient backed by SQLite in-memory — fixes 6 always-failing smoke tests
- **agents/documentation_agent.py**: Replace bare except Exception: pass with logger.warning() calls — improves observability without changing behaviour

## Test Results
All 4 previously-excluded test files now pass." \
  --base master
```
