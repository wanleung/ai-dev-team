# Fix Conftest + Wire TDDReviewerAgent into Revise Mode

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the broken conftest in the cue-test PR #3, then wire TDDReviewerAgent into the revise-mode pipeline so the same bug can't recur.

**Architecture:**
- Task 1 directly fixes `tests/conftest.py` in the workspace (and commits to the PR branch) — replacing the broken `patch(get_db)` pattern with FastAPI's `dependency_overrides`.
- Task 2 modifies `orchestrator.py`'s `_revision_run_reviewer_and_qa()` to call `self.tdd_reviewer.run()` after QA generates test files — same pattern as the existing build-mode stage.
- Task 3 updates `roles/tdd_reviewer.md` so the LLM knows the correct FastAPI dependency-injection mocking pattern, preventing the bug in future runs.

**Tech Stack:** Python 3.13, FastAPI, pytest, SQLAlchemy async, `unittest.mock`, ai-software-house orchestrator.

---

## Task 1: Fix `tests/conftest.py` in the PR branch

**Files:**
- Modify: `workspace/project_cue__hong_kong_snooker_community_app_/tests/conftest.py`

The bug: `client` fixture patches `app.dependencies.get_db` using `unittest.mock.patch`, but `app.main` is imported *inside* the `with patch(...)` block for the first time. The router then captures the `MagicMock` as `get_db`. FastAPI inspects `MagicMock`'s signature → finds `args`/`kwargs` as required query params → every test returns 422.

The fix: use FastAPI's `app.dependency_overrides` instead of `patch`.

Also: `sample_user_obj` fixture is missing `status` and `firebase_uid` fields, causing `AttributeError: MockModel has no attribute 'status'` in `_check_user_status`.

- [ ] **Step 1: Verify the current failure locally**

```bash
cd /home/wanleung/Projects/ai-software-house/workspace/project_cue__hong_kong_snooker_community_app_
python -m pytest tests/test_auth.py::TestOAuthGoogleSuccess::test_google_oauth_returns_tokens_and_user -v --tb=short 2>&1 | tail -20
```

Expected: FAIL with `assert 422 == 200`

- [ ] **Step 2: Rewrite `tests/conftest.py` with the correct fixture**

Replace the full `tests/conftest.py` with:

