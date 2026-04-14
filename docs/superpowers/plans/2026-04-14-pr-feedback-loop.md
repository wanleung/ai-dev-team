# PR Feedback Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a human posts a review comment on an AI-generated PR, the engineer → code reviewer → QA agents automatically re-run, address the feedback, and push updated commits to the same branch.

**Architecture:** A new `run_revision(pr_number)` method on `Orchestrator` collects human PR comments (filtering out bot comments), builds a feedback-augmented design doc, re-runs engineer→reviewer→QA against the current branch files, commits the changes, posts a summary comment, and tracks revision rounds via PR labels. A GitHub Actions workflow (`pr-feedback.yml`) triggers this pipeline via `workflow_dispatch`.

**Tech Stack:** Python 3.11, GitHub REST API v3, PyYAML, Rich, existing agent classes, pytest/unittest.mock

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `github_client.py` | Modify | Add 7 new methods: `get_pr`, `get_pr_review_comments`, `get_pr_reviews`, `get_pr_files`, `get_file_content`, `get_issue_comments`, `add_pr_label`, `remove_pr_label` |
| `orchestrator.py` | Modify | Add `max_revisions` field, helper methods, and `run_revision()` |
| `main.py` | Modify | Add `--mode revise --pr N` CLI flags |
| `config.yaml` | Modify | Add `pipeline.max_revisions: 3` |
| `.github/workflows/pr-feedback.yml` | Create | `workflow_dispatch` workflow calling `--mode revise` |
| `roles/engineer.md` | Modify | Add guidance section on incorporating PR feedback |
| `tests/test_github_client_pr.py` | Create | Unit tests for the 8 new `github_client.py` methods |
| `tests/test_revision.py` | Create | Unit tests for orchestrator revision helpers and `run_revision()` |

---

## Task 1: `github_client.py` — new PR read methods + label management

**Files:**
- Modify: `github_client.py` (after line 268, before `ensure_labels`)
- Create: `tests/test_github_client_pr.py`

### Step 1.1 — Write the failing tests

```bash
cat > tests/test_github_client_pr.py << 'EOF'
"""Tests for new PR read methods and label management on GitHubClient."""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call
import base64

import pytest

from github_client import GitHubClient


@pytest.fixture
def client():
    return GitHubClient(repo="owner/repo", github_token="tok")


def _mock_request(client, return_value):
    """Patch _request to return a fixed value."""
    client._request = MagicMock(return_value=return_value)


# ── get_pr ────────────────────────────────────────────────────────────────────

def test_get_pr_calls_correct_endpoint(client):
    _mock_request(client, {"number": 42, "head": {"ref": "feature/x"}})
    result = client.get_pr(42)
    client._request.assert_called_once_with("GET", "/repos/owner/repo/pulls/42")
    assert result["number"] == 42


# ── get_pr_review_comments ────────────────────────────────────────────────────

def test_get_pr_review_comments_returns_list(client):
    _mock_request(client, [{"id": 1, "body": "Fix this"}, {"id": 2, "body": "Also this"}])
    result = client.get_pr_review_comments(7)
    client._request.assert_called_once_with("GET", "/repos/owner/repo/pulls/7/comments")
    assert len(result) == 2


def test_get_pr_review_comments_empty(client):
    _mock_request(client, [])
    assert client.get_pr_review_comments(7) == []


# ── get_pr_reviews ────────────────────────────────────────────────────────────

def test_get_pr_reviews_returns_list(client):
    _mock_request(client, [{"id": 10, "body": "LGTM", "state": "APPROVED"}])
    result = client.get_pr_reviews(7)
    client._request.assert_called_once_with("GET", "/repos/owner/repo/pulls/7/reviews")
    assert result[0]["state"] == "APPROVED"


# ── get_pr_files ──────────────────────────────────────────────────────────────

def test_get_pr_files_returns_list(client):
    _mock_request(client, [{"filename": "src/main.py", "status": "modified"}])
    result = client.get_pr_files(7)
    client._request.assert_called_once_with("GET", "/repos/owner/repo/pulls/7/files")
    assert result[0]["filename"] == "src/main.py"


# ── get_file_content ──────────────────────────────────────────────────────────

def test_get_file_content_decodes_base64(client):
    encoded = base64.b64encode(b"print('hello')").decode()
    _mock_request(client, {"content": encoded + "\n", "encoding": "base64"})
    result = client.get_file_content("src/main.py", ref="feature/x")
    client._request.assert_called_once_with(
        "GET", "/repos/owner/repo/contents/src/main.py", params={"ref": "feature/x"}
    )
    assert result == "print('hello')"


def test_get_file_content_returns_none_on_error(client):
    client._request = MagicMock(side_effect=RuntimeError("404"))
    result = client.get_file_content("missing.py", ref="main")
    assert result is None


# ── get_issue_comments ────────────────────────────────────────────────────────

def test_get_issue_comments_returns_list(client):
    _mock_request(client, [{"id": 5, "body": "## 🏗️ System Design\n\nDesign here", "user": {"login": "bot"}}])
    result = client.get_issue_comments(3)
    client._request.assert_called_once_with("GET", "/repos/owner/repo/issues/3/comments")
    assert result[0]["user"]["login"] == "bot"


# ── add_pr_label ──────────────────────────────────────────────────────────────

def test_add_pr_label_posts_to_issues_endpoint(client):
    _mock_request(client, [{"name": "ai-revision-1"}])
    client.add_pr_label(42, "ai-revision-1")
    client._request.assert_called_once_with(
        "POST", "/repos/owner/repo/issues/42/labels", json={"labels": ["ai-revision-1"]}
    )


# ── remove_pr_label ───────────────────────────────────────────────────────────

def test_remove_pr_label_calls_delete(client):
    _mock_request(client, {})
    client.remove_pr_label(42, "ai-revision-1")
    client._request.assert_called_once_with(
        "DELETE", "/repos/owner/repo/issues/42/labels/ai-revision-1"
    )


def test_remove_pr_label_ignores_404(client):
    client._request = MagicMock(side_effect=RuntimeError("Label does not exist"))
    client.remove_pr_label(42, "ai-revision-99")  # should not raise
EOF
```

