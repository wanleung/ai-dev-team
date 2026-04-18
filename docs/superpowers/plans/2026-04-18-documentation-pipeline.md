# Documentation Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a lightweight `documentation` pipeline type so the watcher dispatches a `DocumentationAgent` + `DocOrchestrator` when an issue has a `doc_label`, writing/updating docs in the target repo and opening a PR — without running the full feature pipeline.

**Architecture:** `agents/documentation_agent.py` is a `BaseAgent` subclass with three GitHub-API-backed tools (`list_files`, `read_file`, `search_files`). `doc_orchestrator.py` drives the agent, commits its output to a branch, and opens a PR. `watcher.py` gains a `doc_label` config key and a `"documentation"` dispatch path.

**Tech Stack:** Python 3.11+, existing `BaseAgent` / `GitHubClient` patterns, `pytest` for tests, GitHub REST API (contents + git/trees endpoints for listing/searching).

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `github_client.py` | Add `list_files(path, ref)` and `search_files(pattern, ref)` methods |
| Create | `agents/documentation_agent.py` | LLM agent: reads repo files via tools, returns `file_writes[]` |
| Create | `doc_orchestrator.py` | Thin orchestrator: issue → agent → branch → commit → PR |
| Modify | `watcher.py` | Add `doc_label` config key + `"documentation"` queue + `_dispatch` case |
| Modify | `repos.yaml` | Document `doc_label` key with example |
| Create | `tests/test_documentation_agent.py` | Unit tests for `DocumentationAgent` |
| Create | `tests/test_doc_orchestrator.py` | Unit tests for `DocOrchestrator` |

---

## Task 1: Add `list_files` and `search_files` to `GitHubClient`

**Files:**
- Modify: `github_client.py`
- Test: `tests/test_github_client_pr.py` (add to existing file)

These methods back the agent's tool calls. `list_files` uses the GitHub contents API; `search_files` fetches the full git tree and filters by glob pattern.

- [ ] **Step 1: Write failing tests**

Add to `tests/test_github_client_pr.py`:

```python
from unittest.mock import patch, MagicMock
from github_client import GitHubClient


def _make_client():
    return GitHubClient("owner/repo", token="tok")


def test_list_files_returns_names():
    client = _make_client()
    mock_resp = [
        {"name": "README.md", "type": "file", "path": "README.md"},
        {"name": "docs", "type": "dir", "path": "docs"},
    ]
    with patch.object(client, "_request", return_value=mock_resp):
        result = client.list_files("", ref="main")
    assert result == [
        {"name": "README.md", "type": "file", "path": "README.md"},
        {"name": "docs", "type": "dir", "path": "docs"},
    ]


def test_list_files_with_path():
    client = _make_client()
    with patch.object(client, "_request", return_value=[]) as mock_req:
        client.list_files("docs", ref="main")
    mock_req.assert_called_once_with(
        "GET", "/repos/owner/repo/contents/docs", params={"ref": "main"}
    )


def test_search_files_glob_md():
    client = _make_client()
    tree = {
        "tree": [
            {"path": "README.md", "type": "blob"},
            {"path": "docs/api.md", "type": "blob"},
            {"path": "src/main.py", "type": "blob"},
            {"path": "docs/images", "type": "tree"},
        ]
    }
    with patch.object(client, "_request", return_value=tree):
        result = client.search_files("**/*.md", ref="main")
    assert set(result) == {"README.md", "docs/api.md"}


def test_search_files_specific_name():
    client = _make_client()
    tree = {
        "tree": [
            {"path": "README.md", "type": "blob"},
            {"path": "CONTRIBUTING.md", "type": "blob"},
        ]
    }
    with patch.object(client, "_request", return_value=tree):
        result = client.search_files("README.md", ref="main")
    assert result == ["README.md"]
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd ~/Projects/ai-software-house && source venv/bin/activate
pytest tests/test_github_client_pr.py::test_list_files_returns_names tests/test_github_client_pr.py::test_search_files_glob_md -v
```

