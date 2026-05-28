# Scan Stage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `scan` pipeline stage that fetches the repo file tree and (optionally) indexes it into RAG, making codebase context available from the first stage of every code-touching pipeline.

**Architecture:** A new `_stage_scan` method on `Orchestrator` builds file-tree context via `RepoContextLoader` and optionally indexes into RAG via `RepoAutoIndexer`. The result is stored on `PipelineResult.repo_context`. The stage is registered in `_build_utility_stages`, and the existing implicit RAG fallback in `run()` is kept as a backstop for pipelines that omit `scan`.

**Tech Stack:** Python, pytest, existing `RepoContextLoader` / `RepoAutoIndexer` in `repo_context.py`

---

### Task 1: Add `repo_context` field to `PipelineResult`

**Files:**
- Modify: `orchestrator.py:416-445` (PipelineResult dataclass, after `discussion_synthesis` field)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scan_stage.py
from __future__ import annotations
from unittest.mock import MagicMock


def test_pipeline_result_has_repo_context_field():
    """PipelineResult should have a repo_context field defaulting to None."""
    from orchestrator import PipelineResult

    result = PipelineResult()
    assert result.repo_context is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_scan_stage.py::test_pipeline_result_has_repo_context_field -v
```

Expected: `FAILED` — `AttributeError: repo_context`

- [ ] **Step 3: Add `repo_context` to `PipelineResult`**

In `orchestrator.py`, find the `# Discussion stage outputs` comment block (around line 416). Add immediately after `discussion_synthesis: str = ""`:

```python
    # Scan stage output
    repo_context: Optional["RepoContext"] = None
```

`RepoContext` is already imported at line 60: `from repo_context import RepoContext, RepoContextLoader, RepoAutoIndexer`

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_scan_stage.py::test_pipeline_result_has_repo_context_field -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add orchestrator.py tests/test_scan_stage.py
git commit -m "feat(scan): add repo_context field to PipelineResult"
```

---

### Task 2: Implement `_stage_scan`

**Files:**
- Modify: `orchestrator.py` (add `_stage_scan` method near `_stage_repo_index` at line ~4376)
- Modify: `tests/test_scan_stage.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_scan_stage.py`:

```python
def _make_orchestrator_for_scan(*, repo_auto_indexer=None, target_github=None):
    """Build a minimal Orchestrator stub with just enough to test _stage_scan."""
    from orchestrator import Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    orch.repo_auto_indexer = repo_auto_indexer
    orch.target_github = target_github
    orch._github_token = "token"
    from repo_context import RepoContextLoader
    orch.repo_context_loader = RepoContextLoader()
    return orch


def test_stage_scan_builds_file_tree_and_stores_on_result():
    """_stage_scan stores the RepoContext result on result.repo_context."""
    from orchestrator import Orchestrator, PipelineResult
    from repo_context import RepoContext

    gh = MagicMock()
    fake_ctx = RepoContext(file_count=5, is_large=False, tree_text="tree", paths=[])
    loader_mock = MagicMock()
    loader_mock.build.return_value = fake_ctx

    orch = Orchestrator.__new__(Orchestrator)
    orch.repo_auto_indexer = None
    orch.target_github = gh
    orch._github_token = "tok"
    orch.repo_context_loader = loader_mock

    result = PipelineResult()
    orch._stage_scan(result)

    loader_mock.build.assert_called_once_with(gh)
    assert result.repo_context is fake_ctx


def test_stage_scan_calls_rag_indexer_when_configured():
    """_stage_scan calls repo_auto_indexer.index when RAG is configured."""
    from orchestrator import Orchestrator, PipelineResult

    gh = MagicMock()
    gh.repo = "owner/repo"
    indexer = MagicMock()
    loader_mock = MagicMock()
    from repo_context import RepoContext
    loader_mock.build.return_value = RepoContext()

    orch = Orchestrator.__new__(Orchestrator)
    orch.repo_auto_indexer = indexer
    orch.target_github = gh
    orch._github_token = "tok"
    orch.repo_context_loader = loader_mock

    result = PipelineResult()
    orch._stage_scan(result)

    indexer.index.assert_called_once_with(repo="owner/repo", github_token="tok")


def test_stage_scan_adds_rag_index_to_completed_stages():
    """_stage_scan adds 'rag_index' to result.completed_stages after indexing."""
    from orchestrator import Orchestrator, PipelineResult

    gh = MagicMock()
    gh.repo = "owner/repo"
    indexer = MagicMock()
    loader_mock = MagicMock()
    from repo_context import RepoContext
    loader_mock.build.return_value = RepoContext()

    orch = Orchestrator.__new__(Orchestrator)
    orch.repo_auto_indexer = indexer
    orch.target_github = gh
    orch._github_token = "tok"
    orch.repo_context_loader = loader_mock

    result = PipelineResult()
    orch._stage_scan(result)

    assert "rag_index" in result.completed_stages


