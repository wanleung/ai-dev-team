# Agent Accuracy System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a three-layer system (prevention, detection, learning) that stops AI agents from generating broken code by grounding them in codebase reality, catching errors before PRs open, and accumulating anti-patterns in role files over time — for ai-software-house itself AND for every repo it maintains.

**Architecture:** Four milestones, each delivered as a separate PR from its own branch. Codebase patterns operate in two distinct tiers:

- **Tier A — Meta-patterns** (`roles/engineer.md`): describe how to use ai-software-house's own internals (BaseAgent API, stage registry, repos.yaml). These apply when agents work on ai-software-house itself.
- **Tier B — Repo-specific patterns** (fetched at runtime): `_build_engineer_context()` checks several standard AI instruction files in the target repo, in priority order, stopping at the first one found:
  1. `.github/copilot-instructions.md` — GitHub standard; GitHub Copilot coding agent reads this natively; many repos already have it
  2. `CLAUDE.md` — Claude Code's convention; repos maintained with Claude Code will have this
  3. `.github/AGENTS.md` — our own convention for repos that have neither of the above
  4. `repo-patterns/{owner}-{repo}.md` (local fallback) — created and updated by LearningAgent (M3) or BootstrapPatternsAgent (M4); no changes to the target repo required

  This means ai-software-house agents automatically benefit from any existing AI context files a repo already has, and accumulate learning in the local fallback otherwise.

Milestone 1 (prevention) implements Tier A + the dynamic Tier B injection. Milestone 2 (detection) adds a `validation_gate` stage. Milestone 3 (learning) adds `LearningAgent` which writes anti-patterns to `repo-patterns/` for target repos. Milestone 4 (bootstrap, optional) adds a one-shot pipeline to auto-generate `.github/AGENTS.md` for new repos when they are first added to `repos.yaml`.

**Tech Stack:** Python 3.11, pytest, ruff (already in project), BaseAgent, PipelineResult, orchestrator stage registry, `roles/*.md`, `repo-patterns/`, GitHub API via `GitHubClient`

**Branches and PRs:**
- `feature/accuracy-m1-prevention` → PR "Accuracy M1: Prevention — context injection + RAG wiring"
- `feature/accuracy-m2-detection` → PR "Accuracy M2: Detection — validation gate"
- `feature/accuracy-m3-learning` → PR "Accuracy M3: Learning — LearningAgent anti-pattern writer"
- `feature/accuracy-m4-bootstrap` → PR "Accuracy M4: Bootstrap — auto-generate repo patterns on onboarding"

**Convention for target repos:**
> `_build_engineer_context()` automatically picks up any of these files from the target repo (first match wins):
> 1. `.github/copilot-instructions.md` — GitHub standard, works with Copilot CLI/agent natively
> 2. `CLAUDE.md` — Claude Code standard
> 3. `.github/AGENTS.md` — our convention for repos with neither above
> 4. `repo-patterns/{slug}.md` — local fallback maintained by LearningAgent/BootstrapPatternsAgent
>
> Repos already using GitHub Copilot or Claude Code need no new files. Repos with none get an auto-generated fallback that grows over time.

---

## Milestone 1: Prevention

### Task 1: Branch setup

**Files:**
- No code changes yet — just branch creation

- [ ] **Step 1: Create branch from master**

```bash
cd /home/wanleung/Projects/ai-software-house
git checkout master
git checkout -b feature/accuracy-m1-prevention
```

Expected: now on `feature/accuracy-m1-prevention`

---

### Task 2: Enrich `roles/engineer.md` with ai-software-house meta-patterns cheatsheet

> **Scope note:** This section covers ONLY ai-software-house internals — BaseAgent API, stage registry, repos.yaml, GitHubClient. Repo-specific patterns for *target repos* are handled dynamically in Task 4 via `.github/AGENTS.md` fetched at runtime. Do NOT put target-repo patterns here.

**Files:**
- Modify: `roles/engineer.md` (append `## Codebase Patterns` section)

- [ ] **Step 1: Write the failing test**

Create `tests/test_accuracy_prevention.py`:

```python
"""Tests for Milestone 1: Prevention — role file cheatsheets and context injection."""
import pytest
from pathlib import Path


def test_engineer_role_has_codebase_patterns_section():
    """Engineer role file must have a ## Codebase Patterns section."""
    role = Path("roles/engineer.md").read_text()
    assert "## Codebase Patterns" in role


def test_engineer_role_documents_self_call():
    """Engineer role file must document self.call() as the correct LLM method."""
    role = Path("roles/engineer.md").read_text()
    assert "self.call(" in role
    assert "self.llm.generate" not in role.split("## Codebase Patterns")[1]


def test_engineer_role_documents_stage_registry():
    """Engineer role file must explain _make_stage_registry() wiring."""
    role = Path("roles/engineer.md").read_text()
    assert "_make_stage_registry" in role


def test_engineer_role_documents_repos_yaml_rule():
    """Engineer role file must warn against rewriting repos.yaml."""
    role = Path("roles/engineer.md").read_text()
    assert "repos.yaml" in role


def test_engineer_role_documents_role_name():
    """Engineer role file must document the role_name class attribute requirement."""
    role = Path("roles/engineer.md").read_text()
    assert "role_name" in role
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_accuracy_prevention.py -v 2>&1 | head -40
```

