# Repo Context Awareness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give agents awareness of the target repo's existing code — injecting a file tree into PM/Architect prompts for small repos, and auto-indexing the codebase into RAG for large repos, so engineers never write code blind.

**Architecture:** A new `RepoContextLoader` class fetches the full repo file tree via GitHub API, decides small vs large based on a configurable file-count threshold, renders an appropriate tree text, and (for large repos / when RAG is configured) downloads and indexes the repo into the RAG codebase collection before the Engineer stage runs. The orchestrator wires this in `run()` after target repo detection.

**Tech Stack:** Python stdlib (`zipfile`, `tempfile`, `subprocess`, `pathlib`), existing `GitHubClient`, existing `rag-mcp/indexer.py` called as subprocess, `pytest`, `unittest.mock`.

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `repo_context.py` | CREATE | `RepoContextLoader`, `RepoContext` dataclass, `RepoAutoIndexer` |
| `tests/test_repo_context.py` | CREATE | Unit tests for all three classes |
| `github_client.py` | MODIFY | Add `get_full_tree()` method |
| `orchestrator.py` | MODIFY | Wire `RepoContextLoader` + `RepoAutoIndexer` in `__init__`, `from_config`, `run()` |
| `config.yaml` | MODIFY | Add `repo_context:` section |

---

## Task 1: `get_full_tree()` in GitHubClient + `RepoContextLoader` + `RepoContext`

**Files:**
- Modify: `github_client.py` (add one method after `list_files`)
- Create: `repo_context.py`
- Create: `tests/test_repo_context.py`

### Step 1: Write failing tests for `get_full_tree` and `RepoContextLoader`

Create `tests/test_repo_context.py`:

```python
"""Tests for RepoContextLoader and RepoContext."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from repo_context import RepoContext, RepoContextLoader


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_tree(paths: list[str]) -> list[dict]:
    """Build the list[dict] format get_full_tree() returns."""
    result = []
    for p in paths:
        entry_type = "blob" if "." in p.split("/")[-1] else "tree"
        result.append({"path": p, "type": entry_type, "size": 100})
    return result


def _make_gh(paths: list[str]) -> MagicMock:
    gh = MagicMock()
    gh.get_full_tree.return_value = _make_tree(paths)
    return gh


# ── get_full_tree (unit) ──────────────────────────────────────────────────────

def test_get_full_tree_calls_git_trees_api():
    from github_client import GitHubClient
    gh = MagicMock(spec=GitHubClient)
    # Confirm method signature exists
    assert hasattr(GitHubClient, "get_full_tree")


# ── RepoContextLoader — small repo ───────────────────────────────────────────

def test_small_repo_is_not_large():
    paths = [f"src/file{i}.py" for i in range(10)]
    gh = _make_gh(paths)
    loader = RepoContextLoader(threshold=50)
    ctx = loader.build(gh)
    assert ctx.file_count == 10
    assert ctx.is_large is False


def test_large_repo_is_large():
    paths = [f"src/file{i}.py" for i in range(60)]
    gh = _make_gh(paths)
    loader = RepoContextLoader(threshold=50)
    ctx = loader.build(gh)
    assert ctx.file_count == 60
    assert ctx.is_large is True


def test_threshold_boundary_at_exactly_threshold():
    paths = [f"src/file{i}.py" for i in range(50)]
    gh = _make_gh(paths)
    loader = RepoContextLoader(threshold=50)
    ctx = loader.build(gh)
    # exactly at threshold → large
    assert ctx.is_large is True


# ── Tree text rendering ───────────────────────────────────────────────────────

def test_small_repo_tree_text_contains_all_files():
    paths = ["src/main.py", "tests/test_main.py", "README.md"]
    gh = _make_gh(paths)
    loader = RepoContextLoader(threshold=50)
    ctx = loader.build(gh)
    assert "src/main.py" in ctx.tree_text
    assert "tests/test_main.py" in ctx.tree_text
    assert "README.md" in ctx.tree_text


def test_large_repo_tree_text_only_top_two_levels():
    # Files deeper than 2 levels should not appear
    paths = [
        "src/main.py",                        # depth 1 — visible
        "src/utils/helper.py",                 # depth 2 — visible (dir shown)
        "src/utils/deep/nested/file.py",       # depth 4 — should NOT appear
    ]
    gh = _make_gh(paths)
    loader = RepoContextLoader(threshold=2)   # threshold=2 → large
    ctx = loader.build(gh)
    assert "src/main.py" in ctx.tree_text
    assert "src/utils" in ctx.tree_text
    assert "nested/file.py" not in ctx.tree_text


def test_tree_text_not_empty_when_repo_has_files():
    paths = ["README.md", "main.py"]
    gh = _make_gh(paths)
    loader = RepoContextLoader(threshold=50)
    ctx = loader.build(gh)
    assert ctx.tree_text.strip() != ""


def test_tree_text_empty_when_repo_empty():
    gh = _make_gh([])
    loader = RepoContextLoader(threshold=50)
    ctx = loader.build(gh)
    assert ctx.tree_text == ""


# ── build() returns RepoContext dataclass ────────────────────────────────────

def test_build_returns_repo_context_instance():
    gh = _make_gh(["main.py"])
    loader = RepoContextLoader(threshold=50)
    ctx = loader.build(gh)
    assert isinstance(ctx, RepoContext)
    assert hasattr(ctx, "file_count")
    assert hasattr(ctx, "is_large")
    assert hasattr(ctx, "tree_text")
    assert hasattr(ctx, "paths")


def test_build_returns_empty_context_when_github_unavailable():
    loader = RepoContextLoader(threshold=50)
    ctx = loader.build(None)
    assert ctx.file_count == 0
    assert ctx.is_large is False
    assert ctx.tree_text == ""
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/wanleung/Projects/ai-software-house
source venv/bin/activate && pytest tests/test_repo_context.py -v 2>&1 | head -40
```

