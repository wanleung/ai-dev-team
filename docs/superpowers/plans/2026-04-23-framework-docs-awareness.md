# Framework Docs Awareness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically detect and inject framework documentation (AGENTS.md, bundled docs, RAG hints) into engineer agent prompts so agents use accurate, version-matched docs instead of stale training data.

**Architecture:** A new `FrameworkDocsLoader` class (in `framework_docs.py`) inspects the project workspace for `AGENTS.md`/`CLAUDE.md` and config-defined framework doc bundles. The orchestrator calls it before `_stage_engineer` and passes the loaded context string to `EngineerAgent.run_all_modules` / `run_with_github`, which prepends it to each module prompt. Config drives which frameworks are known and where their docs live.

**Tech Stack:** Python 3.11+, PyYAML (already in project), pathlib, existing config merge pattern

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `framework_docs.py` | Create | Detection + loading logic |
| `config.yaml` | Modify | `framework_docs` section |
| `agents/engineer.py` | Modify | Accept + inject `framework_context` |
| `orchestrator.py` | Modify | Wire loader → engineer stage |
| `tests/test_framework_docs.py` | Create | Unit tests for loader |

---

### Task 1: `FrameworkDocsLoader` class

**Files:**
- Create: `framework_docs.py`
- Test: `tests/test_framework_docs.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_framework_docs.py`:

```python
"""Tests for FrameworkDocsLoader."""
import json
from pathlib import Path
import pytest
from framework_docs import FrameworkDocsLoader


@pytest.fixture
def tmp_project(tmp_path):
    return tmp_path


def _loader(config_override=None):
    cfg = {
        "framework_docs": {
            "check_agents_md": True,
            "frameworks": {
                "nextjs": {
                    "detect_file": "package.json",
                    "detect_key": '"next"',
                    "bundled_docs": "node_modules/next/dist/docs/",
                },
                "flutter": {
                    "detect_file": "pubspec.yaml",
                    "detect_key": "flutter:",
                    "rag_hint": "Use search_docs for Flutter API docs.",
                },
            },
        }
    }
    if config_override:
        cfg.update(config_override)
    return FrameworkDocsLoader(config=cfg)


def test_agents_md_injected(tmp_project):
    (tmp_project / "AGENTS.md").write_text("# AGENTS\nRead bundled docs first.")
    loader = _loader()
    ctx = loader.load(tmp_project)
    assert "Read bundled docs first." in ctx
    assert "AGENTS.md" in ctx


def test_claude_md_fallback(tmp_project):
    (tmp_project / "CLAUDE.md").write_text("# CLAUDE\nCustom instructions.")
    loader = _loader()
    ctx = loader.load(tmp_project)
    assert "Custom instructions." in ctx


def test_agents_md_takes_priority_over_claude_md(tmp_project):
    (tmp_project / "AGENTS.md").write_text("agents content")
    (tmp_project / "CLAUDE.md").write_text("claude content")
    loader = _loader()
    ctx = loader.load(tmp_project)
    assert "agents content" in ctx
    assert "claude content" not in ctx


def test_empty_project_returns_empty(tmp_project):
    loader = _loader()
    ctx = loader.load(tmp_project)
    assert ctx == ""


def test_nextjs_framework_detected_no_bundled_docs(tmp_project):
    pkg = {"dependencies": {"next": "^14.0.0", "react": "^18.0.0"}}
    (tmp_project / "package.json").write_text(json.dumps(pkg))
    loader = _loader()
    ctx = loader.load(tmp_project)
    # No bundled docs dir exists, but should still note detection
    assert "next" in ctx.lower()


def test_nextjs_bundled_docs_indexed(tmp_project):
    pkg = {"dependencies": {"next": "^14.0.0"}}
    (tmp_project / "package.json").write_text(json.dumps(pkg))
    docs_dir = tmp_project / "node_modules" / "next" / "dist" / "docs"
    docs_dir.mkdir(parents=True)
    (docs_dir / "routing.md").write_text("# Routing\nUse app/ directory.")
    (docs_dir / "data-fetching.md").write_text("# Data Fetching\nUse fetch() in server components.")
    loader = _loader()
    ctx = loader.load(tmp_project)
    assert "Routing" in ctx or "Data Fetching" in ctx


def test_flutter_rag_hint_injected(tmp_project):
    (tmp_project / "pubspec.yaml").write_text("name: myapp\nflutter:\n  uses-material-design: true\n")
    loader = _loader()
    ctx = loader.load(tmp_project)
    assert "Use search_docs for Flutter API docs." in ctx


def test_check_agents_md_disabled(tmp_project):
    (tmp_project / "AGENTS.md").write_text("should be ignored")
    loader = FrameworkDocsLoader(config={"framework_docs": {"check_agents_md": False}})
    ctx = loader.load(tmp_project)
    assert ctx == ""


def test_framework_docs_disabled_entirely(tmp_project):
    (tmp_project / "AGENTS.md").write_text("should be ignored")
    loader = FrameworkDocsLoader(config={})
    ctx = loader.load(tmp_project)
    assert ctx == ""
```