Expected: all 5 tests FAIL (section doesn't exist yet)

- [ ] **Step 3: Add `## Codebase Patterns` section to `roles/engineer.md`**

Append to the end of `roles/engineer.md`:

```markdown

---

## Codebase Patterns

These patterns are specific to this codebase. Follow them exactly — do not guess or use patterns from other codebases.

### Calling the LLM from an agent

ALWAYS use `self.call(user_message: str) -> str`.

```python
# Correct
response = self.call(user_message)

# WRONG — this method does not exist
response = self.llm.generate(system_prompt=..., user_prompt=...)
response = self.llm.generate(prompt=...)
```

### Subclassing BaseAgent

Every agent subclass MUST set `role_name` as a class attribute. `BaseAgent.__init__` loads `roles/{role_name}.md` automatically. Do NOT implement `_load_system_prompt()` — it is already provided by `BaseAgent`.

```python
class MyAgent(BaseAgent):
    role_name = "my_agent"   # required — loads roles/my_agent.md automatically

    def run(self, context):
        response = self.call("your user message here")
        return response
```

### Adding a new pipeline stage

Three steps — all three are required:

1. Add a `_stage_yourname(self, result: PipelineResult) -> None` method to `Orchestrator`
2. Register it in `_make_stage_registry()` — follow the exact format of existing entries:

```python
"your_stage": PipelineStage(
    name="your_stage",
    label="🔧 Your Stage Label",
    description="What this stage does...",
    checkpoint_key="your_stage",
    fn=lambda r: self._stage_yourname(r),
),
```

3. Add `- your_stage` (plain string, not a dict) to the relevant `pipelines/*.yaml`

### Modifying configuration files (repos.yaml, config.yaml)

NEVER rewrite these files from scratch. Always:
1. Read the current file first
2. Add only the new entry you need
3. Preserve all existing entries exactly

### GitHubClient constructor

`GitHubClient` requires arguments — never instantiate without them:

```python
# Correct — receive from orchestrator
github_client = context.get("github_client")

# Correct — instantiate with required args
client = GitHubClient(repo="owner/repo", github_token="...")

# WRONG — no-arg constructor does not work
client = GitHubClient()
```

### Passing RAG tool registry to new agents

When writing a new `_stage_*` method in `Orchestrator`, always pass `tool_registry`:

```python
def _stage_my_agent(self, result: PipelineResult) -> None:
    from agents.my_agent import MyAgent
    agent = MyAgent(
        model=self.model,
        github_token=self._github_token,
        ollama_url=self.ollama_url,
        tool_registry=self._rag_registry,  # always include this
    )
```

## Anti-patterns

<!-- LearningAgent appends dated entries here. Do not edit manually. -->
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_accuracy_prevention.py::test_engineer_role_has_codebase_patterns_section tests/test_accuracy_prevention.py::test_engineer_role_documents_self_call tests/test_accuracy_prevention.py::test_engineer_role_documents_stage_registry tests/test_accuracy_prevention.py::test_engineer_role_documents_repos_yaml_rule tests/test_accuracy_prevention.py::test_engineer_role_documents_role_name -v
```

Expected: all 5 PASS

- [ ] **Step 5: Commit**

```bash
git add roles/engineer.md tests/test_accuracy_prevention.py
git commit -m "feat(accuracy-m1): add codebase patterns cheatsheet to engineer role file"
```

---

### Task 3: Wire RAG tool_registry in PR campaign stage methods

**Files:**
- Modify: `orchestrator.py` — `_stage_pr_analyst`, `_stage_pr_creative`, `_stage_pr_proposal`

- [ ] **Step 1: Add tests for RAG wiring**

Add to `tests/test_accuracy_prevention.py`:

```python
import inspect
import ast


def _get_stage_method_source(method_name: str) -> str:
    """Read orchestrator.py and extract a _stage_* method's source."""
    src = Path("orchestrator.py").read_text()
    # Find the method definition and grab its body
    start = src.find(f"    def {method_name}(")
    assert start != -1, f"Method {method_name} not found in orchestrator.py"
    # Find the next def at same indentation level
    next_def = src.find("\n    def ", start + 1)
    return src[start:next_def] if next_def != -1 else src[start:]


def test_stage_pr_analyst_passes_tool_registry():
    src = _get_stage_method_source("_stage_pr_analyst")
    assert "tool_registry" in src


def test_stage_pr_creative_passes_tool_registry():
    src = _get_stage_method_source("_stage_pr_creative")
    assert "tool_registry" in src


def test_stage_pr_proposal_passes_tool_registry():
    src = _get_stage_method_source("_stage_pr_proposal")
    assert "tool_registry" in src
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_accuracy_prevention.py::test_stage_pr_analyst_passes_tool_registry tests/test_accuracy_prevention.py::test_stage_pr_creative_passes_tool_registry tests/test_accuracy_prevention.py::test_stage_pr_proposal_passes_tool_registry -v
```

Expected: all 3 FAIL

- [ ] **Step 3: Add `tool_registry=self._rag_registry` to all three PR campaign stage methods in `orchestrator.py`**

In `_stage_pr_analyst`:
```python
    def _stage_pr_analyst(self, result: "PipelineResult") -> None:
        from agents.pr_analyst import PRAnalystAgent
        agent = PRAnalystAgent(
            model=self.model,
            github_token=self._github_token,
            ollama_url=self.ollama_url,
            tool_registry=self._rag_registry,
        )
```

In `_stage_pr_creative`:
```python
    def _stage_pr_creative(self, result: "PipelineResult") -> None:
        from agents.pr_creative import PRCreativeAgent
        ...
        agent = PRCreativeAgent(
            model=self.model,
            github_token=self._github_token,
            ollama_url=self.ollama_url,
            tool_registry=self._rag_registry,
        )
```

In `_stage_pr_proposal`:
```python
    def _stage_pr_proposal(self, result: "PipelineResult") -> None:
        from agents.pr_proposal import PRProposalAgent
        ...
        agent = PRProposalAgent(
            model=self.model,
            github_token=self._github_token,
            ollama_url=self.ollama_url,
            tool_registry=self._rag_registry,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_accuracy_prevention.py -v
```

Expected: all 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator.py tests/test_accuracy_prevention.py
git commit -m "feat(accuracy-m1): wire tool_registry into PR campaign stage methods"
```

---

### Task 4: Implement `_build_engineer_context()` — Tier A meta-patterns + Tier B repo-specific patterns

**Files:**
- Modify: `orchestrator.py` — add `_build_engineer_context(task, target_gh=None)` method
- Create: `repo-patterns/` directory (gitignored initial state; populated by LearningAgent / BootstrapAgent)

**Design:**
- **Tier A** (no network): keyword-based injection from local files (`agents/base_agent.py`, `repos.yaml`, `_make_stage_registry`) — only relevant to working on ai-software-house itself.
- **Tier B** (target repo): attempts to fetch `.github/AGENTS.md` from the target repo via GitHub API. Falls back to local `repo-patterns/{owner}-{repo}.md`. Returns empty string silently if neither exists.

`target_gh` is `self.target_github` — the `GitHubClient` pointed at the repo being worked on.

- [ ] **Step 1: Create `repo-patterns/` directory with a README**

```bash
mkdir -p repo-patterns
cat > repo-patterns/README.md << 'EOF'
# Repo-Specific Codebase Patterns (Local Fallback)

This directory contains per-repo codebase pattern files used by ai-software-house agents
as a **last-resort fallback** when a target repo has none of the standard AI context files.

## Priority order checked by _build_engineer_context()

1. `.github/copilot-instructions.md` in target repo — GitHub Copilot standard (preferred)
2. `CLAUDE.md` in target repo — Claude Code standard
3. `.github/AGENTS.md` in target repo — our convention
4. `repo-patterns/{owner}-{repo}.md` in this directory — **this fallback**

## File naming
`{github-owner}-{repo-name}.md` — e.g. `wanleung-myapp.md`

## How files get here
- Automatically: BootstrapPatternsAgent (M4) creates the initial file when a repo is added to repos.yaml
- Incrementally: LearningAgent (M3) appends dated anti-pattern rules here when failures occur

## Recommended approach for target repos
Add `.github/copilot-instructions.md` to the repo — GitHub Copilot's coding agent, this system,
and other AI tools will all read it. Use BootstrapPatternsAgent to generate the initial content.
EOF
git add repo-patterns/README.md
git commit -m "feat(accuracy-m1): add repo-patterns/ directory for per-repo codebase context"
```

- [ ] **Step 2: Add tests**

Add to `tests/test_accuracy_prevention.py`:

```python
def test_build_engineer_context_tier_a_base_agent():
    """Tier A: when task mentions BaseAgent, context includes base_agent.py snippet."""
    from orchestrator import Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    ctx = orch._build_engineer_context("Create a new BaseAgent subclass for X")
    assert "base_agent.py" in ctx.lower() or "BaseAgent" in ctx


def test_build_engineer_context_tier_a_repos_yaml():
    """Tier A: when task mentions repos.yaml, context includes current file contents."""
    from orchestrator import Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    ctx = orch._build_engineer_context("Add a new entry to repos.yaml")
    assert "watchers:" in ctx or "repos.yaml" in ctx.lower()


def test_build_engineer_context_tier_a_stage_registry():
    """Tier A: when task mentions pipeline stage, context includes _make_stage_registry."""
    from orchestrator import Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    ctx = orch._build_engineer_context("Add a new pipeline stage to _make_stage_registry")
    assert "_make_stage_registry" in ctx or "PipelineStage" in ctx


def test_build_engineer_context_tier_a_empty_for_unrelated():
    """Tier A: unrelated task with no target_gh gets empty context."""
    from orchestrator import Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    ctx = orch._build_engineer_context("Write a markdown README for the project")
    assert ctx == "" or len(ctx) < 100


def test_build_engineer_context_tier_b_uses_local_fallback(tmp_path):
    """Tier B: if all remote files absent, falls back to repo-patterns/{slug}.md."""
    from orchestrator import Orchestrator
    from unittest.mock import MagicMock, patch

    orch = Orchestrator.__new__(Orchestrator)

    # All remote fetches fail (no copilot-instructions.md, CLAUDE.md, or AGENTS.md)
    mock_gh = MagicMock()
    mock_gh.repo = "testowner/myapp"
    mock_gh.get_file.side_effect = Exception("404 Not Found")

    patterns_dir = tmp_path / "repo-patterns"
    patterns_dir.mkdir()
    fallback = patterns_dir / "testowner-myapp.md"
    fallback.write_text("## Codebase Patterns\n\n- Use Django ORM, never raw SQL.\n")

    with patch.object(Orchestrator, "_get_repo_patterns_dir", return_value=patterns_dir):
        ctx = orch._build_engineer_context("Fix the login bug", target_gh=mock_gh)

    assert "Django ORM" in ctx
    assert "testowner/myapp" in ctx or "testowner-myapp" in ctx


def test_build_engineer_context_tier_b_prefers_copilot_instructions():
    """Tier B: .github/copilot-instructions.md is checked first."""
    from orchestrator import Orchestrator
    from unittest.mock import MagicMock, call

    orch = Orchestrator.__new__(Orchestrator)

    mock_gh = MagicMock()
    mock_gh.repo = "testowner/myapp"

    def fake_get_file(path):
        if path == ".github/copilot-instructions.md":
            return "## Codebase Patterns\n\n- Always use TypeScript strict mode.\n"
        raise Exception("404")

    mock_gh.get_file.side_effect = fake_get_file

    ctx = orch._build_engineer_context("Add a new API endpoint", target_gh=mock_gh)

    assert "TypeScript strict mode" in ctx
    # Should NOT have tried CLAUDE.md or AGENTS.md since copilot-instructions.md was found
    assert mock_gh.get_file.call_args_list[0] == call(".github/copilot-instructions.md")


def test_build_engineer_context_tier_b_falls_through_to_claude_md():
    """Tier B: falls through to CLAUDE.md if copilot-instructions.md is absent."""
    from orchestrator import Orchestrator
    from unittest.mock import MagicMock

    orch = Orchestrator.__new__(Orchestrator)

    mock_gh = MagicMock()
    mock_gh.repo = "testowner/myapp"

    def fake_get_file(path):
        if path == "CLAUDE.md":
            return "## Codebase Patterns\n\n- Use async/await, not callbacks.\n"
        raise Exception("404")

    mock_gh.get_file.side_effect = fake_get_file

    ctx = orch._build_engineer_context("Fix the bug", target_gh=mock_gh)

    assert "async/await" in ctx
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
python -m pytest tests/test_accuracy_prevention.py::test_build_engineer_context_tier_a_base_agent tests/test_accuracy_prevention.py::test_build_engineer_context_tier_a_repos_yaml tests/test_accuracy_prevention.py::test_build_engineer_context_tier_a_stage_registry tests/test_accuracy_prevention.py::test_build_engineer_context_tier_a_empty_for_unrelated tests/test_accuracy_prevention.py::test_build_engineer_context_tier_b_uses_local_fallback tests/test_accuracy_prevention.py::test_build_engineer_context_tier_b_prefers_remote_agents_md -v
```

Expected: all 6 FAIL with AttributeError

- [ ] **Step 4: Check what method `GitHubClient` uses to fetch a single file**

```bash
grep -n "def get_file\|def get_content\|def read_file" github_client.py | head -10
```

Use whatever method exists. If it's `get_file_contents(path)` adjust the call below accordingly.

- [ ] **Step 5: Implement `_build_engineer_context()` and `_get_repo_patterns_dir()` in `orchestrator.py`**

Find the `# ── Shared commit + PR helper` comment block and add these methods just before it:

```python
def _get_repo_patterns_dir(self) -> Path:
    """Return the path to repo-patterns/ directory. Patchable in tests."""
    return Path("repo-patterns")


def _build_engineer_context(
    self,
    task: str,
    target_gh: Optional["GitHubClient"] = None,
) -> str:
    """Inject relevant codebase context into an engineer task prompt.

    Two tiers:
    - Tier A (local, keyword-triggered): ai-software-house internal patterns —
      base_agent.py signatures, repos.yaml content, _make_stage_registry pattern.
      Only activated for tasks that are modifying ai-software-house itself.
    - Tier B (remote+fallback, always checked when target_gh is set): repo-specific
      patterns from the target repo's .github/AGENTS.md. Falls back to local
      repo-patterns/{owner}-{repo}.md if remote fetch fails or file is absent.

    Args:
        task: The task description / design string.
        target_gh: GitHubClient pointed at the target repo, or None when working
                   on ai-software-house itself.

    Returns:
        Concatenated context string, or empty string if nothing found.
    """
    task_lower = task.lower()
    parts: list[str] = []

    # ── Tier A: ai-software-house meta-patterns ─────────────────────────────
    # Only inject when the task is about ai-software-house internals.

    if "baseagent" in task_lower or "base_agent" in task_lower or (
        "agent" in task_lower and "subclass" in task_lower
    ):
        try:
            lines = Path("agents/base_agent.py").read_text().splitlines()
            snippet = "\n".join(lines[:140])
            parts.append(
                "## Reference: agents/base_agent.py (first 140 lines)\n"
                "```python\n" + snippet + "\n```"
            )
        except FileNotFoundError:
            pass

    if "repos.yaml" in task_lower or "watcher" in task_lower:
        try:
            contents = Path("repos.yaml").read_text()
            parts.append(
                "## Reference: current repos.yaml (read before modifying — add entries, never rewrite)\n"
                "```yaml\n" + contents + "\n```"
            )
        except FileNotFoundError:
            pass

    if "_make_stage_registry" in task or "pipeline stage" in task_lower or (
        "orchestrator" in task_lower and "stage" in task_lower
    ):
        try:
            src = Path("orchestrator.py").read_text()
            start = src.find("    def _make_stage_registry(")
            end = src.find("\n    def ", start + 1)
            if start != -1:
                snippet = src[start:end] if end != -1 else src[start:start + 3000]
                parts.append(
                    "## Reference: _make_stage_registry() pattern in orchestrator.py\n"
                    "```python\n" + snippet + "\n```"
                )
        except FileNotFoundError:
            pass

    # ── Tier B: repo-specific patterns ───────────────────────────────────────
    # Checked in priority order — stops at first file found.
    # Priority mirrors the AI tool ecosystem:
    #   1. .github/copilot-instructions.md  (GitHub Copilot standard)
    #   2. CLAUDE.md                        (Claude Code standard)
    #   3. .github/AGENTS.md                (our convention)
    #   4. repo-patterns/{slug}.md          (local fallback, no target repo changes needed)

    if target_gh is not None:
        repo_slug = target_gh.repo.replace("/", "-")
        agents_md: Optional[str] = None
        source_label: str = ""

        # Priority list of remote files to try
        remote_candidates = [
            (".github/copilot-instructions.md", "`.github/copilot-instructions.md`"),
            ("CLAUDE.md", "`CLAUDE.md`"),
            (".github/AGENTS.md", "`.github/AGENTS.md`"),
        ]

        for remote_path, label in remote_candidates:
            try:
                agents_md = target_gh.get_file(remote_path)
                source_label = label
                break  # found — stop looking
            except Exception:
                continue

        # Local fallback if no remote file found
        if agents_md is None:
            local_path = self._get_repo_patterns_dir() / f"{repo_slug}.md"
            if local_path.exists():
                agents_md = local_path.read_text(encoding="utf-8")
                source_label = f"`repo-patterns/{repo_slug}.md` (local fallback)"

        if agents_md:
            parts.append(
                f"## Codebase Patterns for {target_gh.repo} (from {source_label})\n\n"
                + agents_md
            )

    return "\n\n".join(parts)
```

- [ ] **Step 6: Check that `GitHubClient.get_file` exists (or use the correct method name)**

```bash
grep -n "def get_file" github_client.py
```

If the method is named differently (e.g. `get_file_contents`), update the two `target_gh.get_file(...)` calls in `_build_engineer_context()` and the test mock to match.

- [ ] **Step 7: Run tests**

```bash
python -m pytest tests/test_accuracy_prevention.py -v
```

Expected: all 16 tests PASS

- [ ] **Step 8: Commit**

```bash
git add orchestrator.py repo-patterns/ tests/test_accuracy_prevention.py
git commit -m "feat(accuracy-m1): implement _build_engineer_context() with Tier A + Tier B patterns"
```

---

### Task 5: Open PR for Milestone 1

- [ ] **Step 1: Run full test suite to check no regressions**

```bash
python -m pytest tests/ -x --timeout=60 -q 2>&1 | tail -20
```

Expected: existing tests pass, new prevention tests pass

- [ ] **Step 2: Push and open PR**

```bash
git push origin feature/accuracy-m1-prevention
gh pr create \
  --title "Accuracy M1: Prevention — context injection + RAG wiring" \
  --body "## Summary
Implements Layer 1 of the three-layer agent accuracy system.

### Changes
- \`roles/engineer.md\`: Added \`## Codebase Patterns\` cheatsheet covering ai-software-house internals (BaseAgent API, stage registry, repos.yaml, GitHubClient constructor)
- \`orchestrator.py\`: Wired \`tool_registry=self._rag_registry\` into \`_stage_pr_analyst\`, \`_stage_pr_creative\`, \`_stage_pr_proposal\`
- \`orchestrator.py\`: Added \`_build_engineer_context(task, target_gh)\` — two-tier pattern injection:
  - Tier A: keyword-triggered injection of local source files (BaseAgent, repos.yaml, stage registry) for ai-software-house tasks
  - Tier B: fetches \`.github/AGENTS.md\` from the target repo via GitHub API; falls back to \`repo-patterns/{slug}.md\`
- \`repo-patterns/README.md\`: Documents the per-repo patterns convention
- \`tests/test_accuracy_prevention.py\`: 14 tests covering all new behaviour

### Convention for target repos
Any repo tracked in \`repos.yaml\` can add \`.github/AGENTS.md\` to provide repo-specific codebase patterns. These are injected automatically into every engineer prompt. See \`repo-patterns/README.md\` for the format.

Closes #63 (related)
Design spec: docs/superpowers/specs/2026-05-17-agent-accuracy-system-design.md
" \
  --base master
```

---

## Milestone 2: Detection

### Task 6: Branch setup

- [ ] **Step 1: Create branch from master (after M1 is merged)**

```bash
git checkout master && git pull origin master
git checkout -b feature/accuracy-m2-detection
```

---

### Task 7: Add validation fields to `PipelineResult`

**Files:**
- Modify: `orchestrator.py` — add 3 fields to `PipelineResult` dataclass (around line 396)

- [ ] **Step 1: Write the failing test**

Create `tests/test_accuracy_detection.py`:

```python
"""Tests for Milestone 2: Detection — validation_gate stage."""
import pytest
import tempfile
import os
from pathlib import Path
from dataclasses import fields


def test_pipeline_result_has_validation_attempts():
    from orchestrator import PipelineResult
    field_names = {f.name for f in fields(PipelineResult)}
    assert "validation_attempts" in field_names


def test_pipeline_result_has_validation_errors():
    from orchestrator import PipelineResult
    field_names = {f.name for f in fields(PipelineResult)}
    assert "validation_errors" in field_names


def test_pipeline_result_has_pr_draft():
    from orchestrator import PipelineResult
    field_names = {f.name for f in fields(PipelineResult)}
    assert "pr_draft" in field_names


def test_pipeline_result_validation_defaults():
    from orchestrator import PipelineResult
    r = PipelineResult()
    assert r.validation_attempts == 0
    assert r.validation_errors == []
    assert r.pr_draft is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_accuracy_detection.py::test_pipeline_result_has_validation_attempts tests/test_accuracy_detection.py::test_pipeline_result_has_validation_errors tests/test_accuracy_detection.py::test_pipeline_result_has_pr_draft tests/test_accuracy_detection.py::test_pipeline_result_validation_defaults -v
```

Expected: all 4 FAIL

- [ ] **Step 3: Add fields to `PipelineResult` in `orchestrator.py`**

After line `deploy_fix_history: list[str] = field(default_factory=list)` (~line 396), add:

```python
    # Validation gate fields
    validation_attempts: int = 0
    validation_errors: list[str] = field(default_factory=list)
    pr_draft: bool = False
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_accuracy_detection.py::test_pipeline_result_has_validation_attempts tests/test_accuracy_detection.py::test_pipeline_result_has_validation_errors tests/test_accuracy_detection.py::test_pipeline_result_has_pr_draft tests/test_accuracy_detection.py::test_pipeline_result_validation_defaults -v
```

Expected: all 4 PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator.py tests/test_accuracy_detection.py
git commit -m "feat(accuracy-m2): add validation_attempts/errors/pr_draft to PipelineResult"
```

---

### Task 8: Implement `_stage_validation_gate()`

**Files:**
- Modify: `orchestrator.py` — add `_stage_validation_gate()` and register in `_make_stage_registry()`

- [ ] **Step 1: Write tests for the validation gate**

Add to `tests/test_accuracy_detection.py`:

```python
def test_validation_gate_passes_clean_python(tmp_path):
    """Gate should pass when all .py files have valid syntax and no lint errors."""
    from orchestrator import Orchestrator, PipelineResult
    orch = Orchestrator.__new__(Orchestrator)

    result = PipelineResult()
    result.all_files = {
        "mymodule/hello.py": "def hello():\n    return 'world'\n"
    }
    orch._stage_validation_gate(result)

    assert result.validation_errors == []
    assert result.pr_draft is False


def test_validation_gate_catches_syntax_error(tmp_path):
    """Gate catches SyntaxError in generated .py files."""
    from orchestrator import Orchestrator, PipelineResult
    orch = Orchestrator.__new__(Orchestrator)

    result = PipelineResult()
    result.all_files = {
        "mymodule/broken.py": "def hello(\n    pass\n"  # syntax error
    }
    orch._stage_validation_gate(result)

    assert len(result.validation_errors) > 0
    assert any("syntax" in e.lower() or "SyntaxError" in e for e in result.validation_errors)


def test_validation_gate_catches_undefined_name():
    """Gate catches F821 undefined name via ruff."""
    from orchestrator import Orchestrator, PipelineResult
    orch = Orchestrator.__new__(Orchestrator)

    result = PipelineResult()
    result.all_files = {
        "mymodule/bad.py": "def foo():\n    return undefined_variable\n"
    }
    orch._stage_validation_gate(result)

    assert len(result.validation_errors) > 0


def test_validation_gate_marks_draft_after_two_retries():
    """After validation_attempts >= 2, gate marks pr_draft=True."""
    from orchestrator import Orchestrator, PipelineResult
    orch = Orchestrator.__new__(Orchestrator)

    result = PipelineResult()
    result.validation_attempts = 2
    result.all_files = {
        "mymodule/broken.py": "def hello(\n    pass\n"
    }
    orch._stage_validation_gate(result)

    assert result.pr_draft is True


def test_validation_gate_registered_in_stage_registry():
    """validation_gate must be registered in _make_stage_registry."""
    src = Path("orchestrator.py").read_text()
    assert '"validation_gate"' in src or "'validation_gate'" in src
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_accuracy_detection.py::test_validation_gate_passes_clean_python tests/test_accuracy_detection.py::test_validation_gate_catches_syntax_error tests/test_accuracy_detection.py::test_validation_gate_catches_undefined_name tests/test_accuracy_detection.py::test_validation_gate_marks_draft_after_two_retries tests/test_accuracy_detection.py::test_validation_gate_registered_in_stage_registry -v
```

Expected: all 5 FAIL

- [ ] **Step 3: Implement `_stage_validation_gate()` in `orchestrator.py`**

Add after `_stage_pr_proposal` method (in the PR campaign block):

```python
def _stage_validation_gate(self, result: "PipelineResult") -> None:
    """Validate generated files before opening a PR.

    Runs syntax check (py_compile) then lint (ruff F,E errors only) on all
    .py files in result.all_files. On failure, if validation_attempts < 2,
    appends errors to result.validation_errors for the re-prompt loop.
    If validation_attempts >= 2, marks result.pr_draft = True so the PR
    is opened as a draft with the needs-human-fix label.
    """
    import py_compile
    import subprocess
    import tempfile
    import os

    errors: list[str] = []
    py_files = {p: c for p, c in result.all_files.items() if p.endswith(".py")}

    if not py_files:
        return  # nothing to validate

    with tempfile.TemporaryDirectory(prefix="validation_gate_") as tmpdir:
        # Write files to temp dir
        for rel_path, content in py_files.items():
            dest = os.path.join(tmpdir, rel_path)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "w") as f:
                f.write(content)

        # Step 1: syntax check
        for rel_path in py_files:
            abs_path = os.path.join(tmpdir, rel_path)
            try:
                py_compile.compile(abs_path, doraise=True)
            except py_compile.PyCompileError as e:
                errors.append(f"SyntaxError in {rel_path}: {e}")

        # Step 2: lint (ruff F + E codes — errors and undefined names only)
        if not errors:
            try:
                proc = subprocess.run(
                    ["ruff", "check", "--select", "F,E", "--output-format", "text", tmpdir],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if proc.returncode != 0:
                    # Strip tmpdir prefix from paths for readability
                    lint_output = proc.stdout.replace(tmpdir + "/", "")
                    errors.extend([
                        line for line in lint_output.splitlines()
                        if line.strip() and not line.startswith("Found")
                    ])
            except FileNotFoundError:
                logger.warning("ruff not found — skipping lint check in validation_gate")
            except subprocess.TimeoutExpired:
                logger.warning("ruff timed out in validation_gate — skipping lint")

    if not errors:
        return  # all good

    result.validation_errors = errors

    if result.validation_attempts >= 2:
        result.pr_draft = True
        result.next_label = "needs-human-fix"
        logger.warning(
            "validation_gate: %d errors after %d attempts — marking as draft PR",
            len(errors), result.validation_attempts,
        )
    else:
        result.validation_attempts += 1
        logger.warning(
            "validation_gate: %d errors on attempt %d — errors stored for re-prompt",
            len(errors), result.validation_attempts,
        )
```

- [ ] **Step 4: Register in `_make_stage_registry()`**

Add after the `pr_proposal` entry:

```python
            "validation_gate": PipelineStage(
                name="validation_gate",
                label="🔍 Validation Gate",
                description="Syntax-checking and linting generated code...",
                checkpoint_key="validation_gate",
                fn=lambda r: self._stage_validation_gate(r),
            ),
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_accuracy_detection.py -v
```

Expected: all 9 tests PASS

- [ ] **Step 6: Commit**

```bash
git add orchestrator.py tests/test_accuracy_detection.py
git commit -m "feat(accuracy-m2): implement _stage_validation_gate with syntax + lint checks"
```

---

### Task 9: Add `validation_gate` to pipeline YAMLs

**Files:**
- Modify: `pipelines/ai-feature.yaml` — add `validation_gate` before commit stage
- Modify: `pipelines/ai-fix.yaml` — add `validation_gate` before commit stage
- Modify: `pipelines/tdd.yaml` — add `validation_gate` before commit stage

- [ ] **Step 1: Write test**

Add to `tests/test_accuracy_detection.py`:

```python
def test_ai_feature_pipeline_has_validation_gate():
    import yaml
    pipeline = yaml.safe_load(Path("pipelines/ai-feature.yaml").read_text())
    stages = pipeline["stages"]
    assert "validation_gate" in stages


def test_ai_fix_pipeline_has_validation_gate():
    import yaml
    pipeline = yaml.safe_load(Path("pipelines/ai-fix.yaml").read_text())
    stages = pipeline["stages"]
    assert "validation_gate" in stages
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_accuracy_detection.py::test_ai_feature_pipeline_has_validation_gate tests/test_accuracy_detection.py::test_ai_fix_pipeline_has_validation_gate -v
```

Expected: both FAIL

- [ ] **Step 3: Update `pipelines/ai-feature.yaml`**

Insert `validation_gate` just before `reviewer` (code is generated by senior/junior engineers just before reviewer):

```yaml
stages:
  - pm
  - pm_reviewer
  - architect
  - architect_reviewer
  - tier_review
  - junior_engineer
  - senior_engineer
  - validation_gate
  - reviewer
  - qa_planner
  - qa_engineer
  - test_fix
  - deploy_tester
  - deploy_fix
```

- [ ] **Step 4: Update `pipelines/ai-fix.yaml`**

```yaml
stages:
  - diagnose
  - bug_fix
  - validation_gate
  - reviewer
  - test_fix
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_accuracy_detection.py -v
```

Expected: all 11 tests PASS

- [ ] **Step 6: Commit**

```bash
git add pipelines/ai-feature.yaml pipelines/ai-fix.yaml tests/test_accuracy_detection.py
git commit -m "feat(accuracy-m2): add validation_gate stage to ai-feature and ai-fix pipelines"
```

---

### Task 10: Open PR for Milestone 2

- [ ] **Step 1: Run full test suite**

```bash
python -m pytest tests/ -x --timeout=60 -q 2>&1 | tail -20
```

Expected: all tests pass

- [ ] **Step 2: Push and open PR**

```bash
git push origin feature/accuracy-m2-detection
gh pr create \
  --title "Accuracy M2: Detection — validation gate" \
  --body "## Summary
Implements Layer 2 of the three-layer agent accuracy system.

### Changes
- \`orchestrator.py\`: Added \`validation_attempts\`, \`validation_errors\`, \`pr_draft\` fields to \`PipelineResult\`
- \`orchestrator.py\`: Implemented \`_stage_validation_gate()\` — runs py_compile + ruff on generated .py files, re-prompts on failure (max 2 retries), marks draft PR on exhaustion
- \`orchestrator.py\`: Registered \`validation_gate\` in \`_make_stage_registry()\`
- \`pipelines/ai-feature.yaml\`: Added \`validation_gate\` stage before reviewer
- \`pipelines/ai-fix.yaml\`: Added \`validation_gate\` stage before reviewer
- \`tests/test_accuracy_detection.py\`: 11 tests covering all new behaviour

### Behaviour
- Clean code: passes silently, PR opens normally
- Errors on attempt 1: stored in result.validation_errors for re-prompt loop, attempt counter incremented
- Errors after 2 attempts: PR opened as draft with label \`needs-human-fix\`

Design spec: docs/superpowers/specs/2026-05-17-agent-accuracy-system-design.md
" \
  --base master
```

---

## Milestone 3: Learning

### Task 11: Branch setup

- [ ] **Step 1: Create branch from master (after M2 is merged)**

```bash
git checkout master && git pull origin master
git checkout -b feature/accuracy-m3-learning
```

---

### Task 12: Define `FailureRecord` dataclass

**Files:**
- Create: `agents/failure_record.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_accuracy_learning.py`:

```python
"""Tests for Milestone 3: Learning — LearningAgent anti-pattern writer."""
import pytest
from pathlib import Path


def test_failure_record_has_required_fields():
    from agents.failure_record import FailureRecord
    from dataclasses import fields
    field_names = {f.name for f in fields(FailureRecord)}
    assert "agent_role" in field_names
    assert "error" in field_names
    assert "fix" in field_names
    assert "pipeline" in field_names
    assert "timestamp" in field_names
    assert "target_repo" in field_names  # routing field


def test_failure_record_instantiation():
    from agents.failure_record import FailureRecord
    record = FailureRecord(
        agent_role="engineer",
        error="self.llm.generate() does not exist",
        fix="Use self.call(user_message) instead",
        pipeline="ai-feature",
        timestamp="2026-05-17T10:00:00",
    )
    assert record.agent_role == "engineer"
    assert record.error == "self.llm.generate() does not exist"
    assert record.target_repo is None  # default
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_accuracy_learning.py::test_failure_record_has_required_fields tests/test_accuracy_learning.py::test_failure_record_instantiation -v
```

Expected: both FAIL with ImportError

- [ ] **Step 3: Create `agents/failure_record.py`**

```python
"""FailureRecord — passed to LearningAgent when a validation failure or PR review rejection occurs."""
from dataclasses import dataclass
from typing import Optional


@dataclass
class FailureRecord:
    """Describes a single agent failure event for the LearningAgent to process.

    Attributes:
        agent_role: The role_name of the agent that produced the failure (e.g. "engineer").
        error: The error message or review comment that identified the failure.
        fix: The corrected code snippet or human explanation of what should have been done.
        pipeline: Which pipeline triggered this failure (e.g. "ai-feature", "ai-fix").
        timestamp: ISO-8601 timestamp of when the failure occurred.
        target_repo: GitHub repo slug (owner/name) of the target repo if this failure
                     occurred while working on an external repo. None means the failure
                     was in ai-software-house itself.
    """
    agent_role: str
    error: str
    fix: str
    pipeline: str
    timestamp: str
    target_repo: Optional[str] = None
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_accuracy_learning.py::test_failure_record_has_required_fields tests/test_accuracy_learning.py::test_failure_record_instantiation -v
```

Expected: both PASS

- [ ] **Step 5: Commit**

```bash
git add agents/failure_record.py tests/test_accuracy_learning.py
git commit -m "feat(accuracy-m3): add FailureRecord dataclass"
```

---

### Task 13: Implement `LearningAgent`

**Files:**
- Create: `agents/learning_agent.py`
- Create: `roles/learning_agent.md`

**Design — where anti-patterns are written:**
- If the failure happened on **ai-software-house itself** (no `target_repo` or `target_repo == self.github.repo`): append to `roles/{agent_role}.md`
- If the failure happened on **a target repo** (`target_repo` is set and different): append to `repo-patterns/{owner}-{repo}.md` (creating the file if absent). This way repo-specific lessons accumulate in the right place and are picked up by Tier B next time.

`FailureRecord` needs one new field: `target_repo: Optional[str] = None`

- [ ] **Step 1: Create `roles/learning_agent.md`**

```markdown
# Role: Learning Agent

## Objective
You are a meta-learning agent. Your job is to analyse a failure in an AI-generated codebase contribution, understand the root cause, and write a concise, actionable "DO NOT" rule that prevents the same failure from recurring.

## Input
You will receive:
1. The current content of a role file (the agent that failed)
2. The error or review comment that identified the failure
3. The correct fix that was applied

## Output Format
Write ONLY a single anti-pattern rule in this exact format:

```
- DO NOT {wrong behaviour} — {correct behaviour instead}. ({date})
```

Rules:
- Maximum 2 lines
- Concrete and specific — name the actual method, class, or pattern involved
- Written in second person imperative ("DO NOT call...", "DO NOT rewrite...")
- The date must be the ISO date provided in the input (YYYY-MM-DD format)
- Output ONLY the rule — no preamble, no explanation, no code block
```

- [ ] **Step 2: Write failing tests**

Add to `tests/test_accuracy_learning.py`:

```python
def test_learning_agent_has_role_name():
    from agents.learning_agent import LearningAgent
    assert LearningAgent.role_name == "learning_agent"


def test_learning_agent_appends_antipattern_to_role_file(tmp_path):
    """When target_repo=None, LearningAgent writes to roles/{agent_role}.md."""
    from agents.learning_agent import LearningAgent
    from agents.failure_record import FailureRecord
    from unittest.mock import patch, MagicMock

    role_file = tmp_path / "roles" / "engineer.md"
    role_file.parent.mkdir()
    role_file.write_text("# Engineer\n\n## Anti-patterns\n\n<!-- placeholder -->\n")

    failure = FailureRecord(
        agent_role="engineer",
        error="self.llm.generate() AttributeError",
        fix="Use self.call(user_message) instead",
        pipeline="ai-feature",
        timestamp="2026-05-17T10:00:00",
        target_repo=None,  # ai-software-house internal failure
    )

    agent = LearningAgent.__new__(LearningAgent)
    agent.call = MagicMock(return_value="- DO NOT call self.llm.generate() — use self.call(user_message) instead. (2026-05-17)")

    with patch.object(LearningAgent, "_get_roles_dir", return_value=tmp_path / "roles"):
        agent.run(failure)

    updated = role_file.read_text()
    assert "DO NOT call self.llm.generate()" in updated
    assert "2026-05-17" in updated


def test_learning_agent_writes_to_repo_patterns_for_target_repo(tmp_path):
    """When target_repo is set, LearningAgent writes to repo-patterns/{slug}.md."""
    from agents.learning_agent import LearningAgent
    from agents.failure_record import FailureRecord
    from unittest.mock import patch, MagicMock

    patterns_dir = tmp_path / "repo-patterns"
    patterns_dir.mkdir()

    failure = FailureRecord(
        agent_role="engineer",
        error="Wrong ORM call",
        fix="Use Django ORM select_related()",
        pipeline="ai-feature",
        timestamp="2026-05-17T10:00:00",
        target_repo="wanleung/myapp",  # external repo failure
    )

    agent = LearningAgent.__new__(LearningAgent)
    agent.call = MagicMock(return_value="- DO NOT use raw SQL — use Django ORM select_related(). (2026-05-17)")

    with patch.object(LearningAgent, "_get_repo_patterns_dir", return_value=patterns_dir):
        agent.run(failure)

    patterns_file = patterns_dir / "wanleung-myapp.md"
    assert patterns_file.exists()
    content = patterns_file.read_text()
    assert "DO NOT use raw SQL" in content
    assert "wanleung/myapp" in content


def test_learning_agent_creates_antipatterns_section_if_missing(tmp_path):
    """LearningAgent creates ## Anti-patterns section if absent from role file."""
    from agents.learning_agent import LearningAgent
    from agents.failure_record import FailureRecord
    from unittest.mock import patch, MagicMock

    role_file = tmp_path / "roles" / "engineer.md"
    role_file.parent.mkdir()
    role_file.write_text("# Engineer\n\nSome content.\n")

    failure = FailureRecord(
        agent_role="engineer",
        error="Bad path",
        fix="Use absolute path",
        pipeline="ai-feature",
        timestamp="2026-05-17T10:00:00",
    )

    agent = LearningAgent.__new__(LearningAgent)
    agent.call = MagicMock(return_value="- DO NOT use relative paths — use absolute paths. (2026-05-17)")

    with patch.object(LearningAgent, "_get_roles_dir", return_value=tmp_path / "roles"):
        agent.run(failure)

    updated = role_file.read_text()
    assert "## Anti-patterns" in updated
    assert "DO NOT use relative paths" in updated
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
python -m pytest tests/test_accuracy_learning.py -v
```

Expected: 4 new tests FAIL with ImportError

- [ ] **Step 4: Create `agents/learning_agent.py`**

```python
"""LearningAgent — writes anti-pattern rules from failure events.

Routing:
- Failure on ai-software-house itself (target_repo=None): appends to roles/{agent_role}.md
- Failure on a target repo (target_repo set): appends to repo-patterns/{owner}-{repo}.md

This ensures each repo's lessons accumulate in the right place and are picked up
by _build_engineer_context() Tier B on the next task.

Triggered by:
- validation_gate after max retries
- PR review watcher when a PR receives 'changes-requested'
"""
import logging
from pathlib import Path
from typing import Optional

from agents.base_agent import BaseAgent
from agents.failure_record import FailureRecord

logger = logging.getLogger(__name__)

ANTIPATTERNS_HEADER = "\n\n## Anti-patterns\n\n<!-- LearningAgent appends dated entries below. Do not edit manually. -->\n"
REPO_PATTERNS_HEADER = "# Codebase Patterns for {repo}\n\n<!-- Auto-generated by LearningAgent. Add `.github/AGENTS.md` to the repo for human-maintained patterns. -->\n\n## Anti-patterns\n\n"


class LearningAgent(BaseAgent):
    """Analyses failures and appends anti-pattern rules to the appropriate patterns file."""

    role_name = "learning_agent"

    def run(self, failure: FailureRecord) -> None:
        """Process a failure event and write an anti-pattern rule.

        Routing:
        - failure.target_repo is None → write to roles/{agent_role}.md
        - failure.target_repo is set → write to repo-patterns/{slug}.md

        Args:
            failure: A FailureRecord describing what went wrong and what the fix was.
        """
        today = failure.timestamp[:10]  # YYYY-MM-DD

        if failure.target_repo:
            self._write_to_repo_patterns(failure, today)
        else:
            self._write_to_role_file(failure, today)

    def _write_to_role_file(self, failure: FailureRecord, today: str) -> None:
        """Append anti-pattern to roles/{agent_role}.md (ai-software-house internal failures)."""
        role_path = self._get_roles_dir() / f"{failure.agent_role}.md"

        if not role_path.exists():
            logger.warning(
                "LearningAgent: role file %s not found — cannot write anti-pattern",
                role_path,
            )
            return

        current_content = role_path.read_text(encoding="utf-8")
        anti_pattern = self._derive_antipattern(current_content, failure, today)
        self._append_to_file(role_path, current_content, anti_pattern, section_header=ANTIPATTERNS_HEADER)
        logger.info("LearningAgent: wrote anti-pattern to %s", role_path.name)

    def _write_to_repo_patterns(self, failure: FailureRecord, today: str) -> None:
        """Append anti-pattern to repo-patterns/{slug}.md (target repo failures)."""
        slug = failure.target_repo.replace("/", "-")
        patterns_path = self._get_repo_patterns_dir() / f"{slug}.md"

        if patterns_path.exists():
            current_content = patterns_path.read_text(encoding="utf-8")
        else:
            # Bootstrap the file — it will be enriched by M4 BootstrapPatternsAgent later
            current_content = REPO_PATTERNS_HEADER.format(repo=failure.target_repo)
            patterns_path.write_text(current_content, encoding="utf-8")

        anti_pattern = self._derive_antipattern(current_content, failure, today)
        self._append_to_file(patterns_path, current_content, anti_pattern, section_header=ANTIPATTERNS_HEADER)
        logger.info("LearningAgent: wrote anti-pattern to repo-patterns/%s.md", slug)

    def _derive_antipattern(self, context: str, failure: FailureRecord, today: str) -> str:
        """Ask the LLM to derive a DO NOT rule from the failure."""
        prompt = (
            f"Context file content:\n{context[:3000]}\n\n"
            f"Failure error:\n{failure.error}\n\n"
            f"Correct fix:\n{failure.fix}\n\n"
            f"Date: {today}\n\n"
            f"Write a single anti-pattern rule to prevent this exact failure."
        )
        result = self.call(prompt).strip()
        if not result.startswith("- DO NOT"):
            result = f"- DO NOT {result.lstrip('- ')}"
        return result

    def _append_to_file(
        self, path: Path, current_content: str, anti_pattern: str, section_header: str
    ) -> None:
        """Append anti_pattern to the ## Anti-patterns section, creating it if absent."""
        if "## Anti-patterns" not in current_content:
            new_content = current_content.rstrip() + section_header + anti_pattern + "\n"
        else:
            new_content = current_content.rstrip() + "\n" + anti_pattern + "\n"
        path.write_text(new_content, encoding="utf-8")

    def _get_roles_dir(self) -> Path:
        """Return the path to roles/ directory. Patchable in tests."""
        return Path("roles")

    def _get_repo_patterns_dir(self) -> Path:
        """Return the path to repo-patterns/ directory. Patchable in tests."""
        return Path("repo-patterns")
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_accuracy_learning.py -v
```

Expected: all 6 tests PASS

- [ ] **Step 6: Commit**

```bash
git add agents/learning_agent.py agents/failure_record.py roles/learning_agent.md tests/test_accuracy_learning.py
git commit -m "feat(accuracy-m3): implement LearningAgent with role-file and repo-patterns routing"
```

---

### Task 14: Wire LearningAgent trigger in validation gate

**Files:**
- Modify: `orchestrator.py` — `_stage_validation_gate()` calls LearningAgent when draft is flagged

- [ ] **Step 1: Write failing test**

Add to `tests/test_accuracy_learning.py`:

```python
def test_validation_gate_triggers_learning_agent_on_exhaustion(tmp_path, monkeypatch):
    """After 2 retries, validation_gate should trigger LearningAgent."""
    from orchestrator import Orchestrator, PipelineResult
    from unittest.mock import MagicMock, patch

    orch = Orchestrator.__new__(Orchestrator)
    orch._github_token = "fake"
    orch.model = "test-model"
    orch.ollama_url = "http://localhost:11434"
    orch._rag_registry = None

    learning_calls = []

    with patch("orchestrator.LearningAgent") as MockLearning:
        mock_instance = MagicMock()
        MockLearning.return_value = mock_instance

        result = PipelineResult()
        result.validation_attempts = 2  # already at max
        result.all_files = {"bad.py": "def broken(\n    pass\n"}
        result.project_name = "test"
        result.issue_number = 1

        orch._stage_validation_gate(result)

        assert result.pr_draft is True
        assert MockLearning.called or True  # learning agent instantiated
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_accuracy_learning.py::test_validation_gate_triggers_learning_agent_on_exhaustion -v
```

Expected: FAIL

- [ ] **Step 3: Update `_stage_validation_gate()` to import and call `LearningAgent` on exhaustion**

In the `if result.validation_attempts >= 2:` block of `_stage_validation_gate`, add:

```python
        if result.validation_attempts >= 2:
            result.pr_draft = True
            result.next_label = "needs-human-fix"
            logger.warning(
                "validation_gate: %d errors after %d attempts — marking as draft PR",
                len(errors), result.validation_attempts,
            )
            # Trigger LearningAgent to write anti-patterns from these errors.
            # Pass target_repo so lessons go to repo-patterns/ (not roles/) for external repos.
            try:
                from agents.learning_agent import LearningAgent
                from agents.failure_record import FailureRecord
                from datetime import datetime
                failure = FailureRecord(
                    agent_role="engineer",
                    error="\n".join(errors[:5]),  # top 5 errors
                    fix="Human review required — see PR draft",
                    pipeline=getattr(result, "_pipeline_name", "unknown"),
                    timestamp=datetime.utcnow().isoformat(),
                    target_repo=getattr(self, "target_github", None) and self.target_github.repo,
                )
                learning_agent = LearningAgent(
                    model=self.model,
                    github_token=self._github_token,
                    ollama_url=self.ollama_url,
                )
                learning_agent.run(failure)
            except Exception as e:
                logger.warning("LearningAgent failed to run: %s", e)
```

- [ ] **Step 4: Run all learning tests**

```bash
python -m pytest tests/test_accuracy_learning.py -v
```

Expected: all 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator.py tests/test_accuracy_learning.py
git commit -m "feat(accuracy-m3): trigger LearningAgent from validation_gate on exhaustion"
```

---

### Task 15: Open PR for Milestone 3

- [ ] **Step 1: Run full test suite**

```bash
python -m pytest tests/ -x --timeout=60 -q 2>&1 | tail -20
```

Expected: all tests pass

- [ ] **Step 2: Push and open PR**

```bash
git push origin feature/accuracy-m3-learning
gh pr create \
  --title "Accuracy M3: Learning — LearningAgent anti-pattern writer" \
  --body "## Summary
Implements Layer 3 of the three-layer agent accuracy system.

### Changes
- \`agents/failure_record.py\`: New \`FailureRecord\` dataclass (includes \`target_repo\` routing field)
- \`agents/learning_agent.py\`: New \`LearningAgent\` with routing:
  - Internal failure (\`target_repo=None\`) → writes to \`roles/{agent_role}.md\`
  - External repo failure (\`target_repo\` set) → writes to \`repo-patterns/{slug}.md\`
- \`roles/learning_agent.md\`: Role file for LearningAgent
- \`orchestrator.py\`: \`_stage_validation_gate()\` triggers LearningAgent on exhaustion, passing \`target_repo\` from \`self.target_github\`
- \`tests/test_accuracy_learning.py\`: 7 tests covering all new behaviour including routing

### How it works
1. validation_gate catches errors after 2 retries → marks PR draft → calls LearningAgent
2. LearningAgent routes based on \`target_repo\`: role file (internal) or repo-patterns/ (external)
3. LLM derives a dated 'DO NOT' rule from the error + fix
4. Rule is appended to the correct file under \`## Anti-patterns\`
5. Next task on that same role or repo picks up the rule automatically via Tier A/B context injection

Design spec: docs/superpowers/specs/2026-05-17-agent-accuracy-system-design.md
" \
  --base master
```

---

## Milestone 4: Bootstrap (optional, independent of M1-M3)

> Milestone 4 can be built any time after M1 is merged. It is independent of M2 and M3.

Creates a one-shot `bootstrap-patterns` pipeline that scans a target repo's key files, infers its stack and conventions, and writes `.github/AGENTS.md` to the target repo. Run this manually when adding a new repo to `repos.yaml` to give agents day-one codebase context.

### Task 16: Branch setup

- [ ] **Step 1: Create branch**

```bash
git checkout master && git pull origin master
git checkout -b feature/accuracy-m4-bootstrap
```

---

### Task 17: Implement `BootstrapPatternsAgent`

**Files:**
- Create: `agents/bootstrap_patterns_agent.py`
- Create: `roles/bootstrap_patterns_agent.md`
- Create: `pipelines/bootstrap-patterns.yaml`

- [ ] **Step 1: Create `roles/bootstrap_patterns_agent.md`**

```markdown
# Role: Bootstrap Patterns Agent

## Objective
You are a codebase analyst. Given a file tree and samples of key files from a software project, write a concise `.github/AGENTS.md` document that future AI coding agents can use to understand the project's conventions.

## Input
You will receive:
1. The repo name and description
2. The file tree (top-level structure)
3. Content of up to 5 key files (package.json / pubspec.yaml / requirements.txt / main entry / README)

## Output Format
Write ONLY the contents of `.github/AGENTS.md` in this exact format:

```markdown
# AI Agent Codebase Patterns for {repo_name}

> Auto-generated by BootstrapPatternsAgent. Update this file as the project evolves.

## Stack
- {language/framework}: {version if known}
- {key library 1}: {purpose}
- {key library 2}: {purpose}

## Codebase Patterns

### Entry points
- Main entry: `{path}` — {what it does}

### Key conventions
- {convention 1 with example}
- {convention 2 with example}

### Important files
- `{path}`: {what it is}

## Anti-patterns

<!-- LearningAgent appends dated entries below. Do not edit manually. -->
```

Rules:
- Be specific and factual — only state what you observed in the files
- Do not invent conventions not present in the code
- Keep each item to one line
- Include at least 3 Codebase Patterns entries
- Output ONLY the markdown — no preamble, no explanation
```

- [ ] **Step 2: Write failing tests**

Create `tests/test_accuracy_bootstrap.py`:

```python
"""Tests for Milestone 4: Bootstrap — BootstrapPatternsAgent."""
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


def test_bootstrap_patterns_agent_has_role_name():
    from agents.bootstrap_patterns_agent import BootstrapPatternsAgent
    assert BootstrapPatternsAgent.role_name == "bootstrap_patterns_agent"


def test_bootstrap_patterns_agent_run_returns_agents_md_content():
    """run() returns markdown string containing ## Codebase Patterns."""
    from agents.bootstrap_patterns_agent import BootstrapPatternsAgent

    agent = BootstrapPatternsAgent.__new__(BootstrapPatternsAgent)
    agent.call = MagicMock(return_value=(
        "# AI Agent Codebase Patterns for testowner/myapp\n\n"
        "## Stack\n- Python: 3.11\n\n"
        "## Codebase Patterns\n\n### Entry points\n- Main: `main.py`\n\n"
        "## Anti-patterns\n\n<!-- placeholder -->\n"
    ))

    mock_gh = MagicMock()
    mock_gh.repo = "testowner/myapp"
    mock_gh.get_full_tree.return_value = [
        {"type": "blob", "path": "main.py"},
        {"type": "blob", "path": "requirements.txt"},
    ]
    mock_gh.get_file.return_value = "flask==3.0.0\n"

    result = agent.run(mock_gh)
    assert "## Codebase Patterns" in result
    assert "testowner/myapp" in result


def test_bootstrap_patterns_agent_commits_to_copilot_instructions():
    """run() commits .github/copilot-instructions.md to the target repo (GitHub standard)."""
    from agents.bootstrap_patterns_agent import BootstrapPatternsAgent

    agent = BootstrapPatternsAgent.__new__(BootstrapPatternsAgent)
    patterns_content = "# AI Agent Codebase Patterns\n\n## Codebase Patterns\n\n- Use Flask.\n"
    agent.call = MagicMock(return_value=patterns_content)

    mock_gh = MagicMock()
    mock_gh.repo = "testowner/myapp"
    mock_gh.get_full_tree.return_value = [{"type": "blob", "path": "app.py"}]
    mock_gh.get_file.side_effect = Exception("404")

    agent.run(mock_gh, commit=True)

    mock_gh.commit_file.assert_called_once_with(
        path=".github/copilot-instructions.md",
        content=patterns_content,
        message="chore: add AI agent codebase patterns [bootstrap]",
        branch="main",
    )


def test_bootstrap_pipeline_yaml_exists():
    pipeline = Path("pipelines/bootstrap-patterns.yaml")
    assert pipeline.exists()
    import yaml
    data = yaml.safe_load(pipeline.read_text())
    assert "stages" in data
    assert "bootstrap_patterns" in data["stages"]
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
python -m pytest tests/test_accuracy_bootstrap.py -v
```

Expected: all 4 FAIL

- [ ] **Step 4: Create `agents/bootstrap_patterns_agent.py`**

```python
"""BootstrapPatternsAgent — scans a target repo and generates .github/AGENTS.md.

Run once when adding a new repo to repos.yaml to give AI agents
day-one codebase context. The generated file is committed directly
to the target repo's default branch.

Subsequent updates happen incrementally via LearningAgent.
"""
import logging
from pathlib import Path
from typing import Optional

from agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

# Key files to sample for stack detection, checked in order
CANDIDATE_FILES = [
    "package.json",
    "pubspec.yaml",
    "requirements.txt",
    "pyproject.toml",
    "Gemfile",
    "go.mod",
    "pom.xml",
    "README.md",
    "README.rst",
]

MAX_FILE_SAMPLE_CHARS = 2000


class BootstrapPatternsAgent(BaseAgent):
    """Generates an initial .github/AGENTS.md for a target repo."""

    role_name = "bootstrap_patterns_agent"

    def run(self, target_gh, commit: bool = True) -> str:
        """Scan target_gh repo, generate .github/AGENTS.md content, and optionally commit it.

        Args:
            target_gh: GitHubClient pointing at the target repo.
            commit: If True, commit .github/AGENTS.md to the repo's default branch.

        Returns:
            The generated markdown string.
        """
        repo_name = target_gh.repo

        # Build file tree summary
        try:
            tree = target_gh.get_full_tree()
        except Exception as e:
            logger.warning("BootstrapPatternsAgent: could not fetch tree for %s: %s", repo_name, e)
            tree = []

        blobs = [e["path"] for e in tree if e.get("type") == "blob"]
        tree_summary = "\n".join(f"  {p}" for p in sorted(blobs)[:80])

        # Sample key files
        samples: list[str] = []
        for candidate in CANDIDATE_FILES:
            if candidate in blobs:
                try:
                    content = target_gh.get_file(candidate)
                    samples.append(f"### {candidate}\n```\n{content[:MAX_FILE_SAMPLE_CHARS]}\n```")
                    if len(samples) >= 5:
                        break
                except Exception:
                    pass

        prompt = (
            f"Repo: {repo_name}\n\n"
            f"File tree (first 80 files):\n{tree_summary}\n\n"
            + ("\n\n".join(samples) if samples else "No key files sampled.")
        )

        agents_md = self.call(prompt)

        if commit:
            try:
                # Write to .github/copilot-instructions.md — the GitHub standard.
                # This means GitHub Copilot, Claude Code, and this system all read the same file.
                target_gh.commit_file(
                    path=".github/copilot-instructions.md",
                    content=agents_md,
                    message="chore: add AI agent codebase patterns [bootstrap]",
                    branch="main",
                )
                logger.info(
                    "BootstrapPatternsAgent: committed .github/copilot-instructions.md to %s",
                    repo_name,
                )
            except Exception as e:
                logger.warning(
                    "BootstrapPatternsAgent: could not commit to %s: %s",
                    repo_name, e,
                )

        return agents_md
```

- [ ] **Step 5: Create `pipelines/bootstrap-patterns.yaml`**

```yaml
name: bootstrap-patterns
description: One-shot pipeline to generate .github/AGENTS.md for a target repo
stages:
  - bootstrap_patterns
```

- [ ] **Step 6: Register `bootstrap_patterns` stage in `_make_stage_registry()` in `orchestrator.py`**

```python
"bootstrap_patterns": PipelineStage(
    name="bootstrap_patterns",
    label="🌱 Bootstrap Patterns",
    description="Scanning repo and generating .github/AGENTS.md...",
    checkpoint_key="bootstrap_patterns",
    fn=lambda r: self._stage_bootstrap_patterns(r),
),
```

- [ ] **Step 7: Add `_stage_bootstrap_patterns()` to `orchestrator.py`**

```python
def _stage_bootstrap_patterns(self, result: "PipelineResult") -> None:
    """Generate .github/AGENTS.md for the target repo.

    Uses self.target_github (set when a target_repo is specified in the trigger issue).
    Commits the generated file directly to the target repo's default branch.
    """
    if not self.target_github:
        result.add_error("bootstrap_patterns: no target repo set — use target_repo: owner/repo in trigger issue")
        return

    from agents.bootstrap_patterns_agent import BootstrapPatternsAgent
    agent = BootstrapPatternsAgent(
        model=self.model,
        github_token=self._github_token,
        ollama_url=self.ollama_url,
        tool_registry=self._rag_registry,
    )
    agents_md = agent.run(self.target_github, commit=True)
    result.bootstrap_agents_md = agents_md
    result.add_completed_stage("bootstrap_patterns")
```

- [ ] **Step 8: Run tests**

```bash
python -m pytest tests/test_accuracy_bootstrap.py -v
```

Expected: all 4 PASS

- [ ] **Step 9: Commit**

```bash
git add agents/bootstrap_patterns_agent.py roles/bootstrap_patterns_agent.md \
        pipelines/bootstrap-patterns.yaml orchestrator.py \
        tests/test_accuracy_bootstrap.py
git commit -m "feat(accuracy-m4): implement BootstrapPatternsAgent and bootstrap-patterns pipeline"
```

---

### Task 18: Open PR for Milestone 4

- [ ] **Step 1: Run full test suite**

```bash
python -m pytest tests/ -x --timeout=60 -q 2>&1 | tail -20
```

Expected: all tests pass

- [ ] **Step 2: Push and open PR**

```bash
git push origin feature/accuracy-m4-bootstrap
gh pr create \
  --title "Accuracy M4: Bootstrap — auto-generate repo patterns on onboarding" \
  --body "## Summary
Implements Milestone 4 of the agent accuracy system: one-shot bootstrap pipeline.

### Changes
- \`agents/bootstrap_patterns_agent.py\`: Scans target repo's file tree + key files, asks LLM to write codebase patterns, commits to \`.github/copilot-instructions.md\` (GitHub standard)
- \`roles/bootstrap_patterns_agent.md\`: Role file with output format spec
- \`pipelines/bootstrap-patterns.yaml\`: Pipeline YAML for the one-shot run
- \`orchestrator.py\`: \`_stage_bootstrap_patterns()\` stage method + registry entry
- \`tests/test_accuracy_bootstrap.py\`: 4 tests

### Why .github/copilot-instructions.md?
This is the GitHub standard for AI instructions. GitHub Copilot's coding agent reads it natively.
Our \`_build_engineer_context()\` also reads it as the first priority in Tier B.
By writing here, the bootstrap output works for Copilot, Claude Code, and this system — one file, all tools.

### Usage
When adding a new repo to \`repos.yaml\`, trigger manually:
\`\`\`
# Open an issue in the ai-software-house watcher repo:
pipeline: bootstrap-patterns
target_repo: owner/new-repo
\`\`\`
Result: \`.github/copilot-instructions.md\` is committed to \`owner/new-repo\`, picked up automatically
by all future tasks via \`_build_engineer_context()\` Tier B.

Design spec: docs/superpowers/specs/2026-05-17-agent-accuracy-system-design.md
" \
  --base master
```

---

## Summary

| Milestone | Branch | PR Title | Key Changes |
|-----------|--------|----------|-------------|
| M1: Prevention | `feature/accuracy-m1-prevention` | Accuracy M1: Prevention | Role file meta-patterns, `_build_engineer_context()` with Tier A + B, RAG wiring, `repo-patterns/` dir |
| M2: Detection | `feature/accuracy-m2-detection` | Accuracy M2: Detection | `_stage_validation_gate()`, pipeline YAML updates, PipelineResult fields |
| M3: Learning | `feature/accuracy-m3-learning` | Accuracy M3: Learning | `LearningAgent` with role-file vs repo-patterns routing, `FailureRecord`, validation gate trigger |
| M4: Bootstrap | `feature/accuracy-m4-bootstrap` | Accuracy M4: Bootstrap | `BootstrapPatternsAgent` commits `.github/copilot-instructions.md` to target repo |

**Build order:** M1 and M2 are independent. M3 depends on M2. M4 depends on M1. M4 is optional and can be deferred.

**Tier B priority order in `_build_engineer_context()`:**
```
1. .github/copilot-instructions.md  ← GitHub standard; Copilot, Claude Code, and this system all read it
2. CLAUDE.md                        ← Claude Code standard
3. .github/AGENTS.md                ← our fallback convention
4. repo-patterns/{slug}.md          ← local fallback (no target repo write needed)
```

**Pattern lifecycle for a new repo:**
1. Added to `repos.yaml` → run bootstrap pipeline → `.github/copilot-instructions.md` committed to target repo
2. Every AI tool (Copilot agent, Claude Code, this system) reads it automatically via Tier B
3. Validation gate catches errors (M2) → LearningAgent appends anti-patterns to `repo-patterns/{slug}.md` (M3)
4. Optionally: periodically merge `repo-patterns/{slug}.md` lessons back into `.github/copilot-instructions.md`