Expected: `AttributeError: 'GitHubClient' object has no attribute 'list_files'`

- [ ] **Step 3: Implement `list_files` and `search_files` in `github_client.py`**

Add after `get_file_content` (around line 302):

```python
def list_files(self, path: str = "", ref: Optional[str] = None) -> list[dict]:
    """List files and directories at `path` in the repo.

    Returns a list of dicts with keys: name, type ('file'|'dir'), path.
    """
    params: dict = {}
    if ref:
        params["ref"] = ref
    url_path = f"/repos/{self.repo}/contents/{path}".rstrip("/")
    result = self._request("GET", url_path, params=params or None)
    if isinstance(result, list):
        return [{"name": e["name"], "type": e["type"] if e["type"] != "dir" else "dir", "path": e["path"]} for e in result]
    # Single file returned (happens when path points to a file, not dir)
    return [{"name": result["name"], "type": "file", "path": result["path"]}]

def search_files(self, pattern: str, ref: Optional[str] = None) -> list[str]:
    """Return all file paths in the repo matching a glob pattern.

    Uses the git tree API (recursive) — pattern matched with fnmatch.
    Returns list of file paths (blobs only, no trees).
    """
    import fnmatch
    params: dict = {"recursive": "1"}
    if ref:
        params["sha"] = ref
    sha = ref or self.get_default_branch()
    tree_data = self._request(
        "GET", f"/repos/{self.repo}/git/trees/{sha}", params={"recursive": "1"}
    )
    blobs = [e["path"] for e in tree_data.get("tree", []) if e["type"] == "blob"]
    return [p for p in blobs if fnmatch.fnmatch(p, pattern)]
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_github_client_pr.py::test_list_files_returns_names \
       tests/test_github_client_pr.py::test_list_files_with_path \
       tests/test_github_client_pr.py::test_search_files_glob_md \
       tests/test_github_client_pr.py::test_search_files_specific_name -v
```

Expected: 4 passed

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
pytest --tb=short -q
```

Expected: same pass count as before (≥132 passed, 0 failures)

- [ ] **Step 6: Commit**

```bash
git add github_client.py tests/test_github_client_pr.py
git commit -m "feat: add list_files and search_files to GitHubClient"
```

---

## Task 2: Create `DocumentationAgent`

**Files:**
- Create: `agents/documentation_agent.py`
- Create: `tests/test_documentation_agent.py`

The agent receives issue title + body, reads existing repo files via tool calls, and returns a list of `{"path": str, "content": str, "action": "create"|"update"}` dicts.

- [ ] **Step 1: Write failing tests**

Create `tests/test_documentation_agent.py`:

```python
"""Unit tests for DocumentationAgent."""
import json
from unittest.mock import MagicMock, patch
import pytest
from agents.documentation_agent import DocumentationAgent


def _make_agent():
    agent = DocumentationAgent.__new__(DocumentationAgent)
    agent.model = "gpt-4.1"
    agent.system_prompt = "you are a doc agent"
    agent._retry_delay = 1
    agent._max_api_retries = 1
    agent._inter_call_delay = 0
    agent._history = []
    agent._backend = "github_models"
    agent._gh = MagicMock()
    agent._target_repo = "owner/repo"
    agent._target_ref = "main"
    return agent


def test_parse_doc_targets_from_body():
    agent = _make_agent()
    body = "Fix the docs.\n\n**Docs:** README.md, docs/api.md"
    result = agent._parse_doc_targets(body)
    assert result == ["README.md", "docs/api.md"]


def test_parse_doc_targets_missing():
    agent = _make_agent()
    result = agent._parse_doc_targets("Just update everything.")
    assert result == []