```python
"""
Shared fixtures for Project Cue backend tests.
Provides mock DB session, test client, authenticated user helpers,
and reusable test data factories.
"""
import pytest
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, AsyncMock, patch


# ---------------------------------------------------------------------------
# MockModel — attribute-access dict wrapper for ORM-like mocks
# ---------------------------------------------------------------------------

class MockModel:
    """Lightweight mock that supports both attribute access and dict-style
    construction, so test fixtures can build mock ORM objects from dicts.

    Usage::

        m = MockModel(id="abc", name="test")
        assert m.id == "abc"
        assert m.name == "test"
    """

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

    def __repr__(self):
        attrs = ", ".join(f"{k}={v!r}" for k, v in self.__dict__.items())
        return f"MockModel({attrs})"


# ---------------------------------------------------------------------------
# Mock database session
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_db():
    """Yields a MagicMock simulating a SQLAlchemy async session."""
    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.delete = AsyncMock()
    session.flush = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# FastAPI TestClient — overrides DB dependency via dependency_overrides
# ---------------------------------------------------------------------------

@pytest.fixture
def client(mock_db):
    """
    Returns a FastAPI TestClient with the DB dependency properly overridden.
    Uses app.dependency_overrides — the correct FastAPI pattern.
    patch() must NOT be used for Depends() since the router captures the
    function reference at import time; patch only replaces the module attr.
    """
    import sys
    import os
    # Ensure backend is importable
    backend_path = os.path.join(os.path.dirname(__file__), "..", "backend")
    if backend_path not in sys.path:
        sys.path.insert(0, os.path.abspath(backend_path))

    from fastapi.testclient import TestClient
    from app.main import app
    from app.dependencies import get_db, get_current_user

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def authed_client(mock_db, sample_user_obj):
    """
    Returns a TestClient where get_current_user is also overridden,
    for routes that require authentication.
    """
    import sys
    import os
    backend_path = os.path.join(os.path.dirname(__file__), "..", "backend")
    if backend_path not in sys.path:
        sys.path.insert(0, os.path.abspath(backend_path))

    from fastapi.testclient import TestClient
    from app.main import app
    from app.dependencies import get_db, get_current_user

    mock_user = MockModel(**sample_user_obj)

    async def override_get_db():
        yield mock_db

    async def override_get_current_user():
        return mock_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)


# ---------------------------------------------------------------------------
# Authenticated user helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_user_id():
    return str(uuid.uuid4())


@pytest.fixture
def sample_user_obj(sample_user_id):
    """A dict representing a standard authenticated user."""
    return {
        "id": uuid.UUID(sample_user_id),
        "email": "player@example.com",
        "display_name": "TestPlayer",
        "profile_completed": False,
        "role": "player",
        "status": "active",
        "firebase_uid": "google-123456",
        "oauth_provider": "google",
        "oauth_provider_id": "google-123456",
    }


@pytest.fixture
def auth_headers(sample_user_id):
    """Authorization headers for a standard user."""
    return {"Authorization": f"Bearer test-token-{sample_user_id}"}


@pytest.fixture
def admin_user_id():
    return str(uuid.uuid4())


@pytest.fixture
def admin_user_obj(admin_user_id):
    """A dict representing an admin user."""
    return {
        "id": uuid.UUID(admin_user_id),
        "email": "admin@example.com",
        "display_name": "AdminUser",
        "profile_completed": True,
        "role": "admin",
        "status": "active",
        "firebase_uid": "admin-firebase-uid",
    }


@pytest.fixture
def admin_headers(admin_user_id):
    """Authorization headers for an admin user."""
    return {"Authorization": f"Bearer admin-token-{admin_user_id}"}


# ---------------------------------------------------------------------------
# Profile / Onboarding data
# ---------------------------------------------------------------------------

@pytest.fixture
def onboarding_data():
    return {
        "gender": "male",
        "age_range": "25-34",
        "play_area": "Yau Tsim Mong",
        "years_playing": "3-5",
    }


@pytest.fixture
def incomplete_onboarding_data():
    return {
        "gender": "male",
        "age_range": "25-34",
    }


# ---------------------------------------------------------------------------
# Marketplace / Listing data
# ---------------------------------------------------------------------------

@pytest.fixture
def listing_data():
    """A dict representing a valid listing creation payload."""
    return {
        "title": "Predator SP2 黑色球桿",
        "description": "九成新，買咗半年",
        "item_type": "cue",
        "brand": "Predator",
        "condition": "like_new",
        "price": 120000,
        "length_inches": 57,
        "weight_oz": 18.5,
        "tip_diameter_mm": 11.5,
        "image_urls": ["https://s3.example.com/img1.jpg"],
    }


@pytest.fixture
def sample_listing_id():
    return str(uuid.uuid4())


@pytest.fixture
def sample_listing_obj(sample_listing_id, sample_user_id):
    """A dict representing a sample listing."""
    now = datetime.now(timezone.utc)
    return {
        "id": sample_listing_id,
        "seller_id": sample_user_id,
        "title": "Predator SP2 黑色球桿",
        "description": "九成新",
        "item_type": "cue",
        "brand": "Predator",
        "condition": "like_new",
        "price_cents": 120000,
        "length_inches": 57,
        "weight_oz": 18.5,
        "tip_diameter_mm": 11.5,
        "image_urls": ["https://s3.example.com/img1.jpg"],
        "status": "pending_approval",
        "report_count": 0,
        "created_at": now,
        "updated_at": now,
    }


@pytest.fixture
def sample_report_data():
    """A dict representing a report submission payload."""
    return {
        "reason": "inappropriate",
        "description": "疑似假冒產品",
    }
```

- [ ] **Step 3: Run auth tests to verify fix**

```bash
cd /home/wanleung/Projects/ai-software-house/workspace/project_cue__hong_kong_snooker_community_app_
python -m pytest tests/test_auth.py -v --tb=short 2>&1 | tail -30
```

Expected: auth tests now get past 422. May still have failures, but they should be meaningful (e.g., missing mock setup in individual tests), not the systemic 422.

- [ ] **Step 4: Run full test suite and note remaining failures**

```bash
cd /home/wanleung/Projects/ai-software-house/workspace/project_cue__hong_kong_snooker_community_app_
python -m pytest tests/ -q --tb=line 2>&1 | tail -40
```

Note which tests still fail and why. The goal is to confirm the systemic 422 is gone.

- [ ] **Step 5: Commit conftest fix to PR branch**

