# Senior / Junior Engineer Tier System — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the engineer stage into senior (expensive model, complex integration modules) and junior (fast model, isolated utility modules) tiers to reduce cost and wall-clock time without sacrificing quality.

**Architecture:** The Architect tags each module with `tier: junior|senior`. A `TierReviewerAgent` validates the assignments. Config override rules take highest priority. Junior modules run first as a batch; their output is injected as context into senior prompts. Junior modules have a per-module test+retry quality gate before seniors start.

**Tech Stack:** Python 3.11, existing `BaseAgent` / `EngineerAgent` hierarchy, `fnmatch` for glob pattern matching, `ThreadPoolExecutor` for parallel execution, pytest for junior quality gate.

---

## File Map

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `agents/tier_reviewer.py` | Validates/corrects tier assignments across all modules |
| Create | `agents/junior_engineer.py` | `JuniorEngineerAgent` — thin subclass, sets `role_name` |
| Create | `agents/senior_engineer.py` | `SeniorEngineerAgent` — injects junior code context into prompt |
| Modify | `agents/architect.py` | Add `tier` field to module format in prompt; extend `_parse_modules` |
| Modify | `roles/architect.md` | Update Implementation Modules format to include `[tier:junior|senior]` |
| Create | `agents/tier_utils.py` | `apply_tier_overrides(modules, rules)` — fnmatch-based config override |
| Modify | `orchestrator.py` | New fields on `PipelineResult`; new init params; new stage methods; memory injection; `from_config` |
| Modify | `main.py` | Add `--junior-engineers`, `--senior-engineers` CLI flags |
| Modify | `config.yaml` | Document new `team:` fields with examples |
| Create | `tests/test_tier_reviewer.py` | Unit tests for `TierReviewerAgent` |
| Create | `tests/test_junior_senior_engineer.py` | Unit tests for both new agent subclasses |
| Create | `tests/test_tier_utils.py` | Unit tests for `apply_tier_overrides` |
| Create | `tests/test_architect_tier.py` | Unit tests for `_parse_modules` with tier field |

---

## Task 1: `apply_tier_overrides` utility + tests

**Files:**
- Create: `agents/tier_utils.py`
- Create: `tests/test_tier_utils.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_tier_utils.py
from agents.tier_utils import apply_tier_overrides


def test_no_rules_returns_unchanged():
    modules = [{"name": "app/models/user", "description": "User model", "tier": "junior"}]
    result = apply_tier_overrides(modules, [])
    assert result == modules


def test_exact_match_overrides_tier():
    modules = [{"name": "app/models/user", "description": "User model", "tier": "senior"}]
    rules = [{"pattern": "app/models/*", "tier": "junior"}]
    result = apply_tier_overrides(modules, rules)
    assert result[0]["tier"] == "junior"


def test_first_matching_rule_wins():
    modules = [{"name": "app/core/config", "description": "Config", "tier": "junior"}]
    rules = [
        {"pattern": "app/core*", "tier": "senior"},
        {"pattern": "app/*", "tier": "junior"},
    ]
    result = apply_tier_overrides(modules, rules)
    assert result[0]["tier"] == "senior"


def test_no_matching_rule_leaves_tier_unchanged():
    modules = [{"name": "app/services/auth", "description": "Auth service", "tier": "junior"}]
    rules = [{"pattern": "*/models*", "tier": "junior"}]
    result = apply_tier_overrides(modules, rules)
    assert result[0]["tier"] == "junior"


def test_multiple_modules_each_matched_independently():
    modules = [
        {"name": "app/models/user", "description": "User model", "tier": "senior"},
        {"name": "app/services/auth", "description": "Auth", "tier": "junior"},
    ]
    rules = [{"pattern": "*/models*", "tier": "junior"}]
    result = apply_tier_overrides(modules, rules)
    assert result[0]["tier"] == "junior"
    assert result[1]["tier"] == "junior"  # unchanged, no match


def test_missing_tier_field_defaults_to_senior():
    modules = [{"name": "app/services/auth", "description": "Auth"}]
    result = apply_tier_overrides(modules, [])
    assert result[0]["tier"] == "senior"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_tier_utils.py -v
```
Expected: `ModuleNotFoundError: No module named 'agents.tier_utils'`

- [ ] **Step 3: Create `agents/tier_utils.py`**

```python
"""
tier_utils: Applies config-based tier override rules to a module list.
"""
from __future__ import annotations

import fnmatch


def apply_tier_overrides(
    modules: list[dict],
    rules: list[dict],
) -> list[dict]:
    """Apply glob-pattern override rules to module tier assignments.

    Rules are evaluated in order; first matching rule wins.
    Modules missing a 'tier' field default to 'senior'.

    Args:
        modules: List of module dicts (each with 'name', 'description', optional 'tier').
        rules: List of override dicts: [{"pattern": "*/models*", "tier": "junior"}, ...]

    Returns:
        New list of module dicts with 'tier' set according to rules (or defaults).
    """
    result = []
    for module in modules:
        mod = dict(module)
        if "tier" not in mod:
            mod["tier"] = "senior"
        for rule in rules:
            if fnmatch.fnmatch(mod["name"], rule["pattern"]):
                mod["tier"] = rule["tier"]
                break
        result.append(mod)
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_tier_utils.py -v
```
Expected: 6 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add agents/tier_utils.py tests/test_tier_utils.py
git commit -m "feat: add tier override utility with fnmatch glob rules

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 2: Architect tier tagging