def test_run_returns_file_writes(monkeypatch):
    agent = _make_agent()
    file_writes = [
        {"path": "README.md", "content": "# Updated\n", "action": "update"}
    ]
    monkeypatch.setattr(agent, "call_with_tools", lambda *a, **kw: json.dumps(file_writes))
    result = agent.run(
        issue_title="Update README",
        issue_body="Please update the README.\n\n**Docs:** README.md",
        target_repo="owner/repo",
        github_token="tok",
    )
    assert isinstance(result, list)
    assert result[0]["path"] == "README.md"
    assert result[0]["action"] == "update"


def test_run_raises_on_empty_writes(monkeypatch):
    agent = _make_agent()
    monkeypatch.setattr(agent, "call_with_tools", lambda *a, **kw: "[]")
    with pytest.raises(ValueError, match="no file writes"):
        agent.run(
            issue_title="Update README",
            issue_body="Please update the README.",
            target_repo="owner/repo",
            github_token="tok",
        )


def test_tool_list_files(monkeypatch):
    agent = _make_agent()
    agent._gh.list_files.return_value = [
        {"name": "README.md", "type": "file", "path": "README.md"}
    ]
    result = agent._tool_list_files({"path": ""})
    agent._gh.list_files.assert_called_once_with("", ref="main")
    assert "README.md" in result


def test_tool_read_file(monkeypatch):
    agent = _make_agent()
    agent._gh.get_file_content.return_value = "# Hello\n"
    result = agent._tool_read_file({"path": "README.md"})
    assert "# Hello" in result


def test_tool_search_files(monkeypatch):
    agent = _make_agent()
    agent._gh.search_files.return_value = ["README.md", "docs/api.md"]
    result = agent._tool_search_files({"pattern": "**/*.md"})
    assert "README.md" in result
    assert "docs/api.md" in result
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_documentation_agent.py -v
```

Expected: `ModuleNotFoundError: No module named 'agents.documentation_agent'`

- [ ] **Step 3: Implement `agents/documentation_agent.py`**

```python
"""DocumentationAgent: reads repo files via GitHub API tools and writes documentation."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from agents.base_agent import BaseAgent
from github_client import GitHubClient


_SYSTEM_PROMPT = """\
You are a technical documentation writer for a software project.

You have three tools to read files from the target repository:
- list_files(path): list files and directories at a path (use "" for root)
- read_file(path): read the full content of a file
- search_files(pattern): find files matching a glob (e.g. "**/*.md", "**/*.py")

Your task:
1. Read the issue title and body carefully.
2. If the body contains "**Docs:** file1, file2", read those files first.
3. Otherwise, discover relevant documentation files by listing/searching the repo.
4. Read related source files when you need to document APIs, classes, or functions.
5. Produce updated or new documentation that fully addresses the issue.

When you are done reading and are ready to write, return ONLY a JSON array (no markdown fences,
no explanation) of file write objects:

[
  {"path": "README.md", "content": "# Full updated content here\\n", "action": "update"},
  {"path": "docs/new-guide.md", "content": "# New Guide\\n...", "action": "create"}
]