- [ ] **Step 2: Run tests — verify they all fail**

```bash
cd /home/wanleung/Projects/ai-software-house
source venv/bin/activate
python -m pytest tests/test_framework_docs.py -v 2>&1 | head -30
```
Expected: `ModuleNotFoundError: No module named 'framework_docs'`

- [ ] **Step 3: Implement `framework_docs.py`**

Create `framework_docs.py` at repo root:

```python
"""Framework docs awareness — detects and loads framework documentation into agent context."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# Max chars to read from a single bundled doc file (avoid giant prompts)
_MAX_DOC_CHARS = 4000
# Max total chars for all bundled docs combined
_MAX_TOTAL_BUNDLED = 12000


class FrameworkDocsLoader:
    """Detects framework docs in a project workspace and returns context to inject into prompts.

    Priority order:
      1. AGENTS.md at project root
      2. CLAUDE.md at project root
      3. Config-defined framework bundled docs or RAG hints
    """

    def __init__(self, config: dict) -> None:
        self._cfg = (config or {}).get("framework_docs", {})

    def load(self, project_dir: Path) -> str:
        """Return a context string to prepend to engineer prompts, or empty string if nothing found.

        Args:
            project_dir: Absolute path to the project workspace directory.
        """
        if not self._cfg:
            return ""

        # Layer 1 — AGENTS.md / CLAUDE.md
        if self._cfg.get("check_agents_md", True):
            for filename in ("AGENTS.md", "CLAUDE.md"):
                candidate = project_dir / filename
                if candidate.is_file():
                    content = candidate.read_text(encoding="utf-8", errors="replace").strip()
                    if content:
                        log.info("Loaded framework context from %s", filename)
                        return (
                            f"## Framework Instructions ({filename})\n\n"
                            f"{content}\n\n"
                            "---\n\n"
                        )

        # Layer 2 — Config-driven framework detection
        frameworks = self._cfg.get("frameworks", {})
        if not frameworks:
            return ""

        collected: list[str] = []

        for fw_name, fw_cfg in frameworks.items():
            detect_file = fw_cfg.get("detect_file")
            detect_key = fw_cfg.get("detect_key", "")

            if not detect_file:
                continue

            target = project_dir / detect_file
            if not target.is_file():
                continue

            file_content = target.read_text(encoding="utf-8", errors="replace")
            if detect_key and detect_key not in file_content:
                continue

            log.info("Detected framework: %s", fw_name)

            # RAG hint (always included if detected)
            rag_hint = fw_cfg.get("rag_hint", "")

            # Bundled docs
            bundled_path = fw_cfg.get("bundled_docs")
            bundled_text = ""
            if bundled_path:
                docs_dir = project_dir / bundled_path
                if docs_dir.is_dir():
                    bundled_text = _read_bundled_docs(docs_dir)

            section_parts = [f"## {fw_name} Framework Docs\n"]
            if bundled_text:
                section_parts.append(bundled_text)
            elif rag_hint:
                section_parts.append(rag_hint)
            else:
                section_parts.append(
                    f"Framework '{fw_name}' detected. "
                    "Check the installed package for bundled documentation or use search_docs."
                )

            collected.append("\n".join(section_parts))

        if not collected:
            return ""

        return "\n\n---\n\n".join(collected) + "\n\n---\n\n"


def _read_bundled_docs(docs_dir: Path) -> str:
    """Read markdown/text files from a bundled docs directory up to _MAX_TOTAL_BUNDLED chars."""
    parts: list[str] = []
    total = 0

    for doc_file in sorted(docs_dir.rglob("*.md")):
        if total >= _MAX_TOTAL_BUNDLED:
            break
        try:
            text = doc_file.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if not text:
            continue
        chunk = text[:_MAX_DOC_CHARS]
        parts.append(f"### {doc_file.name}\n\n{chunk}")
        total += len(chunk)

    return "\n\n".join(parts)
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
python -m pytest tests/test_framework_docs.py -v
```
Expected: `9 passed`