**Files:**
- Modify: `roles/architect.md` (Implementation Modules section)
- Modify: `agents/architect.py` (`_parse_modules` static method)
- Create: `tests/test_architect_tier.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_architect_tier.py
from agents.architect import ArchitectAgent


def test_parse_modules_extracts_tier_junior():
    design = """
## Implementation Modules
1. **`app/models/user`** [tier:junior]: User model and schema
2. **`app/services/auth`** [tier:senior]: Authentication service
"""
    modules = ArchitectAgent._parse_modules(design)
    assert len(modules) == 2
    assert modules[0]["name"] == "`app/models/user`"
    assert modules[0]["tier"] == "junior"
    assert modules[1]["name"] == "`app/services/auth`"
    assert modules[1]["tier"] == "senior"


def test_parse_modules_defaults_to_senior_when_no_tier():
    design = """
## Implementation Modules
1. **`app/models/user`**: User model and schema
"""
    modules = ArchitectAgent._parse_modules(design)
    assert modules[0]["tier"] == "senior"


def test_parse_modules_preserves_description():
    design = """
## Implementation Modules
1. **`app/core`** [tier:senior]: Core config and startup logic
"""
    modules = ArchitectAgent._parse_modules(design)
    assert "Core config and startup logic" in modules[0]["description"]


def test_parse_modules_fallback_returns_senior_tier():
    design = "No modules section here."
    modules = ArchitectAgent._parse_modules(design)
    assert modules[0]["name"] == "main"
    assert modules[0]["tier"] == "senior"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_architect_tier.py -v
```
Expected: `AssertionError` — `tier` key missing from parsed modules

- [ ] **Step 3: Update `roles/architect.md` Implementation Modules format**

Find this section in `roles/architect.md`:
```markdown
## Implementation Modules
1. **[module_name]**: [description] — implements [component]
2. **[module_name]**: [description]
```

Replace with:
```markdown
## Implementation Modules

Classify each module as `junior` (self-contained: models, schemas, utils, config, migrations — no dependencies on other modules in this run) or `senior` (integrates or builds on other modules: service layers, API routes, controllers, auth flows, background tasks).

1. **[module_name]** [tier:junior]: [description] — implements [component]
2. **[module_name]** [tier:senior]: [description]
```

- [ ] **Step 4: Update `_parse_modules` in `agents/architect.py`**

Find the line:
```python
                if name:
                    modules.append({"name": name, "description": desc})
```

Replace with:
```python
                if name:
                    # Extract [tier:junior] or [tier:senior] tag from name or desc
                    tier = "senior"
                    import re as _re
                    tier_match = _re.search(r'\[tier:(junior|senior)\]', name + " " + desc)
                    if tier_match:
                        tier = tier_match.group(1)
                        # Remove the tag from name and desc
                        name = _re.sub(r'\s*\[tier:(?:junior|senior)\]', '', name).strip()
                        desc = _re.sub(r'\s*\[tier:(?:junior|senior)\]', '', desc).strip()
                    modules.append({"name": name, "description": desc, "tier": tier})
```

Also update the fallback at the bottom of `_parse_modules`:
```python
        if not modules:
            modules = [{"name": "main", "description": "Main application module", "tier": "senior"}]
```

- [ ] **Step 5: Move the `import re` to the top of `_parse_modules` properly**

The `import re` is already at the top of `architect.py` (check with `grep "^import re" agents/architect.py`). If it is, remove the inline `import re as _re` and use `re` directly:

```python
                    tier_match = re.search(r'\[tier:(junior|senior)\]', name + " " + desc)
                    if tier_match:
                        tier = tier_match.group(1)
                        name = re.sub(r'\s*\[tier:(?:junior|senior)\]', '', name).strip()
                        desc = re.sub(r'\s*\[tier:(?:junior|senior)\]', '', desc).strip()
```

If `re` is NOT imported at the top of `architect.py`, add `import re` to the imports section.

- [ ] **Step 6: Run tests to verify they pass**

```bash
python -m pytest tests/test_architect_tier.py -v
```
Expected: 4 tests PASSED

- [ ] **Step 7: Run existing tests to check for regressions**

```bash
python -m pytest tests/ -v -k "not integration" --ignore=tests/integration 2>&1 | tail -20
```
Expected: All previously passing tests still PASS

- [ ] **Step 8: Commit**

```bash
git add roles/architect.md agents/architect.py tests/test_architect_tier.py
git commit -m "feat: architect assigns tier field (junior/senior) to each module

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 3: `TierReviewerAgent`

**Files:**
- Create: `agents/tier_reviewer.py`
- Create: `tests/test_tier_reviewer.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_tier_reviewer.py
from unittest.mock import MagicMock
from agents.tier_reviewer import TierReviewerAgent


