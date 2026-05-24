# Orchestrator Function Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the 4 functions in `orchestrator.py` that exceed 200 lines into private helper methods of ≤30 lines each, with no behavior change and all 1757 existing tests still passing.

**Architecture:** Extract-method refactor only — no new files, no public API changes, no import changes. Each giant function is replaced by a sequence of `_private` helper calls. The local `_mk` closure in `__init__` is promoted to a real method `_make_agent_kwargs`.

**Tech Stack:** Python 3.11, pytest, `orchestrator.py` (Orchestrator class, ~5326 lines)

---

## Files

- **Modify:** `orchestrator.py` — all changes are in the `Orchestrator` class
- **Modify:** `tests/test_orchestrator_mcp_init.py` — add 4 new smoke tests for extracted helpers

---

### Task 1: Create branch + run baseline

**Files:**
- No code changes

- [ ] **Step 1: Create the feature branch**

```bash
cd /home/wanleung/Projects/ai-software-house
git checkout -b refactor/orchestrator-fn-split
```

- [ ] **Step 2: Confirm baseline test count**

```bash
python3 -m pytest tests/ -q --tb=no 2>/dev/null | tail -3
```

Expected: `11 failed, 1757 passed` (the 11 failures are pre-existing and unrelated).

- [ ] **Step 3: Confirm fn_map violation count for the 4 target functions**

```bash
python3 tools/fn_map.py --no-html 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -E "(__init__|run |run_revision|_make_stage_registry)" | head -10
```

Expected output includes lines like:
```
   325  __init__                          orchestrator.py:667
   315  run                               orchestrator.py:2876
   275  run_revision                      orchestrator.py:2600
   264  _make_stage_registry              orchestrator.py:1773
```

---

### Task 2: Extract `_init_core_attrs` from `__init__`

**Files:**
- Modify: `orchestrator.py:667-765` (`__init__` body, first block)
- Test: `tests/test_orchestrator_mcp_init.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_orchestrator_mcp_init.py`:

```python
def test_init_core_attrs_sets_model_and_workspace():
    """_init_core_attrs must be callable directly and set scalar config attrs."""
    orch = _make_minimal_orchestrator(model="test-model-xyz")
    assert orch.model == "test-model-xyz"
    assert orch.workspace_dir == Path("./workspace")
    assert orch._checkpoint_lock is not None
    assert isinstance(orch.model_overrides, dict)
```

Add `from pathlib import Path` to the top of the test file if not already present.

- [ ] **Step 2: Run test to verify it passes already (it tests existing behavior)**

```bash
python3 -m pytest tests/test_orchestrator_mcp_init.py::test_init_core_attrs_sets_model_and_workspace -v
```

Expected: PASS (the attributes already exist). This is our regression guard.

- [ ] **Step 3: Extract `_init_core_attrs` into `orchestrator.py`**

Add this method to the `Orchestrator` class, just before `_make_backend` at line ~995:

```python
def _init_core_attrs(
    self,
    model: str,
    num_engineers: int,
    num_junior_engineers: int,
    num_senior_engineers: int,
    junior_model: Optional[str],
    senior_model: Optional[str],
    tier_reviewer_model: Optional[str],
    junior_quality_gate: bool,
    junior_test_retries: int,
    tier_override_rules: "list[dict] | None",
    senior_engineer_use_mcp: bool,
    junior_engineer_use_mcp: bool,
    branch_prefix: str,
    workspace_dir: str,
    stop_on_review_issues: bool,
    model_overrides: Optional[dict],
    use_github: bool,
    github_repo: Optional[str],
    github_token: Optional[str],
    ollama_url: str,
    ollama_api_key: Optional[str],
    ollama_think: bool,
    ollama_preserve_thinking: bool,
    ollama_stream: bool,
    opencode_stream: bool,
    github_models_stream: bool,
    max_revisions: int,
    max_prd_revisions: int,
    max_design_revisions: int,
    stop_on_prd_issues: bool,
    stop_on_design_issues: bool,
    max_test_retries: int,
    max_deploy_retries: int,
    reviewer_max_retries: int,
    skill_loader: Optional["SkillLoader"],
    framework_docs_loader: Optional["FrameworkDocsLoader"],
    repo_context_loader: Optional["RepoContextLoader"],
    press_cfg: Optional[dict],
    raw_cfg: Optional[dict],
) -> None:
    """Assign all scalar configuration attributes."""
    self._press_cfg: dict = press_cfg or {}
    self._raw_cfg: dict = raw_cfg or {}
    self.model = model
    self.num_engineers = num_engineers
    self.num_junior_engineers = num_junior_engineers
    self.num_senior_engineers = num_senior_engineers
    self.junior_model = junior_model
    self.senior_model = senior_model
    self.tier_reviewer_model = tier_reviewer_model
    self.junior_quality_gate = junior_quality_gate
    self.junior_test_retries = junior_test_retries
    self.tier_override_rules = tier_override_rules or []
    self.senior_engineer_use_mcp = senior_engineer_use_mcp
    self.junior_engineer_use_mcp = junior_engineer_use_mcp
    self.branch_prefix = branch_prefix
    self.workspace_dir = Path(workspace_dir)
    self.stop_on_review_issues = stop_on_review_issues
    self.model_overrides = model_overrides or {}
    self.use_github = use_github and bool(github_repo)
    self._github_token = github_token
    self.ollama_url = ollama_url
    self.ollama_api_key = ollama_api_key
    self.ollama_think = ollama_think
    self.ollama_preserve_thinking = ollama_preserve_thinking
    self.ollama_stream = ollama_stream
    self.opencode_stream = opencode_stream
    self.github_models_stream = github_models_stream
    self.max_revisions = max_revisions
    self.max_prd_revisions = max_prd_revisions
    self.max_design_revisions = max_design_revisions
    self.stop_on_prd_issues = stop_on_prd_issues
    self.stop_on_design_issues = stop_on_design_issues
    self.max_test_retries = max_test_retries
    self.max_deploy_retries = max_deploy_retries
    self._reviewer_max_retries = reviewer_max_retries
    self.skill_loader = skill_loader
    self.framework_docs_loader = framework_docs_loader or FrameworkDocsLoader(config={})
    self.repo_context_loader = repo_context_loader
    self._checkpoint_lock: threading.Lock = threading.Lock()
```

- [ ] **Step 4: Replace the block in `__init__` with a call to `_init_core_attrs`**

In `__init__`, replace lines 727–765 (the scalar assignment block up to `self._checkpoint_lock`) with:

```python
        self._init_core_attrs(
            model=model, num_engineers=num_engineers,
            num_junior_engineers=num_junior_engineers,
            num_senior_engineers=num_senior_engineers,
            junior_model=junior_model, senior_model=senior_model,
            tier_reviewer_model=tier_reviewer_model,
            junior_quality_gate=junior_quality_gate,
            junior_test_retries=junior_test_retries,
            tier_override_rules=tier_override_rules,
            senior_engineer_use_mcp=senior_engineer_use_mcp,
            junior_engineer_use_mcp=junior_engineer_use_mcp,
            branch_prefix=branch_prefix, workspace_dir=workspace_dir,
            stop_on_review_issues=stop_on_review_issues,
            model_overrides=model_overrides, use_github=use_github,
            github_repo=github_repo, github_token=github_token,
            ollama_url=ollama_url, ollama_api_key=ollama_api_key,
            ollama_think=ollama_think,
            ollama_preserve_thinking=ollama_preserve_thinking,
            ollama_stream=ollama_stream, opencode_stream=opencode_stream,
            github_models_stream=github_models_stream,
            max_revisions=max_revisions, max_prd_revisions=max_prd_revisions,
            max_design_revisions=max_design_revisions,
            stop_on_prd_issues=stop_on_prd_issues,
            stop_on_design_issues=stop_on_design_issues,
            max_test_retries=max_test_retries,
            max_deploy_retries=max_deploy_retries,
            reviewer_max_retries=reviewer_max_retries,
            skill_loader=skill_loader,
            framework_docs_loader=framework_docs_loader,
            repo_context_loader=repo_context_loader,
            press_cfg=press_cfg, raw_cfg=raw_cfg,
        )
        self._rag_registry = None
        self.repo_auto_indexer = None
```

- [ ] **Step 5: Run tests**

```bash
python3 -m pytest tests/test_orchestrator_mcp_init.py -v --tb=short
```

Expected: All tests PASS (including the new one).

- [ ] **Step 6: Commit**

```bash
git add orchestrator.py tests/test_orchestrator_mcp_init.py
git commit -m "refactor: extract _init_core_attrs from Orchestrator.__init__"
```

---

### Task 3: Extract `_init_tool_registries` from `__init__`

**Files:**
- Modify: `orchestrator.py:772-801` (MCP/RAG/search registry block)
- Test: `tests/test_orchestrator_mcp_init.py`

- [ ] **Step 1: Verify existing test still covers the behavior**

```bash
python3 -m pytest tests/test_orchestrator_mcp_init.py -v --tb=short
```

Expected: All PASS (existing `test_mcp_init_failure_leaves_builtin_tools` covers the registry behavior).

- [ ] **Step 2: Extract `_init_tool_registries`**