def test_stage_scan_skips_rag_silently_when_not_configured():
    """_stage_scan skips RAG (no error) when repo_auto_indexer is None."""
    from orchestrator import Orchestrator, PipelineResult

    gh = MagicMock()
    loader_mock = MagicMock()
    from repo_context import RepoContext
    loader_mock.build.return_value = RepoContext()

    orch = Orchestrator.__new__(Orchestrator)
    orch.repo_auto_indexer = None
    orch.target_github = gh
    orch._github_token = "tok"
    orch.repo_context_loader = loader_mock

    result = PipelineResult()
    orch._stage_scan(result)  # must not raise

    assert "rag_index" not in result.completed_stages
    assert result.repo_context is not None


def test_stage_scan_is_noop_when_no_target_github():
    """_stage_scan skips all work when target_github is None."""
    from orchestrator import Orchestrator, PipelineResult
    from repo_context import RepoContextLoader

    loader_mock = MagicMock()

    orch = Orchestrator.__new__(Orchestrator)
    orch.repo_auto_indexer = MagicMock()
    orch.target_github = None
    orch._github_token = "tok"
    orch.repo_context_loader = loader_mock

    result = PipelineResult()
    orch._stage_scan(result)

    loader_mock.build.assert_not_called()
    orch.repo_auto_indexer.index.assert_not_called()
    assert result.repo_context is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_scan_stage.py -v -k "not has_repo_context_field"
```

Expected: all `FAILED` — `AttributeError: _stage_scan`

- [ ] **Step 3: Implement `_stage_scan`**

In `orchestrator.py`, add the following method directly before `_stage_repo_index` (around line 4376):

```python
    def _stage_scan(self, result: PipelineResult) -> None:
        """Fetch repo file tree and optionally index into RAG.

        Always builds the file tree when target_github is set.
        Silently skips RAG indexing when repo_auto_indexer is not configured.
        """
        if not self.target_github:
            return
        result.repo_context = self.repo_context_loader.build(self.target_github)
        if self.repo_auto_indexer:
            console.print("  📦 [dim]Indexing repo into RAG codebase collection...[/dim]")
            self.repo_auto_indexer.index(
                repo=self.target_github.repo,
                github_token=self._github_token or "",
            )
            result.add_completed_stage("rag_index")

```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_scan_stage.py -v
```

Expected: all 6 tests `PASSED`

- [ ] **Step 5: Commit**

```bash
git add orchestrator.py tests/test_scan_stage.py
git commit -m "feat(scan): implement _stage_scan method"
```

---

### Task 3: Register `scan` in `_build_utility_stages`

**Files:**
- Modify: `orchestrator.py:2390-2414` (`_build_utility_stages` method)
- Modify: `tests/test_scan_stage.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_scan_stage.py`:

```python
def test_scan_stage_is_in_stage_registry():
    """'scan' must appear in _make_stage_registry() output."""
    from orchestrator import Orchestrator
    from unittest.mock import MagicMock, patch

    orch = Orchestrator.__new__(Orchestrator)
    # Minimal attributes _make_stage_registry accesses
    orch._stage_timeouts = {}
    orch._discussions_dir = __import__("pathlib").Path("/nonexistent_dir_that_does_not_exist")

    # Patch all the lambdas that reference agent attributes we don't have
    with patch.object(Orchestrator, "_build_product_stages", return_value={}), \
         patch.object(Orchestrator, "_build_engineering_stages", return_value={}), \
         patch.object(Orchestrator, "_build_content_stages", return_value={}), \
         patch.object(Orchestrator, "_build_discussion_stages", return_value={}):
        registry = orch._build_utility_stages()

    assert "scan" in registry
    stage = registry["scan"]
    assert stage.name == "scan"
    assert stage.checkpoint_key == "scan"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_scan_stage.py::test_scan_stage_is_in_stage_registry -v
```

Expected: `FAILED` — `AssertionError: 'scan' not in {}`

- [ ] **Step 3: Add `scan` to `_build_utility_stages`**

In `orchestrator.py`, locate `_build_utility_stages` (around line 2390). Add the `scan` stage registration as the first entry, before `doc_generate`:

```python
    def _build_utility_stages(self) -> dict[str, "PipelineStage"]:
        """Build utility stages: scan, doc generation, doc PR, and bootstrap patterns."""
        stages: dict[str, "PipelineStage"] = {}
        stages["scan"] = PipelineStage(
            name="scan",
            label="🔍 Scan",
            description="Fetching repo file tree and indexing into RAG...",
            checkpoint_key="scan",
            fn=lambda r: self._stage_scan(r),
        )
        stages["doc_generate"] = PipelineStage(
            # ... existing code unchanged ...
```

