# News Reviewer Agent — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `news_reviewer` stage after translations that checks English fact/wording quality and zh-hk/zh-tw character correctness, auto-retrying the affected stages up to 2 times on issues.

**Architecture:** A new `NewsReviewerAgent` makes one LLM call to evaluate all three article versions and returns a structured `VERDICT / ISSUES / CONFIDENCE` response. The `_stage_news_reviewer()` method in `orchestrator.py` parses the verdict, determines which stages to re-run (English cascade = editor + both translations; translation-only = specific language), and loops up to `press.reviewer_max_retries` (default 2). On source fetch failure or LLM parse error, it logs a warning and passes through.

**Tech Stack:** Python 3.11, existing `BaseAgent` pattern, `urllib.request` for source fetch, `pytest` for tests.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `agents/news_reviewer.py` | **Create** | `NewsReviewerAgent` — one LLM call, structured verdict output |
| `roles/news_reviewer.md` | **Create** | Role prompt for fact check + wording QA + character set rules |
| `agents/__init__.py` | **Modify** | Export `NewsReviewerAgent` |
| `orchestrator.py` | **Modify** | Add `PipelineResult` fields, instantiate agent, register stage, implement `_stage_news_reviewer()`, add `reviewer_notes` params to `_stage_news_editor()` / `_stage_translate()` |
| `pipelines/news-article.yaml` | **Modify** | Insert `news_reviewer` before `news_article_pr` |
| `config.yaml` | **Modify** | Add `news_reviewer` model override, add `press.reviewer_max_retries: 2` |
| `config.local.yaml` | **Modify** | Add `news_reviewer` model override block |
| `tests/test_news_reviewer.py` | **Create** | Unit tests for `NewsReviewerAgent` |
| `tests/test_news_stages.py` | **Modify** | Add integration tests for `_stage_news_reviewer()` |

---

## Task 1: Create `agents/news_reviewer.py`

**Files:**
- Create: `agents/news_reviewer.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_news_reviewer.py`:

```python
"""Tests for NewsReviewerAgent."""
from __future__ import annotations
from unittest.mock import MagicMock, patch
import pytest


def _make_agent(cls, role_name):
    mock_llm = MagicMock()
    mock_llm.chat.return_value = "mock output"
    agent = cls.__new__(cls)
    agent.system_prompt = f"You are a {role_name}."
    agent._llm = mock_llm
    agent.role_name = role_name
    agent.max_api_retries = 1
    agent.retry_delay = 0
    agent.inter_call_delay = 0
    agent._token_ledger = None
    return agent


PASS_OUTPUT = """VERDICT: PASS
ISSUES:
CONFIDENCE: high"""

NEEDS_REVISION_ENGLISH = """VERDICT: NEEDS_REVISION
ISSUES:
- [FACT] Wrong version: article says "3.2" but source says "3.1"
- [WORDING] Awkward phrasing in paragraph 2
CONFIDENCE: high"""

NEEDS_REVISION_ZH_HK = """VERDICT: NEEDS_REVISION
ISSUES:
- [ZH_HK] Simplified character found: "软" should be "軟"
CONFIDENCE: high"""

NEEDS_REVISION_ZH_TW = """VERDICT: NEEDS_REVISION
ISSUES:
- [ZH_TW] Mainland vocabulary: "软件" should be "軟體"
CONFIDENCE: high"""


class TestNewsReviewerAgent:
    def test_run_returns_pass_verdict(self):
        from agents.news_reviewer import NewsReviewerAgent
        agent = _make_agent(NewsReviewerAgent, "news_reviewer")
        with patch.object(agent, "call", return_value=PASS_OUTPUT):
            result = agent.run("# Article", "# 文章", "# 文章", source_url="https://example.com")
        assert result["verdict"] == "PASS"
        assert result["issues"] == []
        assert result["confidence"] == "high"

    def test_run_returns_needs_revision_with_issues(self):
        from agents.news_reviewer import NewsReviewerAgent
        agent = _make_agent(NewsReviewerAgent, "news_reviewer")
        with patch.object(agent, "call", return_value=NEEDS_REVISION_ENGLISH):
            result = agent.run("# Article", "# 文章", "# 文章", source_url="https://example.com")
        assert result["verdict"] == "NEEDS_REVISION"
        assert any("[FACT]" in i for i in result["issues"])
        assert any("[WORDING]" in i for i in result["issues"])

    def test_run_detects_zh_hk_issues(self):
        from agents.news_reviewer import NewsReviewerAgent
        agent = _make_agent(NewsReviewerAgent, "news_reviewer")
        with patch.object(agent, "call", return_value=NEEDS_REVISION_ZH_HK):
            result = agent.run("# Article", "# 文章", "# 文章", source_url="https://example.com")
        assert result["verdict"] == "NEEDS_REVISION"
        assert any("[ZH_HK]" in i for i in result["issues"])

    def test_run_detects_zh_tw_issues(self):
        from agents.news_reviewer import NewsReviewerAgent
        agent = _make_agent(NewsReviewerAgent, "news_reviewer")
        with patch.object(agent, "call", return_value=NEEDS_REVISION_ZH_TW):
            result = agent.run("# Article", "# 文章", "# 文章", source_url="https://example.com")
        assert result["verdict"] == "NEEDS_REVISION"
        assert any("[ZH_TW]" in i for i in result["issues"])

    def test_run_passes_through_on_unparseable_output(self):
        from agents.news_reviewer import NewsReviewerAgent
        agent = _make_agent(NewsReviewerAgent, "news_reviewer")
        with patch.object(agent, "call", return_value="Something went wrong, here is a summary..."):
            result = agent.run("# Article", "# 文章", "# 文章", source_url="https://example.com")
        assert result["verdict"] == "PASS"  # fail-safe: never block on bad reviewer output

    def test_run_works_without_source_url(self):
        from agents.news_reviewer import NewsReviewerAgent
        agent = _make_agent(NewsReviewerAgent, "news_reviewer")
        with patch.object(agent, "call", return_value=PASS_OUTPUT):
            result = agent.run("# Article", "# 文章", "# 文章", source_url="")
        assert result["verdict"] == "PASS"

    def test_run_injects_source_content_into_prompt(self):
        from agents.news_reviewer import NewsReviewerAgent
        agent = _make_agent(NewsReviewerAgent, "news_reviewer")
        captured = {}
        def capture(prompt):
            captured["prompt"] = prompt
            return PASS_OUTPUT
        with patch.object(agent, "call", side_effect=capture):
            with patch("agents.news_reviewer._fetch_source", return_value="Source text here"):
                agent.run("# Article", "# 文章", "# 文章", source_url="https://example.com")
        assert "Source text here" in captured["prompt"]

    def test_exports_from_agents_package(self):
        from agents import NewsReviewerAgent
        assert NewsReviewerAgent
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_news_reviewer.py -v 2>&1 | head -30
```

Expected: `ImportError: cannot import name 'NewsReviewerAgent'`

- [ ] **Step 3: Implement `agents/news_reviewer.py`**