- [ ] **Step 1.2 — Run tests to confirm they fail**

```bash
cd /home/wanleung/Projects/ai-software-house && python -m pytest tests/test_github_client_pr.py -v 2>&1 | tail -20
```

Expected: `ImportError` or `AttributeError` — methods not yet defined.

- [ ] **Step 1.3 — Implement the 8 new methods in `github_client.py`**

Add after the `add_pr_comment` method (after line ~268), before `ensure_labels`:

```python
    def get_pr(self, pr_number: int) -> dict:
        """Return pull request metadata."""
        return self._request("GET", f"/repos/{self.repo}/pulls/{pr_number}")

    def get_pr_review_comments(self, pr_number: int) -> list:
        """Return inline review comments on a pull request."""
        return self._request("GET", f"/repos/{self.repo}/pulls/{pr_number}/comments")

    def get_pr_reviews(self, pr_number: int) -> list:
        """Return review-level submissions (APPROVED, CHANGES_REQUESTED, COMMENTED)."""
        return self._request("GET", f"/repos/{self.repo}/pulls/{pr_number}/reviews")

    def get_pr_files(self, pr_number: int) -> list:
        """Return list of files changed in a pull request."""
        return self._request("GET", f"/repos/{self.repo}/pulls/{pr_number}/files")

    def get_file_content(self, path: str, ref: str) -> Optional[str]:
        """Fetch decoded text content of a file at a given ref (branch/sha).

        Returns None if the file does not exist or cannot be decoded.
        """
        import base64 as _b64
        try:
            data = self._request(
                "GET", f"/repos/{self.repo}/contents/{path}", params={"ref": ref}
            )
        except RuntimeError:
            return None
        raw = data.get("content", "")
        try:
            return _b64.b64decode(raw).decode("utf-8")
        except Exception:
            return None

    def get_issue_comments(self, issue_number: int) -> list:
        """Return all comments on an issue (or PR timeline)."""
        return self._request("GET", f"/repos/{self.repo}/issues/{issue_number}/comments")

    def add_pr_label(self, pr_number: int, label_name: str) -> None:
        """Add a label to a pull request (uses the issues labels endpoint)."""
        self._request(
            "POST", f"/repos/{self.repo}/issues/{pr_number}/labels",
            json={"labels": [label_name]},
        )

    def remove_pr_label(self, pr_number: int, label_name: str) -> None:
        """Remove a label from a pull request. Ignores errors if label absent."""
        try:
            self._request(
                "DELETE", f"/repos/{self.repo}/issues/{pr_number}/labels/{label_name}"
            )
        except RuntimeError:
            pass
```

- [ ] **Step 1.4 — Run tests to confirm they pass**

```bash
cd /home/wanleung/Projects/ai-software-house && python -m pytest tests/test_github_client_pr.py -v 2>&1 | tail -20
```

Expected: all 11 tests pass.

- [ ] **Step 1.5 — Commit**

