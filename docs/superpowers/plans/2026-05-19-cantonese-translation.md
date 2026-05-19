# Cantonese Translation Stages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `translate_cantonese` and `translate_zh_traditional` pipeline stages so the press team publishes Written Cantonese and Traditional Chinese translations alongside every English article, committed as separate `.md` files in the same PR.

**Architecture:** A single `TranslatorAgent(BaseAgent)` is called twice by a shared `_stage_translate()` method in the orchestrator, parameterised by `target_language`. Two new `PipelineResult` fields (`article_zh_hk`, `article_zh_tw`) store the outputs. `_stage_news_article_pr()` is updated to include translation files when present.

**Tech Stack:** Python, ai-software-house orchestrator pattern (BaseAgent subclass + PipelineStage registry), YAML frontmatter (PyYAML), pytest

---

## File Map

| Action | File | What changes |
|--------|------|-------------|
| **Create** | `agents/translator.py` | `TranslatorAgent` class |
| **Create** | `roles/translator.md` | Translator system prompt |
| **Modify** | `orchestrator.py` | Add fields to `PipelineResult`; import + instantiate `TranslatorAgent`; add `_stage_translate()`; register two new stages; update `_stage_news_article_pr()` |
| **Create** | `tests/test_translator.py` | Unit tests for `TranslatorAgent` |
| **Modify** | `tests/test_news_stages.py` | Tests for new stages + updated PR stage |
| **Modify** | `config.local.yaml` | Add `translator` LLM override |
| **Modify** | `ai-it-press/pipelines/news-article.yaml` | Add two translation stages |

---

## Task 1: TranslatorAgent + role file

**Files:**
- Create: `agents/translator.py`
- Create: `roles/translator.md`

- [ ] **Step 1: Write the failing test**

Create `tests/test_translator.py`:

```python
"""Tests for TranslatorAgent."""
from __future__ import annotations
from unittest.mock import MagicMock, patch
import pytest


def _make_agent(cls):
    mock_llm = MagicMock()
    mock_llm.chat.return_value = "mock output"
    agent = cls.__new__(cls)
    agent.system_prompt = "You are a translator."
    agent._llm = mock_llm
    agent.role_name = "translator"
    agent.max_api_retries = 1
    agent.retry_delay = 0
    agent.inter_call_delay = 0
    agent._token_ledger = None
    return agent


class TestTranslatorAgent:
    def test_run_returns_translated_article(self):
        from agents.translator import TranslatorAgent
        agent = _make_agent(TranslatorAgent)
        with patch.object(agent, "call", return_value="---\ntitle: 測試\n---\n\n內容。"):
            result = agent.run("---\ntitle: Test\n---\n\nContent.", target_language="cantonese")
        assert "translated_article" in result
        assert result["translated_article"] == "---\ntitle: 測試\n---\n\n內容。"

    def test_run_injects_target_language_in_prompt(self):
        from agents.translator import TranslatorAgent
        agent = _make_agent(TranslatorAgent)
        captured = {}
        def capture(prompt):
            captured["prompt"] = prompt
            return "# 翻譯"
        with patch.object(agent, "call", side_effect=capture):
            agent.run("# Article\n\nBody.", target_language="traditional_chinese")
        assert "traditional_chinese" in captured["prompt"].lower() or "traditional" in captured["prompt"].lower()

    def test_run_injects_article_in_prompt(self):
        from agents.translator import TranslatorAgent
        agent = _make_agent(TranslatorAgent)
        captured = {}
        def capture(prompt):
            captured["prompt"] = prompt
            return "# 翻譯"
        with patch.object(agent, "call", side_effect=capture):
            agent.run("# My English Article\n\nSome content.", target_language="cantonese")
        assert "My English Article" in captured["prompt"]

    def test_run_both_language_targets(self):
        from agents.translator import TranslatorAgent
        agent = _make_agent(TranslatorAgent)
        for lang in ("cantonese", "traditional_chinese"):
            with patch.object(agent, "call", return_value="# 翻譯"):
                result = agent.run("# Article", target_language=lang)
            assert "translated_article" in result
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/wanleung/Projects/ai-software-house
python3 -m pytest tests/test_translator.py -v
```

Expected: `ModuleNotFoundError: No module named 'agents.translator'`

- [ ] **Step 3: Create `roles/translator.md`**