```python
"""
NewsReviewerAgent: reviews a finalised news article (English + translations).

Checks:
  - English: fact plausibility against source URL, wording QA
  - zh-hk: Traditional Chinese characters, Cantonese vocabulary
  - zh-tw: Traditional Chinese characters, Formal Mandarin vocabulary

Input:  article (str), article_zh_hk (str), article_zh_tw (str), source_url (str)
Output: dict with 'verdict' (PASS|NEEDS_REVISION), 'issues' (list[str]), 'confidence' (str)
"""
from __future__ import annotations

import logging
import re
import urllib.request

from .base_agent import BaseAgent

_log = logging.getLogger("news_reviewer")
_FETCH_TIMEOUT = 10  # seconds


def _fetch_source(url: str) -> str:
    """Fetch source URL content. Returns empty string on any error."""
    if not url:
        return ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
            raw = resp.read(32_000)  # cap at 32 KB
            return raw.decode("utf-8", errors="replace")
    except Exception as exc:
        _log.warning("news_reviewer: could not fetch source URL %r: %s", url, exc)
        return ""


def _parse_verdict(output: str) -> dict:
    """Parse structured reviewer output into a result dict.

    Returns {'verdict': 'PASS'|'NEEDS_REVISION', 'issues': list[str], 'confidence': str}.
    On parse failure returns PASS with a warning (never block on bad reviewer output).
    """
    verdict = "PASS"
    issues: list[str] = []
    confidence = "high"

    verdict_match = re.search(r"VERDICT:\s*(PASS|NEEDS_REVISION)", output)
    if not verdict_match:
        _log.warning("news_reviewer: could not parse VERDICT from output — defaulting to PASS")
        return {"verdict": "PASS", "issues": [], "confidence": "low"}

    verdict = verdict_match.group(1)

    for line in output.splitlines():
        line = line.strip()
        if line.startswith("- ["):
            issues.append(line.lstrip("- "))

    conf_match = re.search(r"CONFIDENCE:\s*(high|medium|low)", output, re.IGNORECASE)
    if conf_match:
        confidence = conf_match.group(1).lower()

    return {"verdict": verdict, "issues": issues, "confidence": confidence}


class NewsReviewerAgent(BaseAgent):
    """Review a finalised news article and its translations for quality."""

    role_name = "news_reviewer"

    def run(
        self,
        article: str,
        article_zh_hk: str,
        article_zh_tw: str,
        source_url: str = "",
    ) -> dict:
        """Review article quality and translation character correctness.

        Args:
            article: Final English article (markdown + frontmatter).
            article_zh_hk: Written Cantonese translation.
            article_zh_tw: Formal Traditional Chinese translation.
            source_url: Original source URL for fact-checking (may be empty).

        Returns:
            dict with keys:
                - verdict (str): "PASS" or "NEEDS_REVISION"
                - issues (list[str]): annotated issue lines e.g. "[FACT] Wrong version…"
                - confidence (str): "high" | "medium" | "low"
        """
        source_content = _fetch_source(source_url)
        source_section = (
            f"<SOURCE_CONTENT>\n{source_content[:8000]}\n</SOURCE_CONTENT>\n\n"
            if source_content
            else "<SOURCE_CONTENT>Not available — skip fact check, still check wording and characters.</SOURCE_CONTENT>\n\n"
        )

        prompt = (
            f"{source_section}"
            f"<ENGLISH_ARTICLE>\n{article}\n</ENGLISH_ARTICLE>\n\n"
            f"<ZH_HK_ARTICLE>\n{article_zh_hk}\n</ZH_HK_ARTICLE>\n\n"
            f"<ZH_TW_ARTICLE>\n{article_zh_tw}\n</ZH_TW_ARTICLE>\n\n"
            "Review all three articles according to your role instructions.\n"
            "Output ONLY the structured verdict in the exact format specified."
        )

        output = self.call(prompt)
        return _parse_verdict(output)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_news_reviewer.py -v
```

Expected: All tests PASS except `test_exports_from_agents_package` (fixed in Task 2).

- [ ] **Step 5: Commit**

```bash
cd /home/wanleung/Projects/ai-software-house
git add agents/news_reviewer.py tests/test_news_reviewer.py
git commit -m "feat: add NewsReviewerAgent with structured verdict output"
```

---

## Task 2: Create `roles/news_reviewer.md` and export agent

**Files:**
- Create: `roles/news_reviewer.md`
- Modify: `agents/__init__.py`

- [ ] **Step 1: Create the role prompt**

Create `roles/news_reviewer.md`:

```markdown
# News Reviewer

You are a senior quality reviewer for an independent IT news press team. You review
finalised news articles (English + Cantonese + Traditional Chinese translations) before
publication.

## Your job

Review the English article for:
- **Fact accuracy**: Do version numbers, dates, product names, and statistics match the
  source content? Flag anything that appears invented or not present in the source.
- **Wording quality**: Is the language clear, natural, and free of awkward LLM artefacts?
  Does the headline match the article body?
- **Content integrity**: Is this a proper news article (not agent commentary, summaries of
  edits, or meta-text)?

Review the zh-hk (Written Cantonese) article for:
- **Traditional characters only**: Flag any Simplified Chinese characters.
  Common errors: 国→國, 软→軟, 网→網, 开→開, 时→時, 为→為, 发→發, 来→來, 问→問, 长→長
- **Cantonese vocabulary**: The article must use Cantonese particles and vocabulary
  (係、唔係、喺、咁、嘅、咗、啲、佢、而家). Flag Mandarin-only patterns.

Review the zh-tw (Formal Traditional Chinese) article for:
- **Traditional characters only**: Same Simplified character checks as above.
- **Taiwanese Mandarin vocabulary**: Flag Mainland Chinese vocabulary.
  Common errors: 软件→軟體, 视频→影片, 网络→網路, 手机→手機, 网站→網站 (last two are OK)
  Mainland patterns to flag: 的话, 这个, 那个 (should be 的話, 這個, 那個 — chars, not vocab)
- **No Cantonese colloquialisms**: zh-tw must be formal Mandarin, not Cantonese.

## Output format

Output ONLY the following structured format — no other text:

```
VERDICT: PASS | NEEDS_REVISION
ISSUES:
- [FACT] <description if any>
- [WORDING] <description if any>
- [ZH_HK] <description if any>
- [ZH_TW] <description if any>
CONFIDENCE: high | medium | low
```

If there are no issues, leave the ISSUES section empty (just write `ISSUES:` with nothing below).
Use CONFIDENCE: low only when you are genuinely uncertain whether something is an error.
```