Add to `Orchestrator` class (after `_init_core_attrs`):

```python
def _init_tool_registries(self, mcp_servers: "list[dict] | None") -> None:
    """Build MCP, RAG and Google Search registries; store on self."""
    # Combined tool registry (builtin + optional MCP)
    if mcp_servers:
        try:
            mcp_registry = MCPToolRegistry(mcp_servers)
            tool_registry = CombinedToolRegistry(builtin_tools, mcp_registry)
        except Exception as exc:
            log.warning("[orchestrator] MCP init failed: %s — continuing with builtin tools only", exc)
            tool_registry = builtin_tools
    else:
        tool_registry = builtin_tools
    self._tool_registry = tool_registry

    # RAG server (isolated from builtin tools for RAG-capable agents)
    rag_servers = [s for s in (mcp_servers or []) if s.get("name") == "rag"]
    try:
        rag_registry = MCPToolRegistry(rag_servers) if rag_servers else None
    except Exception as exc:
        log.warning("[orchestrator] RAG MCP init failed: %s — RAG disabled", exc)
        rag_registry = None
    self._rag_registry = rag_registry
    self.repo_auto_indexer = RepoAutoIndexer() if rag_registry else None

    # Google Search MCP (for news_reviewer etc.)
    search_servers = [s for s in (mcp_servers or []) if s.get("name") == "google_search"]
    try:
        search_registry = MCPToolRegistry(search_servers) if search_servers else None
    except Exception as exc:
        log.warning("[orchestrator] Google Search MCP init failed: %s — web search disabled", exc)
        search_registry = None
    self._search_registry = search_registry
```

- [ ] **Step 3: Replace block in `__init__`**

In `__init__`, replace lines 767–814 (from `# RAG registry...` comment through `self.agent_kwargs = agent_kwargs`) with:

```python
        self._init_tool_registries(mcp_servers)

        agent_kwargs: dict = {
            "github_token": github_token, "ollama_url": ollama_url,
            "ollama_api_key": ollama_api_key,
            "ollama_think": ollama_think,
            "ollama_preserve_thinking": ollama_preserve_thinking,
            "ollama_stream": ollama_stream,
            "opencode_stream": opencode_stream,
            "github_models_stream": github_models_stream,
            "nvidia_nim_api_key": nvidia_nim_api_key,
            "nvidia_nim_base_url": nvidia_nim_base_url,
            "retry_delay": retry_delay, "max_api_retries": max_api_retries,
            "inter_call_delay": inter_call_delay,
        }
        self.agent_kwargs = agent_kwargs
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/test_orchestrator_mcp_init.py -v --tb=short
```

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add orchestrator.py
git commit -m "refactor: extract _init_tool_registries from Orchestrator.__init__"
```

---

### Task 4: Extract `_init_llm_cfg` and promote `_mk` to `_make_agent_kwargs`

**Files:**
- Modify: `orchestrator.py:816-857` (LLM cfg block + `_mk` closure)
- Test: `tests/test_orchestrator_mcp_init.py`

- [ ] **Step 1: Write the failing test for `_make_agent_kwargs`**

Add to `tests/test_orchestrator_mcp_init.py`:

```python
def test_make_agent_kwargs_returns_llm_key():
    """Promoted _mk closure must return dict with 'llm' key."""
    orch = _make_minimal_orchestrator(model="gpt-4.1")
    result = orch._make_agent_kwargs("product_manager")
    assert "llm" in result
    assert result["llm"] is not None
```

- [ ] **Step 2: Run the test — expect FAIL**

```bash
python3 -m pytest tests/test_orchestrator_mcp_init.py::test_make_agent_kwargs_returns_llm_key -v
```

Expected: `FAILED — AttributeError: 'Orchestrator' object has no attribute '_make_agent_kwargs'`

- [ ] **Step 3: Extract `_init_llm_cfg`**

Add to `Orchestrator` class:

```python
def _init_llm_cfg(
    self,
    model: str,
    ollama_url: str,
    ollama_api_key: Optional[str],
    ollama_think: bool,
    ollama_preserve_thinking: bool,
    ollama_stream: bool,
    opencode_stream: bool,
    github_models_stream: bool,
    nvidia_nim_api_key: Optional[str],
    nvidia_nim_base_url: Optional[str],
    llm_fallbacks: Optional[list],
    llm_cfg: Optional[dict],
) -> None:
    """Build self._llm_cfg from params; deep-merge caller-supplied cfg."""
    self._llm_cfg: dict = {
        "model": model,
        "ollama_url": ollama_url,
        "ollama_api_key": ollama_api_key,
        "ollama_think": ollama_think,
        "ollama_preserve_thinking": ollama_preserve_thinking,
        "ollama_stream": ollama_stream,
        "opencode_stream": opencode_stream,
        "github_models_stream": github_models_stream,
    }
    if nvidia_nim_api_key is not None:
        self._llm_cfg["nvidia_nim_api_key"] = nvidia_nim_api_key
    if nvidia_nim_base_url is not None:
        self._llm_cfg["nvidia_nim_base_url"] = nvidia_nim_base_url
    if llm_fallbacks:
        self._llm_cfg["fallbacks"] = llm_fallbacks
    if llm_cfg:
        self._llm_cfg = _deep_merge(self._llm_cfg, llm_cfg)
```

- [ ] **Step 4: Extract `_make_agent_kwargs` (replaces the `_mk` closure)**

Add to `Orchestrator` class:

```python
def _make_agent_kwargs(
    self, agent_name: str, model_fallback: Optional[str] = None
) -> dict:
    """Return ``{"llm": backend}`` for a named agent.

    Routes to :meth:`_make_backend_from_model` when *model_fallback* is given
    (tier agents whose model is resolved via team config), or to
    :meth:`_make_backend` for all other agents.
    """
    if model_fallback:
        backend = self._make_backend_from_model(model_fallback)
    else:
        backend = self._make_backend(agent_name)
    return {"llm": backend}
```

- [ ] **Step 5: Replace block in `__init__`**

In `__init__`, replace lines 816–857 (the `# ── Global LLM config dict` block through the end of the `_mk` closure definition) with:

```python
        self._init_llm_cfg(
            model=model, ollama_url=ollama_url,
            ollama_api_key=ollama_api_key, ollama_think=ollama_think,
            ollama_preserve_thinking=ollama_preserve_thinking,
            ollama_stream=ollama_stream, opencode_stream=opencode_stream,
            github_models_stream=github_models_stream,
            nvidia_nim_api_key=nvidia_nim_api_key,
            nvidia_nim_base_url=nvidia_nim_base_url,
            llm_fallbacks=llm_fallbacks, llm_cfg=llm_cfg,
        )
```

All occurrences of `_mk(...)` in `__init__` body below this point must be replaced with `self._make_agent_kwargs(...)`. The `_model(agent_name)` closure is already unused (its logic is inside `_make_backend`) and can simply be deleted.

- [ ] **Step 6: Run the new test + all mcp_init tests**

```bash
python3 -m pytest tests/test_orchestrator_mcp_init.py -v --tb=short
```

Expected: All PASS including `test_make_agent_kwargs_returns_llm_key`.

- [ ] **Step 7: Commit**

```bash
git add orchestrator.py tests/test_orchestrator_mcp_init.py
git commit -m "refactor: extract _init_llm_cfg, promote _mk closure to _make_agent_kwargs"
```

---

### Task 5: Extract agent init helpers from `__init__`

**Files:**
- Modify: `orchestrator.py:859-928` (agent instantiation block)

- [ ] **Step 1: Extract `_init_standard_agents`**

Add to `Orchestrator` class:

```python
def _init_standard_agents(
    self, agent_kwargs: dict, deploy_cfg: "dict | None"
) -> None:
    """Instantiate PM, news, architect, engineer, QA and deployment agents."""
    mk = self._make_agent_kwargs
    rag = self._rag_registry
    search = self._search_registry
    tools = self._tool_registry
    self.pm = ProductManagerAgent(**{**agent_kwargs, **mk("product_manager")})
    self.news_writer = NewsWriterAgent(tool_registry=search, **{**agent_kwargs, **mk("news_writer")})
    self.news_editor = NewsEditorAgent(**{**agent_kwargs, **mk("news_editor")})
    self.news_reviewer = NewsReviewerAgent(tool_registry=search, **{**agent_kwargs, **mk("news_reviewer")})
    self.translator = TranslatorAgent(**{**agent_kwargs, **mk("translator")})
    self.pm_reviewer = PMReviewerAgent(**{**agent_kwargs, **mk("pm_reviewer")})
    self.architect = ArchitectAgent(tool_registry=rag, **{**agent_kwargs, **mk("architect")})
    self.architect_reviewer = ArchitectReviewerAgent(**{**agent_kwargs, **mk("architect_reviewer")})
    self.engineer = EngineerAgent(tool_registry=rag, **{**agent_kwargs, **mk("engineer")})
    self.reviewer = CodeReviewerAgent(tool_registry=tools, **{**agent_kwargs, **mk("code_reviewer")})
    self.qa_planner = QAPlannerAgent(tool_registry=tools, **{**agent_kwargs, **mk("qa_planner")})
    self.qa = QAEngineerAgent(tool_registry=rag, **{**agent_kwargs, **mk("qa_engineer")})
    _deploy_cfg = deploy_cfg or {"mode": "docker"}
    self._deploy_cfg = _deploy_cfg
    _deploy_backend = build_deploy_backend(_deploy_cfg)
    self.deployment_tester = DeploymentTesterAgent(
        deploy_backend=_deploy_backend,
        deploy_config=_deploy_cfg,
        **{**agent_kwargs, **mk("deployment_tester")},
    )
```