def _make_agent(response: str) -> TierReviewerAgent:
    agent = TierReviewerAgent.__new__(TierReviewerAgent)
    agent.call = MagicMock(return_value=response)
    return agent


def test_run_returns_revised_module_list():
    response = """
1. **`app/models/user`** [tier:junior]: User model
2. **`app/services/auth`** [tier:senior]: Auth service
"""
    agent = _make_agent(response)
    modules = [
        {"name": "`app/models/user`", "description": "User model", "tier": "senior"},
        {"name": "`app/services/auth`", "description": "Auth service", "tier": "junior"},
    ]
    result = agent.run(modules)
    assert result[0]["tier"] == "junior"
    assert result[1]["tier"] == "senior"


def test_run_preserves_modules_on_parse_failure():
    """If LLM returns unparseable output, original modules are returned unchanged."""
    agent = _make_agent("I cannot review these modules right now.")
    modules = [
        {"name": "app/core", "description": "Core", "tier": "senior"},
    ]
    result = agent.run(modules)
    assert result == modules


def test_run_prompt_contains_all_module_names():
    agent = _make_agent("1. **`app/models/user`** [tier:junior]: User model")
    captured = []
    agent.call = MagicMock(side_effect=lambda p: captured.append(p) or "1. **`app/models/user`** [tier:junior]: User model")
    modules = [{"name": "`app/models/user`", "description": "User model", "tier": "senior"}]
    agent.run(modules)
    assert "`app/models/user`" in captured[0]


def test_run_returns_same_length_as_input():
    response = """
1. **`app/a`** [tier:junior]: A
2. **`app/b`** [tier:senior]: B
3. **`app/c`** [tier:junior]: C
"""
    agent = _make_agent(response)
    modules = [
        {"name": "`app/a`", "description": "A", "tier": "senior"},
        {"name": "`app/b`", "description": "B", "tier": "junior"},
        {"name": "`app/c`", "description": "C", "tier": "senior"},
    ]
    result = agent.run(modules)
    assert len(result) == 3
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_tier_reviewer.py -v
```
Expected: `ModuleNotFoundError: No module named 'agents.tier_reviewer'`

- [ ] **Step 3: Create `agents/tier_reviewer.py`**

```python
"""
TierReviewerAgent: validates and corrects module tier assignments (junior/senior).
Single LLM call — not a loop.
"""
from __future__ import annotations

import re

from .base_agent import BaseAgent


class TierReviewerAgent(BaseAgent):
    """Reviews the architect's module tier assignments and corrects any misclassifications.

    Input:  list of modules with tier assignments from the architect
    Output: revised list of modules with corrected tier assignments
    """

    role_name = "tier_reviewer"

    def run(self, modules: list[dict]) -> list[dict]:
        """Review and correct tier assignments for a list of modules.

        Args:
            modules: List of module dicts with 'name', 'description', 'tier' keys.

        Returns:
            Revised list of module dicts with corrected 'tier' values.
            Falls back to original modules if the LLM response cannot be parsed.
        """
        module_lines = "\n".join(
            f"{i+1}. **{m['name']}** [tier:{m.get('tier', 'senior')}]: {m.get('description', '')}"
            for i, m in enumerate(modules)
        )
        prompt = (
            "You are reviewing module tier assignments for a software project.\n\n"
            "Tier definitions:\n"
            "- **junior**: Self-contained modules with NO dependency on other modules in this list "
            "(models, schemas, utils, constants, config loaders, migrations).\n"
            "- **senior**: Modules that integrate, orchestrate, or BUILD ON other modules in this list "
            "(service layers, API routes, controllers, authentication flows, background tasks).\n\n"
            "Review each module below and correct its tier if needed. "
            "Return the COMPLETE revised list in the SAME FORMAT. "
            "Output ONLY the numbered list — no explanations.\n\n"
            f"## Module List\n{module_lines}"
        )

        response = self.call(prompt)
        revised = self._parse_revised_modules(response, modules)
        return revised

    @staticmethod
    def _parse_revised_modules(response: str, original: list[dict]) -> list[dict]:
        """Parse revised tier assignments from LLM response.

        Falls back to original modules if parsing fails or count mismatches.
        """
        pattern = re.compile(
            r'\d+\.\s+\*\*(.+?)\*\*\s+\[tier:(junior|senior)\]',
            re.IGNORECASE,
        )
        matches = pattern.findall(response)

        if len(matches) != len(original):
            return original

        revised = []
        for (_, tier), orig in zip(matches, original):
            mod = dict(orig)
            mod["tier"] = tier.lower()
            revised.append(mod)
        return revised
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_tier_reviewer.py -v
```
Expected: 4 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add agents/tier_reviewer.py tests/test_tier_reviewer.py
git commit -m "feat: add TierReviewerAgent to validate module tier assignments

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 4: `JuniorEngineerAgent` and `SeniorEngineerAgent`

**Files:**
- Create: `agents/junior_engineer.py`
- Create: `agents/senior_engineer.py`
- Create: `tests/test_junior_senior_engineer.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_junior_senior_engineer.py
from unittest.mock import MagicMock
from agents.junior_engineer import JuniorEngineerAgent
from agents.senior_engineer import SeniorEngineerAgent