- [ ] **Step 2: Export from `agents/__init__.py`**

In `agents/__init__.py`, add after the existing `TranslatorAgent` import and export:

```python
from .news_reviewer import NewsReviewerAgent
```

And add `"NewsReviewerAgent"` to the `__all__` list.

- [ ] **Step 3: Run all news reviewer tests**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_news_reviewer.py -v
```

Expected: All 8 tests PASS.

- [ ] **Step 4: Commit**

```bash
cd /home/wanleung/Projects/ai-software-house
git add roles/news_reviewer.md agents/__init__.py
git commit -m "feat: add news_reviewer role prompt and export agent"
```

---

## Task 3: Add fields to `PipelineResult` and instantiate agent

**Files:**
- Modify: `orchestrator.py` (PipelineResult class and `__init__`)

- [ ] **Step 1: Write the failing test**

In `tests/test_news_stages.py`, add:

```python
def test_pipeline_result_has_reviewer_fields():
    from orchestrator import PipelineResult
    r = PipelineResult()
    assert hasattr(r, "article_reviewer_notes")
    assert r.article_reviewer_notes == ""
    assert hasattr(r, "article_review_retry_count")
    assert r.article_review_retry_count == 0
```

Run:
```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_news_stages.py::test_pipeline_result_has_reviewer_fields -v
```

Expected: FAIL — `PipelineResult` has no `article_reviewer_notes`.

- [ ] **Step 2: Add fields to `PipelineResult`**

In `orchestrator.py`, find the section:
```python
    article_zh_hk: str = ""  # Written Cantonese translation
    article_zh_tw: str = ""  # Formal Traditional Chinese translation
```

Add immediately after:
```python
    # News reviewer stage outputs
    article_reviewer_notes: str = ""   # last reviewer issue list (injected on retry)
    article_review_retry_count: int = 0  # total reviewer retries across all loops
```

Also add serialisation — find the `to_dict` method section with `"article_zh_hk"` and add:
```python
            "article_reviewer_notes": self.article_reviewer_notes,
            "article_review_retry_count": self.article_review_retry_count,
```

And in `from_dict`, find the list of string fields containing `"article_zh_hk"` and add:
```python
                    "article_reviewer_notes",
```

And integer fields containing `"article_review_retry_count"` — find `"prd_revision_count"` section and add:
```python
                    "article_review_retry_count",
```

- [ ] **Step 3: Instantiate `NewsReviewerAgent` in `Orchestrator.__init__`**

Find the import at top of orchestrator near line 51:
```python
from agents.news_editor import NewsEditorAgent
```

Add after it:
```python
from agents.news_reviewer import NewsReviewerAgent
```

Find where `self.news_editor` is instantiated (near line 831):
```python
self.news_editor = NewsEditorAgent(**{**agent_kwargs, **_mk("news_editor")})
```

Add after it:
```python
self.news_reviewer = NewsReviewerAgent(**{**agent_kwargs, **_mk("news_reviewer")})
```

Also add `self.news_reviewer` to the agents list near line 885 (where `self.news_editor` is listed).

- [ ] **Step 4: Run the test**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_news_stages.py::test_pipeline_result_has_reviewer_fields -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/wanleung/Projects/ai-software-house
git add orchestrator.py
git commit -m "feat: add PipelineResult reviewer fields and instantiate NewsReviewerAgent"
```

---

