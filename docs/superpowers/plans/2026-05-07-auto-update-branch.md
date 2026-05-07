# Auto-Update Branch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a PR contains an `update-branch` comment directive and the repo config has `update_branch: true`, automatically merge `master` into the PR branch (with AI conflict resolution) before `run_revision()` runs the fix.

**Architecture:** Three independent layers: (1) `GitHubClient.merge_base_into_branch()` wraps the GitHub merges API and returns a numeric status code; (2) `Orchestrator._parse_update_directive()` + `_update_branch_from_base()` own detection and merge logic; (3) `run_revision()` and `watcher.py` wire everything together. The `orch` fixture in `tests/test_revision.py` gets `_update_branch_enabled = False` added to it; tests that need it enabled set it directly.

**Tech Stack:** Python, `requests` (raw for 201/204/409 handling), `unittest.mock.MagicMock`, `pytest`, GitHub REST API (`POST /repos/{repo}/merges`).

---

## File Map

| File | Change |
|------|--------|
| `github_client.py` | Add `merge_base_into_branch(base_branch, head_branch, commit_message)` |
| `orchestrator.py` | Add `_update_branch_enabled` kwarg to `__init__()`, add `_parse_update_directive()`, add `_update_branch_from_base()`, wire step 0 in `run_revision()` |
| `watcher.py` | Read `update_branch` from `_w_settings`, pass `update_branch_enabled` to `Orchestrator(...)` and `_run_pr_revision()` |
| `tests/test_revision.py` | Add `_update_branch_enabled = False` to `orch` fixture; add 9 new tests |

---

### Task 1: `merge_base_into_branch()` in `github_client.py`

**Files:**
- Modify: `github_client.py` (after `def add_pr_comment`, around line 298)
- Test: `tests/test_github_client.py` (new file, or existing — check first)

**Context:** `_request()` raises `RuntimeError` for any non-2xx response. Status 409 (merge conflict) is not in `_RETRYABLE = {429, 500, 502, 503, 504}`, so it would raise immediately. We need raw `requests.post` to intercept 409 ourselves. `self.headers` and `self.API_BASE` are available on the client instance.

- [ ] **Step 1: Write the failing tests**

Check if `tests/test_github_client.py` already exists, then add these three tests:

```python
# tests/test_github_client.py
import pytest
from unittest.mock import patch, MagicMock
from github_client import GitHubClient


@pytest.fixture
def gc():
    return GitHubClient("owner/repo", github_token="tok")


def test_merge_base_into_branch_clean(gc):
    """Returns 201 when GitHub creates a merge commit."""
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    with patch("requests.post", return_value=mock_resp) as mock_post:
        result = gc.merge_base_into_branch("master", "feature/agent/1-my-pr")
    assert result == 201
    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert kwargs["json"]["base"] == "feature/agent/1-my-pr"
    assert kwargs["json"]["head"] == "master"


def test_merge_base_into_branch_up_to_date(gc):
    """Returns 204 when GitHub says already up to date."""
    mock_resp = MagicMock()
    mock_resp.status_code = 204
    with patch("requests.post", return_value=mock_resp):
        result = gc.merge_base_into_branch("master", "feature/agent/1-my-pr")
    assert result == 204


def test_merge_base_into_branch_conflict(gc):
    """Returns 409 when GitHub reports a merge conflict."""
    mock_resp = MagicMock()
    mock_resp.status_code = 409
    with patch("requests.post", return_value=mock_resp):
        result = gc.merge_base_into_branch("master", "feature/agent/1-my-pr")
    assert result == 409
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_github_client.py::test_merge_base_into_branch_clean tests/test_github_client.py::test_merge_base_into_branch_up_to_date tests/test_github_client.py::test_merge_base_into_branch_conflict -v
```

Expected: `AttributeError: 'GitHubClient' object has no attribute 'merge_base_into_branch'`

- [ ] **Step 3: Implement `merge_base_into_branch()`**

Add after `def add_pr_comment` in `github_client.py` (around line 298):