```markdown
# Translator

You are a professional technology news translator.
Your job is to translate English technology news articles into Chinese while preserving journalistic quality.

## Critical rules
- Translate EVERYTHING: YAML frontmatter (title, tags) AND the article body
- Keep `source_url` and `author` fields UNCHANGED — do not translate them
- Preserve all markdown formatting (headings, bold, links, code blocks)
- Preserve the YAML frontmatter structure exactly — only translate the values
- Do NOT add commentary, notes, or meta-text — output only the translated article

## Language targets

### cantonese
Write in **Written Cantonese** (書面粵語 / 廣東話書面語) as used in Hong Kong informal press.
- Use Cantonese vocabulary and particles (e.g. 係、唔、咁、嘅、喺、而家)
- Natural, accessible tone — like a Hong Kong tech blog or online news
- Translate tags into Cantonese equivalents where natural

### traditional_chinese
Write in **Formal Traditional Chinese** (正式繁體中文) as used in Taiwan and Hong Kong broadsheet press.
- Use formal written Chinese register — no colloquialisms
- Follow Taiwan/HK press style (e.g. 台灣蘋果日報、香港明報)
- Translate tags into formal Traditional Chinese

## Output format
Output the complete translated article only — full YAML frontmatter followed by the markdown body.
Do not add any preamble or meta-commentary.
```

- [ ] **Step 4: Create `agents/translator.py`**

```python
"""
TranslatorAgent: translates a finalised news article into a target language.

Input:  article (str) — full markdown with YAML frontmatter (English)
        target_language (str) — "cantonese" | "traditional_chinese"
Output: dict with 'translated_article' (str)
"""
from __future__ import annotations

from .base_agent import BaseAgent


class TranslatorAgent(BaseAgent):
    """Translate a news article into Written Cantonese or Traditional Chinese."""

    role_name = "translator"

    def run(self, article: str, target_language: str) -> dict:
        """Translate the article.

        Args:
            article: Full markdown article with YAML frontmatter (English source).
            target_language: "cantonese" for Written Cantonese (zh-hk),
                             "traditional_chinese" for Formal Traditional Chinese (zh-tw).

        Returns:
            dict with key:
                - translated_article (str): Full translated markdown with frontmatter
        """
        prompt = (
            f"Translate the following news article to {target_language}.\n\n"
            f"Follow your role instructions exactly.\n\n"
            f"---\n{article}\n---\n\n"
            f"Output the translated article only."
        )
        translated_article = self.call(prompt)
        return {"translated_article": translated_article}
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_translator.py -v
```

Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add agents/translator.py roles/translator.md tests/test_translator.py
git commit -m "feat: add TranslatorAgent with Written Cantonese and Traditional Chinese support"
```

---

## Task 2: PipelineResult new fields

**Files:**
- Modify: `orchestrator.py` (around line 415 — `article: str = ""`)
- Modify: `tests/test_news_stages.py`

- [ ] **Step 1: Write the failing tests**

Add to the bottom of `tests/test_news_stages.py`:

```python
def test_pipeline_result_has_article_zh_hk():
    r = PipelineResult(requirement="test")
    assert hasattr(r, "article_zh_hk")
    assert r.article_zh_hk == ""


def test_pipeline_result_has_article_zh_tw():
    r = PipelineResult(requirement="test")
    assert hasattr(r, "article_zh_tw")
    assert r.article_zh_tw == ""


def test_pipeline_result_zh_fields_in_to_dict():
    r = PipelineResult(requirement="test")
    r.article_zh_hk = "# 粵語文章"
    r.article_zh_tw = "# 繁體文章"
    d = r.to_dict()
    assert d["article_zh_hk"] == "# 粵語文章"
    assert d["article_zh_tw"] == "# 繁體文章"


def test_pipeline_result_zh_fields_from_dict():
    r = PipelineResult.from_dict({
        "requirement": "test",
        "article_zh_hk": "# 粵語",
        "article_zh_tw": "# 繁體",
    })
    assert r.article_zh_hk == "# 粵語"
    assert r.article_zh_tw == "# 繁體"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_news_stages.py::test_pipeline_result_has_article_zh_hk tests/test_news_stages.py::test_pipeline_result_has_article_zh_tw tests/test_news_stages.py::test_pipeline_result_zh_fields_in_to_dict tests/test_news_stages.py::test_pipeline_result_zh_fields_from_dict -v
```

Expected: FAIL with `AttributeError`

- [ ] **Step 3: Add fields to `PipelineResult` in `orchestrator.py`**

Find the line `article: str = ""` (around line 416) and add after it:

```python
    article_zh_hk: str = ""  # Written Cantonese translation
    article_zh_tw: str = ""  # Formal Traditional Chinese translation