- [ ] **Step 2: Extract `_init_tier_agents`**

Add to `Orchestrator` class:

```python
def _init_tier_agents(self, agent_kwargs: dict) -> None:
    """Instantiate junior/senior/tier-reviewer agents and snapshot system prompts."""
    mk = self._make_agent_kwargs
    rag = self._rag_registry
    _junior_fallback = (
        None if "junior_engineer" in self.model_overrides
        else (self.junior_model or self.model)
    )
    _senior_fallback = (
        None if "senior_engineer" in self.model_overrides
        else (self.senior_model or self.model)
    )
    _tier_rev_fallback = (
        None if "tier_reviewer" in self.model_overrides
        else (self.tier_reviewer_model or self.junior_model or self.model)
    )
    self.junior_engineer = JuniorEngineerAgent(
        tool_registry=rag if self.junior_engineer_use_mcp else None,
        **{**agent_kwargs, **mk("junior_engineer", model_fallback=_junior_fallback)},
    )
    self.senior_engineer = SeniorEngineerAgent(
        tool_registry=rag if self.senior_engineer_use_mcp else None,
        **{**agent_kwargs, **mk("senior_engineer", model_fallback=_senior_fallback)},
    )
    self.tier_reviewer = TierReviewerAgent(
        **{**agent_kwargs, **mk("tier_reviewer", model_fallback=_tier_rev_fallback)},
    )
    self._original_system_prompts: dict = {
        agent: agent.system_prompt
        for agent in (
            self.pm, self.news_writer, self.news_editor, self.news_reviewer,
            self.pm_reviewer, self.architect, self.architect_reviewer,
            self.engineer, self.junior_engineer, self.senior_engineer,
            self.reviewer, self.qa_planner, self.qa, self.deployment_tester,
        )
        if agent is not None
    }
```

- [ ] **Step 3: Extract `_init_support_agents`**

Add to `Orchestrator` class:

```python
def _init_support_agents(self, agent_kwargs: dict) -> None:
    """Instantiate summariser, refactor agent and memory store."""
    mk = self._make_agent_kwargs
    self.summariser = SummaryAgent(**{**agent_kwargs, **mk("summariser")})
    self.refactor_agent = RefactorAgent(**{**agent_kwargs, **mk("refactor_agent")})
    self.memory = MemoryStore(self.workspace_dir / "memory.db")
```

- [ ] **Step 4: Replace agent block in `__init__`**

In `__init__`, replace lines 859–928 with:

```python
        self._init_standard_agents(agent_kwargs, deploy_cfg)
        self._init_tier_agents(agent_kwargs)
        self._init_support_agents(agent_kwargs)
```

- [ ] **Step 5: Run broader test suite**

```bash
python3 -m pytest tests/test_orchestrator_mcp_init.py tests/test_checkpoint_thread_safety.py tests/test_discuss_orchestrator.py -v --tb=short
```

Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add orchestrator.py
git commit -m "refactor: extract _init_standard_agents, _init_tier_agents, _init_support_agents"
```

---

### Task 6: Extract remaining `__init__` helpers + verify `__init__` body ≤30 lines

**Files:**
- Modify: `orchestrator.py:930-991` (GitHub, pipeline config, health/signals)

- [ ] **Step 1: Extract `_init_github`**

Add to `Orchestrator` class:

```python
def _init_github(
    self,
    github_repo: Optional[str],
    github_token: Optional[str],
    target_repo: Optional[str],
) -> None:
    """Create tracker and target GitHubClient instances."""
    self.github: Optional[GitHubClient] = None
    if self.use_github and github_repo:
        self.github = GitHubClient(repo=github_repo, github_token=github_token)
        self._ensure_github_labels()
    self.target_github: Optional[GitHubClient] = None
    if target_repo and target_repo != github_repo:
        self.target_github = GitHubClient(repo=target_repo, github_token=github_token)
    else:
        self.target_github = self.github
```

- [ ] **Step 2: Extract `_init_pipeline_config`**

Add to `Orchestrator` class:

```python
def _init_pipeline_config(
    self,
    pipeline_mode: str,
    stage_skips: "dict[str, bool] | None",
    pipeline_yaml_stages: "list | None",
    progress_tracker_mode: str,
    tdd_commit_tests: bool,
    cost_tracking: "dict | None",
    update_branch_enabled: bool,
    conflict_resolver_model: Optional[str],
) -> None:
    """Assign pipeline-mode flags, cost tracking and stage-timeout config."""
    self._mode: str = pipeline_mode
    self._stage_skips: dict[str, bool] = stage_skips or {}
    self._pipeline_yaml_stages: "list | None" = pipeline_yaml_stages
    self._discussions_dir: Path = Path(__file__).parent / "discussions"
    self.progress_tracker_mode: str = progress_tracker_mode
    self.tdd_commit_tests: bool = tdd_commit_tests
    self._cost_tracking: dict = cost_tracking or {}
    self._update_branch_enabled: bool = update_branch_enabled
    self.conflict_resolver_model: Optional[str] = conflict_resolver_model
    ct = self._cost_tracking
    if ct.get("enabled", False):
        max_cost = None
        if ct.get("max_cost_usd") is not None:
            try:
                max_cost = float(ct["max_cost_usd"])
            except (TypeError, ValueError):
                pass
        ledger = TokenLedger(pricing=ct.get("pricing", {}), max_cost_usd=max_cost)
        set_ledger(ledger)
    self._stage_timeouts: dict[str, float] = {}
    _pipeline_cfg: dict = {}
    if hasattr(self, "_cfg"):
        _pipeline_cfg = self._cfg.get("pipeline", {}) or {}
    for _stage_name, _secs in (_pipeline_cfg.get("stage_timeouts") or {}).items():
        try:
            self._stage_timeouts[_stage_name] = float(_secs)
        except (TypeError, ValueError):
            pass
```

- [ ] **Step 3: Extract `_init_health_and_signals`**

Add to `Orchestrator` class:

```python
def _init_health_and_signals(self) -> None:
    """Set up AgentHealthMonitor and graceful shutdown signal handlers."""
    from core.agent_health import AgentHealthMonitor
    self._agent_health = AgentHealthMonitor(failure_threshold=3)
    self._shutdown_event = threading.Event()

    def _handle_shutdown(signum, frame) -> None:
        self._shutdown_event.set()

    if threading.current_thread() is threading.main_thread():
        import signal as _signal
        _signal.signal(_signal.SIGTERM, _handle_shutdown)
        _signal.signal(_signal.SIGINT, _handle_shutdown)
```

- [ ] **Step 4: Replace blocks in `__init__`**

Replace lines 930–991 (from `# Long-term SQLite memory store` through the signal handler block) with:

```python
        self._init_github(
            github_repo=github_repo,
            github_token=github_token,
            target_repo=target_repo,
        )
        self._init_pipeline_config(
            pipeline_mode=pipeline_mode,
            stage_skips=stage_skips,
            pipeline_yaml_stages=pipeline_yaml_stages,
            progress_tracker_mode=progress_tracker_mode,
            tdd_commit_tests=tdd_commit_tests,
            cost_tracking=cost_tracking,
            update_branch_enabled=update_branch_enabled,
            conflict_resolver_model=conflict_resolver_model,
        )
        self._init_health_and_signals()
```

- [ ] **Step 5: Verify `__init__` body is ≤30 lines**

Count the lines of the `__init__` body (everything after the signature, before the next method):

```bash
python3 - <<'EOF'
import ast, pathlib

src = pathlib.Path("orchestrator.py").read_text()
tree = ast.parse(src)
for node in ast.walk(tree):
    if isinstance(node, ast.ClassDef) and node.name == "Orchestrator":
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                lines = item.end_lineno - item.lineno + 1
                print(f"__init__ total lines (incl. signature): {lines}")
EOF
```

Expected: ≤80 lines total (signature is ~60 lines; body calls should be ~20 lines).

- [ ] **Step 6: Run full orchestrator tests**

```bash
python3 -m pytest tests/test_orchestrator_mcp_init.py tests/test_orchestrator_stage_timeout.py tests/test_orchestrator_run_functional.py tests/test_checkpoint_thread_safety.py -v --tb=short 2>&1 | tail -20
```

Expected: All PASS.

- [ ] **Step 7: Commit**

```bash
git add orchestrator.py
git commit -m "refactor: extract _init_github, _init_pipeline_config, _init_health_and_signals — __init__ body now ≤30 lines"
```

---

### Task 7: Split `_make_stage_registry` into 5 sub-builders

**Files:**
- Modify: `orchestrator.py:1773-2036`
- Test: `tests/test_orchestrator_mcp_init.py`

- [ ] **Step 1: Write failing test for `_build_product_stages`**

Add to `tests/test_orchestrator_mcp_init.py`:

```python
def test_build_product_stages_returns_expected_keys():
    """_build_product_stages must return pm, architect and revision-loop stages."""
    orch = _make_minimal_orchestrator()
    stages = orch._build_product_stages()
    assert "pm" in stages
    assert "architect" in stages
    assert "architect_reviewer" in stages
    assert "pm_reviewer" in stages
    assert "tier_review" in stages
```

- [ ] **Step 2: Run test — expect FAIL**

```bash
python3 -m pytest tests/test_orchestrator_mcp_init.py::test_build_product_stages_returns_expected_keys -v
```

Expected: `FAILED — AttributeError: 'Orchestrator' object has no attribute '_build_product_stages'`

- [ ] **Step 3: Extract `_build_product_stages`**

Add to `Orchestrator` class:

```python
def _build_product_stages(self) -> "dict[str, PipelineStage]":
    """Build product/design pipeline stages: PM, architect, tier-review."""
    return {
        "pm": PipelineStage(
            name="pm", label="📋 Product Manager",
            description="Analyzing requirements & writing PRD...",
            checkpoint_key="pm", fn=lambda r: self._stage_pm(r, r.requirement),
            required_output_fields=["prd"], is_critical=True,
        ),
        "pm_reviewer": PipelineStage(
            name="pm_reviewer", label="📝 PM Reviewer",
            description="Reviewing PRD for completeness...",
            checkpoint_key="pm_reviewer",
            fn=lambda r: self._stage_pm_reviewer(r, r.requirement),
        ),
        "architect": PipelineStage(
            name="architect", label="🏗️  Architect",
            description="Designing system architecture...",
            checkpoint_key="architect", fn=lambda r: self._stage_architect(r),
            required_output_fields=["design"], is_critical=True,
        ),
        "architect_reviewer": PipelineStage(
            name="architect_reviewer", label="🔎 Architect Reviewer",
            description="Reviewing system design...",
            checkpoint_key="architect_reviewer",
            fn=lambda r: self._stage_architect_reviewer(r),
        ),
        "tier_review": PipelineStage(
            name="tier_review", label="🏷️  Tier Review",
            description="Classifying modules into junior/senior tiers...",
            checkpoint_key="tier_review", fn=lambda r: self._stage_tier_review(r),
        ),
    }
```

- [ ] **Step 4: Extract `_build_engineering_stages`**

Add to `Orchestrator` class:

```python
def _build_engineering_stages(self) -> "dict[str, PipelineStage]":
    """Build engineering pipeline stages: engineer, QA, test/deploy loops."""
    return {
        "junior_engineer": PipelineStage(
            name="junior_engineer", label="🟢 Junior Engineers",
            description="Implementing junior module(s)...",
            checkpoint_key="junior_engineer",
            fn=lambda r: self._stage_junior_engineer(r),
            skip_if=lambda r: "engineer" in r.completed_stages,
        ),
        "senior_engineer": PipelineStage(
            name="senior_engineer", label="🔵 Senior Engineers",
            description="Implementing senior module(s)...",
            checkpoint_key="senior_engineer",
            fn=lambda r: self._stage_senior_engineer(r),
            skip_if=lambda r: "engineer" in r.completed_stages,
        ),
        "reviewer": PipelineStage(
            name="reviewer", label="🔍 Code Reviewer",
            description="Reviewing generated code...",
            checkpoint_key="reviewer", fn=lambda r: self._stage_reviewer(r),
            stop_if=lambda r: self.stop_on_review_issues and r.verdict == "CHANGES REQUESTED",
            stop_message="⛔ Pipeline stopped: code reviewer requested changes.",
        ),
        "qa_planner": PipelineStage(
            name="qa_planner", label="📋 QA Planner",
            description="Creating test plan & acceptance criteria...",
            checkpoint_key="qa_planner", fn=lambda r: self._stage_qa_planner(r),
        ),
        "qa_engineer": PipelineStage(
            name="qa_engineer", label="🧪 QA Engineer",
            description="Writing tests & producing test plan...",
            checkpoint_key="qa", fn=lambda r: self._stage_qa(r),
        ),
        "qa_write": PipelineStage(
            name="qa_write", label="✍️  QA Write (TDD)",
            description="Writing tests before implementation...",
            checkpoint_key="qa_write", fn=lambda r: self._stage_qa_write(r),
        ),
        "test_fix": PipelineStage(
            name="test_fix", label="🏃 Test Runner + Fix Loop",
            description="Executing tests (with auto-fix)…",
            checkpoint_key="test_runner", fn=lambda r: self._stage_test_fix_loop(r),
            skip_if=lambda r: not r.test_files,
        ),
        "deploy_tester": PipelineStage(
            name="deploy_tester", label="🚀 Deployment Tester",
            description="Generating deployment smoke tests...",
            checkpoint_key="deployment_tester",
            fn=lambda r: self._stage_deployment_tester(r),
        ),
        "deploy_fix": PipelineStage(
            name="deploy_fix", label="🐳 Deploy Test Runner + Fix Loop",
            description="Running deployment tests (with auto-fix)…",
            checkpoint_key="deploy_test_runner",
            fn=lambda r: self._stage_deploy_fix_loop(r),
            skip_if=lambda r: not r.deploy_files,
        ),
        "engineer": PipelineStage(
            name="engineer", label="👷 Engineer",
            description="Implementing modules (single-tier)...",
            checkpoint_key="engineer", fn=lambda r: self._stage_engineer(r),
        ),
    }
```

- [ ] **Step 5: Extract `_build_content_stages`**

Add to `Orchestrator` class:

```python
def _build_content_stages(self) -> "dict[str, PipelineStage]":
    """Build news/content pipeline stages."""
    return {
        "news_triage": PipelineStage(
            name="news_triage", label="🗞️  Editorial Triage",
            description="Editorial team voting: publish or skip?",
            checkpoint_key="news_triage", fn=lambda r: self._stage_news_triage(r),
            stop_if=lambda r: r.editorial_verdict == "SKIP",
            stop_message="🚫 Editorial triage: story skipped — pipeline aborted.",
        ),
        "news_writer": PipelineStage(
            name="news_writer", label="✍️  News Writer",
            description="Writing news article draft...",
            checkpoint_key="news_writer", fn=lambda r: self._stage_news_writer(r),
        ),
        "news_editor": PipelineStage(
            name="news_editor", label="📝 News Editor",
            description="Editing and finalising article...",
            checkpoint_key="news_editor", fn=lambda r: self._stage_news_editor(r),
        ),
        "translate_cantonese": PipelineStage(
            name="translate_cantonese", label="🀄 Translate (Cantonese)",
            description="Translating article to Written Cantonese...",
            checkpoint_key="translate_cantonese",
            fn=lambda r: self._stage_translate(r, "cantonese", "article_zh_hk"),
        ),
        "translate_zh_traditional": PipelineStage(
            name="translate_zh_traditional", label="🀄 Translate (Traditional Chinese)",
            description="Translating article to Traditional Chinese...",
            checkpoint_key="translate_zh_traditional",
            fn=lambda r: self._stage_translate(r, "traditional_chinese", "article_zh_tw"),
        ),
        "news_reviewer": PipelineStage(
            name="news_reviewer", label="🔍 News Reviewer",
            description="Reviewing article quality and translation correctness...",
            checkpoint_key="news_reviewer", fn=lambda r: self._stage_news_reviewer(r),
        ),
        "news_article_pr": PipelineStage(
            name="news_article_pr", label="📨 News Article PR",
            description="Opening PR with article...",
            checkpoint_key="news_article_pr",
            fn=lambda r: self._stage_news_article_pr(r),
        ),
    }
```

- [ ] **Step 6: Extract `_build_utility_stages`**

Add to `Orchestrator` class:

```python
def _build_utility_stages(self) -> "dict[str, PipelineStage]":
    """Build utility pipeline stages: diagnose, docs, PR campaign, validation."""
    return {
        "diagnose": PipelineStage(
            name="diagnose", label="🔬 Diagnoser",
            description="Diagnosing bug from issue body and existing files...",
            checkpoint_key="diagnose", fn=lambda r: self._stage_diagnose(r),
        ),
        "bug_fix": PipelineStage(
            name="bug_fix", label="🛠️  Bug Fix",
            description="Applying bug fix patches...",
            checkpoint_key="bug_fix", fn=lambda r: self._stage_bug_fix(r),
        ),
        "doc_generate": PipelineStage(
            name="doc_generate", label="📚 Doc Generator",
            description="Generating documentation files...",
            checkpoint_key="doc_generate", fn=lambda r: self._stage_doc_generate(r),
        ),
        "doc_commit_pr": PipelineStage(
            name="doc_commit_pr", label="📤 Doc Commit + PR",
            description="Committing docs and opening PR...",
            checkpoint_key="doc_commit_pr", fn=lambda r: self._stage_doc_commit_pr(r),
        ),
        "pr_analyst": PipelineStage(
            name="pr_analyst", label="🔍 PR Analyst",
            description="Analysing campaign brief...",
            checkpoint_key="pr_analyst", fn=lambda r: self._stage_pr_analyst(r),
        ),
        "pr_creative": PipelineStage(
            name="pr_creative", label="🎨 PR Creative",
            description="Generating campaign concepts...",
            checkpoint_key="pr_creative", fn=lambda r: self._stage_pr_creative(r),
        ),
        "pr_proposal": PipelineStage(
            name="pr_proposal", label="📋 PR Proposal",
            description="Assembling proposal and opening PR...",
            checkpoint_key="pr_proposal", fn=lambda r: self._stage_pr_proposal(r),
        ),
        "validation_gate": PipelineStage(
            name="validation_gate", label="🔍 Validation Gate",
            description="Syntax-checking and linting generated code...",
            checkpoint_key="validation_gate",
            fn=lambda r: self._stage_validation_gate(r),
        ),
        "bootstrap_patterns": PipelineStage(
            name="bootstrap_patterns", label="🌱 Bootstrap Patterns",
            description="Scanning repo and generating .github/AGENTS.md...",
            checkpoint_key="bootstrap_patterns",
            fn=lambda r: self._stage_bootstrap_patterns(r),
        ),
    }
```

