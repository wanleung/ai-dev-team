# T4-B: Pipeline Correctness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three correctness gaps: token estimation hardcoded to OpenAI, loop verdict not validated against known values, and downstream stages running blindly after an upstream circuit breaker opens.

**Architecture:** Add `model` param to `estimate_tokens()` with per-family dispatch; add `VALID_VERDICTS` whitelist check at pipeline YAML load time; add `is_critical` flag to `PipelineStage` and a cascade check at the top of `_run_stage()`.

**Tech Stack:** Python 3.11+, `pytest`, `agents/token_ledger.py`, `orchestrator.py`

---

## File Map

| File | Change |
|------|--------|
| `agents/token_ledger.py` | Add `model: str = ""` param to `estimate_tokens()`; dispatch by model family |
| `orchestrator.py` | Add `VALID_VERDICTS` check in `_load_pipeline_yaml()`; add `is_critical` to `PipelineStage`; mark `pm`/`architect` critical; add `_critical_cb_open()` helper; call it at top of `_run_stage()` |
| `tests/test_token_ledger.py` | Add 4 new tests for model-aware estimation |
| `tests/test_pipeline_yaml_validation.py` | Add 2 tests for verdict validation |
| `tests/test_cb_cascade.py` | New: 3 tests for CB cascade skip behaviour |

---

### Task 1: Model-aware token estimation

**Files:**
- Modify: `agents/token_ledger.py:252-268` (`estimate_tokens` function)
- Modify: `tests/test_token_ledger.py` (add 4 tests)

- [ ] **Step 1: Write failing tests**

Add to `tests/test_token_ledger.py`:

```python
from agents.token_ledger import estimate_tokens


def test_openai_model_uses_tiktoken():
    """GPT model should use tiktoken encoding, returning integer token counts."""
    messages = [{"role": "user", "content": "Hello world"}]
    prompt_tok, comp_tok = estimate_tokens(messages, "Hi there", model="gpt-4o")
    # tiktoken gives precise counts; char-based would give different values
    assert isinstance(prompt_tok, int) and prompt_tok > 0
    assert isinstance(comp_tok, int) and comp_tok > 0


def test_claude_model_uses_char_estimate():
    """Claude model should use char-based estimation (~3.5 chars/token)."""
    messages = [{"role": "user", "content": "A" * 350}]  # 350 chars → ~100 tokens
    prompt_tok, _ = estimate_tokens(messages, "", model="claude-3-opus")
    # char // 3.5 ≈ 100; tiktoken would give ~88
    assert 90 <= prompt_tok <= 110


def test_gemini_model_uses_char_estimate():
    """Gemini model should use char-based estimation (~4 chars/token)."""
    messages = [{"role": "user", "content": "B" * 400}]  # 400 chars → ~100 tokens
    prompt_tok, _ = estimate_tokens(messages, "", model="gemini-pro")
    assert 90 <= prompt_tok <= 110


def test_unknown_model_uses_char_fallback():
    """Unknown/Ollama model should use safe char-based fallback."""
    messages = [{"role": "user", "content": "C" * 400}]
    prompt_tok, _ = estimate_tokens(messages, "", model="llama3:70b")
    # char // 4 = 100
    assert 90 <= prompt_tok <= 110


def test_no_model_arg_still_works():
    """Calling estimate_tokens without model arg must still return counts (backward compat)."""
    messages = [{"role": "user", "content": "Hello"}]
    prompt_tok, comp_tok = estimate_tokens(messages, "Hi")
    assert prompt_tok >= 0 and comp_tok >= 0
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python3 -m pytest tests/test_token_ledger.py -v -k "claude or gemini or unknown or no_model"
```

Expected: failures because `estimate_tokens` does not accept `model` parameter.

- [ ] **Step 3: Update `estimate_tokens()` in `agents/token_ledger.py`**

Replace the function at line ~252:

```python
def estimate_tokens(
    messages: list[dict],
    reply: str,
    model: str = "",
) -> tuple[int, int]:
    """Estimate prompt + completion token counts.

    Dispatches by model family:
    - OpenAI (gpt-*, text-*): uses tiktoken cl100k_base
    - Anthropic (claude-*): char // 3.5 approximation
    - Google (gemini-*): char // 4 approximation
    - All others (Ollama, unknown): char // 4 safe fallback

    Used as a fallback when response.usage is not available (streaming calls).
    Returns (prompt_tokens, completion_tokens).

    Args:
        messages: List of message dicts with 'content' keys.
        reply: The completion text.
        model: Optional model identifier string for dispatch. Defaults to OpenAI encoding.
    """
    model_lower = model.lower()

    # OpenAI models: use tiktoken for precise counts
    if not model_lower or any(model_lower.startswith(p) for p in ("gpt-", "text-", "o1", "o3")):
        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            prompt_text = " ".join(
                m.get("content", "") or "" for m in messages if isinstance(m.get("content"), str)
            )
            return len(enc.encode(prompt_text)), len(enc.encode(reply))
        except Exception:
            pass  # fall through to char-based

    # Extract prompt text for char-based estimation
    prompt_text = " ".join(
        m.get("content", "") or "" for m in messages if isinstance(m.get("content"), str)
    )

    # Anthropic Claude: ~3.5 chars per token
    if "claude" in model_lower:
        divisor = 3.5
    else:
        # Gemini, Ollama, and all other models: ~4 chars per token (conservative)
        divisor = 4.0

    return (
        max(0, int(len(prompt_text) / divisor)),
        max(0, int(len(reply) / divisor)),
    )
```

- [ ] **Step 4: Find and update call sites in `orchestrator.py`**

Find existing calls:
```bash
grep -n "estimate_tokens(" orchestrator.py
```

For each call site, add `model=` if the backend model is available in scope. Typical pattern:

```python
# Before:
prompt_tok, comp_tok = estimate_tokens(messages, reply)

# After (if backend/model name is available as self._model or similar):
prompt_tok, comp_tok = estimate_tokens(messages, reply, model=getattr(self, "_model", ""))
```

If no model is available in the call site scope, leaving `model=""` is safe — it defaults to OpenAI tiktoken, preserving existing behaviour.

- [ ] **Step 5: Run tests — must pass**

```bash
python3 -m pytest tests/test_token_ledger.py -v
```

Expected: all token ledger tests PASS including the 5 new ones.

- [ ] **Step 6: Commit**

```bash
git add agents/token_ledger.py tests/test_token_ledger.py
git commit -m "feat(tokens): model-aware token estimation in estimate_tokens()

Dispatches by model family:
- OpenAI (gpt-*, text-*): tiktoken cl100k_base (unchanged)
- Claude: chars // 3.5
- Gemini + others: chars // 4.0
Backward compatible: model='' defaults to OpenAI tiktoken path.

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 2: Loop verdict validation

**Files:**
- Modify: `orchestrator.py` (~line 1429, `_load_pipeline_yaml()`)
- Modify: `tests/test_pipeline_yaml_validation.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_pipeline_yaml_validation.py` (create the file if it doesn't exist):

```python
import pytest
import yaml
import tempfile
from pathlib import Path


def _write_pipeline_yaml(tmp_path: Path, until: str) -> Path:
    content = {
        "stages": [
            {
                "loop": {
                    "stages": ["pm", "pm_reviewer"],
                    "until": until,
                    "max": 3,
                }
            }
        ]
    }
    p = tmp_path / "pipeline.yaml"
    p.write_text(yaml.dump(content))
    return p


def test_invalid_loop_until_raises_config_error(tmp_path):
    """A typo in loop 'until' must raise ConfigurationError at load time."""
    from orchestrator import Orchestrator
    pipeline_file = _write_pipeline_yaml(tmp_path, until="APPROVD")  # typo
    with pytest.raises(Exception, match="(?i)until|verdict|APPROVD"):
        Orchestrator._load_pipeline_yaml(pipeline_file)


def test_valid_loop_until_approved_passes(tmp_path):
    """loop until: APPROVED must load without error."""
    from orchestrator import Orchestrator
    pipeline_file = _write_pipeline_yaml(tmp_path, until="APPROVED")
    # Should not raise
    result = Orchestrator._load_pipeline_yaml(pipeline_file)
    assert result is not None


def test_valid_loop_until_needs_revision_passes(tmp_path):
    """loop until: NEEDS_REVISION must load without error."""
    from orchestrator import Orchestrator
    pipeline_file = _write_pipeline_yaml(tmp_path, until="NEEDS_REVISION")
    result = Orchestrator._load_pipeline_yaml(pipeline_file)
    assert result is not None
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python3 -m pytest tests/test_pipeline_yaml_validation.py -v
```

Expected: `test_invalid_loop_until_raises_config_error` fails (no error raised for typo).

- [ ] **Step 3: Add verdict whitelist check in `_load_pipeline_yaml()`**

Find the existing `loop['until']` validation in `_load_pipeline_yaml()` (around line 1425-1430). It currently checks for non-empty string. Add whitelist check immediately after:

```python
VALID_LOOP_VERDICTS = {"APPROVED", "NEEDS_REVISION"}