def _make_junior() -> JuniorEngineerAgent:
    agent = JuniorEngineerAgent.__new__(JuniorEngineerAgent)
    agent._tool_registry = None
    return agent


def _make_senior() -> SeniorEngineerAgent:
    agent = SeniorEngineerAgent.__new__(SeniorEngineerAgent)
    agent._tool_registry = None
    return agent


# ── JuniorEngineerAgent ───────────────────────────────────────────────────────

def test_junior_role_name():
    assert JuniorEngineerAgent.role_name == "junior_engineer"


def test_junior_run_module_returns_files():
    agent = _make_junior()
    agent.call = MagicMock(return_value=(
        "### FILE: app/models/user.py\n"
        "class User:\n    pass\n"
    ))
    result = agent.run_module("design", {"name": "app/models/user", "description": "User model"})
    assert "app/models/user.py" in result["files"]


def test_junior_prompt_does_not_contain_junior_code_context():
    agent = _make_junior()
    captured = []
    agent.call = MagicMock(side_effect=lambda p: captured.append(p) or "### FILE: x.py\npass")
    agent.run_module("design", {"name": "app/models/user", "description": "User model"})
    assert "Junior Code Context" not in captured[0]


# ── SeniorEngineerAgent ───────────────────────────────────────────────────────

def test_senior_role_name():
    assert SeniorEngineerAgent.role_name == "senior_engineer"


def test_senior_run_module_injects_junior_context():
    agent = _make_senior()
    captured = []
    agent.call = MagicMock(side_effect=lambda p: captured.append(p) or "### FILE: x.py\npass")
    junior_files = {"app/models/user.py": "class User:\n    pass\n"}
    agent.run_module(
        "design",
        {"name": "app/services/auth", "description": "Auth service"},
        junior_files=junior_files,
    )
    assert "Junior Code Context" in captured[0]
    assert "app/models/user.py" in captured[0]
    assert "class User" in captured[0]


def test_senior_run_module_no_junior_files_skips_context():
    agent = _make_senior()
    captured = []
    agent.call = MagicMock(side_effect=lambda p: captured.append(p) or "### FILE: x.py\npass")
    agent.run_module(
        "design",
        {"name": "app/services/auth", "description": "Auth service"},
        junior_files={},
    )
    assert "Junior Code Context" not in captured[0]