Rules:
- "action" must be "create" or "update"
- "content" must be the COMPLETE file content (not a diff)
- Do not include files you did not change
- Return an empty array [] ONLY if nothing needs changing (but try hard to be useful)
"""

_TOOLS = [
    {
        "name": "list_files",
        "description": "List files and directories at a path in the target repo.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path (empty string for root)"}
            },
            "required": ["path"],
        },
    },
    {
        "name": "read_file",
        "description": "Read the full text content of a file in the target repo.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to repo root"}
            },
            "required": ["path"],
        },
    },
    {
        "name": "search_files",
        "description": "Find file paths matching a glob pattern (e.g. '**/*.md', '**/*.py').",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern to match file paths"}
            },
            "required": ["pattern"],
        },
    },
]


class DocumentationAgent(BaseAgent):
    role_name = "documentation_agent"

    def __init__(self, **kwargs) -> None:
        # Inject our own system prompt — no roles/ file needed
        roles_dir = kwargs.pop("roles_dir", None)
        super().__init__(roles_dir=roles_dir, **kwargs)
        self.system_prompt = _SYSTEM_PROMPT
        self._gh: Optional[GitHubClient] = None
        self._target_repo: str = ""
        self._target_ref: str = "main"

    def _parse_doc_targets(self, body: str) -> list[str]:
        """Extract file targets from '**Docs:** file1, file2' in issue body."""
        m = re.search(r"\*\*Docs:\*\*\s*(.+)", body)
        if not m:
            return []
        return [p.strip() for p in m.group(1).split(",") if p.strip()]

    # ── Tool implementations ───────────────────────────────────────────────

    def _tool_list_files(self, args: dict) -> str:
        path = args.get("path", "")
        entries = self._gh.list_files(path, ref=self._target_ref)
        lines = [f"[{e['type']}] {e['path']}" for e in entries]
        return "\n".join(lines) if lines else "(empty directory)"

    def _tool_read_file(self, args: dict) -> str:
        path = args["path"]
        content = self._gh.get_file_content(path, ref=self._target_ref)
        if content is None:
            return f"(file not found: {path})"
        return content

    def _tool_search_files(self, args: dict) -> str:
        pattern = args["pattern"]
        matches = self._gh.search_files(pattern, ref=self._target_ref)
        return "\n".join(matches) if matches else "(no matches)"

    def _dispatch_tool(self, name: str, args: dict) -> str:
        if name == "list_files":
            return self._tool_list_files(args)
        if name == "read_file":
            return self._tool_read_file(args)
        if name == "search_files":
            return self._tool_search_files(args)
        return f"(unknown tool: {name})"

    # ── Public API ─────────────────────────────────────────────────────────

    def run(
        self,
        issue_title: str,
        issue_body: str,
        target_repo: str,
        github_token: Optional[str] = None,
        ref: str = "main",
    ) -> list[dict]:
        """Run the documentation agent.

        Returns a list of {"path", "content", "action"} dicts to commit.
        Raises ValueError if the agent produces no file writes.
        """
        self._target_repo = target_repo
        self._target_ref = ref
        self._gh = GitHubClient(target_repo, token=github_token)

        # Seed the prompt with issue context
        user_message = (
            f"## Issue: {issue_title}\n\n{issue_body}\n\n"
            "Please read the relevant files and produce the documentation updates."
        )

        raw = self.call_with_tools(
            user_message=user_message,
            tools=_TOOLS,
            tool_handler=self._dispatch_tool,
        )

        # Parse JSON array from response
        try:
            file_writes = json.loads(raw)
        except json.JSONDecodeError:
            # Try to extract JSON array from response text
            m = re.search(r"\[.*\]", raw, re.DOTALL)
            if m:
                file_writes = json.loads(m.group(0))
            else:
                raise ValueError(f"Agent returned non-JSON response: {raw[:200]}")

        if not isinstance(file_writes, list) or len(file_writes) == 0:
            raise ValueError(
                f"DocumentationAgent produced no file writes for issue: {issue_title!r}"
            )

        return file_writes
```

- [ ] **Step 4: Register the agent in `agents/__init__.py`**

Open `agents/__init__.py` and add:

```python
from agents.documentation_agent import DocumentationAgent
```

alongside the existing imports.

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_documentation_agent.py -v
```

Expected: 7 passed

- [ ] **Step 6: Run full suite for regressions**

```bash
pytest --tb=short -q
```

Expected: ≥132 + 7 passed, 0 failures

- [ ] **Step 7: Commit**

```bash
git add agents/documentation_agent.py agents/__init__.py tests/test_documentation_agent.py
git commit -m "feat: add DocumentationAgent with list/read/search tools"
```

---

## Task 3: Create `DocOrchestrator`

**Files:**
- Create: `doc_orchestrator.py`
- Create: `tests/test_doc_orchestrator.py`

Drives the agent and handles all GitHub API side-effects: branch creation, file commits, PR creation.

- [ ] **Step 1: Write failing tests**

Create `tests/test_doc_orchestrator.py`:

```python
"""Unit tests for DocOrchestrator."""
import re
from unittest.mock import MagicMock, patch, call
import pytest
from doc_orchestrator import DocOrchestrator


def _make_orch(monkeypatch):
    orch = DocOrchestrator(
        model="gpt-4.1",
        github_token="tok",
        github_repo="tracker/repo",
    )
    return orch


def test_branch_name_slug():
    orch = DocOrchestrator.__new__(DocOrchestrator)
    slug = orch._make_branch_name(42, "Update the README installation guide!")
    assert slug.startswith("doc/42-")
    assert "readme" in slug
    assert " " not in slug
    assert len(slug) <= 60


def test_run_creates_pr(monkeypatch):
    orch = DocOrchestrator.__new__(DocOrchestrator)
    orch.model = "gpt-4.1"
    orch._github_token = "tok"
    orch._github_repo = "tracker/repo"
    orch._retry_delay = 1
    orch._max_api_retries = 1
    orch._inter_call_delay = 0

    mock_tracker_gh = MagicMock()
    mock_tracker_gh.get_issue.return_value = {
        "number": 7,
        "title": "Update README",
        "body": "Please update the README.\n\n**Target repo:** owner/myapp",
    }
    mock_target_gh = MagicMock()
    mock_target_gh.get_default_branch.return_value = "main"
    mock_target_gh.create_branch.return_value = "doc/7-update-readme"
    mock_target_gh.create_pull_request.return_value = {"html_url": "https://github.com/owner/myapp/pull/1"}

    mock_agent = MagicMock()
    mock_agent.run.return_value = [
        {"path": "README.md", "content": "# Updated\n", "action": "update"}
    ]

    with patch("doc_orchestrator.GitHubClient", side_effect=[mock_tracker_gh, mock_target_gh]), \
         patch("doc_orchestrator.DocumentationAgent", return_value=mock_agent):
        pr_url = orch.run(issue_number=7)

    assert pr_url == "https://github.com/owner/myapp/pull/1"
    mock_target_gh.create_branch.assert_called_once()
    mock_target_gh.commit_file.assert_called_once_with(
        "README.md", "# Updated\n",
        message="docs: update README.md",
        branch="doc/7-update-readme",
    )
    mock_target_gh.create_pull_request.assert_called_once()
    # PR body must reference the issue
    pr_call_kwargs = mock_target_gh.create_pull_request.call_args
    assert "Closes #7" in pr_call_kwargs.kwargs.get("body", "") or \
           "Closes #7" in (pr_call_kwargs.args[1] if len(pr_call_kwargs.args) > 1 else "")


def test_run_raises_on_no_file_writes(monkeypatch):
    orch = DocOrchestrator.__new__(DocOrchestrator)
    orch.model = "gpt-4.1"
    orch._github_token = "tok"
    orch._github_repo = "tracker/repo"
    orch._retry_delay = 1
    orch._max_api_retries = 1
    orch._inter_call_delay = 0

    mock_tracker_gh = MagicMock()
    mock_tracker_gh.get_issue.return_value = {
        "number": 8,
        "title": "Update docs",
        "body": "Update the docs.",
    }
    mock_target_gh = MagicMock()
    mock_agent = MagicMock()
    mock_agent.run.side_effect = ValueError("no file writes")

    with patch("doc_orchestrator.GitHubClient", side_effect=[mock_tracker_gh, mock_target_gh]), \
         patch("doc_orchestrator.DocumentationAgent", return_value=mock_agent):
        with pytest.raises(ValueError, match="no file writes"):
            orch.run(issue_number=8)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_doc_orchestrator.py -v
```

Expected: `ModuleNotFoundError: No module named 'doc_orchestrator'`

- [ ] **Step 3: Implement `doc_orchestrator.py`**

```python
"""DocOrchestrator: documentation-only pipeline (issue → agent → branch → PR)."""
from __future__ import annotations

import os
import re
import time
from typing import Optional

from github_client import GitHubClient, parse_target_repo
from agents.documentation_agent import DocumentationAgent


def _slugify(text: str, max_len: int = 40) -> str:
    """Convert text to a safe branch-name slug."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s-]+", "-", text).strip("-")
    return text[:max_len]