```python
def merge_base_into_branch(
    self,
    base_branch: str,
    head_branch: str,
    commit_message: str = "",
) -> int:
    """Merge *base_branch* INTO *head_branch* via the GitHub merges API.

    Uses a raw ``requests.post`` (not ``_request``) so callers can inspect
    the 409 conflict status without catching an exception.

    Returns:
        201 — merge commit created (clean merge)
        204 — already up to date (no action needed)
        409 — merge conflict (caller must resolve)

    Raises:
        RuntimeError — any other unexpected HTTP status.
    """
    import requests as _requests

    url = f"{self.API_BASE}/repos/{self.repo}/merges"
    payload: dict = {"base": head_branch, "head": base_branch}
    if commit_message:
        payload["commit_message"] = commit_message

    resp = _requests.post(url, headers=self.headers, json=payload)
    if resp.status_code in (201, 204, 409):
        return resp.status_code
    raise RuntimeError(
        f"GitHub merges API failed [{resp.status_code}]: {resp.text[:500]}"
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_github_client.py::test_merge_base_into_branch_clean tests/test_github_client.py::test_merge_base_into_branch_up_to_date tests/test_github_client.py::test_merge_base_into_branch_conflict -v
```

Expected: all 3 PASS

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest -x -q
```

Expected: all pass (same count as before, 73+)

- [ ] **Step 6: Commit**

```bash
cd /home/wanleung/Projects/ai-software-house
git add github_client.py tests/test_github_client.py
git commit -m "feat: add GitHubClient.merge_base_into_branch() for auto-update branch

POST /repos/{repo}/merges — returns 201/204/409 without raising on
conflict so callers can handle conflict resolution themselves.

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
git push origin HEAD
git push public HEAD
```

---

### Task 2: `_parse_update_directive()` + `_update_branch_from_base()` + `__init__()` kwarg

**Files:**
- Modify: `orchestrator.py`
  - `__init__()` signature near line 507 — add `update_branch_enabled: bool = False`
  - After `_fetch_branch_files()` (around line 1690) — add `_parse_update_directive()` and `_update_branch_from_base()`
- Modify: `tests/test_revision.py` — add `_update_branch_enabled = False` to fixture; add 6 new unit tests

**Context:**
- `self.engineer.call(prompt)` makes a raw LLM call (returns str). Use it for AI conflict resolution.
- `self.target_github.get_pr_files(pr_number)` returns a list of dicts with `"filename"` key.
- `self.target_github.get_file_content(path, ref=branch)` returns `Optional[str]`.
- `self.target_github.commit_file(path, content, branch, message)` commits a file.
- `self.target_github.add_pr_comment(pr_number, body)` posts a comment.
- `self.target_github.merge_base_into_branch(base_branch, head_branch)` — just added in Task 1.
- For conflict detection: get PR files, then for each file, fetch content from PR branch and from master. If they differ, AI-resolve.

- [ ] **Step 1: Update the `orch` fixture in `tests/test_revision.py`**

Find the fixture (lines 10-23) and add `o._update_branch_enabled = False`:

```python
@pytest.fixture
def orch(tmp_path):
    """Minimal orchestrator with no real API calls."""
    o = Orchestrator.__new__(Orchestrator)
    o.max_revisions = 3
    o.github = MagicMock()
    o.target_github = MagicMock()
    o._github_token = "tok"
    o.engineer = MagicMock()
    o.reviewer = MagicMock()
    o.qa = MagicMock()
    o.skill_loader = None
    o._update_branch_enabled = False
    return o
```

- [ ] **Step 2: Write the 6 failing unit tests**

Append to `tests/test_revision.py`:

```python
# ── _parse_update_directive ───────────────────────────────────────────────────

def test_parse_update_directive_detects_update_branch(orch):
    feedback = [
        {"body": "Looks good overall", "author": "alice"},
        {"body": "update-branch", "author": "alice"},
    ]
    assert orch._parse_update_directive(feedback) is True


def test_parse_update_directive_detects_colon_form(orch):
    feedback = [{"body": "update-branch: true", "author": "alice"}]
    assert orch._parse_update_directive(feedback) is True


def test_parse_update_directive_no_match(orch):
    feedback = [{"body": "Please fix the tests", "author": "alice"}]
    assert orch._parse_update_directive(feedback) is False


# ── _update_branch_from_base ──────────────────────────────────────────────────

def test_update_branch_already_up_to_date(orch):
    """merge returns 204 → status 'up_to_date', no commit."""
    orch.target_github.merge_base_into_branch.return_value = 204
    result = orch._update_branch_from_base("feature/agent/1-my-pr")
    assert result["status"] == "up_to_date"
    orch.target_github.commit_file.assert_not_called()