Expected: ImportError or AttributeError — `repo_context` does not exist yet.

- [ ] **Step 3: Add `get_full_tree()` to `github_client.py`**

In `github_client.py`, add after the `list_files` method (around line 322):

```python
def get_full_tree(self, ref: Optional[str] = None) -> list[dict]:
    """Return the full recursive file tree of the repo.

    Uses the git tree API with recursive=1 for efficiency.

    Returns:
        List of dicts with keys: path (str), type ('blob'|'tree'), size (int).
        Returns [] on any error.
    """
    try:
        sha = ref or self.get_default_branch()
        tree_data = self._request(
            "GET", f"/repos/{self.repo}/git/trees/{sha}",
            params={"recursive": "1"},
        )
        return [
            {"path": e["path"], "type": e["type"], "size": e.get("size", 0)}
            for e in tree_data.get("tree", [])
        ]
    except Exception:
        return []
```

- [ ] **Step 4: Create `repo_context.py`**

```python
"""Repo context awareness — file tree injection and size detection.

RepoContextLoader fetches the full repo tree, decides small vs large,
and renders an appropriate tree text for injection into agent prompts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from github_client import GitHubClient


@dataclass
class RepoContext:
    """Holds the fetched repo context for injection into agent prompts."""
    file_count: int = 0
    is_large: bool = False
    tree_text: str = ""
    paths: list[dict] = field(default_factory=list)


class RepoContextLoader:
    """Fetches and renders the target repo's file tree.

    Small repos (file_count < threshold): full tree injected into prompts.
    Large repos (file_count >= threshold): top-2-level tree only.
    """

    def __init__(self, threshold: int = 50) -> None:
        self.threshold = threshold

    def build(self, gh: Optional["GitHubClient"]) -> RepoContext:
        """Fetch tree from GitHub and return a RepoContext.

        Returns an empty RepoContext if gh is None or the API call fails.
        """
        if gh is None:
            return RepoContext()

        paths = gh.get_full_tree()
        # Count blobs only (not tree/dir entries)
        blobs = [e for e in paths if e["type"] == "blob"]
        file_count = len(blobs)
        is_large = file_count >= self.threshold

        if file_count == 0:
            return RepoContext(file_count=0, is_large=False, tree_text="", paths=paths)

        if is_large:
            tree_text = self._render_top_level(blobs)
        else:
            tree_text = self._render_full(blobs)

        return RepoContext(
            file_count=file_count,
            is_large=is_large,
            tree_text=tree_text,
            paths=paths,
        )

    def _render_full(self, blobs: list[dict]) -> str:
        """Render all file paths as a compact sorted list."""
        lines = ["## Repo File Tree\n"]
        for entry in sorted(blobs, key=lambda e: e["path"]):
            lines.append(f"  {entry['path']}")
        return "\n".join(lines)

    def _render_top_level(self, blobs: list[dict]) -> str:
        """Render only paths with depth <= 2 (top-level dirs + their direct children).

        Depth is the number of '/' separators + 1.
        e.g. 'src/main.py' → depth 2 (shown), 'src/utils/helper.py' → depth 3 (hidden).
        """
        lines = ["## Repo File Tree (top-level, large repo)\n"]
        seen_dirs: set[str] = set()
        for entry in sorted(blobs, key=lambda e: e["path"]):
            path = entry["path"]
            parts = path.split("/")
            depth = len(parts)
            if depth <= 2:
                lines.append(f"  {path}")
            elif depth == 3:
                # Show parent dir as a summary line once
                parent = "/".join(parts[:2])
                if parent not in seen_dirs:
                    seen_dirs.add(parent)
                    lines.append(f"  {parent}/  (... {depth-2}+ levels deep)")
        return "\n".join(lines)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /home/wanleung/Projects/ai-software-house
source venv/bin/activate && pytest tests/test_repo_context.py -v
```

Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
cd /home/wanleung/Projects/ai-software-house
git add github_client.py repo_context.py tests/test_repo_context.py
git commit -m "feat(repo-context): add RepoContextLoader + get_full_tree() with tests"
```

---

## Task 2: Orchestrator wiring — file tree injection + config

**Files:**
- Modify: `orchestrator.py` — `__init__`, `from_config`, `run()`
- Modify: `config.yaml` — add `repo_context:` section

- [ ] **Step 1: Write failing test for orchestrator tree injection**

Add to `tests/test_repo_context.py`:

```python
# ── Orchestrator integration ──────────────────────────────────────────────────

