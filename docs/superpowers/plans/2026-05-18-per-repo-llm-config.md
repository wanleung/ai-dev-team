# Per-Repo LLM Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow each repo config file to declare an optional `llm:` section (model, per-agent overrides, fallbacks, pools) that deep-merges on top of the global `config.yaml` LLM config.

**Architecture:** Extract `_llm` from each repo entry in `load_watcher_config()`, compute `effective_llm = deep_merge(global_llm, repo_llm)` per watcher in the `watch()` loop, and pass it through the task dict into `_dispatch()` / `_dispatch_pr_revision()` so they use it instead of re-reading the global config.

**Tech Stack:** Python, Pydantic v2, PyYAML, pytest

**Worktree:** `.worktrees/per-repo-llm-config` (branch `feature/per-repo-llm-config`)

**Spec:** `docs/superpowers/specs/2026-05-18-per-repo-llm-config-design.md`

**Run tests with:** `cd /home/wanleung/Projects/ai-software-house && source venv/bin/activate && cd .worktrees/per-repo-llm-config && python -m pytest`

---

### Task 1: Add `_deep_merge_llm()` helper + unit tests

**Files:**
- Modify: `watcher.py` (add helper near top, after imports)
- Modify: `tests/test_watcher_config.py` (add merge unit tests)

- [ ] **Step 1: Write failing tests**

Add to `tests/test_watcher_config.py`:

```python
# ── _deep_merge_llm ───────────────────────────────────────────────────────────

from watcher import _deep_merge_llm


def test_merge_llm_model_repo_wins():
    global_llm = {"model": "openai/gpt-4.1", "overrides": {"architect": "openai/gpt-4.1"}}
    repo_llm = {"model": "ollama/qwen3.5"}
    result = _deep_merge_llm(global_llm, repo_llm)
    assert result["model"] == "ollama/qwen3.5"
    assert result["overrides"]["architect"] == "openai/gpt-4.1"  # global kept


def test_merge_llm_overrides_key_by_key():
    global_llm = {"model": "openai/gpt-4.1", "overrides": {"architect": "openai/gpt-4.1", "engineer": "openai/gpt-4.1-mini"}}
    repo_llm = {"overrides": {"architect": "claude-3-5-sonnet-20241022"}}
    result = _deep_merge_llm(global_llm, repo_llm)
    assert result["overrides"]["architect"] == "claude-3-5-sonnet-20241022"  # repo wins
    assert result["overrides"]["engineer"] == "openai/gpt-4.1-mini"  # global kept


def test_merge_llm_pools_key_by_key():
    global_llm = {"model": "openai/gpt-4.1", "pools": {"openai": 10, "anthropic": 5}}
    repo_llm = {"pools": {"openai": 3}}
    result = _deep_merge_llm(global_llm, repo_llm)
    assert result["pools"]["openai"] == 3       # repo wins
    assert result["pools"]["anthropic"] == 5    # global kept


def test_merge_llm_fallback_replaced_not_merged():
    global_llm = {"model": "openai/gpt-4.1", "fallback": [{"model": "openai/gpt-4.1-mini"}]}
    repo_llm = {"fallback": [{"model": "ollama/qwen3.5"}]}
    result = _deep_merge_llm(global_llm, repo_llm)
    assert result["fallback"] == [{"model": "ollama/qwen3.5"}]


def test_merge_llm_no_repo_llm_returns_global_copy():
    global_llm = {"model": "openai/gpt-4.1", "overrides": {"architect": "openai/gpt-4.1"}}
    result = _deep_merge_llm(global_llm, {})
    assert result == global_llm
    assert result is not global_llm  # must be a copy


def test_merge_llm_empty_global():
    result = _deep_merge_llm({}, {"model": "ollama/qwen3.5"})
    assert result["model"] == "ollama/qwen3.5"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/test_watcher_config.py::test_merge_llm_model_repo_wins -v
```

Expected: `ImportError: cannot import name '_deep_merge_llm' from 'watcher'`

- [ ] **Step 3: Implement `_deep_merge_llm` in `watcher.py`**

Find the section just before `def load_watcher_config` in `watcher.py` and add:

```python
def _deep_merge_llm(global_llm: dict, repo_llm: dict) -> dict:
    """Deep-merge repo LLM config on top of global. Repo values win.

    Rules:
    - ``model``: repo value replaces global if non-empty
    - ``fallback``: repo list replaces global list entirely
    - ``overrides``: key-by-key merge (repo agent wins)
    - ``pools``: key-by-key merge (repo backend wins)
    - All other scalar keys: repo value replaces global if present
    """
    result = dict(global_llm)  # shallow copy of global

    for key, repo_val in repo_llm.items():
        if key in ("overrides", "pools") and isinstance(repo_val, dict):
            # Key-by-key merge: global base, repo keys win
            merged = dict(result.get(key) or {})
            merged.update(repo_val)
            result[key] = merged
        else:
            # model, fallback, ollama_url, etc: repo replaces global
            result[key] = repo_val

    return result
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
python -m pytest tests/test_watcher_config.py -k "merge_llm" -v
```

Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add watcher.py tests/test_watcher_config.py
git commit -m "feat: add _deep_merge_llm helper for per-repo LLM config"
```

---

### Task 2: Extract `_llm` in `load_watcher_config()`

**Files:**
- Modify: `watcher.py` — `load_watcher_config()` function
- Modify: `tests/test_watcher_config.py` — add extraction tests

- [ ] **Step 1: Write failing tests**

Add to `tests/test_watcher_config.py`:

```python
def test_load_watcher_config_extracts_llm(tmp_path):
    """llm: key is extracted from repo entry and stored as _llm."""
    cfg = tmp_path / "repos.yaml"
    _write(cfg, """
        watchers:
          - tracker_repo: owner/alpha
            enabled: true
            llm:
              model: "ollama/qwen3.5"
              overrides:
                architect: "openai/gpt-4.1"
    """)
    result = load_watcher_config(cfg)
    w = result["watchers"][0]
    assert "_llm" in w
    assert w["_llm"]["model"] == "ollama/qwen3.5"
    assert w["_llm"]["overrides"]["architect"] == "openai/gpt-4.1"
    assert "llm" not in w  # original key removed


def test_load_watcher_config_no_llm_key_absent(tmp_path):
    """Repo entries without llm: have no _llm key."""
    cfg = tmp_path / "repos.yaml"
    _write(cfg, """
        watchers:
          - tracker_repo: owner/alpha
            enabled: true
    """)
    result = load_watcher_config(cfg)
    w = result["watchers"][0]
    assert "_llm" not in w


def test_load_watcher_config_llm_in_repos_enabled(tmp_path):
    """llm: key in repos-available/ entry is extracted to _llm."""
    cfg = tmp_path / "repos.yaml"
    _write(cfg, "settings:\n  max_parallel: 1\n")

    avail = tmp_path / "repos-available"
    avail.mkdir()
    _write(avail / "my-repo.yaml", """
        tracker_repo: owner/my-repo
        enabled: true
        llm:
          model: "openai/gpt-4.1"
          pools:
            openai: 3
    """)

    enabled = tmp_path / "repos-enabled"
    enabled.mkdir()
    os.symlink(avail / "my-repo.yaml", enabled / "my-repo.yaml")

    result = load_watcher_config(cfg)
    w = result["watchers"][0]
    assert w["_llm"]["model"] == "openai/gpt-4.1"
    assert w["_llm"]["pools"]["openai"] == 3
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/test_watcher_config.py::test_load_watcher_config_extracts_llm -v
```

Expected: FAIL — `assert "_llm" in w` fails.

- [ ] **Step 3: Update `load_watcher_config()` to extract `llm:`**

In `watcher.py`, find the `load_watcher_config` function. The existing pattern extracts `settings` and stores it as `_settings`. Apply the same pattern for `llm`:

For the **legacy watchers** loop (around line 629):

```python
    for w in legacy_watchers:
        per_settings = w.pop("settings", None)
        if per_settings is not None:
            w["_settings"] = per_settings
        per_llm = w.pop("llm", None)
        if per_llm is not None:
            w["_llm"] = per_llm