```bash
cd /home/wanleung/Projects/ai-software-house
git add github_client.py tests/test_github_client_pr.py
git commit -m "feat: add PR read methods and label management to GitHubClient

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 2: Orchestrator — revision helpers + `max_revisions` field

**Files:**
- Modify: `orchestrator.py`
- Create: `tests/test_revision.py`

### Step 2.1 — Write the failing tests

```bash
cat > tests/test_revision.py << 'EOF'
"""Tests for orchestrator revision helpers."""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from orchestrator import Orchestrator


@pytest.fixture
def orch(tmp_path):
    """Minimal orchestrator with no real API calls."""
    o = Orchestrator.__new__(Orchestrator)
    o.max_revisions = 3
    o.github = MagicMock()
    o.target_github = MagicMock()
    o._github_token = "tok"
    return o


# ── _get_revision_number ──────────────────────────────────────────────────────

def test_get_revision_number_none(orch):
    assert orch._get_revision_number([]) == 0

def test_get_revision_number_single(orch):
    assert orch._get_revision_number(["ai-generated", "ai-revision-2"]) == 2

def test_get_revision_number_highest(orch):
    assert orch._get_revision_number(["ai-revision-1", "ai-revision-3", "ai-revision-2"]) == 3


# ── _extract_issue_number ─────────────────────────────────────────────────────

def test_extract_issue_number_closes(orch):
    assert orch._extract_issue_number("Some text\nCloses #42\nmore") == 42

def test_extract_issue_number_related(orch):
    assert orch._extract_issue_number("Related to #7") == 7

def test_extract_issue_number_none(orch):
    assert orch._extract_issue_number("No reference here") is None


# ── _collect_pr_feedback ──────────────────────────────────────────────────────

def test_collect_pr_feedback_filters_bot(orch):
    orch.target_github.get_pr_review_comments.return_value = [
        {"user": {"login": "alice"}, "body": "Fix the import", "path": "src/main.py", "line": 10},
        {"user": {"login": "github-actions[bot]"}, "body": "Bot comment", "path": "src/main.py", "line": 1},
    ]
    orch.target_github.get_pr_reviews.return_value = [
        {"user": {"login": "bob"}, "body": "Please add tests", "state": "CHANGES_REQUESTED"},
        {"user": {"login": "github-actions[bot]"}, "body": "Bot review", "state": "COMMENTED"},
    ]
    feedback = orch._collect_pr_feedback(pr_number=1)
    assert len(feedback) == 2
    assert all(f["author"] != "github-actions[bot]" for f in feedback)
    bodies = [f["body"] for f in feedback]
    assert "Fix the import" in bodies
    assert "Please add tests" in bodies


def test_collect_pr_feedback_empty_when_all_bot(orch):
    orch.target_github.get_pr_review_comments.return_value = [
        {"user": {"login": "github-actions[bot]"}, "body": "Bot", "path": "a.py", "line": 1},
    ]
    orch.target_github.get_pr_reviews.return_value = []
    assert orch._collect_pr_feedback(1) == []


# ── _format_feedback ──────────────────────────────────────────────────────────

def test_format_feedback_includes_all_items(orch):
    items = [
        {"author": "alice", "body": "Fix the import", "location": "src/main.py line 10"},
        {"author": "bob", "body": "Add docstring", "location": "review"},
    ]
    md = orch._format_feedback(items)
    assert "Fix the import" in md
    assert "Add docstring" in md
    assert "alice" in md
    assert "bob" in md


# ── _fetch_design_from_issue ──────────────────────────────────────────────────

def test_fetch_design_from_issue_finds_architect_comment(orch):
    orch.github.get_issue_comments.return_value = [
        {"body": "## 📋 PRD\n\nSome product doc", "user": {"login": "github-actions[bot]"}},
        {"body": "## 🏗️ System Design (Architect)\n\nThe full architecture here", "user": {"login": "github-actions[bot]"}},
        {"body": "Random human comment", "user": {"login": "alice"}},
    ]
    design = orch._fetch_design_from_issue(issue_number=5)
    assert "System Design" in design
    assert "architecture here" in design


def test_fetch_design_from_issue_returns_empty_string_when_not_found(orch):
    orch.github.get_issue_comments.return_value = [
        {"body": "Just a comment", "user": {"login": "alice"}},
    ]
    assert orch._fetch_design_from_issue(5) == ""