class DocOrchestrator:
    def __init__(
        self,
        model: str = "gpt-4.1",
        github_token: Optional[str] = None,
        github_repo: Optional[str] = None,
        retry_delay: int = 15,
        max_api_retries: int = 5,
        inter_call_delay: int = 0,
    ) -> None:
        self.model = model
        self._github_token = github_token or os.environ.get("GITHUB_TOKEN")
        self._github_repo = github_repo
        self._retry_delay = retry_delay
        self._max_api_retries = max_api_retries
        self._inter_call_delay = inter_call_delay

    def _make_branch_name(self, issue_number: int, title: str) -> str:
        slug = _slugify(title)
        return f"doc/{issue_number}-{slug}"

    def run(self, issue_number: int) -> str:
        """Run the documentation pipeline for a GitHub issue.

        Returns the URL of the created PR.
        Raises on any unrecoverable error.
        """
        tracker_gh = GitHubClient(self._github_repo, token=self._github_token)
        issue = tracker_gh.get_issue(issue_number)
        issue_title = issue["title"]
        issue_body = issue.get("body") or ""

        # Resolve target repo
        target_repo = parse_target_repo(issue_body) or self._github_repo

        target_gh = GitHubClient(target_repo, token=self._github_token)
        default_branch = target_gh.get_default_branch()

        # Run the agent
        agent = DocumentationAgent(
            model=self.model,
            github_token=self._github_token,
            retry_delay=self._retry_delay,
            max_api_retries=self._max_api_retries,
            inter_call_delay=self._inter_call_delay,
        )
        file_writes = agent.run(
            issue_title=issue_title,
            issue_body=issue_body,
            target_repo=target_repo,
            github_token=self._github_token,
            ref=default_branch,
        )

        # Create branch
        branch = self._make_branch_name(issue_number, issue_title)
        target_gh.create_branch(branch, from_branch=default_branch)

        # Commit each file
        for fw in file_writes:
            target_gh.commit_file(
                fw["path"],
                fw["content"],
                message=f"docs: {fw['action']} {fw['path']}",
                branch=branch,
            )

        # Open PR
        changed = ", ".join(fw["path"] for fw in file_writes)
        pr_body = (
            f"## Documentation Update\n\n"
            f"This PR was generated by the AI Documentation Agent in response to "
            f"[#{issue_number}](https://github.com/{self._github_repo}/issues/{issue_number}).\n\n"
            f"**Files changed:** {changed}\n\n"
            f"Closes #{issue_number}"
        )
        pr = target_gh.create_pull_request(
            title=f"docs: {issue_title}",
            body=pr_body,
            head=branch,
            base=default_branch,
        )
        return pr["html_url"]

    @classmethod
    def from_config(cls, config: dict, **overrides) -> "DocOrchestrator":
        pipeline = config.get("pipeline", {})
        return cls(
            model=overrides.get("model", config.get("model", "gpt-4.1")),
            retry_delay=pipeline.get("retry_delay", 15),
            max_api_retries=pipeline.get("max_api_retries", 5),
            inter_call_delay=pipeline.get("inter_call_delay", 0),
            **overrides,
        )
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_doc_orchestrator.py -v
```

Expected: 3 passed

- [ ] **Step 5: Run full suite**

```bash
pytest --tb=short -q
```

Expected: ≥139 + tests, 0 failures

- [ ] **Step 6: Commit**

```bash
git add doc_orchestrator.py tests/test_doc_orchestrator.py
git commit -m "feat: add DocOrchestrator — issue → agent → branch → PR"
```

---

## Task 4: Wire the watcher

**Files:**
- Modify: `watcher.py`
- Modify: `repos.yaml`

Add `doc_label` polling, queuing, and `_dispatch` case.

- [ ] **Step 1: Add `doc_label` polling to the watcher loop**

In `watcher.py`, inside the `for w in watchers:` loop (after the `bug_label` block, around line 285), add:

```python
        doc_label = w.get("doc_label", "documentation")
        # Ensure state labels exist (already done above for bug/feature labels)

        for issue in get_open_issues(tracker_repo, doc_label):
            add_label(tracker_repo, issue["number"], LABEL_QUEUED)
            tasks.append(dict(
                issue=issue, tracker_repo=tracker_repo,
                default_target=default_target, pipeline_type="documentation",
            ))
            logger.info("  Queued doc issue #%d: %s", issue["number"], issue["title"])