```

For the **repos-enabled** loop (around line 651), after `per_settings` block:

```python
            per_settings = watcher_dict.pop("settings", None)
            if per_settings is not None:
                watcher_dict["_settings"] = per_settings
            per_llm = watcher_dict.pop("llm", None)
            if per_llm is not None:
                watcher_dict["_llm"] = per_llm
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
python -m pytest tests/test_watcher_config.py -k "llm" -v
```

Expected: all new tests pass, existing 25 tests still pass.

- [ ] **Step 5: Commit**

```bash
git add watcher.py tests/test_watcher_config.py
git commit -m "feat: extract llm: key from repo entries in load_watcher_config"
```

---

### Task 3: Merge `effective_llm` in `watch()` and pass through task dict

**Files:**
- Modify: `watcher.py` — `watch()` function (issue loop + PR watch loop)
- Modify: `tests/test_watcher_config.py` — add effective_llm task dict tests

- [ ] **Step 1: Write failing tests**

Add to `tests/test_watcher_config.py`:

```python
def test_watch_task_dict_contains_effective_llm(tmp_path, monkeypatch):
    """Tasks queued for a watcher include effective_llm merging global + repo llm."""
    cfg_path = tmp_path / "repos.yaml"
    _write(cfg_path, """
        watchers:
          - tracker_repo: owner/alpha
            labels:
              ai-feature: {}
            enabled: true
            llm:
              model: "ollama/qwen3.5"
              overrides:
                engineer: "ollama/qwen3.5"
        settings:
          max_parallel: 1
          num_engineers: 1
    """)

    # Patch global config with known LLM settings
    global_cfg = {
        "llm": {
            "model": "openai/gpt-4.1",
            "overrides": {"architect": "openai/gpt-4.1", "engineer": "openai/gpt-4.1-mini"},
        },
        "pipeline": {},
        "settings": {},
    }
    monkeypatch.setattr(watcher, "_load_pipeline_config", lambda: global_cfg)

    issues = [{"number": 1, "title": "feat", "labels": []}]
    monkeypatch.setattr(watcher, "get_open_issues", lambda repo, label: issues if label == "ai-feature" else [])
    monkeypatch.setattr(watcher, "add_label", lambda *a, **kw: None)
    monkeypatch.setattr(watcher, "ensure_label", lambda *a, **kw: None)

    tasks = []
    monkeypatch.setattr(watcher, "_run_tasks", lambda t, *a, **kw: tasks.extend(t))

    watcher.watch(cfg_path, once=True, dry_run=False)

    assert len(tasks) == 1
    llm = tasks[0]["llm"]
    assert llm["model"] == "ollama/qwen3.5"           # repo wins
    assert llm["overrides"]["architect"] == "openai/gpt-4.1"   # global kept
    assert llm["overrides"]["engineer"] == "ollama/qwen3.5"    # repo wins


def test_watch_task_dict_llm_is_global_when_no_repo_llm(tmp_path, monkeypatch):
    """Tasks for repo without llm: section use global LLM config unchanged."""
    cfg_path = tmp_path / "repos.yaml"
    _write(cfg_path, """
        watchers:
          - tracker_repo: owner/alpha
            labels:
              ai-feature: {}
            enabled: true
        settings:
          max_parallel: 1
          num_engineers: 1
    """)

    global_cfg = {
        "llm": {"model": "openai/gpt-4.1", "overrides": {"architect": "openai/gpt-4.1"}},
        "pipeline": {},
        "settings": {},
    }
    monkeypatch.setattr(watcher, "_load_pipeline_config", lambda: global_cfg)

    issues = [{"number": 1, "title": "feat", "labels": []}]
    monkeypatch.setattr(watcher, "get_open_issues", lambda repo, label: issues if label == "ai-feature" else [])
    monkeypatch.setattr(watcher, "add_label", lambda *a, **kw: None)
    monkeypatch.setattr(watcher, "ensure_label", lambda *a, **kw: None)

    tasks = []
    monkeypatch.setattr(watcher, "_run_tasks", lambda t, *a, **kw: tasks.extend(t))

    watcher.watch(cfg_path, once=True, dry_run=False)

    assert tasks[0]["llm"]["model"] == "openai/gpt-4.1"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/test_watcher_config.py::test_watch_task_dict_contains_effective_llm -v
```

Expected: FAIL — `KeyError: 'llm'` on task dict.

- [ ] **Step 3: Update `watch()` to compute and attach `effective_llm`**

In `watcher.py`, find the `watch()` function. Locate the section that loads global config and the per-watcher loop. Add `effective_llm` computation and include it in each task dict:

```python
        # Existing lines (already present):
        _w_settings   = {**global_settings, **w.get("_settings", {})}
        model         = _w_settings.get("model", "gpt-4.1")
        num_engineers = _w_settings.get("num_engineers", 2)

        # ADD these lines:
        global_llm    = pipeline_cfg.get("llm", {})
        effective_llm = _deep_merge_llm(global_llm, w.get("_llm", {}))
        # If settings.model was set, let it override llm.model only if llm.model
        # wasn't explicitly set in the repo's own llm: block
        if not w.get("_llm", {}).get("model") and model != "gpt-4.1":
            effective_llm["model"] = model