EOF
```

- [ ] **Step 2.2 — Run to confirm failures**

```bash
cd /home/wanleung/Projects/ai-software-house && python -m pytest tests/test_revision.py -v 2>&1 | tail -30
```

Expected: `AttributeError` — `_get_revision_number` etc not defined.

- [ ] **Step 2.3 — Add `max_revisions` to `Orchestrator.__init__` and `from_config()`**

In `orchestrator.py`, find the `__init__` method. After the existing fields (around `self.use_github = ...`), add:

```python
        self.max_revisions: int = 3
```

In `from_config()`, after the `pipeline:` block is already parsed (or add a new block), add:

```python
        pipeline_cfg = cfg.get("pipeline", {})
        orch.max_revisions = int(pipeline_cfg.get("max_revisions", 3))
```

- [ ] **Step 2.4 — Add the 4 helper methods to `Orchestrator`**

Add these methods inside the `Orchestrator` class (after `_deep_merge` or near the top of the instance methods):

```python
    # ── Revision helpers ──────────────────────────────────────────────────────

    def _get_revision_number(self, labels: list[str]) -> int:
        """Return the highest ai-revision-N number found in labels, or 0."""
        import re
        nums = [int(m.group(1)) for lbl in labels if (m := re.fullmatch(r"ai-revision-(\d+)", lbl))]
        return max(nums, default=0)

    def _extract_issue_number(self, body: str) -> Optional[int]:
        """Extract a GitHub issue number from phrases like 'Closes #42' or 'Related to #7'."""
        import re
        m = re.search(r"(?:Closes|Related to|Fixes|Resolves)\s+#(\d+)", body, re.IGNORECASE)
        return int(m.group(1)) if m else None

    def _collect_pr_feedback(self, pr_number: int) -> list[dict]:
        """Return non-bot PR review comments and review bodies as a flat list.

        Each item: {"author": str, "body": str, "location": str}
        """
        bot_logins = {"github-actions[bot]", "copilot[bot]"}

        inline = self.target_github.get_pr_review_comments(pr_number)
        reviews = self.target_github.get_pr_reviews(pr_number)

        feedback = []
        for c in inline:
            login = c.get("user", {}).get("login", "")
            if login in bot_logins:
                continue
            body = (c.get("body") or "").strip()
            if not body:
                continue
            location = f"{c.get('path', '?')} line {c.get('line') or c.get('original_line', '?')}"
            feedback.append({"author": login, "body": body, "location": location})

        for r in reviews:
            login = r.get("user", {}).get("login", "")
            if login in bot_logins:
                continue
            body = (r.get("body") or "").strip()
            if not body:
                continue
            feedback.append({"author": login, "body": body, "location": "review"})

        return feedback

    def _format_feedback(self, feedback: list[dict]) -> str:
        """Format a list of feedback dicts as a markdown bullet list."""
        lines = ["### PR Feedback to Address\n"]
        for item in feedback:
            location = f" _(at {item['location']})_" if item["location"] != "review" else ""
            lines.append(f"- **{item['author']}**{location}: {item['body']}")
        return "\n".join(lines)

    def _fetch_design_from_issue(self, issue_number: int) -> str:
        """Read issue comments to find the architect's system design post.

        Returns the body of the first comment containing '🏗️ System Design',
        or an empty string if not found.
        """
        comments = self.github.get_issue_comments(issue_number)
        for c in comments:
            body = c.get("body", "")
            if "System Design" in body and "🏗️" in body:
                return body
        return ""
```

- [ ] **Step 2.5 — Run tests to confirm they pass**

```bash
cd /home/wanleung/Projects/ai-software-house && python -m pytest tests/test_revision.py -v 2>&1 | tail -30
```

Expected: all tests pass.

- [ ] **Step 2.6 — Commit**

```bash
cd /home/wanleung/Projects/ai-software-house
git add orchestrator.py tests/test_revision.py
git commit -m "feat: add revision helpers and max_revisions to Orchestrator

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 3: Orchestrator — `run_revision()` method

**Files:**
- Modify: `orchestrator.py`
- Modify: `tests/test_revision.py` (add integration-level test)

- [ ] **Step 3.1 — Add tests for `run_revision()`**

Append to `tests/test_revision.py`:

```python
# ── run_revision ──────────────────────────────────────────────────────────────

def test_run_revision_exits_when_max_revisions_reached(orch):
    orch.target_github.get_pr.return_value = {
        "head": {"ref": "feature/my-app"},
        "body": "Closes #3",
        "labels": [{"name": "ai-generated"}, {"name": "ai-revision-3"}],
    }
    result = orch.run_revision(pr_number=10)
    assert result["status"] == "max_revisions_reached"
    orch.target_github.add_pr_comment.assert_called_once()
    comment_body = orch.target_github.add_pr_comment.call_args[0][1]
    assert "Max revisions reached" in comment_body


def test_run_revision_exits_when_no_human_feedback(orch):
    orch.target_github.get_pr.return_value = {
        "head": {"ref": "feature/my-app"},
        "body": "Closes #3",
        "labels": [{"name": "ai-generated"}],
    }
    orch.target_github.get_pr_review_comments.return_value = []
    orch.target_github.get_pr_reviews.return_value = []
    result = orch.run_revision(pr_number=10)
    assert result["status"] == "no_feedback"
```

- [ ] **Step 3.2 — Run to confirm failures**

```bash
cd /home/wanleung/Projects/ai-software-house && python -m pytest tests/test_revision.py::test_run_revision_exits_when_max_revisions_reached tests/test_revision.py::test_run_revision_exits_when_no_human_feedback -v 2>&1 | tail -15
```

Expected: `AttributeError: 'Orchestrator' object has no attribute 'run_revision'`

- [ ] **Step 3.3 — Implement `run_revision()` in `orchestrator.py`**

Add this method inside `Orchestrator`, after the helper methods from Task 2:

```python
    def run_revision(self, pr_number: int) -> dict:
        """Re-run engineer→reviewer→QA for a PR based on human review comments.

        Reads all non-bot review comments from the PR, re-generates the code
        incorporating the feedback, pushes commits to the same branch, posts a
        summary comment, and updates the ai-revision-N label.

        Returns a dict with a "status" key:
          - "max_revisions_reached" — revision cap hit, nothing done
          - "no_feedback"           — no human comments found, nothing done
          - "ok"                    — revision committed, "revision" key has round number
        """
        if self.target_github is None:
            raise RuntimeError("target_github is required for run_revision()")

        # ── 1. PR metadata ────────────────────────────────────────────────────
        pr = self.target_github.get_pr(pr_number)
        head_branch = pr["head"]["ref"]
        pr_body = pr.get("body") or ""
        labels = [lbl["name"] for lbl in pr.get("labels", [])]

        # ── 2. Check revision cap ─────────────────────────────────────────────
        current_rev = self._get_revision_number(labels)
        if current_rev >= self.max_revisions:
            self.target_github.add_pr_comment(
                pr_number,
                f"⏹ Max revisions reached ({current_rev}/{self.max_revisions}). "
                "No further automated revisions will be made.",
            )
            return {"status": "max_revisions_reached"}

        # ── 3. Collect human feedback ─────────────────────────────────────────
        feedback = self._collect_pr_feedback(pr_number)
        if not feedback:
            return {"status": "no_feedback"}

        feedback_md = self._format_feedback(feedback)
        console.print(f"  💬 Collected [bold]{len(feedback)}[/bold] feedback item(s) from PR #{pr_number}")

        # ── 4. Fetch design from linked issue ─────────────────────────────────
        issue_number = self._extract_issue_number(pr_body)
        design = self._fetch_design_from_issue(issue_number) if issue_number else ""
        if not design:
            console.print("  [yellow]⚠️  No system design found in linked issue — engineer will use feedback only[/yellow]")

        # ── 5. Read current files from branch ─────────────────────────────────
        pr_files = self.target_github.get_pr_files(pr_number)
        current_files: dict[str, str] = {}
        for f in pr_files:
            path = f["filename"]
            content = self.target_github.get_file_content(path, ref=head_branch)
            if content is not None:
                current_files[path] = content

        console.print(f"  📂 Read [bold]{len(current_files)}[/bold] current file(s) from branch [cyan]{head_branch}[/cyan]")

        # ── 6. Build augmented design for engineer ────────────────────────────
        current_files_block = "\n\n".join(
            f"### `{path}`\n```\n{content}\n```"
            for path, content in current_files.items()
        )
        augmented_design = (
            f"{design}\n\n"
            f"---\n\n"
            f"## Current Code on Branch `{head_branch}`\n\n"
            f"{current_files_block}\n\n"
            f"---\n\n"
            f"{feedback_md}"
        )

        # ── 7. Re-run engineer → reviewer → QA ───────────────────────────────
        new_revision = current_rev + 1
        console.print(f"\n[bold cyan]🔄 Revision {new_revision}/{self.max_revisions}[/bold cyan]")

        revision_modules = [
            {
                "name": "Revision",
                "description": (
                    f"Revise the existing code to address all PR feedback listed above. "
                    f"Return updated versions of these files: {', '.join(current_files.keys())}. "
                    f"Only change what is necessary to address the feedback."
                ),
            }
        ]

        project_name = pr.get("title", f"PR #{pr_number}").replace("[Implementation] ", "")

        # Engineer: generate revised files
        self._run_stage(
            "👷 Engineer (revision)",
            "Revising code based on PR feedback...",
            type("_R", (), {"errors": [], "completed_stages": []})(),
            lambda: None,  # dummy — we call engineer directly below
        )

        eng_result = self.engineer.run_all_modules(augmented_design, revision_modules, project_name)
        revised_files: dict[str, str] = eng_result.get("all_files", {})

        # Commit revised files to the existing branch
        for filepath, content in revised_files.items():
            self.target_github.commit_file(
                path=filepath,
                content=content,
                message=f"fix: revision {new_revision} — address PR feedback [{filepath}]",
                branch=head_branch,
            )

        console.print(f"  ✅ Committed [bold]{len(revised_files)}[/bold] revised file(s) to [cyan]{head_branch}[/cyan]")

        # Code Reviewer
        rev_result = self.reviewer.run(revised_files, design or "N/A", project_name)
        console.print(f"  🔍 Code review verdict: [bold]{rev_result.get('verdict', '?')}[/bold]")

        # QA Engineer
        qa_result = self.qa.run(revised_files, design or "N/A", project_name)
        test_files: dict[str, str] = qa_result.get("test_files", {})
        for filepath, content in test_files.items():
            self.target_github.commit_file(
                path=filepath,
                content=content,
                message=f"test: revision {new_revision} — update tests [{filepath}]",
                branch=head_branch,
            )

        # ── 8. Update label and post summary comment ──────────────────────────
        old_label = f"ai-revision-{current_rev}" if current_rev > 0 else None
        new_label = f"ai-revision-{new_revision}"

        # Ensure label exists (create if missing)
        self.target_github.ensure_labels([{"name": new_label, "color": "0075ca", "description": f"AI revision round {new_revision}"}])
        if old_label:
            self.target_github.remove_pr_label(pr_number, old_label)
        self.target_github.add_pr_label(pr_number, new_label)

        summary = (
            f"## ✅ Revision {new_revision} Complete\n\n"
            f"The AI agents have addressed **{len(feedback)} feedback item(s)**:\n\n"
            + "\n".join(f"- {item['body'][:120]}" for item in feedback)
            + f"\n\n**Files updated:** {', '.join(f'`{p}`' for p in revised_files)}\n"
            f"**Code review verdict:** {rev_result.get('verdict', 'N/A')}\n"
            f"**Test files updated:** {len(test_files)}"
        )
        self.target_github.add_pr_comment(pr_number, summary)

        return {"status": "ok", "revision": new_revision, "files_updated": len(revised_files)}
```