```

- [ ] **Step 2: Add `"documentation"` case to `_dispatch()`**

In `watcher.py`, inside `_dispatch()`, after the `elif pipeline_type == "bug":` block (around line 225), add:

```python
            elif pipeline_type == "documentation":
                from doc_orchestrator import DocOrchestrator

                orch = DocOrchestrator(
                    model=model,
                    github_token=token,
                    github_repo=tracker_repo,
                )
                orch.run(issue_number=issue_number)
```

- [ ] **Step 3: Update `repos.yaml` to document the new key**

In the first watcher entry, add `doc_label` after `bug_label`:

```yaml
  - tracker_repo: wanleung/ai-software-house
    default_target: ~
    feature_label:
      - feature-request
      - ai-build
      - enhancement
    bug_label:
      - bug
      - ai-fix
    doc_label: documentation   # issues labeled 'documentation' → doc-only pipeline
    enabled: true
```

Add a comment block near the top of `repos.yaml` explaining the key:
```yaml
# doc_label — single label string that triggers the documentation pipeline.
#   When set, issues with this label are dispatched to DocOrchestrator only
#   (no PM/Architect/Engineers). The agent reads existing docs, writes updates,
#   and opens a PR. Default: "documentation"
```

- [ ] **Step 4: Run existing test suite**

```bash
pytest --tb=short -q
```

Expected: all previously passing tests still pass

- [ ] **Step 5: Smoke-test the dispatch path (dry run)**

```bash
python watcher.py --config repos.yaml --dry-run
```

Expected: runs without error, shows "Would run documentation pipeline" for any doc-labeled issues (or "Nothing to do." if none queued).

- [ ] **Step 6: Commit**

```bash
git add watcher.py repos.yaml
git commit -m "feat: add doc_label support to watcher — documentation pipeline dispatch"
```

---

## Task 5: Final regression + push

- [ ] **Step 1: Run full test suite**

```bash
pytest --tb=short -q
```

Expected: ≥139 passed (132 original + 7 doc agent + 3 doc orchestrator + 4 github_client), 0 failures

- [ ] **Step 2: Push to master**

```bash
git push origin master
```

- [ ] **Step 3: Update README**

In `README.md`, find the "Watcher labels" or `repos.yaml` reference section and add:

```markdown
### `doc_label` — Documentation-only pipeline

Label an issue `documentation` (configurable via `doc_label` in `repos.yaml`) to trigger a lightweight doc-update pipeline:

1. **No full pipeline** — skips PM, Architect, and Engineers entirely
2. **DocumentationAgent** reads existing docs and source files from the target repo via GitHub API
3. Agent writes/updates files and commits them to a branch `doc/<issue-number>-<slug>`
4. A PR is opened automatically referencing and closing the issue

**Issue body format:**
```
Update the README installation section and add a troubleshooting guide.

**Docs:** README.md, docs/troubleshooting.md
**Target repo:** owner/my-app
```

`**Docs:**` is optional — if omitted, the agent discovers relevant files itself.
```

- [ ] **Step 4: Commit and push docs**

```bash
git add README.md
git commit -m "docs: document doc_label and documentation pipeline in README"
git push origin master
```
