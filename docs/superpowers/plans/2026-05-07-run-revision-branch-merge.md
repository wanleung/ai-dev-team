# run_revision Branch-Merge Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow `run_revision()` to fetch files from a sibling branch (e.g. a separate TDD test PR) and incorporate them into the engineer's context before fixing the implementation branch.

**Architecture:** Parse "merge directives" from PR feedback comments, then use the GitHub API to read all files from those branches and inject them into the engineer's augmented design context. No local git operations — everything goes through `GitHubClient`. New files from the merge branch are committed to the implementation branch after the engineer produces revised code.

**Tech Stack:** Python 3.11, GitHub REST API (`get_full_tree`, `get_file_content`, `get_pr`), existing `orchestrator.py` / `github_client.py` / `tests/test_revision.py`.

---

## Use Case Context

A user ran the TDD pipeline which produced **two separate PRs** on the same base (`main`):

- **PR #2** — branch `feature/agent/1-static-blog-platform` — test files only
- **PR #3** — branch `feature/agent/static-blog-platform` — implementation files only (no tests)

When `ai-fix` triggers `run_revision()` on PR #3, the engineer has no test files. The human (or a bot) posts a comment on PR #3 like:

```
merge-branch: feature/agent/1-static-blog-platform
```

or (natural language):

```
Please incorporate tests from branch `feature/agent/1-static-blog-platform` (PR #2) before fixing.
```

`run_revision()` should:
1. Detect the merge directive from PR comments
2. Fetch all files from the specified branch via GitHub API
3. Inject them as additional context for the engineer ("here are tests you must make pass")
4. Commit the fetched test files onto the implementation branch
5. Proceed with the fix as normal

---

## File Map

| File | Change |
|------|--------|
| `orchestrator.py` | Add `_parse_merge_directives()`, `_fetch_branch_files()`; update `run_revision()` |
| `tests/test_revision.py` | Add tests for both new helpers and the updated `run_revision()` flow |

---

## Task 1: `_parse_merge_directives` — extract branch names from PR feedback

**Files:**
- Modify: `orchestrator.py` — add method to `Orchestrator` class, near `_collect_pr_feedback`
- Test: `tests/test_revision.py`

### What it does

Scans feedback items (from `_collect_pr_feedback`) for branch merge instructions. Returns a deduplicated list of branch names. Supports three formats:

| Format | Example |
|--------|---------|
| Explicit directive | `merge-branch: feature/agent/1-static-blog-platform` |
| Backtick branch name | `merge branch \`feature/agent/1-static-blog-platform\`` |
| PR number reference | `merge from PR #2` → resolved to that PR's head branch |

- [ ] **Step 1.1: Write failing tests**

Add to `tests/test_revision.py`:

```python
# ── _parse_merge_directives ───────────────────────────────────────────────────

def test_parse_merge_directives_explicit_directive(orch):
    feedback = [
        {"author": "wanleung", "body": "merge-branch: feature/agent/1-static-blog-platform", "location": "comment"},
    ]
    result = orch._parse_merge_directives(feedback)
    assert result == ["feature/agent/1-static-blog-platform"]


def test_parse_merge_directives_backtick_branch(orch):
    feedback = [
        {"author": "wanleung", "body": "Please incorporate tests from branch `feature/agent/1-static-blog-platform` before fixing.", "location": "comment"},
    ]
    result = orch._parse_merge_directives(feedback)
    assert result == ["feature/agent/1-static-blog-platform"]


def test_parse_merge_directives_pr_number(orch):
    orch.target_github.get_pr.return_value = {"head": {"ref": "feature/agent/1-static-blog-platform"}}
    feedback = [
        {"author": "wanleung", "body": "merge from PR #2 before fixing tests", "location": "comment"},
    ]
    result = orch._parse_merge_directives(feedback)
    orch.target_github.get_pr.assert_called_once_with(2)
    assert result == ["feature/agent/1-static-blog-platform"]


def test_parse_merge_directives_deduplicates(orch):
    feedback = [
        {"author": "alice", "body": "merge-branch: feature/tests", "location": "comment"},
        {"author": "bob", "body": "merge-branch: feature/tests", "location": "comment"},
    ]
    assert orch._parse_merge_directives(feedback) == ["feature/tests"]


def test_parse_merge_directives_empty_when_no_directives(orch):
    feedback = [
        {"author": "alice", "body": "Please fix the import error on line 10", "location": "comment"},
    ]
    assert orch._parse_merge_directives(feedback) == []
```