```

Then in the task dict append (find `tasks.append(dict(...))`), add `llm=effective_llm`:

```python
                    tasks.append(dict(
                        issue=issue,
                        tracker_repo=tracker_repo,
                        default_target=default_target,
                        label=pipeline_name,
                        parallel_issues=w.get("parallel_issues", 1),
                        model=model,
                        num_engineers=num_engineers,
                        deploy=w.get("deploy"),
                        llm=effective_llm,          # ADD THIS
                    ))
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
python -m pytest tests/test_watcher_config.py -k "task_dict" -v
```

Expected: both new tests pass.

- [ ] **Step 5: Commit**

```bash
git add watcher.py tests/test_watcher_config.py
git commit -m "feat: compute effective_llm per watcher and attach to task dict"
```

---

### Task 4: Pass `llm_cfg` through `_dispatch()` and `_dispatch_pr_revision()`

**Files:**
- Modify: `watcher.py` — `_dispatch()`, `_dispatch_pr_revision()`, and the `_run_tasks()` call site that invokes them
- Modify: `tests/test_watcher_dispatch.py` — add llm_cfg passthrough tests

- [ ] **Step 1: Write failing tests**

Add to `tests/test_watcher_dispatch.py`:

```python
def test_dispatch_uses_llm_cfg_model(tmp_path, monkeypatch):
    """_dispatch uses llm_cfg['model'] instead of global config model."""
    captured = {}

    def fake_orchestrator(**kwargs):
        captured.update(kwargs)
        class FakeOrch:
            def load_pipeline_for_label(self, label): return None
            def run(self, *a, **kw): return {"verdict": "approved", "pr_url": "http://x"}
            _pipeline_yaml_stages = None
        return FakeOrch()

    monkeypatch.setattr(watcher, "_load_pipeline_config", lambda: {
        "llm": {"model": "openai/gpt-4.1"},
        "pipeline": {},
    })

    import sys
    import types
    fake_orch_mod = types.ModuleType("orchestrator")
    fake_orch_mod.Orchestrator = lambda **kw: (captured.update(kw), type("O", (), {
        "load_pipeline_for_label": lambda s, l: None,
        "run": lambda s, *a, **kw: {"verdict": "approved", "pr_url": "http://x"},
        "_pipeline_yaml_stages": None,
    })())[-1]
    monkeypatch.setitem(sys.modules, "orchestrator", fake_orch_mod)

    log_file = tmp_path / "run.log"
    repo_llm = {"model": "ollama/qwen3.5", "overrides": {"engineer": "ollama/qwen3.5"}}

    from watcher import _dispatch
    _dispatch(
        label="ai-feature",
        tracker_repo="owner/tracker",
        target_repo="owner/target",
        issue_number=1,
        model="gpt-4.1",
        num_engineers=1,
        log_file=log_file,
        logger=None,
        llm_cfg=repo_llm,
    )

    assert captured.get("model") == "ollama/qwen3.5"
    assert captured.get("model_overrides", {}).get("engineer") == "ollama/qwen3.5"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/test_watcher_dispatch.py::test_dispatch_uses_llm_cfg_model -v