- [ ] **Step 7: Extract `_build_discussion_stages`**

Add to `Orchestrator` class:

```python
def _build_discussion_stages(self) -> "dict[str, PipelineStage]":
    """Auto-discover discussions/*.yaml and register as discuss_<name> stages."""
    registry: dict[str, PipelineStage] = {}
    discussions_dir = getattr(self, "_discussions_dir", Path(__file__).parent / "discussions")
    if not discussions_dir.is_dir():
        return registry
    all_presets = sorted(
        list(discussions_dir.glob("*.yaml")) + list(discussions_dir.glob("*.yml"))
    )
    for preset_path in all_presets:
        stage_key = f"discuss_{preset_path.stem.replace('-', '_')}"
        if stage_key in registry:
            log.warning(
                "discuss stage key collision: '%s' from '%s' already registered; skipping.",
                stage_key, preset_path.name,
            )
            continue
        label_name = preset_path.stem.replace("-", " ").replace("_", " ").title()
        registry[stage_key] = PipelineStage(
            name=stage_key,
            label=f"💬 Discuss: {label_name}",
            description=f"Multi-agent round-table discussion ({preset_path.name})",
            checkpoint_key=stage_key,
            fn=lambda r, p=str(preset_path): self._stage_discuss(r, p),
        )
    return registry
```

- [ ] **Step 8: Replace `_make_stage_registry` body**

Replace the entire body of `_make_stage_registry` (keeping the def signature and docstring) with:

```python
    def _make_stage_registry(self) -> "dict[str, PipelineStage]":
        """Build the full registry of all known pipeline stages."""
        registry: dict[str, PipelineStage] = {
            **self._build_product_stages(),
            **self._build_engineering_stages(),
            **self._build_content_stages(),
            **self._build_utility_stages(),
            **self._build_discussion_stages(),
        }
        for _name, _stage in registry.items():
            if _name in (self._stage_timeouts or {}):
                _stage.timeout_s = self._stage_timeouts[_name]  # type: ignore[index]
        return registry
```

- [ ] **Step 9: Run tests**

```bash
python3 -m pytest tests/test_orchestrator_mcp_init.py::test_build_product_stages_returns_expected_keys tests/test_discuss_orchestrator.py -v --tb=short
```

Expected: All PASS.

- [ ] **Step 10: Commit**

```bash
git add orchestrator.py tests/test_orchestrator_mcp_init.py
git commit -m "refactor: split _make_stage_registry into 5 sub-builders"
```

---

### Task 8: Extract context-setup helpers from `run`

**Files:**
- Modify: `orchestrator.py:2876-3028` (top of `run` before the try block)

- [ ] **Step 1: Extract `_resolve_target_repo`**

Add to `Orchestrator` class (after `_build_discussion_stages`):

```python
def _resolve_target_repo(self, trigger_issue_body: Optional[str]) -> None:
    """Override target_github if trigger body specifies a different repo."""
    target_repo_override = parse_target_repo(trigger_issue_body or "")
    if target_repo_override and self.github and target_repo_override != self.github.repo:
        self.target_github = GitHubClient(
            repo=target_repo_override, github_token=self._github_token
        )
        console.print(f"  🎯 Targeting project repo: [bold]{target_repo_override}[/bold]")
    elif not self.target_github:
        self.target_github = self.github
```

- [ ] **Step 2: Extract `_inject_repo_context`**

Add to `Orchestrator` class:

```python
def _inject_repo_context(self) -> None:
    """Load repo file tree and prepend to planning agents' system prompts."""
    if not (self.repo_context_loader and self.target_github):
        return
    repo_context = self.repo_context_loader.build(self.target_github)
    if not repo_context.tree_text:
        return
    size_label = "large" if repo_context.is_large else "small"
    console.print(
        f"  🗂️  [dim]Repo tree loaded ({repo_context.file_count} files, {size_label})[/dim]"
    )
    tree_block = repo_context.tree_text + "\n\n---\n\n"
    for agent in (self.pm, self.architect, self.pm_reviewer, self.architect_reviewer):
        if agent.system_prompt is not None and not agent.system_prompt.startswith(tree_block):
            agent.system_prompt = tree_block + agent.system_prompt
```

- [ ] **Step 3: Extract `_inject_memory`**

Add to `Orchestrator` class:

```python
def _inject_memory(self) -> None:
    """Load long-term memory and prepend to engineering agents' system prompts."""
    active_repo = str(
        self.target_github.repo if self.target_github
        else (self.github.repo if self.github else "local")
    )
    memory_context = self.memory.recall(active_repo)
    if not memory_context:
        return
    console.print(f"  🧠 [dim]Loaded memory from {active_repo}[/dim]")
    for agent in (
        self.pm, self.architect, self.engineer,
        self.junior_engineer, self.senior_engineer,
        self.reviewer, self.qa, self.qa_planner,
    ):
        if agent.system_prompt is not None:
            original = self._original_system_prompts.get(agent, agent.system_prompt)
            agent.system_prompt = memory_context + "\n\n---\n\n" + original
```

- [ ] **Step 4: Extract `_inject_skills`**

Add to `Orchestrator` class:

```python
def _inject_skills(
    self, trigger_issue_body: Optional[str], requirement: str
) -> None:
    """Detect and inject skill blocks into each role agent's system prompt."""
    if not self.skill_loader:
        return
    active_repo = str(
        self.target_github.repo if self.target_github
        else (self.github.repo if self.github else "local")
    )
    repo_languages: list[str] = []
    if self.target_github:
        repo_languages = self.target_github.get_repo_languages(active_repo)
    explicit_skills = _parse_explicit_skills(trigger_issue_body or "")
    skill_ctx = SkillContext(
        issue_body=trigger_issue_body or requirement,
        explicit_skills=explicit_skills,
        repo_languages=repo_languages,
    )
    matched_skills = self.skill_loader.detect(skill_ctx)
    if matched_skills:
        skill_names = ", ".join(s.name for s in matched_skills)
        console.print(f"  🎯 [dim]Skills loaded: {skill_names}[/dim]")
    _role_agents = {
        "product_manager": self.pm, "pm_reviewer": self.pm_reviewer,
        "architect": self.architect, "architect_reviewer": self.architect_reviewer,
        "engineer": self.engineer, "junior_engineer": self.junior_engineer,
        "senior_engineer": self.senior_engineer, "tier_reviewer": self.tier_reviewer,
        "code_reviewer": self.reviewer, "qa_planner": self.qa_planner,
        "qa_engineer": self.qa, "deployment_tester": self.deployment_tester,
    }
    for role, agent in _role_agents.items():
        blocks = self.skill_loader.for_role(role, matched_skills)
        block_text = self.skill_loader.render_prompt_block(blocks)
        if block_text:
            original = self._original_system_prompts.get(agent, agent.system_prompt or "")
            if original:
                agent.system_prompt = block_text + "\n\n---\n\n" + original
```

- [ ] **Step 5: Extract `_load_or_init_result`**

Add to `Orchestrator` class:

```python
def _load_or_init_result(
    self,
    requirement: str,
    resume: bool,
    issue_number: Optional[int],
    trigger_issue_body: Optional[str],
    run_id: str,
) -> "PipelineResult":
    """Load checkpoint or create a fresh PipelineResult; extract prior context."""
    result = self._load_checkpoint(requirement) if resume else None
    if result:
        console.print(
            f"[bold yellow]⏭️  Resuming from checkpoint[/bold yellow] "
            f"(completed: {', '.join(result.completed_stages)})"
        )
    else:
        result = PipelineResult(requirement=requirement)
    _prior_marker = "\n\n---\n\n## 📜 Prior Work Context\n\n"
    if trigger_issue_body and _prior_marker in trigger_issue_body:
        self._issue_prior_context: str = trigger_issue_body[
            trigger_issue_body.index(_prior_marker) + len("\n\n---\n\n"):
        ]
    else:
        self._issue_prior_context = ""
    if not result.run_id:
        result.run_id = run_id
    if issue_number is not None and not result.issue_number:
        result.issue_number = issue_number
    return result
```

- [ ] **Step 6: Extract `_setup_progress_tracker`**

Add to `Orchestrator` class:

```python
def _setup_progress_tracker(self, result: "PipelineResult") -> None:
    """Build ProgressTracker; restore from checkpoint if resuming."""
    self._tracker = ProgressTracker(
        github=self.github,
        issue_number=result.issue_number,
        mode=self.progress_tracker_mode,
    )
    if result.progress_comment_id:
        self._tracker.restore(result.progress_comment_id)
        self._tracker.restore_stages(result.completed_stages)
    self._tracker.set_stages(self._expected_stages())
    result.progress_comment_id = self._tracker.comment_id
```

- [ ] **Step 7: Replace the top of `run` with calls**

Replace lines 2889–3027 (from `start_time = time.time()` through the panel print, leaving the `try:` intact) with:

```python
        start_time = time.time()
        run_id = str(uuid.uuid4())
        ct = self._cost_tracking
        if ct.get("enabled", False):
            active_repo = str(
                self.target_github.repo if self.target_github
                else (self.github.repo if self.github else "local")
            )
            get_ledger().start_run(run_id, "", active_repo)

        self._resolve_target_repo(trigger_issue_body)
        self._inject_repo_context()
        self._inject_memory()
        self._inject_skills(trigger_issue_body, requirement)
        result = self._load_or_init_result(
            requirement, resume, issue_number, trigger_issue_body, run_id
        )
        self._setup_progress_tracker(result)

        console.print(Panel.fit(
            f"[bold cyan]🏢 AI Software House Pipeline[/bold cyan]\n"
            f"[dim]{requirement[:120]}{'...' if len(requirement) > 120 else ''}[/dim]",
            border_style="cyan",
        ))
```

- [ ] **Step 8: Run orchestrator tests**

```bash
python3 -m pytest tests/test_orchestrator_run_functional.py tests/test_orchestrator_mcp_init.py -v --tb=short 2>&1 | tail -20
```

Expected: All PASS.

- [ ] **Step 9: Commit**

```bash
git add orchestrator.py
git commit -m "refactor: extract run() context-setup helpers (_resolve_target_repo, _inject_repo_context, _inject_memory, _inject_skills, _load_or_init_result, _setup_progress_tracker)"
```

---

### Task 9: Extract stage-loop helpers from `run`

**Files:**
- Modify: `orchestrator.py:3029-3190` (the `try` block inside `run`)

- [ ] **Step 1: Extract `_run_preamble_stages`**

Add to `Orchestrator` class:

```python
def _run_preamble_stages(
    self, result: "PipelineResult", requirement: str, start_time: float
) -> "Optional[PipelineResult]":
    """Run PM/arch revision loops and RAG index; return early-exit result or None."""
    if getattr(self, "_pipeline_yaml_stages", None) is None:
        if "pm_review_loop" not in result.completed_stages:
            if not self._prd_revision_loop(result, requirement):
                return self._finish(result, start_time)
        else:
            console.print("  ⏭️  [dim]PRD revision loop — skipped (checkpoint)[/dim]")
        if "architect_review_loop" not in result.completed_stages:
            if not self._design_revision_loop(result):
                return self._finish(result, start_time)
        else:
            console.print("  ⏭️  [dim]Design revision loop — skipped (checkpoint)[/dim]")
    self._tracker.issue_number = result.issue_number
    if self.repo_auto_indexer and self.target_github and "rag_index" not in result.completed_stages:
        self._run_stage(
            "📦 RAG Index", "Indexing repo codebase into RAG...",
            result, lambda: self._stage_repo_index(result),
        )
        result.add_completed_stage("rag_index")
    return None
```

- [ ] **Step 2: Extract `_collect_stage_batch`**

Add to `Orchestrator` class:

```python
def _collect_stage_batch(
    self, stage_list: "list[PipelineStage]", i: int
) -> "tuple[list[PipelineStage], int]":
    """Return (batch, next_i) — a parallel group or a single stage."""
    stage = stage_list[i]
    if stage.parallel_group is not None:
        batch = [stage]
        j = i + 1
        while j < len(stage_list) and stage_list[j].parallel_group == stage.parallel_group:
            batch.append(stage_list[j])
            j += 1
        return batch, j
    return [stage], i + 1
```

- [ ] **Step 3: Extract `_filter_runnable_stages`**

Add to `Orchestrator` class:

```python
def _filter_runnable_stages(
    self, batch: "list[PipelineStage]", result: "PipelineResult"
) -> "list[PipelineStage]":
    """Return stages in batch that are not checkpointed or skipped."""
    runnable = []
    for s in batch:
        if s.checkpoint_key in result.completed_stages or s.name in result.completed_stages:
            console.print(f"  ⏭️  [dim]{s.label} — skipped (checkpoint)[/dim]")
            self._tracker.mark_skipped(s.checkpoint_key)
        elif s.skip_if(result):
            console.print(f"  ⏭️  [dim]{s.label} — skipped[/dim]")
            self._tracker.mark_skipped(s.checkpoint_key)
        else:
            runnable.append(s)
    return runnable
```

- [ ] **Step 4: Extract `_execute_sequential_stage`**

Add to `Orchestrator` class:

```python
def _execute_sequential_stage(
    self, s: "PipelineStage", result: "PipelineResult", start_time: float
) -> "Optional[PipelineResult]":
    """Execute a single stage (loop-block or normal); return early-exit or None."""
    _stage_token = current_stage.set(s.checkpoint_key)
    try:
        if s.loop_stages:
            if not self._run_loop_stage(s, result):
                self._tracker.mark_failed(s.checkpoint_key)
                result.progress_comment_id = self._tracker.comment_id
                self._save_checkpoint(result)
                return self._finish(result, start_time)
        else:
            self._run_stage(
                s.label, s.description, result,
                lambda ss=s: ss.fn(result),
                required_output_fields=s.required_output_fields,
            )
    finally:
        current_stage.reset(_stage_token)
    return None
```

- [ ] **Step 5: Extract `_finalize_stage_batch`**

Add to `Orchestrator` class:

```python
def _finalize_stage_batch(
    self,
    runnable: "list[PipelineStage]",
    result: "PipelineResult",
    start_time: float,
    errors_before: int,
    stage_results: "dict[str, bool]",
) -> "Optional[PipelineResult]":
    """Mark stages done/failed, checkpoint, handle stop_if; return early-exit or None."""
    any_failed = False
    if len(runnable) > 1:
        for s in runnable:
            if not stage_results.get(s.checkpoint_key, True):
                self._tracker.mark_failed(s.checkpoint_key, str(result.errors[-1]) if result.errors else "")
                any_failed = True
            else:
                if s.name == "senior_engineer":
                    result.add_completed_stage("engineer")
                result.add_completed_stage(s.checkpoint_key)
                self._tracker.mark_done(s.checkpoint_key)
    elif len(result.errors) > errors_before:
        any_failed = True
        self._tracker.mark_failed(runnable[0].checkpoint_key, str(result.errors[-1]))
    if any_failed:
        result.progress_comment_id = self._tracker.comment_id
        self._save_checkpoint(result)
        return self._finish(result, start_time)
    if len(runnable) == 1:
        seq_s = runnable[0]
        if seq_s.name == "senior_engineer":
            result.add_completed_stage("engineer")
        result.add_completed_stage(seq_s.checkpoint_key)
        self._tracker.mark_done(seq_s.checkpoint_key)
    result.progress_comment_id = self._tracker.comment_id
    self._save_checkpoint(result)
    if len(runnable) == 1 and runnable[0].stop_if(result):
        console.print(f"\n  🛑 [bold yellow]{runnable[0].stop_message or 'Pipeline stopped early.'}[/bold yellow]")
        return self._finish(result, start_time)
    return None
```

- [ ] **Step 6: Extract `_run_stage_loop`**

Add to `Orchestrator` class:

```python
def _run_stage_loop(
    self, result: "PipelineResult", start_time: float
) -> "PipelineResult":
    """Iterate through the mode-driven stage list; return final PipelineResult."""
    stage_list = self._build_stage_list()
    i = 0
    while i < len(stage_list):
        batch, i = self._collect_stage_batch(stage_list, i)
        runnable = self._filter_runnable_stages(batch, result)
        if not runnable:
            continue
        for s in runnable:
            self._tracker.mark_in_progress(s.checkpoint_key)
        errors_before = len(result.errors)
        stage_results: dict[str, bool] = {}
        if len(runnable) > 1:
            early = self._run_parallel_batch(runnable, result, start_time, stage_results)
            if early is not None:
                return early
        else:
            early = self._execute_sequential_stage(runnable[0], result, start_time)
            if early is not None:
                return early
        early = self._finalize_stage_batch(runnable, result, start_time, errors_before, stage_results)
        if early is not None:
            return early
    self._clear_checkpoint(result)
    return self._finish(result, start_time)
```

- [ ] **Step 7: Replace `run` try-block with calls**

Replace lines 3029–3190 (the entire try/except block including the except clauses) with:

```python
        try:
            early = self._run_preamble_stages(result, requirement, start_time)
            if early is not None:
                return early
            return self._run_stage_loop(result, start_time)

        except _ShutdownRequested:
            logging.info("Graceful shutdown: pipeline interrupted before completion")
            result.progress_comment_id = self._tracker.comment_id
            self._save_checkpoint(result)
            return self._finish(result, start_time)
        except BudgetExceededError:
            logging.warning("Token budget exceeded — saving checkpoint and aborting pipeline")
            result.add_error("Pipeline aborted: token budget exceeded")
            result.progress_comment_id = self._tracker.comment_id
            self._save_checkpoint(result)
            return self._finish(result, start_time)
```