# Existing check (non-empty):
if not loop.get("until"):
    raise ConfigurationError(
        "pipeline.yaml loop block missing 'until' verdict "
        "(e.g. 'APPROVED'). Got: {!r}".format(loop.get("until"))
    )

# NEW: whitelist check
until_val = str(loop["until"]).strip().upper()
if until_val not in VALID_LOOP_VERDICTS:
    raise ConfigurationError(
        f"pipeline.yaml loop 'until' must be one of {sorted(VALID_LOOP_VERDICTS)}. "
        f"Got: {loop['until']!r}"
    )
loop["until"] = until_val  # normalise to uppercase
```

Place `VALID_LOOP_VERDICTS` as a module-level constant near the top of `orchestrator.py` (after imports).

- [ ] **Step 4: Run tests — must pass**

```bash
python3 -m pytest tests/test_pipeline_yaml_validation.py -v
```

Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add orchestrator.py tests/test_pipeline_yaml_validation.py
git commit -m "fix(config): validate loop 'until' verdict against whitelist at load time

Raises ConfigurationError immediately for typos like 'APPROVD' instead of
silently looping forever. Valid values: APPROVED, NEEDS_REVISION.
Normalises to uppercase on load.

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 3: Circuit breaker cascade for critical stages

**Files:**
- Modify: `orchestrator.py` (`PipelineStage` dataclass, `_make_stage_registry()`, `_run_stage()`)
- Create: `tests/test_cb_cascade.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_cb_cascade.py
from unittest.mock import MagicMock, patch
import pytest


def _make_stage(name="pm", is_critical=True):
    from orchestrator import PipelineStage
    return PipelineStage(
        name=name,
        label=f"🔧 {name}",
        description=f"Running {name}",
        checkpoint_key=name,
        fn=lambda r: None,
        is_critical=is_critical,
    )


def test_pipeline_stage_has_is_critical_field():
    """PipelineStage dataclass must have is_critical field defaulting to False."""
    from orchestrator import PipelineStage
    stage = PipelineStage(
        name="test", label="test", description="test", checkpoint_key="test", fn=lambda r: None
    )
    assert hasattr(stage, "is_critical")
    assert stage.is_critical is False


def test_pm_and_architect_marked_critical():
    """pm and architect stages must be marked is_critical=True in stage registry."""
    from orchestrator import Orchestrator
    from orchestrator import PipelineResult
    config = {
        "llm": {"backend": "openai", "model": "gpt-4o", "api_key": "test"},
        "github": {"token": "gh_test", "owner": "o", "repo": "r"},
    }
    orch = Orchestrator(config=config)
    result = PipelineResult(requirement="test")
    registry = orch._make_stage_registry(result)
    pm_stage = next((s for s in registry if s.name == "pm"), None)
    arch_stage = next((s for s in registry if s.name == "architect"), None)
    assert pm_stage is not None and pm_stage.is_critical is True
    assert arch_stage is not None and arch_stage.is_critical is True


def test_downstream_stage_skipped_when_critical_cb_open():
    """When a critical stage CB is open, non-critical stages must be skipped."""
    from orchestrator import Orchestrator, PipelineResult
    config = {
        "llm": {"backend": "openai", "model": "gpt-4o", "api_key": "test"},
        "github": {"token": "gh_test", "owner": "o", "repo": "r"},
    }
    orch = Orchestrator(config=config)
    result = PipelineResult(requirement="test")

    # Mock _critical_cb_open to return "pm" (simulating open CB)
    with patch.object(orch, "_critical_cb_open", return_value="pm"):
        orch._run_stage("⚙️ engineer", "Running engineer", result, lambda r: None)

    # Engineer stage must have recorded a cascade skip error
    assert any("cascade" in (e.stage or "").lower() or "pm" in e.message.lower()
               for e in result.errors)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python3 -m pytest tests/test_cb_cascade.py -v