> **Note:** The `_run_stage` call in the implementation above is simplified — replace it with a direct `console.print` if `_run_stage` requires a full `PipelineResult`. The engineer, reviewer, and QA are called directly without going through the stage methods, since the revision flow is simpler than the full pipeline.

Actually, simplify by removing the `_run_stage` call entirely and using `console.print` for status:

Replace the `_run_stage(...)` and `lambda` block with:
```python
        console.print("  👷 [cyan]Engineer[/cyan] — revising code based on PR feedback...")
```

- [ ] **Step 3.4 — Run the new tests**

```bash
cd /home/wanleung/Projects/ai-software-house && python -m pytest tests/test_revision.py -v 2>&1 | tail -30
```

Expected: all tests pass.

- [ ] **Step 3.5 — Commit**

```bash
cd /home/wanleung/Projects/ai-software-house
git add orchestrator.py
git commit -m "feat: add run_revision() to Orchestrator

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 4: `main.py` + `config.yaml` — CLI `--mode revise` + config field

**Files:**
- Modify: `main.py`
- Modify: `config.yaml`
- Modify: `orchestrator.py` — ensure `from_config()` reads `pipeline.max_revisions`

- [ ] **Step 4.1 — Add `pipeline.max_revisions` to `config.yaml`**

Find the `pipeline:` section in `config.yaml` (or add it if absent):

```yaml
pipeline:
  max_revisions: 3   # Maximum automated revision rounds per PR (0 = disabled)
```

- [ ] **Step 4.2 — Wire `max_revisions` in `from_config()`**

In `orchestrator.py`, inside `from_config()`, find where `pipeline_cfg` is built (or add it). After building the orchestrator object (`orch = cls(...)`):

```python
        pipeline_cfg = cfg.get("pipeline", {})
        orch.max_revisions = int(pipeline_cfg.get("max_revisions", 3))