## Task 4: Add `reviewer_notes` params and implement `_stage_news_reviewer()`

**Files:**
- Modify: `orchestrator.py` (`_stage_news_editor`, `_stage_translate`, `_stage_news_reviewer`, `_build_stage_registry`)

- [ ] **Step 1: Write the failing stage test**

In `tests/test_news_stages.py`, add:

```python
def test_stage_news_reviewer_pass_does_not_retry():
    """PASS verdict — no retry, stage completes normally."""
    from unittest.mock import MagicMock, patch
    from orchestrator import PipelineResult

    result = PipelineResult()
    result.article = "---\ntitle: Test\ndate: 2026-01-01\nsource_url: https://example.com\n---\n\nBody."
    result.article_zh_hk = "# 文章"
    result.article_zh_tw = "# 文章"

    mock_reviewer = MagicMock()
    mock_reviewer.run.return_value = {"verdict": "PASS", "issues": [], "confidence": "high"}

    orch = _make_minimal_orchestrator()
    orch.news_reviewer = mock_reviewer
    orch._stage_news_reviewer(result)

    assert mock_reviewer.run.call_count == 1
    assert result.article_review_retry_count == 0


def test_stage_news_reviewer_english_issue_retries_editor_and_translations():
    """NEEDS_REVISION with English [FACT] — retries editor + both translations."""
    from unittest.mock import MagicMock, call
    from orchestrator import PipelineResult

    result = PipelineResult()
    result.article = "---\ntitle: Test\ndate: 2026-01-01\nsource_url: https://example.com\n---\n\nBody."
    result.article_zh_hk = "# 文章"
    result.article_zh_tw = "# 文章"

    mock_reviewer = MagicMock()
    # First call: NEEDS_REVISION with English fact issue
    # Second call: PASS
    mock_reviewer.run.side_effect = [
        {"verdict": "NEEDS_REVISION", "issues": ["[FACT] Wrong version"], "confidence": "high"},
        {"verdict": "PASS", "issues": [], "confidence": "high"},
    ]

    orch = _make_minimal_orchestrator()
    orch.news_reviewer = mock_reviewer

    editor_calls = []
    translate_calls = []

    def fake_editor(r, reviewer_notes=""):
        editor_calls.append(reviewer_notes)

    def fake_translate(r, lang, field, reviewer_notes=""):
        translate_calls.append((lang, field))

    orch._stage_news_editor = fake_editor
    orch._stage_translate = fake_translate
    orch._stage_news_reviewer(result)

    assert mock_reviewer.run.call_count == 2
    assert len(editor_calls) == 1
    assert len(translate_calls) == 2  # both languages retried
    assert result.article_review_retry_count == 1


def test_stage_news_reviewer_zh_hk_only_retries_cantonese():
    """NEEDS_REVISION with only [ZH_HK] — retries translate_cantonese only."""
    from unittest.mock import MagicMock
    from orchestrator import PipelineResult

    result = PipelineResult()
    result.article = "---\ntitle: Test\ndate: 2026-01-01\nsource_url: https://example.com\n---\n\nBody."
    result.article_zh_hk = "# 文章"
    result.article_zh_tw = "# 文章"

    mock_reviewer = MagicMock()
    mock_reviewer.run.side_effect = [
        {"verdict": "NEEDS_REVISION", "issues": ["[ZH_HK] Simplified char"], "confidence": "high"},
        {"verdict": "PASS", "issues": [], "confidence": "high"},
    ]

    orch = _make_minimal_orchestrator()
    orch.news_reviewer = mock_reviewer

    editor_calls = []
    translate_calls = []
    orch._stage_news_editor = lambda r, reviewer_notes="": editor_calls.append(reviewer_notes)
    orch._stage_translate = lambda r, lang, field, reviewer_notes="": translate_calls.append(lang)
    orch._stage_news_reviewer(result)

    assert len(editor_calls) == 0          # English editor NOT called
    assert translate_calls == ["cantonese"] # only zh-hk retried


def test_stage_news_reviewer_stops_after_max_retries():
    """After max retries, accept the article and continue regardless."""
    from unittest.mock import MagicMock
    from orchestrator import PipelineResult

    result = PipelineResult()
    result.article = "---\ntitle: Test\ndate: 2026-01-01\nsource_url: https://example.com\n---\n\nBody."
    result.article_zh_hk = "# 文章"
    result.article_zh_tw = "# 文章"

    mock_reviewer = MagicMock()
    mock_reviewer.run.return_value = {
        "verdict": "NEEDS_REVISION",
        "issues": ["[FACT] Wrong version"],
        "confidence": "high",
    }

    orch = _make_minimal_orchestrator()
    orch.news_reviewer = mock_reviewer
    orch._reviewer_max_retries = 2
    orch._stage_news_editor = lambda r, reviewer_notes="": None
    orch._stage_translate = lambda r, lang, field, reviewer_notes="": None

    # Should NOT raise — just accept after max retries
    orch._stage_news_reviewer(result)

    assert result.article_review_retry_count == 2
    assert mock_reviewer.run.call_count == 3  # initial + 2 retries
```