```

Expected: `test_pipeline_stage_has_is_critical_field` fails with `AttributeError`.

- [ ] **Step 3: Add `is_critical` to `PipelineStage` dataclass**

Find `class PipelineStage` (~line 445). Add field after `required_output_fields`:

```python
is_critical: bool = False
"""When True, this stage's circuit breaker state is checked by downstream stages.
Downstream non-critical stages are skipped if any critical CB is open."""
```

- [ ] **Step 4: Mark `pm` and `architect` as critical in `_make_stage_registry()`**

Find the `"pm"` and `"architect"` PipelineStage entries in `_make_stage_registry()`. Add `is_critical=True` to each:

```python
PipelineStage(
    name="pm",
    label="📋 Product Manager",
    # ... existing fields ...,
    is_critical=True,
),
PipelineStage(
    name="architect",
    label="🏗️ Architect",
    # ... existing fields ...,
    is_critical=True,
),
```

- [ ] **Step 5: Add `_critical_cb_open()` helper method to `Orchestrator`**

Add this method near other helper methods:

```python
def _critical_cb_open(self) -> str | None:
    """Return the name of the first critical stage whose circuit breaker is open, or None."""
    from core.circuit_breaker_registry import get_registry
    registry = get_registry()
    # Check well-known critical stage names
    for name in ("pm", "architect"):
        try:
            cb = registry.get_or_create("agent", name)
            if cb.state == "open":
                return name
        except Exception:
            pass
    return None
```

- [ ] **Step 6: Add cascade check at top of `_run_stage()`**

Find `def _run_stage(self, label, description, result, fn` (~line 3518). At the very top of the method body (before any other logic), add:

```python
# CB cascade: skip non-critical stages if a critical upstream CB is open
open_stage = self._critical_cb_open()
if open_stage:
    error_msg = (
        f"Stage skipped: upstream '{open_stage}' circuit breaker is open "
        f"(cb_cascade). Fix the {open_stage} agent failures first."
    )
    result.add_error(
        _PipelineError(code="CB_CASCADE", stage="cb_cascade", message=error_msg, severity="error")
    )
    return
```

- [ ] **Step 7: Run tests — must pass**

```bash
python3 -m pytest tests/test_cb_cascade.py -v
```

Expected: 3 PASSED.

- [ ] **Step 8: Full suite — no regressions**

```bash
python3 -m pytest tests/ -x -q 2>/dev/null | tail -5
```

- [ ] **Step 9: Commit and push**

```bash
git add orchestrator.py tests/test_cb_cascade.py
git commit -m "feat(resilience): CB cascade — skip downstream stages when critical CB open

- Add is_critical: bool = False field to PipelineStage
- Mark pm and architect stages as is_critical=True
- Add _critical_cb_open() helper checking well-known critical stage CBs
- _run_stage() now returns early with CB_CASCADE error when a critical
  upstream CB is open, preventing confusing downstream failures

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
git push origin t4-b-pipeline-correctness
```

---

### Task 4: Create PR

- [ ] **Create PR**

```bash
gh pr create \
  --title "feat(correctness): T4-B — model-aware tokens, loop verdict validation, CB cascade" \
  --body "## Summary

Three pipeline correctness improvements:

### 1. Model-aware token estimation
\`estimate_tokens()\` now accepts \`model: str = ''\` and dispatches:
- OpenAI (gpt-*, text-*): tiktoken cl100k\_base (unchanged)
- Claude: chars // 3.5
- Gemini + others/Ollama: chars // 4.0
Budget tracking now accurate across all backends.

### 2. Loop verdict validation
\`_load_pipeline_yaml()\` now checks \`loop.until\` against \`VALID_LOOP_VERDICTS = {\"APPROVED\", \"NEEDS_REVISION\"}\`. Typos raise \`ConfigurationError\` immediately at load time rather than silently looping forever.

### 3. Circuit breaker cascade
Added \`is_critical: bool\` to \`PipelineStage\`. \`pm\` and \`architect\` marked critical. \`_run_stage()\` checks \`_critical_cb_open()\` at entry — non-critical stages are skipped with a \`CB_CASCADE\` error when a critical upstream CB is open.

## Tests
- \`tests/test_token_ledger.py\` — 5 new tests (OpenAI/Claude/Gemini/unknown/no-arg)
- \`tests/test_pipeline_yaml_validation.py\` — 3 tests (invalid/valid verdicts)
- \`tests/test_cb_cascade.py\` (new) — 3 tests (is_critical field, critical stages marked, cascade skip)

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>" \
  --base master
```