```

Verify `from_config()` doesn't already read this — search for `max_revisions` to confirm it's not already there.

- [ ] **Step 4.3 — Add `--mode` and `--pr` to `main.py`**

In `parse_args()`, add two new arguments after the existing `--refactor` argument:

```python
    parser.add_argument(
        "--mode",
        choices=["build", "revise"],
        default="build",
        help="Pipeline mode: 'build' (default) builds new software; 'revise' processes PR feedback.",
    )
    parser.add_argument(
        "--pr",
        type=int,
        metavar="PR_NUMBER",
        help="Pull request number to revise (required when --mode=revise).",
    )
```

- [ ] **Step 4.4 — Add the `revise` branch in `main()`**

In `main()`, find the `# ── Run the pipeline ──` block and replace the existing `if args.refactor:` chain with:

```python
    # ── Run the pipeline ──────────────────────────────────────────────────────
    try:
        if args.refactor or (hasattr(args, "mode") and args.mode == "build" and False):
            # kept for backward compat — --refactor still works
            pass

        if args.refactor:
            refactor_result = orch.refactor()
            if refactor_result.get("pr_url"):
                console.print(f"\n[bold green]🌙 Refactor complete![/bold green] PR: {refactor_result['pr_url']}")
            else:
                console.print("\n[bold green]🌙 Refactor analysis complete![/bold green] (No PR — GitHub not configured or no changes)")
            return 0

        if getattr(args, "mode", "build") == "revise":
            if not args.pr:
                console.print("[red]--pr PR_NUMBER is required when --mode=revise[/red]")
                return 1
            if not orch.target_github and not orch.use_github:
                console.print("[red]GitHub integration required for --mode=revise. Set --repo or configure target_repo in config.yaml[/red]")
                return 1
            revision_result = orch.run_revision(args.pr)
            status = revision_result.get("status")
            if status == "max_revisions_reached":
                console.print("\n[yellow]⏹ Max revisions reached — no changes made.[/yellow]")
            elif status == "no_feedback":
                console.print("\n[dim]No human feedback found — no changes made.[/dim]")
            else:
                rev_num = revision_result.get("revision", "?")
                files = revision_result.get("files_updated", 0)
                console.print(f"\n[bold green]✅ Revision {rev_num} complete![/bold green] {files} file(s) updated.")
            return 0

        result = orch.run(requirement, resume=not args.no_resume)
    except KeyboardInterrupt:
```

> **Important:** Remove the intermediate dead-code `if ... and False:` block — that was just a placeholder. The final structure should be: `if args.refactor: ... return 0` then `if args.mode == "revise": ... return 0` then `result = orch.run(...)`.

- [ ] **Step 4.5 — Verify `--mode revise` shows help correctly**

```bash
cd /home/wanleung/Projects/ai-software-house && python main.py --help 2>&1 | grep -A3 "mode\|--pr"
```

Expected: `--mode {build,revise}` and `--pr PR_NUMBER` appear in help.

- [ ] **Step 4.6 — Verify revise mode requires `--pr`**

```bash
cd /home/wanleung/Projects/ai-software-house && python main.py --mode revise 2>&1
```

Expected: `--pr PR_NUMBER is required when --mode=revise`

- [ ] **Step 4.7 — Run all existing tests**

```bash
cd /home/wanleung/Projects/ai-software-house && python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: all tests pass.

- [ ] **Step 4.8 — Commit**

```bash
cd /home/wanleung/Projects/ai-software-house
git add main.py config.yaml orchestrator.py
git commit -m "feat: add --mode revise --pr N CLI flag and max_revisions config

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 5: `.github/workflows/pr-feedback.yml` — GitHub Actions workflow

**Files:**
- Create: `.github/workflows/pr-feedback.yml`

- [ ] **Step 5.1 — Create the workflow file**