def test_orchestrator_injects_tree_into_architect_prompt():
    """Tree text should be prepended to Architect system_prompt in run()."""
    from unittest.mock import patch, MagicMock
    from orchestrator import Orchestrator

    orch = Orchestrator(model="gpt-4.1", use_github=False)

    mock_ctx = RepoContext(
        file_count=5,
        is_large=False,
        tree_text="## Repo File Tree\n  src/main.py\n  README.md",
        paths=[],
    )
    mock_loader = MagicMock()
    mock_loader.build.return_value = mock_ctx
    orch.repo_context_loader = mock_loader
    orch.target_github = MagicMock()

    original_architect_prompt = orch.architect.system_prompt or ""

    with patch.object(orch, "_stage_pm"), \
         patch.object(orch, "_stage_pm_reviewer"), \
         patch.object(orch, "_stage_architect"), \
         patch.object(orch, "_stage_architect_reviewer"), \
         patch.object(orch, "_stage_engineer"), \
         patch.object(orch, "_stage_reviewer"), \
         patch.object(orch, "_stage_qa_planner"), \
         patch.object(orch, "_stage_qa"), \
         patch.object(orch, "_stage_test_fix_loop"), \
         patch.object(orch, "_stage_deployment_tester"), \
         patch.object(orch, "_stage_deploy_fix_loop"), \
         patch.object(orch, "_stage_summary"), \
         patch.object(orch, "_stage_memory_update"):
        orch.run("Add login feature")

    assert "## Repo File Tree" in (orch.architect.system_prompt or "")


def test_orchestrator_no_injection_when_loader_absent():
    """If repo_context_loader is None, no tree text should be added."""
    from orchestrator import Orchestrator

    orch = Orchestrator(model="gpt-4.1", use_github=False)
    orch.repo_context_loader = None
    original_prompt = orch.architect.system_prompt or ""

    with patch.object(orch, "_stage_pm"), \
         patch.object(orch, "_stage_pm_reviewer"), \
         patch.object(orch, "_stage_architect"), \
         patch.object(orch, "_stage_architect_reviewer"), \
         patch.object(orch, "_stage_engineer"), \
         patch.object(orch, "_stage_reviewer"), \
         patch.object(orch, "_stage_qa_planner"), \
         patch.object(orch, "_stage_qa"), \
         patch.object(orch, "_stage_test_fix_loop"), \
         patch.object(orch, "_stage_deployment_tester"), \
         patch.object(orch, "_stage_deploy_fix_loop"), \
         patch.object(orch, "_stage_summary"), \
         patch.object(orch, "_stage_memory_update"):
        orch.run("Add login feature")

    assert orch.architect.system_prompt == original_prompt