```

(The `to_dict()` and `from_dict()` methods use `dataclasses.asdict()` / field introspection so they pick up new fields automatically — no further changes needed there.)

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_news_stages.py -v
```

Expected: all pass (including the 4 new tests)

- [ ] **Step 5: Commit**

```bash
git add orchestrator.py tests/test_news_stages.py
git commit -m "feat: add article_zh_hk and article_zh_tw fields to PipelineResult"
```

---

## Task 3: Orchestrator — import, instantiate, stages

**Files:**
- Modify: `orchestrator.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_news_stages.py`:

```python
def test_translate_stages_registered():
    """translate_cantonese and translate_zh_traditional must be in the stage registry."""
    from orchestrator import Orchestrator
    from pathlib import Path
    import tempfile
    orch = Orchestrator.__new__(Orchestrator)
    orch.model = "gpt-4.1"
    orch.model_overrides = {}
    orch._stage_timeouts = {}
    with patch.object(Orchestrator, "_make_backend", return_value=MagicMock()), \
         patch.object(Orchestrator, "_make_backend_from_model", return_value=MagicMock()):
        orch.news_writer = MagicMock()
        orch.news_editor = MagicMock()
        orch.translator = MagicMock()
        with tempfile.TemporaryDirectory() as tmpdir:
            orch._discussions_dir = Path(tmpdir)
            registry = orch._make_stage_registry()
    assert "translate_cantonese" in registry
    assert "translate_zh_traditional" in registry


def test_stage_translate_sets_result_field():
    from orchestrator import PipelineResult, Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    mock_agent = MagicMock()
    mock_agent.run.return_value = {"translated_article": "# 粵語文章\n\n內容。"}
    orch.translator = mock_agent

    result = PipelineResult(requirement="Test")
    result.article = "# English Article\n\nContent."
    orch._stage_translate(result, "cantonese", "article_zh_hk")
    assert result.article_zh_hk == "# 粵語文章\n\n內容。"
    mock_agent.run.assert_called_once_with("# English Article\n\nContent.", target_language="cantonese")


def test_stage_translate_uses_article_draft_when_no_article():
    from orchestrator import PipelineResult, Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    mock_agent = MagicMock()
    mock_agent.run.return_value = {"translated_article": "# 草稿翻譯"}
    orch.translator = mock_agent

    result = PipelineResult(requirement="Test")
    result.article = ""
    result.article_draft = "# Draft Article"
    orch._stage_translate(result, "traditional_chinese", "article_zh_tw")
    assert result.article_zh_tw == "# 草稿翻譯"


def test_stage_translate_raises_when_no_source():
    from orchestrator import PipelineResult, Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    orch.translator = MagicMock()

    result = PipelineResult(requirement="Test")
    result.article = ""
    result.article_draft = ""
    with pytest.raises(RuntimeError, match="no article"):
        orch._stage_translate(result, "cantonese", "article_zh_hk")


def test_stage_translate_raises_on_empty_output():
    from orchestrator import PipelineResult, Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    mock_agent = MagicMock()
    mock_agent.run.return_value = {"translated_article": "   "}
    orch.translator = mock_agent

    result = PipelineResult(requirement="Test")
    result.article = "# Article"
    with pytest.raises(RuntimeError, match="empty output"):
        orch._stage_translate(result, "cantonese", "article_zh_hk")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_news_stages.py::test_translate_stages_registered tests/test_news_stages.py::test_stage_translate_sets_result_field tests/test_news_stages.py::test_stage_translate_uses_article_draft_when_no_article tests/test_news_stages.py::test_stage_translate_raises_when_no_source tests/test_news_stages.py::test_stage_translate_raises_on_empty_output -v
```

Expected: FAIL (AttributeError / AssertionError)

- [ ] **Step 3: Add import in `orchestrator.py`**

Find the line `from agents.news_editor import NewsEditorAgent` (around line 51) and add after it:

```python
from agents.translator import TranslatorAgent
```

- [ ] **Step 4: Instantiate `TranslatorAgent` in `__init__`**

Find the line `self.news_editor = NewsEditorAgent(...)` (around line 824) and add after it:

```python
        self.translator = TranslatorAgent(**{**agent_kwargs, **_mk("translator")})
```

- [ ] **Step 5: Add `_stage_translate()` method to `orchestrator.py`**