def test_senior_run_module_returns_files():
    agent = _make_senior()
    agent.call = MagicMock(return_value=(
        "### FILE: app/services/auth.py\n"
        "def login(): pass\n"
    ))
    result = agent.run_module(
        "design",
        {"name": "app/services/auth", "description": "Auth"},
        junior_files={},
    )
    assert "app/services/auth.py" in result["files"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_junior_senior_engineer.py -v
```
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Create `agents/junior_engineer.py`**

```python
"""
JuniorEngineerAgent: implements simple, self-contained modules using a fast/cheap model.
Inherits all behaviour from EngineerAgent — only role_name differs for model routing.
"""
from __future__ import annotations

from .engineer import EngineerAgent


class JuniorEngineerAgent(EngineerAgent):
    """Junior Engineer — implements isolated modules (models, schemas, utils).

    Uses a fast/cheap model. Inherits run_module, run_all_modules, run_with_github
    from EngineerAgent unchanged.
    """

    role_name = "junior_engineer"
```

- [ ] **Step 4: Create `agents/senior_engineer.py`**

```python
"""
SeniorEngineerAgent: implements complex integration modules using an expensive model.
Injects all junior-tier code as context so seniors can reference utility code directly.
"""
from __future__ import annotations

from .engineer import EngineerAgent


class SeniorEngineerAgent(EngineerAgent):
    """Senior Engineer — implements integration/orchestration modules.

    Uses an expensive model. Extends run_module to inject junior code as context.
    """

    role_name = "senior_engineer"

    def run_module(
        self,
        design: str,
        module: dict,
        project_name: str = "Project",
        framework_context: str = "",
        junior_files: dict[str, str] | None = None,
    ) -> dict:
        """Implement a single senior module.

        Identical to EngineerAgent.run_module but prepends a 'Junior Code Context'
        section when junior_files are available.

        Args:
            design: Full system design markdown.
            module: Module dict with 'name', 'description', 'tier' keys.
            project_name: Project name for context.
            framework_context: Optional framework documentation.
            junior_files: Dict of {filepath: content} produced by the junior batch.

        Returns:
            Same as EngineerAgent.run_module.
        """
        augmented_design = design
        if junior_files:
            file_dump = "\n\n".join(
                f"### FILE: {path}\n```\n{content}\n```"
                for path, content in junior_files.items()
            )
            augmented_design = (
                f"## Junior Code Context\n\n"
                f"The following utility/model files have already been implemented by junior engineers. "
                f"You MUST use these files as-is — do NOT reimplement them.\n\n"
                f"{file_dump}\n\n"
                f"---\n\n"
                f"{design}"
            )
        return super().run_module(augmented_design, module, project_name, framework_context)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
python -m pytest tests/test_junior_senior_engineer.py -v
```
Expected: 7 tests PASSED

- [ ] **Step 6: Commit**

```bash
git add agents/junior_engineer.py agents/senior_engineer.py tests/test_junior_senior_engineer.py
git commit -m "feat: add JuniorEngineerAgent and SeniorEngineerAgent tier subclasses

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 5: Orchestrator — PipelineResult + config + agent instantiation

**Files:**
- Modify: `orchestrator.py` (PipelineResult dataclass, `__init__`, `from_config`)
- Modify: `config.yaml` (add team tier fields with comments)

- [ ] **Step 1: Add `junior_files` and `tier_classifications` to `PipelineResult`**

In `orchestrator.py`, find the `PipelineResult` dataclass. After the `all_files` field, add:

```python
    junior_files: dict[str, str] = field(default_factory=dict)
    tier_classifications: list[dict] = field(default_factory=list)
```

- [ ] **Step 2: Update `PipelineResult.to_dict()` to include new fields**

Find the `to_dict` method. After `"all_files": self.all_files,` add:

```python
            "junior_files": self.junior_files,
            "tier_classifications": self.tier_classifications,
```

- [ ] **Step 3: Update `PipelineResult.from_dict()` / checkpoint loading to restore new fields**

In the `from_dict` (or wherever checkpoint data is restored into `PipelineResult`), find the section that sets fields from a dict (look for `"all_files"` being read back). Add:

```python
                    "junior_files", "tier_classifications",
```

to the list of fields being restored from checkpoint. (It follows the same pattern as the existing fields — find `"all_files"` in the restore section and add the new fields alongside it.)

- [ ] **Step 4: Add new params to `Orchestrator.__init__`**

In `Orchestrator.__init__`, after `num_engineers: int = 2,` add:

```python
        num_junior_engineers: int = 5,
        num_senior_engineers: int = 2,
        junior_model: Optional[str] = None,
        senior_model: Optional[str] = None,
        tier_reviewer_model: Optional[str] = None,
        junior_quality_gate: bool = True,
        junior_test_retries: int = 3,
        tier_override_rules: list[dict] | None = None,
```

In the body of `__init__`, after `self.num_engineers = num_engineers` add:

```python
        self.num_junior_engineers = num_junior_engineers
        self.num_senior_engineers = num_senior_engineers
        self.junior_model = junior_model
        self.senior_model = senior_model
        self.tier_reviewer_model = tier_reviewer_model
        self.junior_quality_gate = junior_quality_gate
        self.junior_test_retries = junior_test_retries
        self.tier_override_rules = tier_override_rules or []
```

- [ ] **Step 5: Instantiate new agents in `Orchestrator.__init__`**

Add imports at the top of `orchestrator.py`:

```python
from agents.junior_engineer import JuniorEngineerAgent
from agents.senior_engineer import SeniorEngineerAgent
from agents.tier_reviewer import TierReviewerAgent
from agents.tier_utils import apply_tier_overrides
```

In the agent instantiation block (near `self.engineer = EngineerAgent(...)`), add:

```python
        _junior_model = self.junior_model or self.model
        _senior_model = self.senior_model or self.model
        _tier_rev_model = self.tier_reviewer_model or _junior_model

        self.junior_engineer = JuniorEngineerAgent(
            model=_junior_model,
            tool_registry=rag_registry,
            **{**agent_kwargs, **_agent_ollama_kwargs("junior_engineer")},
        )
        self.senior_engineer = SeniorEngineerAgent(
            model=_senior_model,
            tool_registry=rag_registry,
            **{**agent_kwargs, **_agent_ollama_kwargs("senior_engineer")},
        )
        self.tier_reviewer = TierReviewerAgent(
            model=_tier_rev_model,
            **{**agent_kwargs, **_agent_ollama_kwargs("tier_reviewer")},
        )
```

- [ ] **Step 6: Add new agents to memory injection loop**

Find the memory injection loop:
```python
            for agent in (self.pm, self.architect, self.engineer,
                          self.reviewer, self.qa, self.qa_planner):
```

Replace with:
```python
            for agent in (self.pm, self.architect, self.engineer,
                          self.junior_engineer, self.senior_engineer,
                          self.reviewer, self.qa, self.qa_planner):
```

- [ ] **Step 7: Add new agents to `_role_agents` dict for skills injection**

Find the `_role_agents` dict in the skills injection block:
```python
            _role_agents = {
                ...
                "engineer": self.engineer,
                ...
            }
```

Add:
```python
                "junior_engineer": self.junior_engineer,
                "senior_engineer": self.senior_engineer,
                "tier_reviewer": self.tier_reviewer,
```

- [ ] **Step 8: Update `from_config` to read new team fields**

In `from_config`, find the line:
```python
            num_engineers=team.get("num_engineers", 2),
```

After it, add:
```python
            num_junior_engineers=team.get("num_junior_engineers", 5),
            num_senior_engineers=team.get("num_senior_engineers", 2),
            junior_model=team.get("junior_model"),
            senior_model=team.get("senior_model"),
            tier_reviewer_model=team.get("tier_reviewer_model"),
            junior_quality_gate=team.get("junior_quality_gate", True),
            junior_test_retries=team.get("junior_test_retries", 3),
            tier_override_rules=team.get("tier_override_rules", []),
```

- [ ] **Step 9: Document new fields in `config.yaml`**

Find the `team:` section in `config.yaml`. After `num_engineers: 1`, add:

```yaml
  # Senior/Junior tier system
  # senior_model: gpt-4.1          # expensive model for senior engineers (defaults to model above)
  # junior_model: gpt-4.1-mini     # fast model for junior engineers (defaults to model above)
  # tier_reviewer_model: ~         # model for tier reviewer (defaults to junior_model)
  # num_senior_engineers: 2        # parallel workers for senior tier
  # num_junior_engineers: 5        # parallel workers for junior tier
  # junior_quality_gate: true      # run per-module tests on junior output before senior stage
  # junior_test_retries: 3         # retries before escalating failing junior module to senior
  # tier_override_rules:           # config-level tier overrides (highest priority)
  #   - pattern: "*/models*"
  #     tier: junior
  #   - pattern: "*/utils*"
  #     tier: junior
  #   - pattern: "*/services*"
  #     tier: senior
```

- [ ] **Step 10: Run existing tests to verify no regressions**

```bash
python -m pytest tests/ -v -k "not integration" --ignore=tests/integration 2>&1 | tail -30
```
Expected: All previously passing tests still PASS

- [ ] **Step 11: Commit**

```bash
git add orchestrator.py config.yaml
git commit -m "feat: add senior/junior engineer params and agents to orchestrator

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 6: Orchestrator — new stage methods + junior quality gate

**Files:**
- Modify: `orchestrator.py` (new `_stage_tier_review`, `_stage_junior_engineer`, `_stage_senior_engineer` methods; update `run()`)

- [ ] **Step 1: Add `_stage_tier_review` method**

Add this method to `Orchestrator` (near `_stage_engineer`):

```python
    def _stage_tier_review(self, result: PipelineResult) -> None:
        """Validate module tier assignments via TierReviewerAgent, then apply config overrides."""
        # TierReviewer validates architect assignments
        revised = self.tier_reviewer.run(result.modules)
        # Config override rules take highest priority
        final = apply_tier_overrides(revised, self.tier_override_rules)
        result.modules = final
        result.tier_classifications = final
```

- [ ] **Step 2: Add `_run_junior_module_tests` helper method**

```python
    def _run_junior_module_tests(self, files: dict[str, str], project_name: str) -> tuple[bool, str]:
        """Write module files to a temp directory and run pytest on them.

        Args:
            files: Dict of {filepath: content} for one junior module.
            project_name: Used for the temp dir name.

        Returns:
            (passed: bool, output: str)
        """
        import subprocess
        import tempfile
        import os

        test_files = {p: c for p, c in files.items() if "test" in p.lower()}
        if not test_files:
            return True, "No test files — skipping junior quality gate for this module"

        with tempfile.TemporaryDirectory(prefix=f"junior_gate_{project_name}_") as tmpdir:
            # Write all files (impl + tests) so imports resolve
            for filepath, content in files.items():
                dest = os.path.join(tmpdir, filepath)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "w") as f:
                    f.write(content)
            # Run pytest on test files only
            test_paths = [os.path.join(tmpdir, p) for p in test_files]
            proc = subprocess.run(
                ["python", "-m", "pytest"] + test_paths + ["-v", "--tb=short", "-x"],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=tmpdir,
            )
            passed = proc.returncode == 0
            output = proc.stdout + proc.stderr
        return passed, output