```bash
cat > /home/wanleung/Projects/ai-software-house/.github/workflows/pr-feedback.yml << 'EOF'
name: 🔄 AI PR Feedback Loop

# Triggers:
#   1. Manually via GitHub UI (primary — specify PR number and target repo)
#   2. Via API using repository_dispatch (for automation from target repos)
#
# For automatic triggering from the target repo, add a workflow to the target
# repo that sends a repository_dispatch event to wanleung/ai-software-house
# when a pull_request_review or pull_request_review_comment event fires.
on:
  workflow_dispatch:
    inputs:
      pr_number:
        description: "PR number to revise (in the target repo)"
        required: true
        type: number
      target_repo:
        description: "Target repo (owner/repo) where the PR lives"
        required: false
        type: string

  repository_dispatch:
    types: [ai-pr-revise]

concurrency:
  group: ai-revise-pr-${{ github.event.inputs.pr_number || github.event.client_payload.pr_number }}
  cancel-in-progress: false

jobs:
  revise:
    name: Run AI Revision Pipeline
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write
      issues: write

    steps:
      - name: Checkout ai-software-house
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Determine PR number and target repo
        id: params
        run: |
          if [ "${{ github.event_name }}" = "workflow_dispatch" ]; then
            echo "pr_number=${{ github.event.inputs.pr_number }}" >> $GITHUB_OUTPUT
            echo "target_repo=${{ github.event.inputs.target_repo || secrets.TARGET_REPO }}" >> $GITHUB_OUTPUT
          else
            echo "pr_number=${{ github.event.client_payload.pr_number }}" >> $GITHUB_OUTPUT
            echo "target_repo=${{ github.event.client_payload.target_repo || secrets.TARGET_REPO }}" >> $GITHUB_OUTPUT
          fi

      - name: Run revision pipeline
        run: |
          python main.py --mode revise --pr ${{ steps.params.outputs.pr_number }} \
            --repo ${{ steps.params.outputs.target_repo }}
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          TARGET_REPO: ${{ steps.params.outputs.target_repo }}
EOF
```

- [ ] **Step 5.2 — Verify YAML is valid**

```bash
cd /home/wanleung/Projects/ai-software-house && python -c "import yaml; yaml.safe_load(open('.github/workflows/pr-feedback.yml'))" && echo "YAML OK"
```

Expected: `YAML OK`

- [ ] **Step 5.3 — Commit**

```bash
cd /home/wanleung/Projects/ai-software-house
git add .github/workflows/pr-feedback.yml
git commit -m "feat: add pr-feedback.yml workflow for AI PR revision loop

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 6: `roles/engineer.md` — PR feedback guidance

**Files:**
- Modify: `roles/engineer.md`

- [ ] **Step 6.1 — Check current file**

```bash
tail -20 /home/wanleung/Projects/ai-software-house/roles/engineer.md
```

- [ ] **Step 6.2 — Append PR feedback guidance section**

Add the following section at the end of `roles/engineer.md`:

```markdown

---

## Incorporating PR Review Feedback

When you receive a task that includes a **"## PR Feedback to Address"** section and **"## Current Code on Branch"**, you are in **revision mode**. Your job is to fix the existing code, not write it from scratch.

**Rules for revision mode:**

1. **Read the current code carefully** — it's in the "Current Code on Branch" section.
2. **Address every feedback item** — list each one and state what you changed.
3. **Minimal diff principle** — only change what is necessary. Do not restructure or rename unless the feedback asks for it.
4. **Preserve working parts** — if code is correct and not mentioned in feedback, keep it.
5. **Return all files** — even unchanged files must be returned in your output so the system can commit them correctly.
6. **Explain your changes** — add a brief comment in your response summarising what you changed and why (not in the code comments, in your reasoning block).
```

- [ ] **Step 6.3 — Commit**

```bash
cd /home/wanleung/Projects/ai-software-house
git add roles/engineer.md
git commit -m "docs: add PR feedback revision guidance to engineer role

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 7: Final integration check + push

- [ ] **Step 7.1 — Run full test suite**

```bash
cd /home/wanleung/Projects/ai-software-house && python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: all tests pass (including existing 14 Ollama tests + new PR client tests + new revision tests).

- [ ] **Step 7.2 — Verify `--mode revise` CLI works end-to-end (dry run)**

```bash
cd /home/wanleung/Projects/ai-software-house && python main.py --mode revise --pr 99 --no-github 2>&1
```

Expected: `GitHub integration required for --mode=revise` error (expected — confirms CLI path works).

- [ ] **Step 7.3 — Push to GitHub**

```bash
cd /home/wanleung/Projects/ai-software-house && git push origin master
```

- [ ] **Step 7.4 — Verify workflow appears in GitHub Actions**

```bash
gh workflow list --repo wanleung/ai-software-house 2>&1 | grep -i "feedback\|revise"
```

Expected: `🔄 AI PR Feedback Loop` appears.

---

## Known Limitation / Future Work

The `pr-feedback.yml` workflow in `ai-software-house` uses `workflow_dispatch` as its primary trigger. For **fully automatic** triggering (no manual step), the generated target repo must also include a `.github/workflows/ai-revise-hook.yml` that fires a `repository_dispatch` event to `wanleung/ai-software-house` when a PR review is submitted. Generating this hook file can be added to the engineer's output in a future iteration.