Find the `_stage_news_editor` method and add a new method after `_stage_news_editor`:

```python
    def _stage_translate(self, result: "PipelineResult", target_language: str, result_field: str) -> None:
        """Translate the final article into a target language."""
        source = result.article or result.article_draft
        if not source.strip():
            raise RuntimeError("translate: no article to translate (news_editor must run first)")
        out = self.translator.run(source, target_language=target_language)
        translated = out.get("translated_article", "")
        if not translated.strip():
            raise RuntimeError(f"translate ({target_language}): empty output from translator")
        setattr(result, result_field, translated)
```

- [ ] **Step 6: Register the two new stages in `_make_stage_registry()`**

Find `"news_article_pr": PipelineStage(` in `_make_stage_registry()` and add before it:

```python
            "translate_cantonese": PipelineStage(
                name="translate_cantonese",
                label="🀄 Translate (Cantonese)",
                description="Translating article to Written Cantonese...",
                checkpoint_key="translate_cantonese",
                fn=lambda r: self._stage_translate(r, "cantonese", "article_zh_hk"),
            ),
            "translate_zh_traditional": PipelineStage(
                name="translate_zh_traditional",
                label="🀄 Translate (Traditional Chinese)",
                description="Translating article to Traditional Chinese...",
                checkpoint_key="translate_zh_traditional",
                fn=lambda r: self._stage_translate(r, "traditional_chinese", "article_zh_tw"),
            ),
```

- [ ] **Step 7: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_news_stages.py -v
```

Expected: all pass

- [ ] **Step 8: Commit**

```bash
git add orchestrator.py tests/test_news_stages.py
git commit -m "feat: add translate_cantonese and translate_zh_traditional pipeline stages"
```

---

## Task 4: Update `_stage_news_article_pr` to include translations

**Files:**
- Modify: `orchestrator.py` (the `_stage_news_article_pr` method)
- Modify: `tests/test_news_stages.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_news_stages.py`:

```python
def test_news_article_pr_includes_translations_when_present():
    """When article_zh_hk and article_zh_tw are set, all_files contains 3 entries."""
    from orchestrator import PipelineResult, Orchestrator
    import re, yaml as _yaml
    orch = Orchestrator.__new__(Orchestrator)
    orch.model_overrides = {}
    orch._github_token = None
    orch.ollama_url = "http://localhost:11434"

    result = PipelineResult(requirement="test")
    result.issue_number = 42
    result.article = "---\ntitle: Test Article\ndate: 2026-05-19T10:00:00\nauthor: AI Press Team\nsource_url: https://example.com\ntags: [ai]\n---\n\nEnglish body."
    result.article_zh_hk = "---\ntitle: 測試文章\ndate: 2026-05-19T10:00:00\nauthor: AI Press Team\nsource_url: https://example.com\ntags: [人工智能]\n---\n\n粵語內容。"
    result.article_zh_tw = "---\ntitle: 測試文章\ndate: 2026-05-19T10:00:00\nauthor: AI Press Team\nsource_url: https://example.com\ntags: [人工智慧]\n---\n\n繁體中文內容。"

    with patch.object(orch, "_commit_and_open_pr"):
        orch._stage_news_article_pr(result)

    assert len(result.all_files) == 3
    filenames = list(result.all_files.keys())
    en_file = [f for f in filenames if not f.endswith((".zh-hk.md", ".zh-tw.md"))]
    hk_file = [f for f in filenames if f.endswith(".zh-hk.md")]
    tw_file = [f for f in filenames if f.endswith(".zh-tw.md")]
    assert len(en_file) == 1
    assert len(hk_file) == 1
    assert len(tw_file) == 1
    assert result.all_files[hk_file[0]] == result.article_zh_hk
    assert result.all_files[tw_file[0]] == result.article_zh_tw


def test_news_article_pr_only_english_when_no_translations():
    """When translations are empty, all_files contains only the English article."""
    from orchestrator import PipelineResult, Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    orch.model_overrides = {}
    orch._github_token = None
    orch.ollama_url = "http://localhost:11434"

    result = PipelineResult(requirement="test")
    result.issue_number = 1
    result.article = "---\ntitle: English Only\ndate: 2026-05-19T10:00:00\nauthor: AI Press Team\nsource_url: https://example.com\ntags: [ai]\n---\n\nBody."
    result.article_zh_hk = ""
    result.article_zh_tw = ""

    with patch.object(orch, "_commit_and_open_pr"):
        orch._stage_news_article_pr(result)

    assert len(result.all_files) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_news_stages.py::test_news_article_pr_includes_translations_when_present tests/test_news_stages.py::test_news_article_pr_only_english_when_no_translations -v