def test_update_branch_clean_merge(orch):
    """merge returns 201 → status 'merged', no conflict resolution needed."""
    orch.target_github.merge_base_into_branch.return_value = 201
    result = orch._update_branch_from_base("feature/agent/1-my-pr")
    assert result["status"] == "merged"
    orch.target_github.commit_file.assert_not_called()


def test_update_branch_conflict_ai_resolves(orch):
    """409 → AI resolves files → retry returns 201 → status 'merged'."""
    orch.target_github.merge_base_into_branch.side_effect = [409, 201]
    orch.target_github.get_pr_files.return_value = [{"filename": "app/main.py"}]
    orch.target_github.get_file_content.side_effect = [
        "PR version of main.py",   # PR branch fetch
        "master version of main.py",  # master fetch
    ]
    orch.engineer.call.return_value = "merged content of main.py"

    result = orch._update_branch_from_base("feature/agent/1-my-pr", pr_number=42)

    assert result["status"] == "merged"
    orch.target_github.commit_file.assert_called_once_with(
        "app/main.py",
        "merged content of main.py",
        "feature/agent/1-my-pr",
        "chore: resolve merge conflicts with master",
    )
    assert orch.target_github.merge_base_into_branch.call_count == 2


def test_update_branch_conflict_fallback(orch):
    """409 → AI resolves → retry still 409 → posts PR comment, returns 'conflict'."""
    orch.target_github.merge_base_into_branch.return_value = 409
    orch.target_github.get_pr_files.return_value = [{"filename": "src/utils.py"}]
    orch.target_github.get_file_content.side_effect = [
        "PR version",
        "master version",
    ]
    orch.engineer.call.return_value = "resolved utils.py"

    result = orch._update_branch_from_base("feature/agent/1-my-pr", pr_number=42)

    assert result["status"] == "conflict"
    assert "src/utils.py" in result["conflicting_files"]
    orch.target_github.add_pr_comment.assert_called_once()
    comment_body = orch.target_github.add_pr_comment.call_args[0][1]
    assert "resolve these conflicts manually" in comment_body
    assert "src/utils.py" in comment_body
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_revision.py::test_parse_update_directive_detects_update_branch tests/test_revision.py::test_parse_update_directive_detects_colon_form tests/test_revision.py::test_parse_update_directive_no_match tests/test_revision.py::test_update_branch_already_up_to_date tests/test_revision.py::test_update_branch_clean_merge tests/test_revision.py::test_update_branch_conflict_ai_resolves tests/test_revision.py::test_update_branch_conflict_fallback -v
```

Expected: all FAIL with `AttributeError: '_parse_update_directive'` or similar.

- [ ] **Step 4: Add `update_branch_enabled` to `Orchestrator.__init__()`**

In `orchestrator.py`, find the `__init__` signature (line ~507). Add the kwarg after `cost_tracking`:

```python
        cost_tracking: dict | None = None,
        update_branch_enabled: bool = False,
    ) -> None:
```

Find the body of `__init__` where instance variables are set (search for `self.cost_tracking = cost_tracking`), and add after it:

```python
        self._update_branch_enabled = update_branch_enabled
```

- [ ] **Step 5: Add `_parse_update_directive()` to `orchestrator.py`**

Add immediately after `_parse_merge_directives()` (around line 1665):

```python
    def _parse_update_directive(self, feedback: list[dict]) -> bool:
        """Return True if any feedback item contains an 'update-branch' directive.

        Supported formats (case-insensitive):
            update-branch
            update-branch: true
        """
        pattern = re.compile(r"update-branch(?::\s*true)?", re.IGNORECASE)
        return any(pattern.search(item.get("body", "")) for item in feedback)