Also add a `_make_minimal_orchestrator()` helper at the top of the test file:
```python
def _make_minimal_orchestrator():
    """Create a minimal Orchestrator with only press-related agents mocked."""
    from unittest.mock import MagicMock
    import orchestrator as orch_mod

    o = object.__new__(orch_mod.Orchestrator)
    o._reviewer_max_retries = 2
    o.news_editor = MagicMock()
    o.news_reviewer = MagicMock()
    o.translator = MagicMock()
    return o
```

Run:
```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_news_stages.py::test_stage_news_reviewer_pass_does_not_retry -v
```

Expected: FAIL — `Orchestrator` has no `_stage_news_reviewer`.

- [ ] **Step 2: Add `reviewer_notes` param to `_stage_news_editor()`**

Find `_stage_news_editor` in `orchestrator.py`:

```python
def _stage_news_editor(self, result: PipelineResult) -> None:
    """Edit the article draft to publication standard."""
    issue_body = getattr(result, "issue_body", "") or result.requirement
    synthesis = result.discussion_synthesis or ""
    ed = self.news_editor.run(
        result.article_draft,
        issue_body=issue_body,
        discussion_synthesis=synthesis,
    )
```

Replace with:

```python
def _stage_news_editor(self, result: PipelineResult, reviewer_notes: str = "") -> None:
    """Edit the article draft to publication standard."""
    issue_body = getattr(result, "issue_body", "") or result.requirement
    synthesis = result.discussion_synthesis or ""
    # On reviewer retry, use the current article as the draft so we don't lose edits
    draft = result.article if reviewer_notes and result.article else result.article_draft
    ed = self.news_editor.run(
        draft,
        issue_body=issue_body,
        discussion_synthesis=synthesis,
        reviewer_notes=reviewer_notes,
    )
```

Also update `NewsEditorAgent.run()` in `agents/news_editor.py` to accept `reviewer_notes`:

```python
def run(
    self,
    article_draft: str,
    issue_body: str = "",
    discussion_synthesis: str = "",
    reviewer_notes: str = "",
) -> dict:
```

And inject it into the prompt (add after `synthesis_section` construction):

```python
        reviewer_section = (
            f"A reviewer found the following issues that must be fixed:\n\n"
            f"---\n{reviewer_notes}\n---\n\n"
            if reviewer_notes.strip()
            else ""
        )
```

Then prepend `reviewer_section` before `synthesis_section` in the prompt.

- [ ] **Step 3: Add `reviewer_notes` param to `_stage_translate()`**

Find `_stage_translate` in `orchestrator.py`. Add `reviewer_notes: str = ""` param:

```python
def _stage_translate(self, result: "PipelineResult", target_language: str, result_field: str, reviewer_notes: str = "") -> None:
```

Pass it to `self.translator.run()`:

```python
out = self.translator.run(source, target_language=target_language, reviewer_notes=reviewer_notes)
```

Also update `TranslatorAgent.run()` in `agents/translator.py` to accept `reviewer_notes`:

```python
def run(self, article: str, target_language: Literal["cantonese", "traditional_chinese"], reviewer_notes: str = "") -> dict:
```

Inject into prompt (add after `label =` line):

```python
        notes_section = (
            f"A reviewer found the following issues in the previous translation that must be fixed:\n\n"
            f"---\n{reviewer_notes}\n---\n\n"
            if reviewer_notes.strip()
            else ""
        )
```

Prepend `notes_section` to the prompt string.