```

- [ ] **Step 3: Add `_stage_junior_engineer` method**

```python
    def _stage_junior_engineer(self, result: PipelineResult) -> None:
        """Implement junior-tier modules with fast model; run quality gate per module."""
        junior_modules = [m for m in result.modules if m.get("tier") == "junior"]
        if not junior_modules:
            console.print("  [dim]No junior modules to implement.[/dim]")
            return

        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in result.project_name.lower())
        project_dir = (self.workspace_dir / safe).resolve()
        framework_context = self.framework_docs_loader.load(project_dir)

        if self.target_github:
            eng_result = self.junior_engineer.run_with_github(
                result.design,
                junior_modules,
                result.project_name,
                self.target_github,
                branch_prefix=self.branch_prefix,
                issue_number=result.issue_number,
                max_workers=self.num_junior_engineers,
                framework_context=framework_context,
            )
        else:
            eng_result = self.junior_engineer.run_all_modules(
                result.design,
                junior_modules,
                result.project_name,
                max_workers=self.num_junior_engineers,
                framework_context=framework_context,
            )

        junior_files: dict[str, str] = eng_result["all_files"]
        escalated: list[dict] = []

        if self.junior_quality_gate:
            # Per-module test+retry loop
            for mod_result in eng_result["modules"]:
                mod_files = mod_result["files"]
                mod_name = mod_result["module_name"]
                passed, output = self._run_junior_module_tests(mod_files, result.project_name)

                retries = 0
                while not passed and retries < self.junior_test_retries:
                    retries += 1
                    console.print(
                        f"  🔄 [yellow]Junior gate retry {retries}/{self.junior_test_retries} "
                        f"for {mod_name}[/yellow]"
                    )
                    # Ask junior engineer to fix failures
                    fixed = self.junior_engineer.fix_failures(
                        failure_output=output,
                        all_files=mod_files,
                        design=result.design,
                        project_name=result.project_name,
                    )
                    mod_files.update(fixed)
                    junior_files.update(fixed)
                    passed, output = self._run_junior_module_tests(mod_files, result.project_name)

                if not passed:
                    # Escalate to senior batch
                    console.print(
                        f"  ⬆️  [yellow]Escalating {mod_name} to senior tier "
                        f"(failed after {self.junior_test_retries} retries)[/yellow]"
                    )
                    # Find original module dict and re-tier it
                    for m in result.modules:
                        if m["name"] == mod_name:
                            m["tier"] = "senior"
                            escalated.append(m)
                            break
                    # Remove escalated files from junior_files
                    for path in list(mod_files.keys()):
                        junior_files.pop(path, None)

        result.junior_files = junior_files
        self._save_files_locally(junior_files, result.project_name)

        if escalated:
            console.print(
                f"  ⬆️  [dim]{len(escalated)} module(s) escalated to senior tier.[/dim]"
            )