- [ ] **Step 5: Commit**

```bash
git add framework_docs.py tests/test_framework_docs.py
git commit -m "feat(framework-docs): add FrameworkDocsLoader with AGENTS.md + config-driven detection"
```

---

### Task 2: Add `framework_docs` section to `config.yaml`

**Files:**
- Modify: `config.yaml`

- [ ] **Step 1: Add the section**

Find the bottom of `config.yaml` (before the final comments or EOF) and append:

```yaml
# ── Framework Docs Awareness ───────────────────────────────────────────────
# Controls automatic injection of framework documentation into engineer prompts.
# Priority: AGENTS.md > CLAUDE.md > bundled docs > rag_hint
framework_docs:
  # When true, look for AGENTS.md or CLAUDE.md at the project root and inject into prompts.
  # AGENTS.md is the emerging standard (Next.js, etc.) for directing AI agents to bundled docs.
  check_agents_md: true

  # Per-framework doc detection. The orchestrator checks these BEFORE calling the engineer.
  # detect_file: a file that must exist in the project root (e.g. package.json, pubspec.yaml)
  # detect_key:  a string that must appear in detect_file (identifies the framework)
  # bundled_docs: relative path to bundled docs dir shipped with the package (optional)
  # rag_hint:     fallback text injected when no bundled docs found (optional)
  frameworks:
    nextjs:
      detect_file: package.json
      detect_key: '"next"'
      bundled_docs: node_modules/next/dist/docs/
      # bundled docs are auto-created by: npx create-next-app (v16.2+)

    nuxt:
      detect_file: package.json
      detect_key: '"nuxt"'
      bundled_docs: node_modules/nuxt/docs/

    react:
      detect_file: package.json
      detect_key: '"react"'
      rag_hint: >
        Use search_docs to find React documentation (hooks, components, patterns).
        If this is a Next.js project, prefer Next.js docs over raw React docs.

    flutter:
      detect_file: pubspec.yaml
      detect_key: "flutter:"
      rag_hint: >
        Use search_docs to find Flutter widget and API documentation.
        For Dart-specific APIs, check the Dart SDK docs.

    fastapi:
      detect_file: requirements.txt
      detect_key: fastapi
      rag_hint: >
        Use search_docs for FastAPI routing, dependency injection, and Pydantic schemas.

    django:
      detect_file: requirements.txt
      detect_key: django
      rag_hint: >
        Use search_docs for Django ORM, views, serializers, and URL routing patterns.
```

- [ ] **Step 2: Verify YAML parses cleanly**

```bash
python -c "import yaml; cfg = yaml.safe_load(open('config.yaml')); print(list(cfg.get('framework_docs', {}).get('frameworks', {}).keys()))"
```
Expected: `['nextjs', 'nuxt', 'react', 'flutter', 'fastapi', 'django']`

- [ ] **Step 3: Commit**

```bash
git add config.yaml
git commit -m "feat(framework-docs): add framework_docs config section with 6 frameworks"
```

---

### Task 3: Engineer agent accepts `framework_context`

**Files:**
- Modify: `agents/engineer.py`

- [ ] **Step 1: Update `run_module` signature and prompt**

In `agents/engineer.py`, update `run_module` to accept and use `framework_context`:

```python
def run_module(
    self,
    design: str,
    module: dict,
    project_name: str = "Project",
    framework_context: str = "",
) -> dict:
    """Implement a single module.

    Args:
        design: Full system design markdown.
        module: Module dict with 'name' and 'description' keys.
        project_name: Project name for context.
        framework_context: Optional framework docs/instructions to prepend to the prompt.

    Returns:
        dict with keys:
            - module_name (str): The module name
            - files (dict): {filepath: file_content} for all generated files
            - raw_response (str): Full LLM response
    """
    fw_block = (
        f"## Framework Documentation\n\n{framework_context}\n\n"
        if framework_context else ""
    )
    scaffold_hint = (
        "\n\n> **Note:** If you scaffold a new project (e.g. `create-next-app`, `flutter create`), "
        "check for an `AGENTS.md` file afterwards and follow its instructions before writing feature code."
    ) if not framework_context else ""

    prompt = (
        f"{fw_block}"
        f"You are implementing the '{module['name']}' module for the project '{project_name}'.\n\n"
        f"Module description: {module.get('description', '')}\n\n"
        f"Full System Design:\n---\n{design}\n---\n\n"
        f"Please implement ALL files for this module. "
        f"Output each file using the '### FILE: path/to/file.py' format as instructed."
        f"{scaffold_hint}"
    )

    if self._tool_registry is not None:
        rag_hint = (
            "\n\nYou have access to RAG search tools: `search_codebase` and `search_docs`. "
            "Use them to find relevant existing code patterns and documentation before implementing."
        )
        try:
            response = self.call_with_tools(prompt + rag_hint, tools=self._tool_registry)
        except NotImplementedError:
            response = self.call(prompt)
    else:
        response = self.call(prompt)
    files = self._parse_files(response)

    return {
        "module_name": module["name"],
        "files": files,
        "raw_response": response,
    }
```

- [ ] **Step 2: Update `run_all_modules` to accept and forward `framework_context`**

Replace the `run_all_modules` signature and the `run_module` call inside it:

Find the existing `run_all_modules` method and update its signature and the call to `run_module`:

```python
def run_all_modules(
    self,
    design: str,
    modules: list[dict],
    project_name: str = "Project",
    max_workers: int = 3,
    framework_context: str = "",
) -> dict:
```

And in the thread-pool executor call inside `run_all_modules`, pass `framework_context=framework_context` to `run_module`. The executor call will look like:

```python
future_to_mod[executor.submit(
    self.run_module, design, mod, project_name, framework_context
)] = mod
```

- [ ] **Step 3: Update `run_with_github` to accept and forward `framework_context`**

Find `run_with_github` in `agents/engineer.py` and add `framework_context: str = ""` to its signature, then forward it to the `run_all_modules` call inside it:

```python
def run_with_github(
    self,
    design: str,
    modules: list[dict],
    project_name: str,
    github_client,
    branch_prefix: str = "feature/agent",
    issue_number: Optional[int] = None,
    max_workers: int = 3,
    framework_context: str = "",
) -> dict:
    result = self.run_all_modules(
        design, modules, project_name,
        max_workers=max_workers,
        framework_context=framework_context,
    )
    ...
```

- [ ] **Step 4: Run existing tests to verify nothing broke**

```bash
python -m pytest tests/ -v -k "engineer" --ignore=tests/test_outlook_provider.py --ignore=tests/test_sse.py 2>&1 | tail -20
```
Expected: all engineer-related tests pass (or no test collection errors)

- [ ] **Step 5: Commit**

```bash
git add agents/engineer.py
git commit -m "feat(framework-docs): engineer agent accepts framework_context param"
```

---

### Task 4: Wire `FrameworkDocsLoader` into orchestrator

**Files:**
- Modify: `orchestrator.py`

- [ ] **Step 1: Import and instantiate `FrameworkDocsLoader`**

At the top of `orchestrator.py`, add the import alongside other local imports:

```python
from framework_docs import FrameworkDocsLoader
```

In `Orchestrator.__init__`, add parameter and store it (alongside `skill_loader`):

```python
framework_docs_loader: Optional["FrameworkDocsLoader"] = None,
```

And in the body:

```python
self.framework_docs_loader: Optional[FrameworkDocsLoader] = framework_docs_loader
```

In `Orchestrator.from_config`, after `skill_loader = SkillLoader(config=cfg)`, add:

```python
framework_docs_loader = FrameworkDocsLoader(config=cfg)
```

And pass it to the constructor:

```python
framework_docs_loader=framework_docs_loader,
```

- [ ] **Step 2: Load context before `_stage_engineer` and pass it through**

In `_stage_engineer`, compute `framework_context` from the workspace project dir before calling the engineer:

```python
def _stage_engineer(self, result: PipelineResult) -> None:
    # Detect framework docs for this project
    framework_context = ""
    if self.framework_docs_loader:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in result.project_name.lower())
        project_dir = (self.workspace_dir / safe).resolve()
        if project_dir.exists():
            framework_context = self.framework_docs_loader.load(project_dir)
            if framework_context:
                console.print("  📚 [dim]Framework docs injected into engineer prompts[/dim]")

    # Limit to num_engineers modules for parallel dispatch
    modules = result.modules[: max(self.num_engineers, len(result.modules))]
    if self.target_github:
        eng_result = self.engineer.run_with_github(
            result.design,
            modules,
            result.project_name,
            self.target_github,
            branch_prefix=self.branch_prefix,
            issue_number=result.issue_number,
            max_workers=self.num_engineers,
            framework_context=framework_context,
        )
        result.branch = eng_result.get("branch")
        result.pr_number = eng_result.get("pr_number")
        result.pr_url = eng_result.get("pr_url")
    else:
        eng_result = self.engineer.run_all_modules(
            result.design, modules, result.project_name,
            max_workers=self.num_engineers,
            framework_context=framework_context,
        )
    result.all_files = eng_result["all_files"]
    self._save_files_locally(result.all_files, result.project_name)
```

- [ ] **Step 3: Run full test suite (excluding known failing tests)**

```bash
python -m pytest tests/ -v \
  --ignore=tests/test_outlook_provider.py \
  --ignore=tests/test_sse.py \
  2>&1 | tail -20
```
Expected: all previously passing tests still pass + 9 new framework_docs tests pass.

- [ ] **Step 4: Commit**

```bash
git add orchestrator.py
git commit -m "feat(framework-docs): wire FrameworkDocsLoader into orchestrator pre-engineer stage"
```

---

### Task 5: Integration test + README update

**Files:**
- Modify: `tests/test_framework_docs.py` (add integration-style test)
- Modify: `README.md`

- [ ] **Step 1: Add an integration test that covers the orchestrator path**

Add to `tests/test_framework_docs.py`:

```python
def test_loader_returns_empty_for_nonexistent_dir(tmp_path):
    """Project dir doesn't exist yet (first-time scaffold) — must not crash."""
    loader = _loader()
    nonexistent = tmp_path / "does_not_exist"
    ctx = loader.load(nonexistent)
    assert ctx == ""


def test_loader_config_loaded_from_dict():
    """FrameworkDocsLoader initialises correctly with empty config."""
    loader = FrameworkDocsLoader(config={})
    assert loader.load(Path("/tmp")) == ""
```

- [ ] **Step 2: Run updated test file**

```bash
python -m pytest tests/test_framework_docs.py -v
```
Expected: `11 passed`

- [ ] **Step 3: Add README section**

In `README.md`, find the `## 🔍 RAG Knowledge Base` section heading and add a new section just before it:

```markdown
## 📚 Framework Docs Awareness

The engineer agent automatically detects framework documentation in the project workspace before writing code.

**Priority order:**
1. `AGENTS.md` at project root — read and injected verbatim (Next.js v16.2+, and other frameworks adopting the standard)
2. `CLAUDE.md` at project root — same as AGENTS.md, for Claude-specific instructions
3. Config-defined bundled docs (e.g. `node_modules/next/dist/docs/`) — content excerpts injected
4. Config-defined RAG hint — tells the agent to use `search_docs` for a known framework

**For empty/new projects:** The engineer's prompt includes an instruction to check for `AGENTS.md` after scaffolding (e.g. after `create-next-app`). This handles the bootstrap case where docs don't exist until the framework is installed.

**Configuration** (`config.yaml`):

```yaml
framework_docs:
  check_agents_md: true   # look for AGENTS.md/CLAUDE.md at project root

  frameworks:
    nextjs:
      detect_file: package.json   # must exist in project root
      detect_key: '"next"'        # must appear in that file
      bundled_docs: node_modules/next/dist/docs/
    flutter:
      detect_file: pubspec.yaml
      detect_key: "flutter:"
      rag_hint: "Use search_docs for Flutter widget and API documentation."
```

To add support for a new framework, add an entry under `framework_docs.frameworks` in `config.local.yaml`. No code changes needed.
```

- [ ] **Step 4: Run full test suite one final time**

```bash
python -m pytest tests/ -v \
  --ignore=tests/test_outlook_provider.py \
  --ignore=tests/test_sse.py \
  2>&1 | tail -10
```
Expected: all tests pass.

- [ ] **Step 5: Final commit**

```bash
git add tests/test_framework_docs.py README.md
git commit -m "feat(framework-docs): integration tests + README documentation"
```