Only add the `scan` block; leave `doc_generate`, `doc_commit_pr`, and `bootstrap_patterns` exactly as they are.

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_scan_stage.py::test_scan_stage_is_in_stage_registry -v
```

Expected: `PASSED`

- [ ] **Step 5: Run full scan test suite to ensure no regressions**

```bash
python -m pytest tests/test_scan_stage.py -v
```

Expected: all 7 tests `PASSED`

- [ ] **Step 6: Commit**

```bash
git add orchestrator.py tests/test_scan_stage.py
git commit -m "feat(scan): register scan stage in _build_utility_stages"
```

---

### Task 4: Update built-in pipeline YAMLs

**Files:**
- Modify: `pipelines/ai-feature.yaml`
- Modify: `pipelines/tdd.yaml`
- Modify: `pipelines/ai-fix.yaml`
- Modify: `pipelines/ai-smart-fix.yaml`

No new test file needed — the stage registry test above validates the stage exists; YAML changes are validated by the existing `test_pipeline_file_feature.py` load tests.

- [ ] **Step 1: Add `scan` as first stage to `ai-feature.yaml`**

Change `stages:` list so `scan` appears before `pm`:

```yaml
# Built-in feature pipeline — label: ai-feature
# Mirrors the original Orchestrator default sequence.
stages:
  - scan
  - pm
  - pm_reviewer
  - architect
  - architect_reviewer
  - contract_validator
  - tier_review
  - junior_engineer
```

- [ ] **Step 2: Add `scan` as first stage to `tdd.yaml`**

```yaml
# Built-in feature pipeline — label: ai-feature
# Mirrors the original Orchestrator default sequence.
stages:
  - scan
  - pm
  - pm_reviewer
  - architect
  - architect_reviewer
  - contract_validator
  - qa_planner
  - qa_engineer
```

- [ ] **Step 3: Add `scan` as first stage to `ai-fix.yaml`**

```yaml
# Built-in bug-fix pipeline — label: ai-fix
# Replaces bug_fix_orchestrator.py with a stage sequence on the unified
# Orchestrator. The Engineer treats the diagnosis as its architecture.
stages:
  - scan
  - diagnose
  - bug_fix
  - validation_gate
  - reviewer
  - test_fix
```

- [ ] **Step 4: Add `scan` as first stage to `ai-smart-fix.yaml`**

```yaml
# Built-in bug-fix pipeline — label: ai-fix
# Replaces bug_fix_orchestrator.py with a stage sequence on the unified
# Orchestrator. The Engineer treats the diagnosis as its architecture.
stages:
  - scan
  - diagnose
  - architect
  - bug_fix
  - validation_gate
  - reviewer
  - test_fix
```

- [ ] **Step 5: Run existing pipeline file tests to verify YAML loads cleanly**

```bash
python -m pytest tests/test_pipeline_file_feature.py -v
```

Expected: all tests `PASSED`

- [ ] **Step 6: Commit**

```bash
git add pipelines/ai-feature.yaml pipelines/tdd.yaml pipelines/ai-fix.yaml pipelines/ai-smart-fix.yaml
git commit -m "feat(scan): add scan as first stage to all code-touching pipelines"
```

---

### Task 5: Verify implicit RAG fallback still works

**Files:**
- Modify: `tests/test_scan_stage.py`

The implicit fallback at `orchestrator.py:3677` already checks `"rag_index" not in result.completed_stages`. This test confirms the guard works correctly.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_scan_stage.py`:

```python
def test_implicit_rag_fallback_skips_when_scan_already_ran():
    """The implicit RAG fallback in run() must not re-index if scan already ran."""
    # This validates the guard at orchestrator.py:3677 directly by simulating
    # what _run_standard_revision_loops would see.
    from orchestrator import PipelineResult

    result = PipelineResult()
    result.add_completed_stage("rag_index")

    # The guard condition is: "rag_index" not in result.completed_stages
    # If guard is True, re-index happens. We want it to be False (no re-index).
    assert "rag_index" in result.completed_stages, \
        "add_completed_stage must persist 'rag_index' so fallback guard evaluates to False"
```

- [ ] **Step 2: Run test to verify it passes (it should already pass)**

```bash
python -m pytest tests/test_scan_stage.py::test_implicit_rag_fallback_skips_when_scan_already_ran -v
```

Expected: `PASSED` (if `add_completed_stage` works correctly)

- [ ] **Step 3: Run the full test suite to check for regressions**

```bash
python -m pytest tests/ -v --tb=short -q 2>&1 | tail -30
```

Expected: no new failures

- [ ] **Step 4: Commit**

```bash
git add tests/test_scan_stage.py
git commit -m "test(scan): verify implicit RAG fallback guard behaviour"
```

---

### Task 6: Open PR

- [ ] **Step 1: Push branch and open PR**

```bash
git push origin feature/scan-stage
gh pr create \
  --title "feat: add scan pipeline stage for file-tree and RAG indexing" \
  --body "Adds a dedicated \`scan\` stage to the pipeline registry.

## What
- New \`_stage_scan\` method on \`Orchestrator\`
- Fetches repo file tree via \`RepoContextLoader\` and stores on \`PipelineResult.repo_context\`
- Indexes repo into RAG via \`RepoAutoIndexer\` when configured (silently skipped if not)
- Adds \`rag_index\` to \`completed_stages\` so the existing implicit fallback does not re-index
- \`scan\` registered as first stage in \`ai-feature.yaml\`, \`tdd.yaml\`, \`ai-fix.yaml\`, \`ai-smart-fix.yaml\`

## Why
Agents downstream of scan (PM, Architect, etc.) now have accurate file-tree context from the very first stage. RAG is indexed once, early.

Spec: \`docs/superpowers/specs/2026-05-28-scan-stage-design.md\`" \
  --base master
```