```

- [ ] **Step 4: Add `_stage_senior_engineer` method**

```python
    def _stage_senior_engineer(self, result: PipelineResult) -> None:
        """Implement senior-tier modules with expensive model; inject junior code as context."""
        senior_modules = [m for m in result.modules if m.get("tier") == "senior"]
        if not senior_modules:
            console.print("  [dim]No senior modules to implement.[/dim]")
            result.all_files = dict(result.junior_files)
            return

        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in result.project_name.lower())
        project_dir = (self.workspace_dir / safe).resolve()
        framework_context = self.framework_docs_loader.load(project_dir)

        # Senior engineer needs junior files to inject as context per module
        # Override run_all_modules to pass junior_files to each run_module call
        from concurrent.futures import ThreadPoolExecutor

        senior_results = []
        with ThreadPoolExecutor(max_workers=self.num_senior_engineers) as executor:
            futures = [
                executor.submit(
                    self.senior_engineer.run_module,
                    result.design,
                    mod,
                    result.project_name,
                    framework_context,
                    result.junior_files,
                )
                for mod in senior_modules
            ]
            for future in futures:
                senior_results.append(future.result())

        senior_files: dict[str, str] = {}
        for sr in senior_results:
            senior_files.update(sr["files"])

        # Merge junior + senior into all_files
        result.all_files = {**result.junior_files, **senior_files}
        self._save_files_locally(result.all_files, result.project_name)

        if self.target_github and result.branch:
            # Commit senior files to the same branch created by junior batch
            from github_client import GitHubClient
            for filepath, content in senior_files.items():
                self.target_github.create_or_update_file(
                    filepath,
                    content,
                    branch=result.branch,
                    message=f"feat({result.project_name}): implement senior module files",
                )
```

- [ ] **Step 5: Wire new stages into `run()` — replace the existing engineer stage block**

In the `run()` method, find the existing engineer stage block:

```python
        if "engineer" not in result.completed_stages:
            self._run_stage(
                f"💻 Engineers (×{self.num_engineers})",
                f"Implementing {len(result.modules)} module(s) in parallel...",
                result,
                lambda: self._stage_engineer(result),
            )
            if result.errors:
                self._save_checkpoint(result)
                return self._finish(result, start_time)
            result.completed_stages.append("engineer")
            self._save_checkpoint(result)
        else:
            console.print("  ⏭️  [dim]💻 Engineers — skipped (checkpoint)[/dim]")