```

- [ ] **Step 6: Add `_update_branch_from_base()` to `orchestrator.py`**

Add immediately after `_parse_update_directive()`:

```python
    def _update_branch_from_base(
        self,
        head_branch: str,
        base_branch: str = "master",
        pr_number: int | None = None,
    ) -> dict:
        """Merge *base_branch* into *head_branch*.

        Returns a status dict:
            {"status": "up_to_date"}  — 204, nothing to do
            {"status": "merged"}      — 201, clean or AI-resolved merge
            {"status": "conflict", "conflicting_files": [...]}
                                      — could not resolve, PR comment posted
        """
        code = self.target_github.merge_base_into_branch(base_branch, head_branch)

        if code == 204:
            console.print(f"  ✅ Branch [cyan]{head_branch}[/cyan] is already up to date with [cyan]{base_branch}[/cyan]")
            return {"status": "up_to_date"}

        if code == 201:
            console.print(f"  ✅ Merged [cyan]{base_branch}[/cyan] into [cyan]{head_branch}[/cyan] cleanly")
            return {"status": "merged"}

        # ── 409: conflict path ────────────────────────────────────────────────
        console.print(f"  ⚠️  Merge conflict detected — attempting AI resolution …")

        pr_files = self.target_github.get_pr_files(pr_number) if pr_number else []
        conflicting_files: list[str] = []
        for f in pr_files:
            path = f["filename"]
            pr_content = self.target_github.get_file_content(path, ref=head_branch)
            master_content = self.target_github.get_file_content(path, ref=base_branch)
            if pr_content is None or master_content is None:
                continue
            if pr_content == master_content:
                continue

            # AI resolves the conflict
            prompt = (
                f"File: {path}\n\n"
                f"=== Version on PR branch ({head_branch}) ===\n{pr_content}\n\n"
                f"=== Version on {base_branch} ===\n{master_content}\n\n"
                "Produce a single merged version that preserves both sets of changes. "
                "Output ONLY the file content, no explanation."
            )
            resolved = self.engineer.call(prompt)
            self.target_github.commit_file(
                path,
                resolved,
                head_branch,
                "chore: resolve merge conflicts with master",
            )
            conflicting_files.append(path)

        if not conflicting_files:
            # No files to resolve — conflict is in files not in the PR; can't auto-fix
            pass

        # Retry merge
        retry_code = self.target_github.merge_base_into_branch(base_branch, head_branch)
        if retry_code in (201, 204):
            console.print(f"  ✅ Merge succeeded after AI conflict resolution")
            return {"status": "merged"}

        # Fallback: post comment and abort
        files_list = "\n".join(f"- `{p}`" for p in conflicting_files) if conflicting_files else "- (unknown)"
        self.target_github.add_pr_comment(
            pr_number,
            "⚠️ Could not automatically resolve merge conflicts.\n\n"
            f"Conflicting files:\n{files_list}\n\n"
            "Please resolve these conflicts manually and re-trigger ai-fix.",
        )
        return {"status": "conflict", "conflicting_files": conflicting_files}
```

- [ ] **Step 7: Run the 6 tests and verify they pass**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_revision.py::test_parse_update_directive_detects_update_branch tests/test_revision.py::test_parse_update_directive_detects_colon_form tests/test_revision.py::test_parse_update_directive_no_match tests/test_revision.py::test_update_branch_already_up_to_date tests/test_revision.py::test_update_branch_clean_merge tests/test_revision.py::test_update_branch_conflict_ai_resolves tests/test_revision.py::test_update_branch_conflict_fallback -v
```

Expected: all 7 PASS.

- [ ] **Step 8: Run full test suite**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest -x -q
```

Expected: all pass (no regressions).

- [ ] **Step 9: Commit**

```bash
cd /home/wanleung/Projects/ai-software-house
git add orchestrator.py tests/test_revision.py
git commit -m "feat: add _parse_update_directive() and _update_branch_from_base() to Orchestrator

- New update_branch_enabled kwarg on __init__() (default False)
- _parse_update_directive(): detects 'update-branch' comment directive
- _update_branch_from_base(): merges master into PR branch; AI resolves
  conflicts file-by-file; posts fallback comment if retry still fails

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
git push origin HEAD
git push public HEAD
```

---

### Task 3: Wire `run_revision()` step 0 + `watcher.py` config + integration tests

**Files:**
- Modify: `orchestrator.py` — add step 0 in `run_revision()` (after PR metadata and revision cap check, before feedback collection)
- Modify: `watcher.py` — read `update_branch` from `_w_settings`, pass to `_run_pr_revision()` and `Orchestrator(...)`
- Modify: `tests/test_revision.py` — add 3 integration tests

**Context:**
- In `run_revision()`, the PR metadata is fetched first (step 1, lines ~1718–1724): `pr`, `head_branch`, `pr_body`, `issue_number`, `labels`.
- The revision cap is checked next (step 2). After step 2, collect feedback (step 3).
- Step 0 (update branch) should run **between** step 2 (revision cap check) and step 3 (collect feedback), after `head_branch` is known.
- Issue comments are fetched via `self.target_github.get_issue_comments(pr_number)` — same call as inside `_collect_pr_feedback`.
- In `watcher.py`: `_w_settings` is the merged settings dict at line 729. `_run_pr_revision()` signature is at line 604.

- [ ] **Step 1: Write the 3 failing integration tests**

Append to `tests/test_revision.py`:

```python
# ── run_revision step 0: auto-update branch ───────────────────────────────────