- [ ] **Step 1.2: Run tests to verify they fail**

```bash
cd /home/wanleung/Projects/ai-software-house
python3 -m pytest tests/test_revision.py::test_parse_merge_directives_explicit_directive -v
```

Expected: `FAILED` — `AttributeError: 'Orchestrator' object has no attribute '_parse_merge_directives'`

- [ ] **Step 1.3: Implement `_parse_merge_directives`**

Add to `orchestrator.py` immediately after `_collect_pr_feedback` (search for `def _format_feedback`):

```python
# Patterns recognised as merge directives in PR feedback comments.
_MERGE_DIRECTIVE_RE = re.compile(
    r"merge-branch:\s*(\S+)"              # explicit: merge-branch: <branch>
    r"|merge\s+branch\s+`([^`]+)`"        # backtick: merge branch `<branch>`
    r"|incorporate.*?branch\s+`([^`]+)`"  # incorporate: from branch `<branch>`
    r"|merge\s+from\s+PR\s+#(\d+)",       # PR number: merge from PR #N
    re.IGNORECASE,
)

def _parse_merge_directives(self, feedback: list[dict]) -> list[str]:
    """Scan PR feedback for merge directives and return deduplicated branch names.

    Supports:
      - ``merge-branch: <branch>``
      - ``merge branch `<branch>```
      - ``incorporate ... from branch `<branch>```
      - ``merge from PR #N``  (resolved to head branch via GitHub API)
    """
    seen: list[str] = []
    for item in feedback:
        body = item.get("body", "")
        for m in _MERGE_DIRECTIVE_RE.finditer(body):
            branch = m.group(1) or m.group(2) or m.group(3)
            pr_num_str = m.group(4)
            if pr_num_str and self.target_github:
                try:
                    pr = self.target_github.get_pr(int(pr_num_str))
                    branch = pr["head"]["ref"]
                except Exception:
                    continue
            if branch and branch not in seen:
                seen.append(branch)
    return seen
```

Make sure `import re` is at the top of `orchestrator.py` (it already is — verify with `grep "^import re" orchestrator.py`).

- [ ] **Step 1.4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_revision.py -k "parse_merge" -v
```

Expected: `5 passed`

- [ ] **Step 1.5: Commit**

```bash
git add orchestrator.py tests/test_revision.py
git commit -m "feat: add _parse_merge_directives to detect branch merge instructions in PR feedback"
```

---

## Task 2: `_fetch_branch_files` — read all files from a branch via GitHub API

**Files:**
- Modify: `orchestrator.py` — add method to `Orchestrator` class
- Test: `tests/test_revision.py`

### What it does

Uses `target_github.get_full_tree(ref=branch)` to list all blob paths, then reads each file with `get_file_content(path, ref=branch)`. Skips files that return `None` (binary, too large, or missing). Returns `dict[str, str]` of path → content.

- [ ] **Step 2.1: Write failing tests**

Add to `tests/test_revision.py`:

```python
# ── _fetch_branch_files ───────────────────────────────────────────────────────

def test_fetch_branch_files_returns_text_files(orch):
    orch.target_github.get_full_tree.return_value = [
        {"path": "tests/test_app.py", "type": "blob", "size": 500},
        {"path": "tests/conftest.py", "type": "blob", "size": 200},
        {"path": "src/", "type": "tree", "size": 0},
    ]
    orch.target_github.get_file_content.side_effect = lambda path, ref: f"# content of {path}"
    result = orch._fetch_branch_files("feature/tests")
    assert "tests/test_app.py" in result
    assert "tests/conftest.py" in result
    assert "src/" not in result  # tree entries excluded
    assert result["tests/test_app.py"] == "# content of tests/test_app.py"


def test_fetch_branch_files_skips_unreadable_files(orch):
    orch.target_github.get_full_tree.return_value = [
        {"path": "tests/test_app.py", "type": "blob", "size": 500},
        {"path": "data/image.png", "type": "blob", "size": 10000},
    ]
    def _content(path, ref):
        if path == "data/image.png":
            return None  # binary / unreadable
        return "# test content"
    orch.target_github.get_file_content.side_effect = _content
    result = orch._fetch_branch_files("feature/tests")
    assert "tests/test_app.py" in result
    assert "data/image.png" not in result


def test_fetch_branch_files_empty_on_tree_failure(orch):
    orch.target_github.get_full_tree.return_value = []
    result = orch._fetch_branch_files("feature/tests")
    assert result == {}
```

- [ ] **Step 2.2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_revision.py -k "fetch_branch_files" -v
```

Expected: `FAILED` — `AttributeError: 'Orchestrator' object has no attribute '_fetch_branch_files'`

- [ ] **Step 2.3: Implement `_fetch_branch_files`**

Add to `orchestrator.py` immediately after `_parse_merge_directives`:

```python
def _fetch_branch_files(self, branch: str) -> dict[str, str]:
    """Fetch all readable text files from a branch using the GitHub API.

    Uses get_full_tree() for an efficient single-call file listing, then
    reads each blob. Skips trees, unreadable files (binary, too large), and
    files that get_file_content() returns None for.

    Returns dict of {path: content}.
    """
    if self.target_github is None:
        return {}
    tree = self.target_github.get_full_tree(ref=branch)
    files: dict[str, str] = {}
    for entry in tree:
        if entry.get("type") != "blob":
            continue
        path = entry["path"]
        content = self.target_github.get_file_content(path, ref=branch)
        if content is not None:
            files[path] = content
    return files
```

- [ ] **Step 2.4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_revision.py -k "fetch_branch_files" -v
```

Expected: `3 passed`

- [ ] **Step 2.5: Commit**

```bash
git add orchestrator.py tests/test_revision.py
git commit -m "feat: add _fetch_branch_files to read all files from a branch via GitHub API"
```

---

## Task 3: Wire into `run_revision()` — detect, fetch, inject, commit

**Files:**
- Modify: `orchestrator.py` — update `run_revision()` steps 3–8
- Test: `tests/test_revision.py`

### What changes in `run_revision()`

After **step 3** (collect feedback): call `_parse_merge_directives(feedback)`.

After **step 5** (read current files): for each merge branch, call `_fetch_branch_files(branch)`, collect into `merge_branch_files: dict[str, dict[str, str]]` (branch → files).

In **step 6** (build augmented design): append a section per merge branch:
```
## Files from Branch `<branch>` (to be incorporated)

### `tests/test_app.py`
```python
...
```
```

In **step 7** (commit revised files): after committing `revised_files`, also commit any files from `merge_branch_files` that are NOT already in `revised_files` (the engineer may have updated them, or they may be new additions).

In **step 8** (summary): mention the incorporated branches.

- [ ] **Step 3.1: Write failing tests**

Add to `tests/test_revision.py`:

```python
# ── run_revision merge-branch integration ────────────────────────────────────

def test_run_revision_incorporates_merge_branch_files(orch):
    """When a PR comment contains 'merge-branch: X', files from X are fetched
    and committed to the implementation branch."""
    orch.target_github.get_pr.return_value = {
        "head": {"ref": "feature/impl"},
        "body": "Closes #1",
        "labels": [],
        "title": "Implementation",
    }
    orch.target_github.get_pr_review_comments.return_value = []
    orch.target_github.get_pr_reviews.return_value = []
    orch.target_github.get_issue_comments.return_value = [
        {
            "user": {"login": "wanleung"},
            "body": "merge-branch: feature/tests",
        }
    ]
    orch.target_github.get_pr_files.return_value = [
        {"filename": "app/main.py"}
    ]
    orch.target_github.get_file_content.side_effect = lambda path, ref: f"# {path} on {ref}"
    orch.target_github.get_full_tree.return_value = [
        {"path": "tests/test_app.py", "type": "blob", "size": 300},
    ]

    from unittest.mock import MagicMock
    orch.engineer.run_all_modules = MagicMock(return_value={
        "all_files": {"app/main.py": "# fixed main.py"}
    })
    orch.reviewer.run = MagicMock(return_value={"verdict": "APPROVED"})
    orch.qa.run = MagicMock(return_value={"test_files": {}})

    result = orch.run_revision(pr_number=3)

    assert result["status"] == "ok"
    # tests/test_app.py from the merge branch should have been committed
    commit_calls = [call[1] for call in orch.target_github.commit_file.call_args_list]
    committed_paths = [c["path"] for c in commit_calls]
    assert "tests/test_app.py" in committed_paths


def test_run_revision_no_merge_branch_when_no_directive(orch):
    """Without a merge-branch directive, _fetch_branch_files is never called."""
    orch.target_github.get_pr.return_value = {
        "head": {"ref": "feature/impl"},
        "body": "Closes #1",
        "labels": [],
        "title": "Implementation",
    }
    orch.target_github.get_pr_review_comments.return_value = [
        {"user": {"login": "alice"}, "body": "Fix the import", "path": "app/main.py", "line": 5},
    ]
    orch.target_github.get_pr_reviews.return_value = []
    orch.target_github.get_issue_comments.return_value = []
    orch.target_github.get_pr_files.return_value = [{"filename": "app/main.py"}]
    orch.target_github.get_file_content.return_value = "# original"

    from unittest.mock import MagicMock
    orch.engineer.run_all_modules = MagicMock(return_value={
        "all_files": {"app/main.py": "# fixed"}
    })
    orch.reviewer.run = MagicMock(return_value={"verdict": "APPROVED"})
    orch.qa.run = MagicMock(return_value={"test_files": {}})

    orch.run_revision(pr_number=3)

    # get_full_tree should never be called if no merge directives
    orch.target_github.get_full_tree.assert_not_called()
```

- [ ] **Step 3.2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_revision.py -k "incorporates_merge_branch or no_merge_branch_when" -v
```

Expected: `FAILED` — merge branch files not committed / `get_full_tree` still called

- [ ] **Step 3.3: Update `run_revision()` — add merge detection after step 3**

In `orchestrator.py`, inside `run_revision()`, after the line:
```python
feedback_md = self._format_feedback(feedback)
console.print(f"  💬 Collected [bold]{len(feedback)}[/bold] feedback item(s) from PR #{pr_number}")
```

Add:

```python
        # ── 3b. Detect merge directives ───────────────────────────────────────
        merge_branches = self._parse_merge_directives(feedback)
        if merge_branches:
            console.print(
                f"  🔀 Merge directives found: {', '.join(f'[cyan]{b}[/cyan]' for b in merge_branches)}"
            )
```

- [ ] **Step 3.4: Fetch merge branch files after step 5**

After the line:
```python
console.print(f"  📂 Read [bold]{len(current_files)}[/bold] current file(s) from branch [cyan]{head_branch}[/cyan]")
```

Add:

```python
        # ── 5b. Fetch files from merge branches ───────────────────────────────
        merge_branch_files: dict[str, dict[str, str]] = {}
        for mb in merge_branches:
            mb_files = self._fetch_branch_files(mb)
            if mb_files:
                merge_branch_files[mb] = mb_files
                console.print(
                    f"  📂 Fetched [bold]{len(mb_files)}[/bold] file(s) from merge branch [cyan]{mb}[/cyan]"
                )
```

- [ ] **Step 3.5: Inject merge branch files into augmented design (step 6)**

Replace the `augmented_design` assignment with:

```python
        # ── 6. Build augmented design for engineer ────────────────────────────
        current_files_block = "\n\n".join(
            f"### `{path}`\n```\n{self._safe_fence(content)}\n```"
            for path, content in current_files.items()
        )
        merge_branch_blocks = ""
        for mb, mb_files in merge_branch_files.items():
            mb_block = "\n\n".join(
                f"### `{path}`\n```\n{self._safe_fence(content)}\n```"
                for path, content in mb_files.items()
            )
            merge_branch_blocks += (
                f"\n\n---\n\n"
                f"## Files from Branch `{mb}` (incorporate these — make the implementation pass these tests)\n\n"
                f"{mb_block}"
            )
        augmented_design = (
            f"{design}\n\n"
            f"---\n\n"
            f"## Current Code on Branch `{head_branch}`\n\n"
            f"{current_files_block}"
            f"{merge_branch_blocks}\n\n"
            f"---\n\n"
            f"{feedback_md}"
        )
```

- [ ] **Step 3.6: Commit merge branch files after committing revised files (step 7)**

After the `if commit_errors:` early-return block, and before the `console.print(f"  ✅ Committed...")` line, add:

```python
        # Commit files from merge branches that the engineer did not already update
        merge_commit_errors: list[str] = []
        for mb, mb_files in merge_branch_files.items():
            for filepath, content in mb_files.items():
                if filepath in revised_files:
                    continue  # engineer already committed an updated version
                try:
                    self.target_github.commit_file(
                        path=filepath,
                        content=content,
                        message=f"feat: incorporate {filepath} from branch {mb}",
                        branch=head_branch,
                    )
                except RuntimeError as exc:
                    merge_commit_errors.append(f"{filepath}: {exc}")
                    console.print(f"  [yellow]⚠️  Could not commit merge file {filepath}: {exc}[/yellow]")
```

- [ ] **Step 3.7: Update summary comment (step 8) to mention merged branches**

Replace the `summary` string with:

```python
        merge_branch_note = ""
        if merge_branch_files:
            names = ", ".join(f"`{b}`" for b in merge_branch_files)
            total_files = sum(len(v) for v in merge_branch_files.values())
            merge_branch_note = f"\n**Incorporated branches:** {names} ({total_files} file(s))\n"

        summary = (
            f"## ✅ Revision {new_revision} Complete\n\n"
            f"The AI agents have addressed **{len(feedback)} feedback item(s)**:\n\n"
            + "\n".join(
                f"- {item['body'][:120]}{'…' if len(item['body']) > 120 else ''}"
                for item in feedback
            )
            + f"\n\n**Files updated:** {', '.join(f'`{p}`' for p in revised_files)}\n"
            f"**Code review verdict:** {rev_result.get('verdict', 'N/A')}\n"
            f"**Test files updated:** {len(test_files)}"
            + merge_branch_note
        )
```

- [ ] **Step 3.8: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_revision.py -v
```

Expected: all tests pass including the two new integration tests.

- [ ] **Step 3.9: Run the full core test suite**

```bash
python3 -m pytest tests/test_revision.py tests/test_watcher.py tests/test_watcher_dispatch.py tests/test_prd_design_loops.py tests/test_backend_ollama.py -q
```

Expected: all pass.

- [ ] **Step 3.10: Commit**

```bash
git add orchestrator.py tests/test_revision.py
git commit -m "feat: run_revision incorporates files from sibling branches via merge directives

When a PR comment contains a merge directive (merge-branch: <branch>,
merge branch \`<branch>\`, or merge from PR #N), run_revision():
- Fetches all files from the specified branch via GitHub API
- Injects them into the engineer's augmented design context
- Commits them to the implementation branch (skipping files the
  engineer already updated)
- Notes the incorporated branches in the PR summary comment

Trigger format (add to any PR comment):
  merge-branch: feature/agent/1-static-blog-platform
  merge branch \`feature/tests\`
  merge from PR #2"
```

- [ ] **Step 3.11: Push to both remotes**

```bash
git push origin master && git push public master
```

---

## Usage: How to trigger for PR #3 / custom-blog

1. **Post a comment on PR #3** (`wanleung/custom-blog` pull/3):
   ```
   merge-branch: feature/agent/1-static-blog-platform
   ```
2. **Add `ai-fix` label** to PR #3.
3. The watcher picks it up, calls `run_revision(3)`, which reads the comment, fetches the test files from PR #2's branch, incorporates them, and pushes a commit with both the fixed implementation and the tests.