- [ ] **Step 4: Implement `_stage_news_reviewer()`**

Add this method to `orchestrator.py` after `_stage_translate`:

```python
def _stage_news_reviewer(self, result: PipelineResult) -> None:
    """Review article quality and translation correctness; retry on issues."""
    import re as _re

    max_retries: int = getattr(self, "_reviewer_max_retries", 2)

    # Extract source_url from frontmatter
    source_url = ""
    fm_match = _re.match(r"^---\s*\n(.*?)\n---", result.article or "", _re.DOTALL)
    if fm_match:
        try:
            import yaml as _yaml
            fm = _yaml.safe_load(fm_match.group(1)) or {}
            source_url = str(fm.get("source_url", ""))
        except Exception:
            pass

    for attempt in range(max_retries + 1):
        out = self.news_reviewer.run(
            result.article or result.article_draft,
            result.article_zh_hk,
            result.article_zh_tw,
            source_url=source_url,
        )
        verdict = out.get("verdict", "PASS")
        issues = out.get("issues", [])

        if verdict == "PASS":
            if attempt > 0:
                console.print(f"  ✅ [green]Reviewer passed after {attempt} retry(s)[/green]")
            else:
                console.print("  ✅ [dim]Reviewer: PASS[/dim]")
            return

        if attempt >= max_retries:
            console.print(
                f"  [yellow]⚠️  Reviewer still has issues after {max_retries} retries — accepting article[/yellow]"
            )
            return

        # Classify issues
        has_english = any(
            i.startswith("[FACT]") or i.startswith("[WORDING]") for i in issues
        )
        has_zh_hk = any("[ZH_HK]" in i for i in issues)
        has_zh_tw = any("[ZH_TW]" in i for i in issues)
        notes = "\n".join(issues)
        result.article_reviewer_notes = notes
        result.article_review_retry_count += 1

        console.print(
            f"  [yellow]📝 Reviewer: NEEDS_REVISION (attempt {attempt + 1}/{max_retries})[/yellow]"
        )
        for issue in issues:
            console.print(f"     {issue}")

        if has_english:
            # Cascade: English issues → redo editor + both translations
            console.print("  🔄 [dim]Retrying editor + all translations…[/dim]")
            self._stage_news_editor(result, reviewer_notes=notes)
            self._stage_translate(result, "cantonese", "article_zh_hk")
            self._stage_translate(result, "traditional_chinese", "article_zh_tw")
        else:
            if has_zh_hk:
                console.print("  🔄 [dim]Retrying Cantonese translation…[/dim]")
                self._stage_translate(
                    result, "cantonese", "article_zh_hk", reviewer_notes=notes
                )
            if has_zh_tw:
                console.print("  🔄 [dim]Retrying Traditional Chinese translation…[/dim]")
                self._stage_translate(
                    result, "traditional_chinese", "article_zh_tw", reviewer_notes=notes
                )
```

- [ ] **Step 5: Register `news_reviewer` in `_build_stage_registry()`**

Find the `"news_article_pr"` entry in `_build_stage_registry()` and add `news_reviewer` before it:

```python
            "news_reviewer": PipelineStage(
                name="news_reviewer",
                label="🔍 News Reviewer",
                description="Reviewing article quality and translation correctness...",
                checkpoint_key="news_reviewer",
                fn=lambda r: self._stage_news_reviewer(r),
            ),
```

- [ ] **Step 6: Load `reviewer_max_retries` from config**

Find where `Orchestrator.__init__` loads press/pipeline config. Find where `self.stop_on_review_issues` is set (around line 723) and add nearby:

```python
press_cfg = pipeline.get("press", {})
self._reviewer_max_retries: int = int(press_cfg.get("reviewer_max_retries", 2))
```

- [ ] **Step 7: Run stage tests**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_news_stages.py -v -k "reviewer"
```

Expected: All 4 new reviewer tests PASS.

- [ ] **Step 8: Commit**

```bash
cd /home/wanleung/Projects/ai-software-house
git add orchestrator.py agents/news_editor.py agents/translator.py
git commit -m "feat: implement _stage_news_reviewer with retry loop"
```

---

## Task 5: Update pipeline YAML and config

**Files:**
- Modify: `pipelines/news-article.yaml`
- Modify: `config.yaml`
- Modify: `config.local.yaml`

- [ ] **Step 1: Update `pipelines/news-article.yaml`**

```yaml
# pipelines/news-article.yaml
stages:
  - discuss_news_analysis
  - news_writer
  - discuss_news_draft
  - news_editor
  - translate_cantonese
  - translate_zh_traditional
  - news_reviewer             # quality gate: facts, wording, character set
  - news_article_pr