Use the GitHubClient to commit the fixed `tests/conftest.py` to `wanleung/cue-test` on branch `feature/agent/project-cue--hong-kong-snooker-community`:

```python
# Run from ai-software-house directory:
import sys; sys.path.insert(0, '.')
from github_client import GitHubClient
from pathlib import Path

gh = GitHubClient(repo="wanleung/cue-test", github_token=<your_token>)
content = Path("workspace/project_cue__hong_kong_snooker_community_app_/tests/conftest.py").read_text()
gh.commit_file(
    path="tests/conftest.py",
    content=content,
    message="fix(tests): use dependency_overrides for FastAPI DB mock\n\nReplace patch() with app.dependency_overrides[get_db] in the client fixture.\nPatch() replaces the module attr but Depends() captured the original reference\nat import time — FastAPI was inspecting MagicMock's signature and returning\n422 for every test. Also add status/firebase_uid to sample_user_obj.",
    branch="feature/agent/project-cue--hong-kong-snooker-community",
)
```

Or use the main.py CLI:
```bash
cd /home/wanleung/Projects/ai-software-house
python main.py --mode revise --pr 3 --repo wanleung/cue-test
```
(After wiring TDDReviewerAgent in Task 2, this will auto-fix future regressions too.)

---

## Task 2: Wire TDDReviewerAgent into `_revision_run_reviewer_and_qa()`

**Files:**
- Modify: `orchestrator.py` lines ~3165–3187 (`_revision_run_reviewer_and_qa`)
- Modify: `tests/test_revision.py` (add `tdd_reviewer` to `orch` fixture + new test)

- [ ] **Step 1: Write the failing test first**

In `tests/test_revision.py`, add to the existing `orch` fixture and add a new test class.

Find the `orch` fixture (around line 10) and add `tdd_reviewer` to it:

```python
# In the existing orch fixture, add after o.qa = MagicMock():
o.tdd_reviewer = MagicMock()
o.tdd_reviewer.run.return_value = ({"tests/test_foo.py": "# fixed"}, "Fixed 1 issue")
```

Then add this test class at the bottom of the file:

```python
class TestRevisionRunReviewerAndQA:
    """TDDReviewerAgent must be called in revise mode after QA generates tests."""

    def test_tdd_reviewer_called_with_qa_test_files(self, orch):
        orch.reviewer.run.return_value = {"verdict": "approved"}
        orch.qa.run.return_value = {"test_files": {"tests/test_foo.py": "# original"}}
        orch.tdd_reviewer.run.return_value = ({"tests/test_foo.py": "# fixed"}, "Fixed 1 issue")

        rev_result, test_files = orch._revision_run_reviewer_and_qa(
            revised_files={"app/main.py": "# code"},
            design="# Design doc",
            project_name="TestProject",
            head_branch="feature/test",
            new_revision=1,
        )

        orch.tdd_reviewer.run.assert_called_once_with(
            {"tests/test_foo.py": "# original"},
            prd="# Design doc",
            project_name="TestProject",
        )
        # Confirm the REVISED files (not originals) are committed
        committed_paths = [
            call.kwargs["path"]
            for call in orch.target_github.commit_file.call_args_list
        ]
        assert "tests/test_foo.py" in committed_paths
        assert test_files == {"tests/test_foo.py": "# fixed"}

    def test_tdd_reviewer_skipped_when_no_test_files(self, orch):
        orch.reviewer.run.return_value = {"verdict": "approved"}
        orch.qa.run.return_value = {"test_files": {}}

        orch._revision_run_reviewer_and_qa(
            revised_files={"app/main.py": "# code"},
            design="# Design doc",
            project_name="TestProject",
            head_branch="feature/test",
            new_revision=1,
        )

        orch.tdd_reviewer.run.assert_not_called()

    def test_tdd_reviewer_original_used_when_revised_empty(self, orch):
        """If TDDReviewer returns empty dict, fall back to QA-generated files."""
        orch.reviewer.run.return_value = {"verdict": "approved"}
        orch.qa.run.return_value = {"test_files": {"tests/test_foo.py": "# original"}}
        orch.tdd_reviewer.run.return_value = ({}, "No changes needed")

        _, test_files = orch._revision_run_reviewer_and_qa(
            revised_files={"app/main.py": "# code"},
            design="# Design doc",
            project_name="TestProject",
            head_branch="feature/test",
            new_revision=1,
        )

        assert test_files == {"tests/test_foo.py": "# original"}
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_revision.py::TestRevisionRunReviewerAndQA -v --tb=short 2>&1 | tail -20
```