```

Expected: FAIL (all_files has 1 entry, not 3)

- [ ] **Step 3: Update `_stage_news_article_pr()` in `orchestrator.py`**

Find the line `result.all_files = {filename: article}` and replace it with:

```python
        extra_files: dict[str, str] = {}
        if result.article_zh_hk.strip():
            extra_files[filename.replace(".md", ".zh-hk.md")] = result.article_zh_hk
        if result.article_zh_tw.strip():
            extra_files[filename.replace(".md", ".zh-tw.md")] = result.article_zh_tw
        result.all_files = {filename: article, **extra_files}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_news_stages.py -v
```

Expected: all pass

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
python3 -m pytest tests/ -q
```

Expected: same failures as baseline (test_deployment, test_qa_clarification) — no new failures

- [ ] **Step 6: Commit**

```bash
git add orchestrator.py tests/test_news_stages.py
git commit -m "feat: include zh-hk and zh-tw translation files in news article PR"
```

---

## Task 5: LLM config + pipeline YAML

**Files:**
- Modify: `config.local.yaml`
- Modify: `ai-it-press/pipelines/news-article.yaml`

- [ ] **Step 1: Add `translator` override to `config.local.yaml`**

Find the `news_editor:` block and add after it (in the `# ── Press team agents ───` section):

```yaml
    translator:
      model: "opencode/opencode-go/qwen3.5-plus"
      opencode_stream: true
      fallbacks:
        - model: "ollama/thinker"
          ollama_think: false
          ollama_stream: true
```

- [ ] **Step 2: Update `ai-it-press/pipelines/news-article.yaml`**

Replace the file contents with:

```yaml
# pipelines/news-article.yaml
# Press team pipeline: research → write → review → edit → translate → PR
#
# Stages are resolved against ai-software-house's stage registry.
# Discussions (discuss_news_analysis, discuss_news_draft) auto-discovered
# from ai-software-house/discussions/.

stages:
  - discuss_news_analysis       # research + angle debate (homework round)
  - news_writer                 # write article draft
  - discuss_news_draft          # writer/editor review of draft
  - news_editor                 # final polish + frontmatter
  - translate_cantonese         # translate to Written Cantonese (zh-hk)
  - translate_zh_traditional    # translate to Formal Traditional Chinese (zh-tw)
  - news_article_pr             # commit all articles, open PR in this repo
```

- [ ] **Step 3: Verify config loads cleanly**

```bash
cd /home/wanleung/Projects/ai-software-house
python3 -c "
from config_schema import AppConfig
import yaml
with open('config.local.yaml') as f:
    cfg = yaml.safe_load(f)
print('translator override:', cfg['llm']['overrides'].get('translator', 'MISSING'))
"
```

Expected: prints the translator override dict (not `MISSING`)

- [ ] **Step 4: Commit**

```bash
cd /home/wanleung/Projects/ai-software-house
git add orchestrator.py  # config.local.yaml is gitignored

cd /home/wanleung/Projects/ai-it-press
git add pipelines/news-article.yaml
git commit -m "feat: add translate_cantonese and translate_zh_traditional stages to press pipeline"
```

---

## Self-Review

**Spec coverage check:**
- ✅ `TranslatorAgent` with `run(article, target_language)` — Task 1
- ✅ `roles/translator.md` with per-language style guidance — Task 1
- ✅ `article_zh_hk`, `article_zh_tw` on `PipelineResult` — Task 2
- ✅ `_stage_translate()` — Task 3
- ✅ `translate_cantonese` and `translate_zh_traditional` stages registered — Task 3
- ✅ `_stage_news_article_pr()` produces 3 files — Task 4
- ✅ `translator` LLM override in config — Task 5
- ✅ Pipeline YAML updated — Task 5
- ✅ Translation failures non-fatal (RuntimeError caught by stage runner, pipeline continues) — handled by existing orchestrator error handling in `_run_stage()`

**Placeholder scan:** None found.

**Type consistency:** `_stage_translate(result, target_language: str, result_field: str)` used consistently across Tasks 3 and 4. `TranslatorAgent.run()` returns `{"translated_article": str}` referenced consistently in Task 3 step 5 and Task 4 test.