```

- [ ] **Step 2: Add `news_reviewer` to `config.yaml` model overrides**

Find the `memory_bank_updater` entry in `model_overrides:` and add after it:

```yaml
    news_reviewer: "openai/gpt-4.1"
```

Add a `press:` section after the `model_overrides:` block (or at the end of the pipeline config block):

```yaml
# ── Press Team Settings ─────────────────────────────────────────────────────
press:
  # Max reviewer retry loops per article (English cascade or per-language)
  reviewer_max_retries: 2
```

- [ ] **Step 3: Add `news_reviewer` to `config.local.yaml`**

Find the `translator:` block in `config.local.yaml` and add after it:

```yaml
    news_reviewer:
      model: "opencode-go/qwen3.5-plus"
      fallbacks:
        - model: "ollama/thinker"
          ollama_think: false
          ollama_stream: true
```

- [ ] **Step 4: Verify pipeline loads without error**

```bash
cd /home/wanleung/Projects/ai-software-house
python -c "
from orchestrator import Orchestrator
import yaml
with open('config.local.yaml') as f:
    cfg = yaml.safe_load(f)
print('Config loaded OK')
# Verify stage exists
with open('pipelines/news-article.yaml') as f:
    p = yaml.safe_load(f)
print('Pipeline stages:', p['stages'])
assert 'news_reviewer' in p['stages']
print('news_reviewer stage present ✅')
"
```

Expected: `news_reviewer stage present ✅`

- [ ] **Step 5: Commit**

```bash
cd /home/wanleung/Projects/ai-software-house
git add pipelines/news-article.yaml config.yaml config.local.yaml
git commit -m "feat: add news_reviewer to pipeline and config"
```

---

## Task 6: Run full test suite and create PR

**Files:**
- No new files — validation and PR only

- [ ] **Step 1: Run all news-related tests**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_news_reviewer.py tests/test_news_agents.py tests/test_news_stages.py -v
```

Expected: All tests PASS.

- [ ] **Step 2: Run full test suite to check for regressions**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest --timeout=60 -q 2>&1 | tail -20
```

Expected: No regressions. (Pre-existing failures are OK — do not fix unrelated tests.)

- [ ] **Step 3: Push and create PR**

```bash
cd /home/wanleung/Projects/ai-software-house
git push origin HEAD
gh pr create \
  --title "feat: add news_reviewer stage with fact-check and translation QA" \
  --body "## Summary

- New \`NewsReviewerAgent\` checks English facts/wording + zh-hk/zh-tw character correctness in one LLM call
- Runs after all translations, before the PR stage
- English issues cascade: retry \`news_editor\` + both translations
- Translation-only issues: retry only the affected language
- Max 2 retries (configurable via \`press.reviewer_max_retries\`)
- Fail-safe: on reviewer error or unparseable output, logs warning and passes through

## Test Plan
- [ ] Run \`pytest tests/test_news_reviewer.py\` — all pass
- [ ] Run \`pytest tests/test_news_stages.py -k reviewer\` — all pass
- [ ] Run full \`pytest\` — no regressions
- [ ] Trigger a watcher article run and verify reviewer stage appears in console output

Closes: docs/superpowers/specs/2026-05-20-news-reviewer-design.md"
```

---

## Self-Review Notes

- All types used in later tasks match definitions in earlier tasks (`reviewer_notes: str = ""`)
- `_reviewer_max_retries` loaded from `press.reviewer_max_retries` in config (Task 4 Step 6)
- `_fetch_source` is module-level in `news_reviewer.py` so test can patch it (`agents.news_reviewer._fetch_source`)
- `_stage_translate` lambda in `_build_stage_registry` uses `lambda r` — no `reviewer_notes` needed there (it's only called with notes when invoked directly from `_stage_news_reviewer`)
- `config.local.yaml` is git-ignored; changes there won't appear in the PR diff — that's expected