Expected: FAIL — `AttributeError: Mock object has no attribute 'tdd_reviewer'` or `AssertionError: tdd_reviewer.run not called`

- [ ] **Step 3: Implement the fix in `_revision_run_reviewer_and_qa()`**

In `orchestrator.py`, replace lines ~3165–3187 (`_revision_run_reviewer_and_qa`):

```python
def _revision_run_reviewer_and_qa(
    self,
    revised_files: dict,
    design: str,
    project_name: str,
    head_branch: str,
    new_revision: int,
) -> tuple:
    """Run code review and QA passes, committing any new test files. Returns (rev_result, test_files)."""
    # Code Reviewer
    rev_result = self.reviewer.run(revised_files, design or "N/A", project_name)
    console.print(f"  🔍 Code review verdict: [bold]{rev_result.get('verdict', '?')}[/bold]")
    # QA Engineer
    qa_result = self.qa.run(revised_files, design or "N/A", project_name)
    test_files: dict[str, str] = qa_result.get("test_files", {})
    # TDD Reviewer — catches broken conftest patterns, bad imports, syntax errors
    if test_files:
        revised_tests, tdd_summary = self.tdd_reviewer.run(
            test_files, prd=design or "N/A", project_name=project_name
        )
        if revised_tests:
            test_files = revised_tests
        if tdd_summary:
            console.print(f"  🔎 TDD review: {tdd_summary[:120]}")
    for filepath, content in test_files.items():
        self.target_github.commit_file(
            path=filepath,
            content=content,
            message=f"test: revision {new_revision} — update tests [{filepath}]",
            branch=head_branch,
        )
    return rev_result, test_files
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_revision.py::TestRevisionRunReviewerAndQA -v --tb=short 2>&1 | tail -20
```

Expected: 3 tests PASS

- [ ] **Step 5: Run the full test suite to confirm no regressions**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_revision.py -v --tb=short 2>&1 | tail -20
```

Expected: All existing revision tests still pass.

- [ ] **Step 6: Commit**

```bash
cd /home/wanleung/Projects/ai-software-house
git add orchestrator.py tests/test_revision.py
git commit -m "feat(orchestrator): wire TDDReviewerAgent into revise mode

Call tdd_reviewer.run() after QA generates test files in
_revision_run_reviewer_and_qa(). This is the same pattern as
build mode (_stage_tdd_review). Prevents broken conftest patterns,
bad imports, and syntax errors from being committed to PRs.

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 3: Update `roles/tdd_reviewer.md` with FastAPI dependency injection guidance

**Files:**
- Modify: `roles/tdd_reviewer.md`

The TDDReviewerAgent's system prompt currently doesn't mention FastAPI-specific patterns. Adding explicit guidance prevents the QA engineer's wrong `patch()` pattern from surviving review.

- [ ] **Step 1: Write a test for the new guidance**

In `tests/test_tdd_reviewer.py`, add:

```python
class TestFastAPIConftest:
    """TDDReviewer should detect and fix wrong FastAPI DB mocking pattern."""

    def test_rejects_patch_based_get_db_fixture(self):
        """patch() for Depends() is wrong — reviewer should rewrite to dependency_overrides."""
        from agents.tdd_reviewer import TDDReviewerAgent

        bad_conftest = '''import pytest
from unittest.mock import patch, MagicMock

@pytest.fixture
def client(mock_db):
    with patch("app.dependencies.get_db", return_value=mock_db):
        from app.main import app
        app.dependency_overrides = {}
        from fastapi.testclient import TestClient
        yield TestClient(app)
'''
        good_conftest = '''import pytest

@pytest.fixture
def client(mock_db):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.dependencies import get_db

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)
'''
        agent = _make_agent(response=f"""
### FILE: tests/conftest.py
```python
{good_conftest}
```

### REVIEW SUMMARY:
- Correctness fixes: replaced patch(get_db) with dependency_overrides
- Quality additions: none
- Remaining concerns: none
""")
        revised, summary = agent.run(
            test_files={"tests/conftest.py": bad_conftest},
            prd="# PRD",
            project_name="TestProject",
        )
        assert "dependency_overrides" in revised.get("tests/conftest.py", "")
        assert "patch" not in revised.get("tests/conftest.py", "")
```