```

Expected: FAIL — `TypeError: _dispatch() got an unexpected keyword argument 'llm_cfg'`

- [ ] **Step 3: Update `_dispatch()` signature and body**

In `watcher.py`, find `def _dispatch(` and update its signature:

```python
def _dispatch(
    label: str,
    tracker_repo: str,
    target_repo: str,
    issue_number: int,
    model: str,
    num_engineers: int,
    log_file: Path,
    logger: logging.Logger,
    deploy_cfg: dict | None = None,
    llm_cfg: dict | None = None,          # ADD THIS
) -> "PipelineResult":
```

Then replace the LLM extraction block inside `_dispatch`:

**Before:**
```python
    pipeline_cfg = _load_pipeline_config()
    llm_cfg = pipeline_cfg.get("llm", {})
    pipe_cfg = pipeline_cfg.get("pipeline", {})
    cfg_model = llm_cfg.get("model", "") or ""
    effective_model = cfg_model if cfg_model and cfg_model != "gpt-4.1" else model
    model_overrides = llm_cfg.get("overrides", {})
    ollama_url = llm_cfg.get("ollama_url", "http://localhost:11434")
    nvidia_nim_api_key = llm_cfg.get("nvidia_nim_api_key") or os.environ.get("NVIDIA_API_KEY")
    nvidia_nim_base_url = llm_cfg.get("nvidia_nim_base_url") or os.environ.get("NVIDIA_NIM_BASE_URL")
```

**After:**
```python
    pipeline_cfg = _load_pipeline_config()
    _llm = llm_cfg if llm_cfg is not None else pipeline_cfg.get("llm", {})
    pipe_cfg = pipeline_cfg.get("pipeline", {})
    cfg_model = _llm.get("model", "") or ""
    effective_model = cfg_model if cfg_model and cfg_model != "gpt-4.1" else model
    model_overrides = _llm.get("overrides", {})
    ollama_url = _llm.get("ollama_url", "http://localhost:11434")
    nvidia_nim_api_key = _llm.get("nvidia_nim_api_key") or os.environ.get("NVIDIA_API_KEY")
    nvidia_nim_base_url = _llm.get("nvidia_nim_base_url") or os.environ.get("NVIDIA_NIM_BASE_URL")
```

Also pass `llm_fallbacks` to the Orchestrator (it reads `fallbacks` from `_llm`):

Find the `orch = Orchestrator(` call inside `_dispatch` and add:

```python
            orch = Orchestrator(
                model=effective_model,
                model_overrides=model_overrides,
                ...
                llm_fallbacks=_llm.get("fallbacks") or None,   # ADD THIS
                ...
            )
```

- [ ] **Step 4: Apply the same change to `_dispatch_pr_revision()`**

In `watcher.py`, find `def _dispatch_pr_revision(` and update its signature to add `llm_cfg: dict | None = None` as the last parameter. Apply the identical rename from `llm_cfg` → `_llm` inside that function body (same 8-line block and same `llm_fallbacks` addition to the `Orchestrator(...)` call).

- [ ] **Step 5: Update `_run_tasks()` to forward `llm` from task dict**

Find where `_dispatch` is called inside `_run_tasks` (or its equivalent) and pass through `llm_cfg=task.get("llm")`. Search for the call site:

```bash
grep -n "_dispatch(" watcher.py | head -10
```

At each call site, add `llm_cfg=task.get("llm")` (or `llm_cfg=w.get("llm")` depending on context).

For `_dispatch_pr_revision`, it is called from `_watch_prs`. Find that call and pass `llm_cfg` from the watcher's `effective_llm` (computed the same way as in the issue loop — use `_deep_merge_llm(global_llm, w.get("_llm", {}))`).

- [ ] **Step 6: Run all watcher tests**

```bash
python -m pytest tests/test_watcher_config.py tests/test_watcher_dispatch.py tests/test_watcher.py -q
```

Expected: all pass (no regressions).

- [ ] **Step 7: Commit**

```bash
git add watcher.py tests/test_watcher_dispatch.py
git commit -m "feat: pass llm_cfg through _dispatch and _dispatch_pr_revision"
```

---

### Task 5: Update `config_schema.py` — add `llm` to `RepoWatcherEntry`

**Files:**
- Modify: `config_schema.py`
- Modify: `tests/test_config_schema.py` (or `tests/test_watcher_config_validation.py`)

- [ ] **Step 1: Write failing test**

Add to `tests/test_config_schema.py`:

```python
from config_schema import RepoWatcherEntry, LLMConfig


def test_repo_watcher_entry_accepts_llm_section():
    entry = RepoWatcherEntry(
        tracker_repo="owner/my-repo",
        llm={
            "model": "ollama/qwen3.5",
            "overrides": {"architect": "openai/gpt-4.1"},
            "pools": {"openai": 3},
        },
    )
    assert entry.llm is not None
    assert entry.llm.model == "ollama/qwen3.5"


def test_repo_watcher_entry_no_llm_defaults_none():
    entry = RepoWatcherEntry(tracker_repo="owner/my-repo")
    assert entry.llm is None
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/test_config_schema.py::test_repo_watcher_entry_accepts_llm_section -v
```

Expected: FAIL — `llm` field not on `RepoWatcherEntry` (or validation error).

- [ ] **Step 3: Add `llm` field to `RepoWatcherEntry`**

In `config_schema.py`, find `class RepoWatcherEntry` and add the `llm` field:

```python
class RepoWatcherEntry(BaseModel):
    model_config = {"extra": "allow"}   # allow custom keys for future expansion

    tracker_repo: str
    default_target: Optional[str] = None
    parallel_issues: int = 1
    labels: Dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    senior_model: Optional[str] = None
    conflict_resolver_model: Optional[str] = None
    llm: Optional[LLMConfig] = None          # ADD THIS
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_config_schema.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add config_schema.py tests/test_config_schema.py
git commit -m "feat: add llm field to RepoWatcherEntry schema"
```

---

### Task 6: Document the `llm:` key in config files

**Files:**
- Modify: `repos.yaml` (comment block at top)
- Modify: `repos-available/custom-blog.yaml` (add example `llm:` block)

- [ ] **Step 1: Add documentation comment to `repos.yaml`**

In `repos.yaml`, find the comment block near the top (the `# Example with new per-label pipeline mapping...` section) and add after the `labels:` example lines:

```yaml
#
# Per-repo LLM config (optional) — overrides global config.yaml settings for this repo only:
#
#   llm:
#     model: "openai/gpt-4.1"          # default model for all agents in this repo
#     fallback:                          # fallback chain (replaces global chain)
#       - model: "openai/gpt-4.1-mini"
#       - model: "ollama/qwen3.5"
#     overrides:                         # per-agent overrides (merged with global)
#       architect: "claude-3-5-sonnet-20241022"
#       engineer: "openai/gpt-4.1-mini"
#     pools:                             # per-repo concurrency pool limits
#       openai: 5
#       anthropic: 2
#
# All llm: keys are optional. Unspecified agents/pools inherit global config.yaml values.
```

- [ ] **Step 2: Update `repos-available/custom-blog.yaml`**

Add a commented-out `llm:` example at the bottom of `repos-available/custom-blog.yaml`:

```yaml
# Per-repo LLM config example (uncomment and edit to override global settings):
# llm:
#   model: "openai/gpt-4.1"
#   overrides:
#     architect: "claude-3-5-sonnet-20241022"
#     engineer: "openai/gpt-4.1-mini"
```

- [ ] **Step 3: Commit**

```bash
git add repos.yaml repos-available/custom-blog.yaml
git commit -m "docs: document llm: key in repo config files"
```

---

### Task 7: Full test run + push PR

- [ ] **Step 1: Run full test suite**

```bash
python -m pytest tests/test_watcher_config.py tests/test_watcher_dispatch.py tests/test_watcher.py tests/test_config_schema.py tests/test_watcher_config_validation.py -v 2>&1 | tail -20
```

Expected: all pass, no regressions.

- [ ] **Step 2: Run broader regression check**

```bash
python -m pytest tests/ -q --ignore=tests/integration -x 2>&1 | tail -15
```

Expected: pass (one known pre-existing deployment test failure is acceptable).

- [ ] **Step 3: Push branch and open PR**

```bash
git push -u origin feature/per-repo-llm-config
gh pr create \
  --title "feat: per-repo LLM config in repo config files" \
  --body "## Summary

Allows each repo config file (\`repos-available/*.yaml\` or inline \`repos.yaml\`) to declare an optional \`llm:\` section that overrides the global LLM config for that repo only.

## What's new

\`\`\`yaml
# repos-available/my-project.yaml
tracker_repo: owner/my-project
labels:
  ai-feature: tdd

llm:
  model: \"openai/gpt-4.1\"
  fallback:
    - model: \"openai/gpt-4.1-mini\"
  overrides:
    architect: \"claude-3-5-sonnet-20241022\"
    engineer: \"openai/gpt-4.1-mini\"
  pools:
    openai: 5
\`\`\`

## Merge behaviour

- \`model\`: repo wins over global
- \`overrides\`: key-by-key merge (repo agent wins, unspecified agents keep global values)
- \`pools\`: key-by-key merge (repo backend wins, other backends keep global limits)
- \`fallback\`: repo list replaces global list entirely

## Files changed

- \`watcher.py\`: \`_deep_merge_llm()\` helper, \`load_watcher_config()\` extraction, \`watch()\` effective_llm computation, \`_dispatch()\` + \`_dispatch_pr_revision()\` llm_cfg param
- \`config_schema.py\`: \`llm\` field on \`RepoWatcherEntry\`
- \`repos.yaml\` + \`repos-available/custom-blog.yaml\`: documentation

Spec: \`docs/superpowers/specs/2026-05-18-per-repo-llm-config-design.md\`" \
  --base master
```