```

Replace with:

```python
        # ── Backward-compat: old checkpoints that completed "engineer" skip both tiers ──
        if "engineer" in result.completed_stages:
            console.print("  ⏭️  [dim]💻 Engineers — skipped (checkpoint)[/dim]")
        else:
            # Stage 3a: Tier review
            if "tier_review" not in result.completed_stages:
                self._run_stage(
                    "🏷️  Tier Review",
                    f"Classifying {len(result.modules)} module(s) into junior/senior tiers...",
                    result,
                    lambda: self._stage_tier_review(result),
                )
                if result.errors:
                    self._save_checkpoint(result)
                    return self._finish(result, start_time)
                result.completed_stages.append("tier_review")
                self._save_checkpoint(result)
            else:
                console.print("  ⏭️  [dim]🏷️  Tier Review — skipped (checkpoint)[/dim]")

            junior_count = sum(1 for m in result.modules if m.get("tier") == "junior")
            senior_count = len(result.modules) - junior_count

            # Stage 3b: Junior batch
            if "junior_engineer" not in result.completed_stages:
                self._run_stage(
                    f"🟢 Junior Engineers (×{self.num_junior_engineers})",
                    f"Implementing {junior_count} junior module(s)...",
                    result,
                    lambda: self._stage_junior_engineer(result),
                )
                if result.errors:
                    self._save_checkpoint(result)
                    return self._finish(result, start_time)
                result.completed_stages.append("junior_engineer")
                self._save_checkpoint(result)
            else:
                console.print("  ⏭️  [dim]🟢 Junior Engineers — skipped (checkpoint)[/dim]")

            # Stage 3c: Senior batch
            if "senior_engineer" not in result.completed_stages:
                self._run_stage(
                    f"🔵 Senior Engineers (×{self.num_senior_engineers})",
                    f"Implementing {senior_count} senior module(s) with junior context...",
                    result,
                    lambda: self._stage_senior_engineer(result),
                )
                if result.errors:
                    self._save_checkpoint(result)
                    return self._finish(result, start_time)
                result.completed_stages.append("senior_engineer")
                # Also mark "engineer" for backward compat with downstream checkpoint checks
                result.completed_stages.append("engineer")
                self._save_checkpoint(result)
            else:
                console.print("  ⏭️  [dim]🔵 Senior Engineers — skipped (checkpoint)[/dim]")
```

- [ ] **Step 6: Run existing tests to verify no regressions**

```bash
python -m pytest tests/ -v -k "not integration" --ignore=tests/integration 2>&1 | tail -30
```
Expected: All previously passing tests still PASS

- [ ] **Step 7: Commit**

```bash
git add orchestrator.py
git commit -m "feat: wire senior/junior engineer stages into orchestrator pipeline

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 7: CLI flags

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add `--junior-engineers` and `--senior-engineers` flags**

In `main.py`, find the existing `--engineers` argument:

```python
        "--engineers",
        ...
        help="Number of parallel engineer agents (default: 2). Overrides config.yaml.",
```

After it, add:

```python
    parser.add_argument(
        "--junior-engineers",
        type=int,
        default=None,
        metavar="N",
        help="Number of parallel junior engineer agents. Overrides config.yaml num_junior_engineers.",
    )
    parser.add_argument(
        "--senior-engineers",
        type=int,
        default=None,
        metavar="N",
        help="Number of parallel senior engineer agents. Overrides config.yaml num_senior_engineers.",
    )
```

- [ ] **Step 2: Apply the new flags when building the orchestrator**

Find the section where `args.engineers` is applied (near `orch.num_engineers = args.engineers`):

```python
        if args.engineers:
            orch.num_engineers = args.engineers
```

After it, add:

```python
        if args.junior_engineers:
            orch.num_junior_engineers = args.junior_engineers
        elif args.engineers:
            # --engineers shorthand: junior gets 2× senior
            orch.num_junior_engineers = args.engineers * 2
            orch.num_senior_engineers = args.engineers

        if args.senior_engineers:
            orch.num_senior_engineers = args.senior_engineers
```

- [ ] **Step 3: Verify the CLI help text**

```bash
python main.py --help | grep -A2 "engineers"
```
Expected: All three flags listed (`--engineers`, `--junior-engineers`, `--senior-engineers`)

- [ ] **Step 4: Run existing tests**

```bash
python -m pytest tests/ -v -k "not integration" --ignore=tests/integration 2>&1 | tail -20
```
Expected: All previously passing tests PASS

- [ ] **Step 5: Commit**

```bash
git add main.py
git commit -m "feat: add --junior-engineers and --senior-engineers CLI flags

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 8: Smoke test end-to-end

**Files:**
- No new files — manual verification

- [ ] **Step 1: Run all unit tests**

```bash
python -m pytest tests/ -v -k "not integration" --ignore=tests/integration 2>&1 | tail -40
```
Expected: All tests PASS including new test files:
- `tests/test_tier_utils.py` — 6 tests
- `tests/test_architect_tier.py` — 4 tests
- `tests/test_tier_reviewer.py` — 4 tests
- `tests/test_junior_senior_engineer.py` — 7 tests

- [ ] **Step 2: Dry-run import check**

```bash
cd /home/wanleung/Projects/ai-software-house
python -c "
from agents.tier_reviewer import TierReviewerAgent
from agents.junior_engineer import JuniorEngineerAgent
from agents.senior_engineer import SeniorEngineerAgent
from agents.tier_utils import apply_tier_overrides
from orchestrator import Orchestrator
print('All imports OK')
"
```
Expected: `All imports OK`

- [ ] **Step 3: Verify CLI flags work**

```bash
python main.py --help | grep -E "junior|senior|engineers"
```
Expected output includes:
```
  --engineers N
  --junior-engineers N
  --senior-engineers N
```

- [ ] **Step 4: Final commit — update public repo**

```bash
cd /home/wanleung/Projects/ai-software-house
git log --oneline -8
```

Then sync to public repo:
```bash
cd /home/wanleung/Projects/ai-dev-team
git remote add upstream /home/wanleung/Projects/ai-software-house 2>/dev/null || true
git fetch upstream master
git merge upstream/master --no-edit
git push origin master
```