- [ ] **Step 2: Run to verify test is meaningful (will pass since we're mocking the LLM)**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_tdd_reviewer.py::TestFastAPIConftest -v --tb=short 2>&1 | tail -10
```

Expected: PASS (agent is mocked to return the correct output)

- [ ] **Step 3: Add FastAPI section to `roles/tdd_reviewer.md`**

In `roles/tdd_reviewer.md`, after the existing `### Pass 1 — Correctness` section, add a new bullet under point 2 (Import paths):

Find this text:
```
2. **Import paths**: Test files should not hardcode app import paths that assume a specific project structure not guaranteed by the PRD (e.g. `from app.main import app` when the PRD doesn't specify that path). Use flexible import patterns or fixture injection.
```

Replace with:
```
2. **Import paths**: Test files should not hardcode app import paths that assume a specific project structure not guaranteed by the PRD. Use flexible import patterns or fixture injection.

3. **FastAPI dependency injection**: NEVER use `unittest.mock.patch()` to mock a FastAPI `Depends()` dependency. `Depends(get_db)` captures the function reference at route-decorator time; patching the module attribute afterwards has no effect, and importing `app.main` inside a `with patch(...)` block poisons the route's dependency with a `MagicMock`. Always use `app.dependency_overrides`:

   ```python
   # WRONG — causes 422 on every request:
   with patch("app.dependencies.get_db", return_value=mock_db):
       from app.main import app
       app.dependency_overrides = {}   # ← clears overrides!
       yield TestClient(app)

   # CORRECT:
   from app.main import app
   from app.dependencies import get_db

   async def override_get_db():
       yield mock_db          # yield, not return

   app.dependency_overrides[get_db] = override_get_db
   yield TestClient(app)
   app.dependency_overrides.pop(get_db, None)  # cleanup
   ```

4. **Mock user objects**: When mocking ORM User objects, ensure the mock includes all fields the route accesses — at minimum `status`, `role`, `id`, `email`, `firebase_uid`. Missing attributes cause `AttributeError` that surfaces as 500 responses.
```

- [ ] **Step 4: Commit**

```bash
cd /home/wanleung/Projects/ai-software-house
git add roles/tdd_reviewer.md tests/test_tdd_reviewer.py
git commit -m "docs(tdd_reviewer): add FastAPI dependency_overrides guidance

Explicitly document that patch() must not be used for FastAPI Depends()
and that mock user objects need status/firebase_uid fields.
This prevents the conftest anti-pattern from surviving TDD review.

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 4: Push conftest fix to PR branch and re-trigger test run

**Files:**
- Commit to: `wanleung/cue-test` branch `feature/agent/project-cue--hong-kong-snooker-community`

- [ ] **Step 1: Commit the fixed conftest to the PR branch using GitHubClient**

```bash
cd /home/wanleung/Projects/ai-software-house
python - <<'EOF'
import sys; sys.path.insert(0, '.')
from pathlib import Path
from github_client import GitHubClient
import os

gh = GitHubClient(
    repo="wanleung/cue-test",
    github_token=os.environ["GITHUB_TOKEN"],
)
content = Path("workspace/project_cue__hong_kong_snooker_community_app_/tests/conftest.py").read_text()
gh.commit_file(
    path="tests/conftest.py",
    content=content,
    message="fix(tests): use dependency_overrides for FastAPI DB mock\n\nreplace patch() with app.dependency_overrides[get_db].\nAlso add status/firebase_uid to sample_user_obj fixture.",
    branch="feature/agent/project-cue--hong-kong-snooker-community",
)
print("✅ conftest.py committed to PR branch")
EOF
```

- [ ] **Step 2: Run tests locally from workspace to confirm improvement**

```bash
cd /home/wanleung/Projects/ai-software-house/workspace/project_cue__hong_kong_snooker_community_app_
python -m pytest tests/ -q --tb=line 2>&1 | tail -10
```

Expected: significantly fewer failures (the systemic 422s are gone).

- [ ] **Step 3: Post result to PR**

```bash
cd /home/wanleung/Projects/ai-software-house
python main.py --mode revise --pr 3 --repo wanleung/cue-test
```

This triggers a full revise cycle: engineer re-checks code, QA regenerates tests (now going through TDDReviewerAgent from Task 2), and posts updated test results to the PR.