- [ ] **Step 8: Run broader test suite**

```bash
python3 -m pytest tests/test_orchestrator_run_functional.py tests/test_orchestrator_parallel.py tests/test_orchestrator_stage_timeout.py -v --tb=short 2>&1 | tail -20
```

Expected: All PASS.

- [ ] **Step 9: Commit**

```bash
git add orchestrator.py
git commit -m "refactor: split run() stage loop into _run_preamble_stages, _collect_stage_batch, _filter_runnable_stages, _execute_sequential_stage, _finalize_stage_batch, _run_stage_loop"
```

---

### Task 10: Split `run_revision` into 7 helpers

**Files:**
- Modify: `orchestrator.py:2600-2874`

- [ ] **Step 1: Extract `_revision_fetch_pr_context`**

Add to `Orchestrator` class:

```python
def _revision_fetch_pr_context(self, pr_number: int) -> "tuple[dict, str, Optional[int], list[str]]":
    """Fetch PR metadata, head branch, issue number and label list."""
    pr = self.target_github.get_pr(pr_number)
    head_branch = pr["head"]["ref"]
    pr_body = pr.get("body") or ""
    issue_number = self._extract_issue_number(pr_body)
    labels = [lbl["name"] for lbl in pr.get("labels", [])]
    return pr, head_branch, issue_number, labels
```

- [ ] **Step 2: Extract `_revision_inject_skills`**

Add to `Orchestrator` class:

```python
def _revision_inject_skills(self, pr_body: str) -> None:
    """Inject skill blocks into engineer/reviewer/qa for a PR revision."""
    if not self.skill_loader:
        return
    active_repo = self.target_github.repo
    repo_languages = self.target_github.get_repo_languages(active_repo)
    skill_ctx = SkillContext(
        issue_body=pr_body,
        explicit_skills=_parse_explicit_skills(pr_body),
        repo_languages=repo_languages,
    )
    matched_skills = self.skill_loader.detect(skill_ctx)
    for role, agent in [("engineer", self.engineer), ("code_reviewer", self.reviewer), ("qa_engineer", self.qa)]:
        blocks = self.skill_loader.for_role(role, matched_skills)
        block_text = self.skill_loader.render_prompt_block(blocks)
        if block_text:
            original = self._original_system_prompts.get(agent, agent.system_prompt or "")
            if original:
                agent.system_prompt = block_text + "\n\n---\n\n" + original
```

- [ ] **Step 3: Extract `_revision_check_cap`**

Add to `Orchestrator` class:

```python
def _revision_check_cap(self, pr_number: int, current_rev: int) -> bool:
    """Post cap-reached comment and return True if revision limit is hit."""
    if current_rev < self.max_revisions:
        return False
    self.target_github.add_pr_comment(
        pr_number,
        f"⏹ Max revisions reached ({current_rev}/{self.max_revisions}). "
        "No further automated revisions will be made.",
    )
    return True
```

- [ ] **Step 4: Extract `_revision_maybe_update_branch`**

Add to `Orchestrator` class:

```python
def _revision_maybe_update_branch(
    self, pr_number: int, pr: dict, head_branch: str
) -> "Optional[dict]":
    """If update-branch directive found, merge base into head; return conflict dict or None."""
    if not self._update_branch_enabled:
        return None
    pr_base_branch = pr["base"]["ref"]
    pr_issue_comments = self.target_github.get_issue_comments(pr_number)
    feedback = [
        {"body": c.get("body", ""), "author": c.get("user", {}).get("login", "")}
        for c in pr_issue_comments
    ]
    if not self._parse_update_directive(feedback):
        return None
    pr_ctx = PRContext(
        pr_title=pr.get("title", ""), pr_body=pr.get("body", "") or "",
        design_doc="", skills="",
    )
    update_result = self._update_branch_from_base(
        head_branch, base_branch=pr_base_branch,
        pr_number=pr_number, pr_context=pr_ctx,
    )
    return update_result if update_result["status"] == "conflict" else None
```

- [ ] **Step 5: Extract `_revision_collect_context`**

Add to `Orchestrator` class:

```python
def _revision_collect_context(
    self, pr_number: int, issue_number: Optional[int], head_branch: str
) -> "tuple[list[dict], str, dict[str, str], dict[str, dict[str, str]]]":
    """Return (feedback, design, current_files, merge_branch_files)."""
    feedback = self._collect_pr_feedback(pr_number)
    design = self._fetch_design_from_issue(issue_number) if issue_number else ""
    if not design:
        console.print("  [yellow]⚠️  No system design found — engineer will use feedback only[/yellow]")
    pr_files = self.target_github.get_pr_files(pr_number)
    current_files: dict[str, str] = {}
    for f in pr_files:
        content = self.target_github.get_file_content(f["filename"], ref=head_branch)
        if content is not None:
            current_files[f["filename"]] = content
    console.print(f"  📂 Read [bold]{len(current_files)}[/bold] file(s) from [cyan]{head_branch}[/cyan]")
    merge_branches = self._parse_merge_directives(feedback)
    merge_branch_files: dict[str, dict[str, str]] = {}
    for mb in merge_branches:
        mb_files = self._fetch_branch_files(mb)
        if mb_files:
            merge_branch_files[mb] = mb_files
            console.print(f"  📂 Fetched [bold]{len(mb_files)}[/bold] file(s) from [cyan]{mb}[/cyan]")
    return feedback, design, current_files, merge_branch_files
```

- [ ] **Step 6: Extract `_revision_build_augmented_design`**

Add to `Orchestrator` class:

```python
def _revision_build_augmented_design(
    self,
    design: str,
    head_branch: str,
    current_files: "dict[str, str]",
    feedback_md: str,
    merge_branch_files: "dict[str, dict[str, str]]",
) -> str:
    """Assemble the augmented design string for the revision engineer."""
    current_files_block = "\n\n".join(
        f"### `{path}`\n```\n{self._safe_fence(content)}\n```"
        for path, content in current_files.items()
    )
    merge_blocks = ""
    for mb, mb_files in merge_branch_files.items():
        mb_block = "\n\n".join(
            f"### `{path}`\n```\n{self._safe_fence(content)}\n```"
            for path, content in mb_files.items()
        )
        merge_blocks += (
            f"\n\n---\n\n## Files from Branch `{mb}` "
            f"(incorporate these — make the implementation pass these tests)\n\n{mb_block}"
        )
    return (
        f"{design}\n\n---\n\n"
        f"## Current Code on Branch `{head_branch}`\n\n"
        f"{current_files_block}{merge_blocks}\n\n---\n\n{feedback_md}"
    )
```

- [ ] **Step 7: Extract `_revision_run_and_commit`**

Add to `Orchestrator` class:

```python
def _revision_run_and_commit(
    self,
    pr_number: int,
    head_branch: str,
    design: str,
    augmented_design: str,
    revision_modules: list,
    project_name: str,
    new_revision: int,
    current_files: "dict[str, str]",
    merge_branch_files: "dict[str, dict[str, str]]",
) -> "tuple[Optional[dict], dict[str, str], dict, dict[str, str]]":
    """Run engineer→reviewer→QA; commit files. Return (error_dict, revised_files, rev_result, test_files)."""
    console.print("  👷 [cyan]Engineer[/cyan] — revising code based on PR feedback...")
    eng_result = self.engineer.run_all_modules(augmented_design, revision_modules, project_name)
    revised_files: dict[str, str] = eng_result.get("all_files", {})
    if not revised_files:
        self.target_github.add_pr_comment(pr_number, "⚠️ Revision aborted: the engineer agent produced no updated files.")
        return {"status": "error", "reason": "engineer_returned_no_files"}, {}, {}, {}
    commit_errors: list[str] = []
    for filepath, content in revised_files.items():
        try:
            self.target_github.commit_file(
                path=filepath, content=content,
                message=f"fix: revision {new_revision} — address PR feedback [{filepath}]",
                branch=head_branch,
            )
        except RuntimeError as exc:
            commit_errors.append(f"{filepath}: {exc}")
    if commit_errors:
        self.target_github.add_pr_comment(pr_number, f"⚠️ Revision {new_revision} partially failed.\n" + "\n".join(f"- `{e}`" for e in commit_errors))
        return {"status": "error", "reason": "commit_failed", "errors": commit_errors}, {}, {}, {}
    for mb, mb_files in merge_branch_files.items():
        for filepath, content in mb_files.items():
            if filepath in revised_files or filepath in current_files:
                continue
            try:
                self.target_github.commit_file(path=filepath, content=content, message=f"feat: incorporate {filepath} from branch {mb}", branch=head_branch)
            except RuntimeError as exc:
                console.print(f"  [yellow]⚠️  Could not commit merge file {filepath}: {exc}[/yellow]")
    console.print(f"  ✅ Committed [bold]{len(revised_files)}[/bold] revised file(s) to [cyan]{head_branch}[/cyan]")
    rev_result = self.reviewer.run(revised_files, design or "N/A", project_name)
    console.print(f"  🔍 Code review verdict: [bold]{rev_result.get('verdict', '?')}[/bold]")
    qa_result = self.qa.run(revised_files, design or "N/A", project_name)
    test_files: dict[str, str] = qa_result.get("test_files", {})
    for filepath, content in test_files.items():
        self.target_github.commit_file(path=filepath, content=content, message=f"test: revision {new_revision} — update tests [{filepath}]", branch=head_branch)
    return None, revised_files, rev_result, test_files

- [ ] **Step 8: Extract `_revision_post_summary`**

Add to `Orchestrator` class:

```python
def _revision_post_summary(
    self,
    pr_number: int,
    new_revision: int,
    current_rev: int,
    feedback: list,
    revised_files: "dict[str, str]",
    rev_result: dict,
    test_files: "dict[str, str]",
    merge_branch_files: "dict[str, dict[str, str]]",
) -> None:
    """Update PR label and post revision-complete summary comment."""
    old_label = f"ai-revision-{current_rev}" if current_rev > 0 else None
    new_label = f"ai-revision-{new_revision}"
    self.target_github.ensure_labels([{"name": new_label, "color": "0075ca", "description": f"AI revision round {new_revision}"}])
    if old_label:
        self.target_github.remove_pr_label(pr_number, old_label)
    self.target_github.add_pr_label(pr_number, new_label)
    merge_note = ""
    if merge_branch_files:
        names = ", ".join(f"`{b}`" for b in merge_branch_files)
        total = sum(len(v) for v in merge_branch_files.values())
        merge_note = f"\n**Incorporated branches:** {names} ({total} file(s))\n"
    summary = (
        f"## ✅ Revision {new_revision} Complete\n\n"
        f"The AI agents have addressed **{len(feedback)} feedback item(s)**:\n\n"
        + "\n".join(f"- {item['body'][:120]}{'…' if len(item['body']) > 120 else ''}" for item in feedback)
        + f"\n\n**Files updated:** {', '.join(f'`{p}`' for p in revised_files)}\n"
        f"**Code review verdict:** {rev_result.get('verdict', 'N/A')}\n"
        f"**Test files updated:** {len(test_files)}" + merge_note
    )
    self.target_github.add_pr_comment(pr_number, summary)
```

- [ ] **Step 9: Replace `run_revision` body with calls**

Replace the entire body of `run_revision` (lines 2612–2874) with:

```python
        if self.target_github is None:
            raise RuntimeError("target_github is required for run_revision()")

        pr, head_branch, issue_number, labels = self._revision_fetch_pr_context(pr_number)
        self._revision_inject_skills(pr.get("body") or "")

        current_rev = self._get_revision_number(labels)
        if self._revision_check_cap(pr_number, current_rev):
            return {"status": "max_revisions_reached"}

        conflict = self._revision_maybe_update_branch(pr_number, pr, head_branch)
        if conflict is not None:
            return conflict

        feedback, design, current_files, merge_branch_files = self._revision_collect_context(
            pr_number, issue_number, head_branch
        )
        if not feedback:
            return {"status": "no_feedback"}

        feedback_md = self._format_feedback(feedback)
        console.print(f"  💬 Collected [bold]{len(feedback)}[/bold] feedback item(s) from PR #{pr_number}")
        if merge_branch_files:
            console.print(f"  🔀 Merge directives found: {', '.join(f'[cyan]{b}[/cyan]' for b in merge_branch_files)}")

        augmented_design = self._revision_build_augmented_design(
            design, head_branch, current_files, feedback_md, merge_branch_files
        )

        new_revision = current_rev + 1
        console.print(f"\n[bold cyan]🔄 Revision {new_revision}/{self.max_revisions}[/bold cyan]")

        merge_hint = ""
        if merge_branch_files:
            branch_names = ", ".join(f"`{b}`" for b in merge_branch_files)
            merge_hint = f"\n\nFiles from merge branch(es) {branch_names} are included above. Make your revised implementation pass those tests."

        revision_modules = [{
            "name": "Revision",
            "description": (
                f"Revise the existing code to address all PR feedback listed above. "
                f"Return updated versions of these files: {', '.join(current_files.keys())}. "
                f"Only change what is necessary to address the feedback.{merge_hint}"
            ),
        }]
        project_name = pr.get("title", f"PR #{pr_number}").replace("[Implementation] ", "")

        error, revised_files, rev_result, test_files = self._revision_run_and_commit(
            pr_number=pr_number, head_branch=head_branch,
            design=design, augmented_design=augmented_design,
            revision_modules=revision_modules,
            project_name=project_name, new_revision=new_revision,
            current_files=current_files, merge_branch_files=merge_branch_files,
        )
        if error is not None:
            return error

        self._revision_post_summary(
            pr_number=pr_number, new_revision=new_revision, current_rev=current_rev,
            feedback=feedback, revised_files=revised_files, rev_result=rev_result,
            test_files=test_files, merge_branch_files=merge_branch_files,
        )
        return {"status": "ok", "revision": new_revision, "files_updated": len(revised_files)}
```

**Note:** `_revision_run_and_commit` used `design` from the outer scope for reviewer/QA. Update its signature to accept `design: str` as a parameter and pass it from `run_revision`. Also remove the walrus operator hack in `_revision_run_and_commit` — replace the `rev_result` line with:
```python
    rev_result = self.reviewer.run(revised_files, design or "N/A", project_name)
    qa_result = self.qa.run(revised_files, design or "N/A", project_name)
```
And add `design: str` to `_revision_run_and_commit`'s signature.

- [ ] **Step 10: Run tests**

```bash
python3 -m pytest tests/ -q --tb=short -x --ignore=workspace 2>&1 | tail -10
```

Expected: Same 11 pre-existing failures, 1757+ passing.

- [ ] **Step 11: Commit**

```bash
git add orchestrator.py
git commit -m "refactor: split run_revision() into 7 helpers"
```

---

### Task 11: Verify, add final tests, and create PR

**Files:**
- Modify: `tests/test_orchestrator_mcp_init.py` (add final regression tests)

- [ ] **Step 1: Verify fn_map — all 4 targets must show 0 violations**

```bash
python3 tools/fn_map.py --no-html 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -E "(__init__|^[[:space:]].*run |run_revision|_make_stage_registry)" | head -10
```

Expected: None of the 4 functions appear in the violations list.

- [ ] **Step 2: Check overall violation count decreased**

```bash
python3 tools/fn_map.py --no-html 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | tail -3
```

Expected: Violation count ≤ 133 (was 152; these 4 functions contributed 19 violations removed).

- [ ] **Step 3: Run full test suite one final time**

```bash
python3 -m pytest tests/ -q --tb=short --ignore=workspace 2>&1 | tail -5
```

Expected: `11 failed, 1757+ passed` — same pre-existing failures, no regressions.

- [ ] **Step 4: Push branch and create PR**

```bash
git push -u origin refactor/orchestrator-fn-split
gh pr create \
  --title "refactor: split orchestrator.py top-4 oversized functions (≤30 lines)" \
  --body "## Summary

Splits the 4 functions in \`orchestrator.py\` that exceeded 200 lines into private helper methods of ≤30 lines each. No behavior changes, no public API changes.

## Functions refactored

| Function | Before | Result |
|---|---|---|
| \`__init__\` | 325 lines | ~20-line body calling 10 helpers |
| \`run\` | 315 lines | ~15-line body calling 8 helpers |
| \`run_revision\` | 275 lines | ~45-line body calling 7 helpers |
| \`_make_stage_registry\` | 264 lines | ~10-line body calling 5 builders |

## New helpers added

- \`_init_core_attrs\`, \`_init_tool_registries\`, \`_init_llm_cfg\`
- \`_make_agent_kwargs\` (replaces \`_mk\` closure — now testable)
- \`_init_standard_agents\`, \`_init_tier_agents\`, \`_init_support_agents\`
- \`_init_github\`, \`_init_pipeline_config\`, \`_init_health_and_signals\`
- \`_build_product_stages\`, \`_build_engineering_stages\`, \`_build_content_stages\`, \`_build_utility_stages\`, \`_build_discussion_stages\`
- \`_resolve_target_repo\`, \`_inject_repo_context\`, \`_inject_memory\`, \`_inject_skills\`
- \`_load_or_init_result\`, \`_setup_progress_tracker\`, \`_run_preamble_stages\`
- \`_collect_stage_batch\`, \`_filter_runnable_stages\`, \`_execute_sequential_stage\`, \`_finalize_stage_batch\`, \`_run_stage_loop\`
- \`_revision_fetch_pr_context\`, \`_revision_inject_skills\`, \`_revision_check_cap\`
- \`_revision_maybe_update_branch\`, \`_revision_collect_context\`, \`_revision_build_augmented_design\`
- \`_revision_run_and_commit\`, \`_revision_post_summary\`

## Testing

- All 1757 existing tests pass
- 4 new smoke tests added for extracted helpers
- \`fn_map\` reports 0 violations for all 4 refactored functions

Closes #(no issue)" \
  --base master
```

- [ ] **Step 5: Confirm PR was created successfully**

```bash
gh pr view --json number,url,state
```