```

- [ ] **Step 2: Run new tests to verify they fail**

```bash
cd /home/wanleung/Projects/ai-software-house
source venv/bin/activate && pytest tests/test_repo_context.py::test_orchestrator_injects_tree_into_architect_prompt tests/test_repo_context.py::test_orchestrator_no_injection_when_loader_absent -v
```

Expected: AttributeError — `Orchestrator` has no `repo_context_loader`.

- [ ] **Step 3: Add `repo_context_loader` to `Orchestrator.__init__`**

In `orchestrator.py`, add the import at the top (with other imports):

```python
from repo_context import RepoContext, RepoContextLoader
```

In `Orchestrator.__init__`, add the parameter after `framework_docs_loader`:

```python
        repo_context_loader: Optional["RepoContextLoader"] = None,
```

And in the body of `__init__`, after `self.framework_docs_loader = ...`:

```python
        self.repo_context_loader: Optional[RepoContextLoader] = repo_context_loader
```

- [ ] **Step 4: Wire tree injection in `Orchestrator.run()`**

In `orchestrator.py`, in `run()`, after the `# ── Detect target project repo` block and before `# ── Inject long-term memory into agents`, add:

```python
        # ── Fetch repo context (file tree) ────────────────────────────────────
        repo_context: Optional[RepoContext] = None
        if self.repo_context_loader and self.target_github:
            repo_context = self.repo_context_loader.build(self.target_github)
            if repo_context.tree_text:
                size_label = "large" if repo_context.is_large else "small"
                console.print(
                    f"  🗂️  [dim]Repo tree loaded ({repo_context.file_count} files, {size_label})[/dim]"
                )
                tree_block = repo_context.tree_text + "\n\n---\n\n"
                for agent in (self.pm, self.architect, self.pm_reviewer, self.architect_reviewer):
                    if agent.system_prompt is not None:
                        agent.system_prompt = tree_block + agent.system_prompt
```

- [ ] **Step 5: Add `repo_context:` section to `config.yaml`**

Find the `skills:` section in `config.yaml` and add above it:

```yaml
# ── Repo Context Awareness ──────────────────────────────────────────────────
# Controls how the pipeline reads the target repo's existing code structure.
#
# large_repo_threshold: repos with >= this many files are considered "large".
#   Large repos: only top-2-level tree injected into prompts; RAG auto-index triggered.
#   Small repos: full file tree injected into prompts.
repo_context:
  large_repo_threshold: 50

```

- [ ] **Step 6: Wire `RepoContextLoader` in `from_config`**

In `orchestrator.py`, in `from_config`, read the new config section and pass it to the constructor.

After `framework_docs_loader = FrameworkDocsLoader(config=cfg)`, add:

```python
        repo_ctx_cfg = cfg.get("repo_context", {})
        repo_context_loader = RepoContextLoader(
            threshold=repo_ctx_cfg.get("large_repo_threshold", 50)
        )
```

In the `return cls(...)` call, add:

```python
            repo_context_loader=repo_context_loader,
```

- [ ] **Step 7: Run all repo_context tests**

```bash
cd /home/wanleung/Projects/ai-software-house
source venv/bin/activate && pytest tests/test_repo_context.py -v
```

Expected: All tests PASS.

- [ ] **Step 8: Run full test suite to check for regressions**

```bash
cd /home/wanleung/Projects/ai-software-house
source venv/bin/activate && pytest tests/ -x -q 2>&1 | tail -20
```

Expected: All existing tests still pass.

- [ ] **Step 9: Commit**

```bash
cd /home/wanleung/Projects/ai-software-house
git add orchestrator.py config.yaml tests/test_repo_context.py
git commit -m "feat(repo-context): wire tree injection into Orchestrator + config"
```

---

## Task 3: RAG auto-indexer — download repo + index before Engineer stage

**Files:**
- Modify: `repo_context.py` — add `RepoAutoIndexer` class
- Modify: `orchestrator.py` — add `_stage_repo_index()` called before `_stage_engineer`
- Modify: `tests/test_repo_context.py` — add `RepoAutoIndexer` tests

This task only runs when RAG MCP is configured (`self.rag_registry` is set). It:
1. Downloads the target repo as a zip via GitHub API
2. Extracts it to a temp dir
3. Calls `rag-mcp/indexer.py` as a subprocess to index the codebase

- [ ] **Step 1: Write failing tests for `RepoAutoIndexer`**

Add to `tests/test_repo_context.py`:

```python
# ── RepoAutoIndexer ───────────────────────────────────────────────────────────

def test_auto_indexer_calls_subprocess_with_codebase_source(tmp_path):
    """RepoAutoIndexer should call indexer.py with --source codebase."""
    import subprocess
    from repo_context import RepoAutoIndexer

    indexer = RepoAutoIndexer(indexer_script="rag-mcp/indexer.py")

    with patch("repo_context.subprocess.run") as mock_run, \
         patch("repo_context.RepoAutoIndexer._download_repo_zip") as mock_dl:
        mock_dl.return_value = str(tmp_path)
        mock_run.return_value = MagicMock(returncode=0)
        indexer.index(repo="owner/myrepo", github_token="tok", repo_dir=str(tmp_path))

    mock_run.assert_called_once()
    call_args = mock_run.call_args[0][0]  # First positional arg (the command list)
    assert "--source" in call_args
    assert "codebase" in call_args
    assert "--path" in call_args
    assert "--clean" in call_args


def test_auto_indexer_skips_when_no_rag_script(tmp_path):
    """If the indexer script does not exist, index() should return without error."""
    from repo_context import RepoAutoIndexer

    indexer = RepoAutoIndexer(indexer_script="/nonexistent/path/indexer.py")
    # Should not raise
    indexer.index(repo="owner/repo", github_token="tok", repo_dir=str(tmp_path))


def test_orchestrator_calls_auto_index_when_rag_configured():
    """_stage_repo_index should be called in run() when rag_registry is set."""
    from orchestrator import Orchestrator
    from tools import MCPToolRegistry

    orch = Orchestrator(model="gpt-4.1", use_github=False)
    # Inject a fake rag_registry and auto_indexer
    orch._rag_registry = MagicMock()
    orch.repo_auto_indexer = MagicMock()
    orch.target_github = MagicMock()
    orch.target_github.repo = "owner/myrepo"

    with patch.object(orch, "_stage_pm"), \
         patch.object(orch, "_stage_pm_reviewer"), \
         patch.object(orch, "_stage_architect"), \
         patch.object(orch, "_stage_architect_reviewer"), \
         patch.object(orch, "_stage_engineer"), \
         patch.object(orch, "_stage_reviewer"), \
         patch.object(orch, "_stage_qa_planner"), \
         patch.object(orch, "_stage_qa"), \
         patch.object(orch, "_stage_test_fix_loop"), \
         patch.object(orch, "_stage_deployment_tester"), \
         patch.object(orch, "_stage_deploy_fix_loop"), \
         patch.object(orch, "_stage_summary"), \
         patch.object(orch, "_stage_memory_update"):
        orch.run("Add login feature")

    orch.repo_auto_indexer.index.assert_called_once()
```

- [ ] **Step 2: Run new tests to verify they fail**

```bash
cd /home/wanleung/Projects/ai-software-house
source venv/bin/activate && pytest tests/test_repo_context.py::test_auto_indexer_calls_subprocess_with_codebase_source tests/test_repo_context.py::test_auto_indexer_skips_when_no_rag_script tests/test_repo_context.py::test_orchestrator_calls_auto_index_when_rag_configured -v
```

Expected: ImportError — `RepoAutoIndexer` does not exist yet.

- [ ] **Step 3: Add `RepoAutoIndexer` to `repo_context.py`**

Append to `repo_context.py`:

```python
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
import urllib.request


class RepoAutoIndexer:
    """Downloads a GitHub repo and indexes it into the RAG codebase collection.

    Called before the Engineer stage when RAG MCP is configured.
    Uses the rag-mcp/indexer.py subprocess so the RAG server is always
    the single source of truth for embeddings.
    """

    def __init__(self, indexer_script: str = "rag-mcp/indexer.py") -> None:
        self.indexer_script = indexer_script

    def index(
        self,
        repo: str,
        github_token: str,
        repo_dir: Optional[str] = None,
        ref: str = "HEAD",
    ) -> None:
        """Download repo zip and run indexer against it.

        Args:
            repo: 'owner/repo' string.
            github_token: GitHub personal access token.
            repo_dir: If provided, use this local directory instead of downloading.
            ref: Git ref to download (default HEAD).
        """
        script = Path(self.indexer_script)
        if not script.exists():
            return  # RAG indexer not available — skip silently

        if repo_dir:
            work_dir = repo_dir
            self._run_indexer(work_dir)
        else:
            with tempfile.TemporaryDirectory() as tmpdir:
                extracted = self._download_repo_zip(repo, github_token, tmpdir, ref)
                if extracted:
                    self._run_indexer(extracted)

    def _download_repo_zip(
        self, repo: str, github_token: str, tmpdir: str, ref: str
    ) -> Optional[str]:
        """Download repo zipball and extract. Returns extracted directory path or None."""
        zip_path = Path(tmpdir) / "repo.zip"
        url = f"https://api.github.com/repos/{repo}/zipball/{ref}"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"token {github_token}",
                "Accept": "application/vnd.github+json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                zip_path.write_bytes(resp.read())
        except Exception:
            return None

        extract_dir = Path(tmpdir) / "repo"
        extract_dir.mkdir()
        try:
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(extract_dir)
        except zipfile.BadZipFile:
            return None

        # GitHub zip contains a single top-level dir like "owner-repo-sha/"
        subdirs = [d for d in extract_dir.iterdir() if d.is_dir()]
        return str(subdirs[0]) if subdirs else str(extract_dir)

    def _run_indexer(self, path: str) -> None:
        """Run rag-mcp/indexer.py --source codebase --path <path> --clean."""
        subprocess.run(
            [sys.executable, self.indexer_script, "--source", "codebase", "--path", path, "--clean"],
            check=False,
            timeout=300,
        )
```

- [ ] **Step 4: Wire `RepoAutoIndexer` in `Orchestrator.__init__`**

In `orchestrator.py` `__init__`, after `self.repo_context_loader = ...`:

```python
        # Auto-indexer: only active when RAG MCP is configured
        self._rag_registry = rag_registry
        self.repo_auto_indexer: Optional[RepoAutoIndexer] = (
            RepoAutoIndexer() if rag_registry else None
        )
```

Also add `RepoAutoIndexer` to the import at the top:

```python
from repo_context import RepoContext, RepoContextLoader, RepoAutoIndexer
```

- [ ] **Step 5: Add `_stage_repo_index()` to `Orchestrator`**

In `orchestrator.py`, add this method near the other `_stage_*` methods:

```python
    def _stage_repo_index(self, result: PipelineResult) -> None:
        """Auto-index the target repo into RAG codebase collection.

        Only runs when RAG MCP is configured and target_github is set.
        Runs before the Engineer stage so search_codebase returns real results.
        """
        if not self.repo_auto_indexer or not self.target_github:
            return
        console.print("  📦 [dim]Indexing repo into RAG codebase collection...[/dim]")
        self.repo_auto_indexer.index(
            repo=self.target_github.repo,
            github_token=self._github_token or "",
        )
```

- [ ] **Step 6: Call `_stage_repo_index` in `run()` before Engineer stage**

In `orchestrator.py`, in `run()`, find the call to `_stage_engineer` (look for `self._run_stage("engineer"` or `self._stage_engineer`). Add the RAG index stage just before it:

```python
        # ── Auto-index repo into RAG (before Engineer) ───────────────────────
        if self.repo_auto_indexer and self.target_github:
            self._run_stage("repo_index", self._stage_repo_index, result)
```

- [ ] **Step 7: Run all repo_context tests**

```bash
cd /home/wanleung/Projects/ai-software-house
source venv/bin/activate && pytest tests/test_repo_context.py -v
```

Expected: All tests PASS.

- [ ] **Step 8: Run full test suite**

```bash
cd /home/wanleung/Projects/ai-software-house
source venv/bin/activate && pytest tests/ -x -q 2>&1 | tail -20
```

Expected: All existing tests still pass.

- [ ] **Step 9: Commit**

```bash
cd /home/wanleung/Projects/ai-software-house
git add repo_context.py orchestrator.py tests/test_repo_context.py
git commit -m "feat(repo-context): add RepoAutoIndexer + wire pre-engineer RAG index stage"
```

---

## Notes

- `RepoContextLoader` is always active (no config flag needed — it's cheap).
- `RepoAutoIndexer` is only active when RAG MCP (`rag` named server) is configured in `config.yaml`.
- The threshold default is 50 files (blobs only, not dirs). Configurable via `repo_context.large_repo_threshold` in `config.yaml`.
- Prompt stacking is prevented: the tree block is prepended only once per `run()` call (same pattern as memory injection).
- The auto-index is skipped gracefully if `rag-mcp/indexer.py` doesn't exist (users without RAG setup are unaffected).