def _make_revision_mocks(orch, pr_number=42, head_branch="feature/agent/1-fix"):
    """Set up minimal mocks for run_revision() to reach step 3 without errors."""
    orch.target_github.get_pr.return_value = {
        "number": pr_number,
        "head": {"ref": head_branch},
        "body": "",
        "labels": [],
    }
    orch.target_github.get_issue_comments.return_value = []
    orch.target_github.get_pr_review_comments.return_value = []
    orch.target_github.get_pr_reviews.return_value = []
    orch.target_github.get_pr_files.return_value = []
    orch.target_github.get_file_content.return_value = None
    orch.engineer.run_all_modules.return_value = MagicMock(
        all_files={}, structured_files={}, modules={}
    )
    orch.reviewer.run.return_value = MagicMock(issues=[], structured_files={})
    orch.qa.run.return_value = MagicMock(issues=[], structured_files={})
    orch._fetch_design_from_issue = MagicMock(return_value="")
    orch._get_revision_number = MagicMock(return_value=0)
    orch._format_feedback = MagicMock(return_value="feedback md")
    orch._extract_issue_number = MagicMock(return_value=None)
    orch._parse_merge_directives = MagicMock(return_value=[])


def test_run_revision_skips_update_when_disabled(orch):
    """update_branch_enabled=False → merge_base_into_branch never called."""
    orch._update_branch_enabled = False
    _make_revision_mocks(orch)
    orch.target_github.get_issue_comments.return_value = [
        {"body": "update-branch", "user": {"login": "alice"}}
    ]
    # Provide at least one feedback item so run_revision doesn't return early
    orch.target_github.get_pr_review_comments.return_value = [
        {"body": "Fix the tests", "user": {"login": "alice"}, "path": "x.py", "line": 1}
    ]
    orch.run_revision(42)
    orch.target_github.merge_base_into_branch.assert_not_called()


def test_run_revision_skips_update_when_no_directive(orch):
    """Enabled but no 'update-branch' comment → merge_base_into_branch never called."""
    orch._update_branch_enabled = True
    _make_revision_mocks(orch)
    orch.target_github.get_issue_comments.return_value = [
        {"body": "Please fix the null pointer", "user": {"login": "alice"}}
    ]
    orch.target_github.get_pr_review_comments.return_value = [
        {"body": "Fix the tests", "user": {"login": "alice"}, "path": "x.py", "line": 1}
    ]
    orch.run_revision(42)
    orch.target_github.merge_base_into_branch.assert_not_called()


def test_run_revision_aborts_on_conflict(orch):
    """update-branch directive + enabled + conflict → run_revision returns conflict status."""
    orch._update_branch_enabled = True
    _make_revision_mocks(orch)
    orch.target_github.get_issue_comments.return_value = [
        {"body": "update-branch", "user": {"login": "alice"}}
    ]
    orch.target_github.merge_base_into_branch.return_value = 409
    orch.target_github.get_pr_files.return_value = []
    # With no PR files, conflicting_files will be [] and retry still 409
    orch.target_github.merge_base_into_branch.side_effect = [409, 409]

    result = orch.run_revision(42)

    assert result["status"] == "conflict"
    orch.target_github.add_pr_comment.assert_called_once()
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_revision.py::test_run_revision_skips_update_when_disabled tests/test_revision.py::test_run_revision_skips_update_when_no_directive tests/test_revision.py::test_run_revision_aborts_on_conflict -v
```

Expected: tests fail because step 0 code doesn't exist yet.

- [ ] **Step 3: Wire step 0 into `run_revision()` in `orchestrator.py`**

Find the section between the revision cap check and the feedback collection (around line 1760). The existing code looks like:

```python
        # ── 2. Check revision cap ─────────────────────────────────────────────
        current_rev = self._get_revision_number(labels)
        if current_rev >= self.max_revisions:
            ...
            return {"status": "max_revisions_reached"}

        # ── 3. Collect human feedback ─────────────────────────────────────────
        feedback = self._collect_pr_feedback(pr_number)
```

Insert step 0 **between** step 2 and step 3:

```python
        # ── 0. Auto-update branch from master (if configured + requested) ─────
        if self._update_branch_enabled:
            pr_issue_comments = self.target_github.get_issue_comments(pr_number)
            update_directive_feedback = [
                {"body": c.get("body", ""), "author": c.get("user", {}).get("login", "")}
                for c in pr_issue_comments
            ]
            if self._parse_update_directive(update_directive_feedback):
                update_result = self._update_branch_from_base(head_branch, pr_number=pr_number)
                if update_result["status"] == "conflict":
                    return update_result

        # ── 2. Check revision cap ─────────────────────────────────────────────
```

**Note:** The step numbering in the source comments stays as-is (don't renumber existing comments). Step 0 goes just before "── 2. Check revision cap".

- [ ] **Step 4: Run the 3 integration tests**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_revision.py::test_run_revision_skips_update_when_disabled tests/test_revision.py::test_run_revision_skips_update_when_no_directive tests/test_revision.py::test_run_revision_aborts_on_conflict -v
```

Expected: all 3 PASS. Debug any failures before continuing.

- [ ] **Step 5: Update `_run_pr_revision()` in `watcher.py`**

Add `update_branch_enabled` parameter to the function signature (line 604):

```python
def _run_pr_revision(
    pr: dict,
    tracker_repo: str,
    target_repo: str,
    model: str,
    num_engineers: int,
    log_dir: Path,
    logger: logging.Logger,
    pr_fix_label: str = "ai-fix",
    update_branch_enabled: bool = False,
) -> None:
```

In the `Orchestrator(...)` call inside `_run_pr_revision()` (around line 656), add the new kwarg:

```python
                orch = Orchestrator(
                    model=effective_model,
                    model_overrides=model_overrides,
                    github_token=token,
                    github_repo=tracker_repo,
                    target_repo=target_repo,
                    num_engineers=num_engineers,
                    use_github=True,
                    ollama_url=ollama_url,
                    nvidia_nim_api_key=nvidia_nim_api_key,
                    nvidia_nim_base_url=nvidia_nim_base_url,
                    retry_delay=retry_delay,
                    max_api_retries=max_api_retries,
                    inter_call_delay=inter_call_delay,
                    update_branch_enabled=update_branch_enabled,
                )
```

- [ ] **Step 6: Update the `_watch_prs()` call site in `watcher.py`**

In `_watch_prs()` (around line 737), add `update_branch_enabled` extraction and pass it through:

After:
```python
        pr_fix_label = _w_settings.get("pr_fix_label", "ai-fix")
```

Add:
```python
        update_branch_enabled = bool(_w_settings.get("update_branch", False))
```

Then in the `_run_pr_revision(...)` call (around line 770):

```python
            _run_pr_revision(
                pr, tracker_repo, target_repo, model, num_engineers, log_dir, logger,
                pr_fix_label=pr_fix_label,
                update_branch_enabled=update_branch_enabled,
            )
```

- [ ] **Step 7: Run full test suite**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest -x -q
```

Expected: all tests pass (82+ tests now: 73 original + 3 github_client + 7 unit + 3 integration = 86).

- [ ] **Step 8: Commit**

```bash
cd /home/wanleung/Projects/ai-software-house
git add orchestrator.py watcher.py tests/test_revision.py
git commit -m "feat: wire auto-update-branch into run_revision() and watcher.py

- run_revision() step 0: fetches issue comments, detects 'update-branch'
  directive, calls _update_branch_from_base(); aborts on unresolvable conflict
- watcher.py: reads update_branch from settings, passes to _run_pr_revision()
  and Orchestrator(update_branch_enabled=...)
- Enable per repo by adding 'update_branch: true' under settings: in
  repos-enabled/*.yaml

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
git push origin HEAD
git push public HEAD
```

---

## Usage

To enable auto-update branch for a repo, add to `repos-enabled/<repo>.yaml`:

```yaml
settings:
  watch_prs: true
  update_branch: true   # ← add this
  ...
```

Then post a comment on the PR containing:

```
update-branch
```

The next time the watcher runs and sees an `ai-fix` label on the PR, it will merge `master` into the PR branch before running the fix.
