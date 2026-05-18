# Press Team Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a fully automated AI press team: RSS→issue→pipeline→PR article in ai-it-press, published to hklug-sitegen via GitHub Action.

**Architecture:** Eight independent PRs — five in ai-software-house (fetch_url tool, news agents, orchestrator stages, pipeline_file watcher feature, rss_watcher), one config file, and two in ai-it-press (repo init, GitHub Action). Each PR is independently mergeable and testable.

**Tech Stack:** Python 3.11+, requests (existing), feedparser (new dep), PyYAML (existing), pytest (existing), GitHub Actions (YAML), hklug-sitegen `.txt` format.

**Spec:** `docs/superpowers/specs/2026-05-18-press-team-design.md`

---

## Task 1 (PR 1): `fetch_url` tool

**Files:**
- Create: `tools/fetch_url.py`
- Modify: `requirements.txt` (no change — uses stdlib + existing `requests`)
- Test: `tests/test_fetch_url.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fetch_url.py
"""Tests for the fetch_url tool."""
from __future__ import annotations
from unittest.mock import patch, MagicMock
import pytest
from tools.fetch_url import fetch_url, fetch_url_tools


def test_fetch_url_returns_text():
    mock_resp = MagicMock()
    mock_resp.text = "<html><head><title>Test</title></head><body><p>Hello world</p></body></html>"
    mock_resp.raise_for_status = MagicMock()
    with patch("tools.fetch_url.requests.get", return_value=mock_resp):
        result = fetch_url("https://example.com")
    assert "Hello world" in result


def test_fetch_url_strips_scripts():
    mock_resp = MagicMock()
    mock_resp.text = "<html><body><script>evil()</script><p>Real content</p></body></html>"
    mock_resp.raise_for_status = MagicMock()
    with patch("tools.fetch_url.requests.get", return_value=mock_resp):
        result = fetch_url("https://example.com")
    assert "evil" not in result
    assert "Real content" in result


def test_fetch_url_truncates_to_max_chars():
    long_content = "x" * 20000
    mock_resp = MagicMock()
    mock_resp.text = f"<html><body><p>{long_content}</p></body></html>"
    mock_resp.raise_for_status = MagicMock()
    with patch("tools.fetch_url.requests.get", return_value=mock_resp):
        result = fetch_url("https://example.com", max_chars=8000)
    assert len(result) <= 8000


def test_fetch_url_registered_in_registry():
    schema_names = [s["function"]["name"] for s in fetch_url_tools.schemas]
    assert "fetch_url" in schema_names


def test_fetch_url_http_error_returns_error_string():
    import requests as req_lib
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = req_lib.HTTPError("404")
    with patch("tools.fetch_url.requests.get", return_value=mock_resp):
        result = fetch_url("https://example.com/404")
    assert "Error" in result
```

- [ ] **Step 2: Run test — expect failure**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_fetch_url.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError: No module named 'tools.fetch_url'`

- [ ] **Step 3: Create `tools/fetch_url.py`**

```python
"""
fetch_url — HTTP page fetcher tool.

Uses stdlib html.parser to strip tags. No extra dependencies beyond requests.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

import requests

from .registry import LocalToolRegistry

fetch_url_tools = LocalToolRegistry()

_SKIP_TAGS = frozenset(["script", "style", "nav", "footer", "head", "noscript"])


class _TextExtractor(HTMLParser):
    """Strip HTML tags; skip content inside script/style/nav/footer."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip: int = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:  # noqa: ARG002
        if tag.lower() in _SKIP_TAGS:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)

    def handle_data(self, data: str) -> None:
        if self._skip == 0:
            self._parts.append(data)

    def get_text(self) -> str:
        raw = " ".join(self._parts)
        return re.sub(r"\s+", " ", raw).strip()


@fetch_url_tools.tool(
    name="fetch_url",
    description=(
        "Fetch the text content of a web page. "
        "Returns clean plain text extracted from the HTML body (scripts and nav removed). "
        "Use this to read source articles during research."
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "Full URL of the page to fetch (https://...)",
            },
            "max_chars": {
                "type": "integer",
                "description": "Maximum characters to return (default 8000)",
            },
        },
        "required": ["url"],
    },
)
def fetch_url(url: str, max_chars: int = 8000) -> str:
    """Fetch and return plain text from a URL."""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; ai-software-house/1.0)"}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        return f"[Error fetching {url}]: {exc}"
    extractor = _TextExtractor()
    extractor.feed(resp.text)
    text = extractor.get_text()
    return text[:max_chars]
```

- [ ] **Step 4: Run tests — expect pass**

```bash
python -m pytest tests/test_fetch_url.py -v
```
Expected: 5 tests pass

- [ ] **Step 5: Commit**

```bash
git add tools/fetch_url.py tests/test_fetch_url.py
git commit -m "feat: add fetch_url tool for web page text extraction

Strips HTML tags (scripts, nav, footer removed) using stdlib html.parser.
Registered in fetch_url_tools LocalToolRegistry for agent homework rounds.

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 2 (PR 2): `news_writer` and `news_editor` agents

**Files:**
- Create: `agents/news_writer.py`
- Create: `agents/news_editor.py`
- Create: `roles/news_writer.md`
- Create: `roles/news_editor.md`
- Modify: `agents/__init__.py` (add exports)
- Test: `tests/test_news_agents.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_news_agents.py
"""Tests for NewsWriterAgent and NewsEditorAgent."""
from __future__ import annotations
from unittest.mock import MagicMock, patch
import pytest


def _make_agent(cls, role_name):
    """Create agent with a mocked LLM backend."""
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


class TestNewsWriterAgent:
    def test_run_returns_article_draft(self):
        from agents.news_writer import NewsWriterAgent
        agent = _make_agent(NewsWriterAgent, "news_writer")
        with patch.object(agent, "call", return_value="# Draft Article\n\nContent here."):
            result = agent.run("https://example.com story about Linux")
        assert "article_draft" in result
        assert "Draft Article" in result["article_draft"]

    def test_run_injects_discussion_synthesis(self):
        from agents.news_writer import NewsWriterAgent
        agent = _make_agent(NewsWriterAgent, "news_writer")
        captured = {}
        def capture_call(prompt):
            captured["prompt"] = prompt
            return "# Article"
        with patch.object(agent, "call", side_effect=capture_call):
            agent.run("brief", discussion_synthesis="Key insight: AI is big")
        assert "Key insight: AI is big" in captured["prompt"]

    def test_run_without_synthesis_still_works(self):
        from agents.news_writer import NewsWriterAgent
        agent = _make_agent(NewsWriterAgent, "news_writer")
        with patch.object(agent, "call", return_value="# Article\nBody."):
            result = agent.run("Some news brief")
        assert result["article_draft"]


class TestNewsEditorAgent:
    def test_run_returns_article(self):
        from agents.news_editor import NewsEditorAgent
        agent = _make_agent(NewsEditorAgent, "news_editor")
        with patch.object(agent, "call", return_value="---\ntitle: Final\n---\n\nBody."):
            result = agent.run(article_draft="# Draft\nBody.", issue_body="Brief")
        assert "article" in result
        assert "Final" in result["article"]

    def test_run_injects_draft_review_synthesis(self):
        from agents.news_editor import NewsEditorAgent
        agent = _make_agent(NewsEditorAgent, "news_editor")
        captured = {}
        def capture_call(prompt):
            captured["prompt"] = prompt
            return "# Edited"
        with patch.object(agent, "call", side_effect=capture_call):
            agent.run("Draft text", discussion_synthesis="Fix the headline")
        assert "Fix the headline" in captured["prompt"]

    def test_exports_from_agents_package(self):
        from agents import NewsWriterAgent, NewsEditorAgent
        assert NewsWriterAgent
        assert NewsEditorAgent
```

- [ ] **Step 2: Run test — expect failure**

```bash
python -m pytest tests/test_news_agents.py -v 2>&1 | head -20
```
Expected: `ImportError: cannot import name 'NewsWriterAgent'`

- [ ] **Step 3: Create `roles/news_writer.md`**

```markdown
# News Writer

You are a professional technology news writer for an independent IT press team.
Your job is to research and write accurate, balanced, factual news articles about technology topics.

## Style
- Clear, factual, journalistic tone — not promotional or opinionated
- Lead with the most important fact (inverted pyramid structure)
- Include: what happened, who is involved, why it matters, relevant context
- Cite sources inline where possible
- Length: 400–700 words

## Output format
Always output a complete markdown article with YAML frontmatter:

```yaml
---
title: "Exact descriptive headline"
date: YYYY-MM-DDTHH:MM:00
author: AI Press Team
source_url: https://original-source-url
tags: [tag1, tag2, tag3]
---
```

Follow the frontmatter with the article body in markdown.
Only output the article — no preamble, no meta-commentary.
```

- [ ] **Step 4: Create `roles/news_editor.md`**

```markdown
# News Editor

You are a senior technology news editor for an independent IT press team.
Your job is to review and polish news article drafts to publication standard.

## Responsibilities
- Verify the headline is accurate and compelling
- Check that facts stated in the article match the source material
- Improve clarity and flow where needed
- Ensure the article follows inverted pyramid structure
- Review and correct the YAML frontmatter (title, date, tags)
- Keep the author's voice — only change what needs changing

## Output format
Output the final, publication-ready article in full — complete YAML frontmatter followed by the markdown body.
Do not add meta-commentary. Output only the article.
```

- [ ] **Step 5: Create `agents/news_writer.py`**

```python
"""
NewsWriterAgent: researches and writes a first-draft news article.

Input:  issue_body (str) — the news brief from the GitHub issue
Output: dict with 'article_draft' (markdown string with YAML frontmatter)
"""
from __future__ import annotations

from .base_agent import BaseAgent


class NewsWriterAgent(BaseAgent):
    """Write a first-draft news article from an issue brief and optional discussion synthesis."""

    role_name = "news_writer"

    def run(self, issue_body: str, discussion_synthesis: str = "") -> dict:
        """Write a news article draft.

        Args:
            issue_body: The GitHub issue body containing the news brief and source URL.
            discussion_synthesis: Optional synthesis from discuss_news_analysis stage.

        Returns:
            dict with key:
                - article_draft (str): Full markdown article with YAML frontmatter
        """
        synthesis_section = (
            f"A pre-write analysis of this story has been conducted.\n"
            f"Use the key insights below to guide your article — do not copy them verbatim.\n\n"
            f"---\n{discussion_synthesis}\n---\n\n"
            if discussion_synthesis.strip()
            else ""
        )
        prompt = (
            f"{synthesis_section}"
            f"Write a news article based on the following brief:\n\n"
            f"---\n{issue_body}\n---\n\n"
            f"Follow your role instructions. Output the full article in markdown with YAML frontmatter."
        )
        article_draft = self.call(prompt)
        return {"article_draft": article_draft}
```

- [ ] **Step 6: Create `agents/news_editor.py`**

```python
"""
NewsEditorAgent: edits a news article draft to publication standard.

Input:  article_draft (str), issue_body (str), optional discussion_synthesis (str)
Output: dict with 'article' (final markdown string)
"""
from __future__ import annotations

from .base_agent import BaseAgent


class NewsEditorAgent(BaseAgent):
    """Edit and finalise a news article draft."""

    role_name = "news_editor"

    def run(
        self,
        article_draft: str,
        issue_body: str = "",
        discussion_synthesis: str = "",
    ) -> dict:
        """Edit and finalise the article.

        Args:
            article_draft: The draft article from NewsWriterAgent (or discuss_news_draft synthesis).
            issue_body: The original brief for reference.
            discussion_synthesis: Optional synthesis from discuss_news_draft stage.

        Returns:
            dict with key:
                - article (str): Final publication-ready markdown article
        """
        synthesis_section = (
            f"A draft review discussion has been conducted. Key feedback:\n\n"
            f"---\n{discussion_synthesis}\n---\n\n"
            if discussion_synthesis.strip()
            else ""
        )
        original_brief = f"Original brief:\n---\n{issue_body}\n---\n\n" if issue_body.strip() else ""
        prompt = (
            f"{synthesis_section}"
            f"{original_brief}"
            f"Please edit and finalise the following news article draft:\n\n"
            f"---\n{article_draft}\n---\n\n"
            f"Follow your role instructions. Output the final article only."
        )
        article = self.call(prompt)
        return {"article": article}
```

- [ ] **Step 7: Update `agents/__init__.py`**

Add to the existing imports and `__all__` list:

```python
# After the existing imports, add:
from .news_writer import NewsWriterAgent
from .news_editor import NewsEditorAgent
```

Add `"NewsWriterAgent"` and `"NewsEditorAgent"` to the `__all__` list.

- [ ] **Step 8: Run tests — expect pass**

```bash
python -m pytest tests/test_news_agents.py -v
```
Expected: 6 tests pass

- [ ] **Step 9: Commit**

```bash
git add agents/news_writer.py agents/news_editor.py agents/__init__.py \
        roles/news_writer.md roles/news_editor.md tests/test_news_agents.py
git commit -m "feat: add news_writer and news_editor agents

- NewsWriterAgent: writes markdown article with YAML frontmatter from issue brief
- NewsEditorAgent: edits draft to publication standard, injects discussion synthesis
- roles/news_writer.md: journalist role (400-700 words, inverted pyramid)
- roles/news_editor.md: senior editor role (fact-check, clarity, frontmatter)

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 3 (PR 3): PipelineResult fields + orchestrator stage registration

**Files:**
- Modify: `orchestrator.py` — add `article_draft`/`article` to `PipelineResult`; add `_stage_news_writer`, `_stage_news_editor`, `_stage_news_article_pr` methods; register in `_make_stage_registry()`; instantiate agents in `__init__`
- Test: `tests/test_news_stages.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_news_stages.py
"""Tests for news pipeline stages in the orchestrator."""
from __future__ import annotations
from unittest.mock import MagicMock, patch
import pytest

from orchestrator import PipelineResult


def test_pipeline_result_has_article_draft():
    r = PipelineResult(requirement="test")
    assert hasattr(r, "article_draft")
    assert r.article_draft == ""


def test_pipeline_result_has_article():
    r = PipelineResult(requirement="test")
    assert hasattr(r, "article")
    assert r.article == ""


def test_pipeline_result_article_draft_in_to_dict():
    r = PipelineResult(requirement="test")
    r.article_draft = "# Draft"
    r.article = "# Final"
    d = r.to_dict()
    assert d["article_draft"] == "# Draft"
    assert d["article"] == "# Final"


def test_pipeline_result_article_from_dict():
    r = PipelineResult.from_dict({
        "requirement": "test",
        "article_draft": "# Draft",
        "article": "# Final",
    })
    assert r.article_draft == "# Draft"
    assert r.article == "# Final"


def test_news_stages_registered():
    """news_writer, news_editor, news_article_pr must be in the stage registry."""
    from orchestrator import Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    orch.model = "gpt-4.1"
    orch.model_overrides = {}
    orch._stage_timeouts = {}
    orch._discussions_dir = None
    with patch.object(Orchestrator, "_make_backend", return_value=MagicMock()), \
         patch.object(Orchestrator, "_make_backend_from_model", return_value=MagicMock()):
        # Manually set required attributes
        orch.news_writer = MagicMock()
        orch.news_editor = MagicMock()
        from pathlib import Path
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmpdir:
            orch._discussions_dir = Path(tmpdir)
            registry = orch._make_stage_registry()
    assert "news_writer" in registry
    assert "news_editor" in registry
    assert "news_article_pr" in registry


def test_stage_news_writer_sets_article_draft():
    from orchestrator import PipelineResult, Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    mock_agent = MagicMock()
    mock_agent.run.return_value = {"article_draft": "# My Draft\n\nContent."}
    orch.news_writer = mock_agent

    result = PipelineResult(requirement="Test article")
    result.issue_body = "https://example.com"
    result.discussion_synthesis = "Key point: important"
    orch._stage_news_writer(result)
    assert result.article_draft == "# My Draft\n\nContent."


def test_stage_news_editor_sets_article():
    from orchestrator import PipelineResult, Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    mock_agent = MagicMock()
    mock_agent.run.return_value = {"article": "---\ntitle: Final\n---\n\nBody."}
    orch.news_editor = mock_agent

    result = PipelineResult(requirement="Test article")
    result.article_draft = "# Draft"
    result.issue_body = "Brief"
    result.discussion_synthesis = ""
    orch._stage_news_editor(result)
    assert result.article == "---\ntitle: Final\n---\n\nBody."


def test_stage_news_article_pr_sets_all_files():
    from orchestrator import PipelineResult, Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    orch.github = None
    orch.target_github = None

    result = PipelineResult(requirement="Test article")
    result.article = "---\ntitle: Test Article\ndate: 2026-01-15T10:30:00\nauthor: AI Press Team\n---\n\nBody."
    result.issue_number = 42

    orch._stage_news_article_pr(result)
    assert len(result.all_files) == 1
    path = list(result.all_files.keys())[0]
    assert path.startswith("articles/")
    assert path.endswith(".md")
    assert "test-article" in path or "2026" in path
```

- [ ] **Step 2: Run test — expect failure**

```bash
python -m pytest tests/test_news_stages.py -v 2>&1 | head -20
```
Expected: failures on missing `article_draft`/`article` fields and missing stage keys.

- [ ] **Step 3: Add `article_draft` and `article` to `PipelineResult`**

In `orchestrator.py`, find the `# Discussion stage outputs` comment (around line 409) and add after `discussion_synthesis`:

```python
    # News article stage outputs
    article_draft: str = ""
    article: str = ""
```

Also add both fields to `to_dict()` (after `discussion_synthesis` entry):
```python
            "article_draft": self.article_draft,
            "article": self.article,
```

And add both fields to the key list in `from_dict()` (after `"discussion_synthesis"`):
```python
                    "article_draft", "article",
```

- [ ] **Step 4: Add agents import and instantiation**

At the top of `orchestrator.py`, add to the `from agents import (...)` block:
```python
from agents.news_writer import NewsWriterAgent
from agents.news_editor import NewsEditorAgent
```

In `__init__`, after `self.pm = ProductManagerAgent(...)` (around line 815), add:
```python
        self.news_writer = NewsWriterAgent(**{**agent_kwargs, **_mk("news_writer")})
        self.news_editor = NewsEditorAgent(**{**agent_kwargs, **_mk("news_editor")})
```

Also add both to the `_original_system_prompts` dict snapshot (around line 868):
```python
                self.news_writer, self.news_editor,
```

- [ ] **Step 5: Add stage methods to `orchestrator.py`**

After `_stage_pm_reviewer` (around line 3099), add the three new stage methods:

```python
    def _stage_news_writer(self, result: PipelineResult) -> None:
        """Write a first-draft news article from the issue brief."""
        issue_body = getattr(result, "issue_body", "") or result.requirement
        synthesis = result.discussion_synthesis or ""
        wr = self.news_writer.run(issue_body, discussion_synthesis=synthesis)
        if not wr.get("article_draft", "").strip():
            raise RuntimeError("NewsWriter produced an empty draft — LLM may have returned no content.")
        result.article_draft = wr["article_draft"]
        # Reset discussion_synthesis so news_editor sees discuss_news_draft synthesis (if any)
        result.discussion_synthesis = ""

    def _stage_news_editor(self, result: PipelineResult) -> None:
        """Edit the article draft to publication standard."""
        issue_body = getattr(result, "issue_body", "") or result.requirement
        synthesis = result.discussion_synthesis or ""
        ed = self.news_editor.run(
            result.article_draft,
            issue_body=issue_body,
            discussion_synthesis=synthesis,
        )
        if not ed.get("article", "").strip():
            raise RuntimeError("NewsEditor produced an empty article — LLM may have returned no content.")
        result.article = ed["article"]

    def _stage_news_article_pr(self, result: PipelineResult) -> None:
        """Commit the final article as a file and open a PR in the tracker repo."""
        import re
        import yaml as _yaml

        article = result.article or result.article_draft
        if not article.strip():
            result.add_error("news_article_pr: no article content to commit.")
            return

        # Parse frontmatter for date and title
        date_str = ""
        title_slug = "article"
        fm_match = re.match(r"^---\s*\n(.*?)\n---", article, re.DOTALL)
        if fm_match:
            try:
                fm = _yaml.safe_load(fm_match.group(1)) or {}
                raw_date = str(fm.get("date", ""))
                date_str = raw_date[:10].replace("-", "") if raw_date else ""
                title = str(fm.get("title", ""))
                title_slug = re.sub(r"[^a-z0-9]+", "-", title.lower())[:40].strip("-")
            except Exception:  # noqa: BLE001
                pass

        if not date_str:
            from datetime import datetime
            date_str = datetime.utcnow().strftime("%Y%m%d")

        issue_part = f"{result.issue_number}-" if result.issue_number else ""
        filename = f"articles/{date_str}-{issue_part}{title_slug or 'article'}.md"
        result.all_files = {filename: article}

        self._commit_and_open_pr(
            result,
            branch_prefix="article",
            title_prefix="article",
            body_header="## 📰 AI-Generated News Article",
            commit_msg_prefix="article",
        )
```

- [ ] **Step 6: Register stages in `_make_stage_registry()`**

In `_make_stage_registry()`, add the three stages just before the `return _registry` line (around line 1889):

```python
            "news_writer": PipelineStage(
                name="news_writer",
                label="✍️  News Writer",
                description="Writing news article draft...",
                checkpoint_key="news_writer",
                fn=lambda r: self._stage_news_writer(r),
                required_output_fields=["article_draft"],
                is_critical=True,
            ),
            "news_editor": PipelineStage(
                name="news_editor",
                label="📝 News Editor",
                description="Editing and finalising article...",
                checkpoint_key="news_editor",
                fn=lambda r: self._stage_news_editor(r),
                required_output_fields=["article"],
                is_critical=True,
            ),
            "news_article_pr": PipelineStage(
                name="news_article_pr",
                label="📨 News Article PR",
                description="Opening PR with article...",
                checkpoint_key="news_article_pr",
                fn=lambda r: self._stage_news_article_pr(r),
            ),
```

- [ ] **Step 7: Run tests — expect pass**

```bash
python -m pytest tests/test_news_stages.py -v
```
Expected: all tests pass.

Also run the existing orchestrator test suite to check for regressions:
```bash
python -m pytest tests/test_orchestrator*.py -v --timeout=30 2>&1 | tail -20
```
Expected: all previously passing tests still pass.

- [ ] **Step 8: Commit**

```bash
git add orchestrator.py tests/test_news_stages.py
git commit -m "feat: add news_writer/news_editor/news_article_pr pipeline stages

- PipelineResult: add article_draft and article fields
- _stage_news_writer: calls NewsWriterAgent, sets result.article_draft
- _stage_news_editor: calls NewsEditorAgent, sets result.article
- _stage_news_article_pr: parses frontmatter, commits article, opens PR
- All three stages registered in _make_stage_registry()
- news_writer and news_editor agents instantiated in Orchestrator.__init__

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 4 (PR 4): `pipeline_file:` watcher feature

**Files:**
- Modify: `watcher.py` — parse `pipeline_file:` from repo config; pass to `_dispatch()`; fetch and apply pipeline YAML from target repo GitHub API
- Test: `tests/test_pipeline_file_feature.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline_file_feature.py
"""Tests for pipeline_file: feature — loading pipeline YAML from target repo."""
from __future__ import annotations
from unittest.mock import MagicMock, patch
import pytest
import yaml


def _make_orch_mock(stages=None):
    """Return a mock Orchestrator that records _pipeline_yaml_stages."""
    m = MagicMock()
    m._pipeline_yaml_stages = None
    m.load_pipeline_for_label.return_value = stages
    return m


def test_pipeline_file_fetched_and_applied():
    """When pipeline_file: is set, watcher fetches YAML and sets orch._pipeline_yaml_stages."""
    from watcher import _dispatch

    pipeline_yaml = yaml.dump({
        "stages": ["news_writer", "news_editor", "news_article_pr"]
    })

    mock_result = MagicMock()
    mock_result.verdict = "ok"
    mock_result.next_label = None

    with patch("watcher.Orchestrator") as mock_cls, \
         patch("watcher.GitHubClient") as mock_gh_cls, \
         patch("watcher._load_pipeline_config", return_value={}), \
         patch("watcher._collect_issue_prior_context", return_value=""):

        mock_gh = MagicMock()
        mock_gh.get_issue.return_value = {"number": 1, "title": "Article: Test", "body": "brief"}
        mock_gh.get_file_content.return_value = pipeline_yaml
        mock_gh_cls.return_value = mock_gh

        mock_orch = _make_orch_mock()
        mock_orch.run.return_value = mock_result
        mock_cls.return_value = mock_orch

        import tempfile, logging
        from pathlib import Path
        log = logging.getLogger("test")
        with tempfile.NamedTemporaryFile(suffix=".log") as f:
            _dispatch(
                label="news-article",
                tracker_repo="wanleung/ai-it-press",
                target_repo="wanleung/ai-it-press",
                issue_number=1,
                model="gpt-4.1",
                num_engineers=1,
                log_file=Path(f.name),
                logger=log,
                pipeline_file="pipelines/news-article.yaml",
            )

    # Verify get_file_content was called with the pipeline file path
    mock_gh.get_file_content.assert_called_with("pipelines/news-article.yaml")
    # Verify _pipeline_yaml_stages was set on the orchestrator
    assert mock_orch._pipeline_yaml_stages == ["news_writer", "news_editor", "news_article_pr"]


def test_pipeline_file_missing_falls_back_gracefully():
    """If pipeline_file cannot be fetched, pipeline falls back to label-based lookup."""
    from watcher import _dispatch

    mock_result = MagicMock()
    mock_result.verdict = "ok"
    mock_result.next_label = None

    with patch("watcher.Orchestrator") as mock_cls, \
         patch("watcher.GitHubClient") as mock_gh_cls, \
         patch("watcher._load_pipeline_config", return_value={}), \
         patch("watcher._collect_issue_prior_context", return_value=""):

        mock_gh = MagicMock()
        mock_gh.get_issue.return_value = {"number": 1, "title": "Article: Test", "body": "brief"}
        mock_gh.get_file_content.return_value = None  # file not found
        mock_gh_cls.return_value = mock_gh

        mock_orch = _make_orch_mock()
        mock_orch.run.return_value = mock_result
        mock_cls.return_value = mock_orch

        import tempfile, logging
        from pathlib import Path
        log = logging.getLogger("test")
        with tempfile.NamedTemporaryFile(suffix=".log") as f:
            _dispatch(
                label="news-article",
                tracker_repo="wanleung/ai-it-press",
                target_repo="wanleung/ai-it-press",
                issue_number=1,
                model="gpt-4.1",
                num_engineers=1,
                log_file=Path(f.name),
                logger=log,
                pipeline_file="pipelines/news-article.yaml",
            )

    # _pipeline_yaml_stages should NOT have been set (fallback to load_pipeline_for_label)
    assert mock_orch._pipeline_yaml_stages is None


def test_watch_passes_pipeline_file_from_repo_config(tmp_path):
    """watch() passes pipeline_file from repo config to run_pipeline tasks."""
    import watcher
    repo_config = {
        "tracker_repo": "wanleung/ai-it-press",
        "pipeline_file": "pipelines/news-article.yaml",
        "labels": {"news-article": {}},
        "enabled": True,
    }

    with patch.object(watcher, "_load_watcher_config", return_value=[repo_config]), \
         patch.object(watcher, "get_open_issues", return_value=[
             {"number": 1, "title": "Article: X", "labels": [{"name": "news-article"}],
              "body": None, "state": "open", "pull_request": None, "html_url": ""}
         ]), \
         patch.object(watcher, "ensure_label"), \
         patch.object(watcher, "add_label"), \
         patch.object(watcher, "run_pipeline", return_value=True) as mock_run, \
         patch("os.environ.get", return_value="fake-token"):
        watcher.watch(dry_run=True)
    # With dry_run, run_pipeline is not called; but tasks should be built with pipeline_file
    # (dry_run short-circuits before run_pipeline is actually invoked with pipeline_file)
    # So instead test the task-building path directly:
    tasks = []
    with patch.object(watcher, "_load_watcher_config", return_value=[repo_config]), \
         patch.object(watcher, "get_open_issues", return_value=[
             {"number": 1, "title": "Article: X", "labels": [{"name": "news-article"}],
              "body": None, "state": "open", "pull_request": None, "html_url": ""}
         ]), \
         patch.object(watcher, "ensure_label"), \
         patch.object(watcher, "add_label"), \
         patch.object(watcher, "_process_resume_queue", return_value=[]), \
         patch("os.environ.get", return_value="fake-token"), \
         patch("concurrent.futures.ThreadPoolExecutor") as mock_pool:
        # Check that tasks dict includes pipeline_file
        # We do this by inspecting what gets appended to tasks list via _build_tasks
        # The simplest check: call the internal _build_watch_tasks helper
        built = watcher._build_watch_tasks(
            watchers=[repo_config],
            model="gpt-4.1",
            num_engineers=1,
            github_token="fake-token",
        )
    pipeline_files = [t.get("pipeline_file") for t in built]
    assert "pipelines/news-article.yaml" in pipeline_files
```

- [ ] **Step 2: Run test — expect failure**

```bash
python -m pytest tests/test_pipeline_file_feature.py -v 2>&1 | head -30
```
Expected: failures — `_dispatch` doesn't accept `pipeline_file`, `_build_watch_tasks` doesn't exist.

- [ ] **Step 3: Add `pipeline_file` parameter to `_dispatch()`**

In `watcher.py`, find `def _dispatch(` (around line 782) and add `pipeline_file: str = ""` to its parameters:

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
    llm_cfg: dict | None = None,
    pipeline_file: str = "",   # ← new
) -> "PipelineResult":
```

Inside `_dispatch()`, after creating `orch` and before the existing `stages = orch.load_pipeline_for_label(label)` line, add:

```python
            # pipeline_file: fetch pipeline YAML from tracker repo via GitHub API
            if pipeline_file:
                raw = tracker_gh.get_file_content(pipeline_file)
                if raw:
                    import yaml as _yaml
                    data = _yaml.safe_load(raw) or {}
                    fetched_stages = data.get("stages")
                    if fetched_stages is not None:
                        orch._validate_pipeline_stages(pipeline_file, fetched_stages)
                        orch._pipeline_yaml_stages = fetched_stages
                        _log.info("    Using pipeline_file: %s (%d stages)", pipeline_file, len(fetched_stages))
                else:
                    _log.warning("    pipeline_file %r not found in %s — falling back to label lookup", pipeline_file, tracker_repo)
```

- [ ] **Step 4: Add `pipeline_file` to `run_pipeline()`**

Find `def run_pipeline(` and add `pipeline_file: str = ""` to its keyword parameters. Pass it through to `_dispatch()`:

```python
        result = _dispatch(
            label=label,
            tracker_repo=tracker_repo,
            target_repo=_target_repo,
            issue_number=_issue_number,
            model=model,
            num_engineers=num_engineers,
            log_file=issue_log,
            logger=logger,
            deploy_cfg=deploy_cfg,
            llm_cfg=llm_cfg,
            pipeline_file=pipeline_file,   # ← new
        )
```

- [ ] **Step 5: Add `_build_watch_tasks()` helper and populate `pipeline_file` in task dicts**

Extract the task-building loop in `watch()` into a new `_build_watch_tasks()` helper function (refactor), and ensure it reads `pipeline_file` from the repo config dict:

```python
def _build_watch_tasks(
    watchers: list[dict],
    model: str,
    num_engineers: int,
    github_token: str,
) -> list[dict]:
    """Build the list of task dicts from watcher repo configs.

    Each returned dict maps directly to run_pipeline() kwargs.
    """
    import copy
    tasks: list[dict] = []
    for w in watchers:
        if not w.get("enabled", True):
            continue
        tracker_repo = w.get("tracker_repo", "")
        default_target = w.get("default_target")
        pipeline_file = w.get("pipeline_file", "")

        # Build effective LLM config (same logic as before)
        repo_llm = w.get("llm") or {}
        global_cfg = _load_pipeline_config()
        effective_llm = {**global_cfg.get("llm", {}), **repo_llm}
        if not repo_llm.get("model") and model != "gpt-4.1":
            effective_llm["model"] = model

        labels_cfg = w.get("labels") or {}

        for label_name, label_cfg in labels_cfg.items():
            if isinstance(label_cfg, str):
                pipeline_name = label_cfg
            else:
                pipeline_name = (label_cfg or {}).get("pipeline", label_name)
            for issue in get_open_issues(tracker_repo, label_name):
                add_label(tracker_repo, issue["number"], LABEL_QUEUED)
                tasks.append(dict(
                    issue=issue,
                    tracker_repo=tracker_repo,
                    default_target=default_target,
                    label=pipeline_name,
                    parallel_issues=w.get("parallel_issues", 1),
                    model=model,
                    num_engineers=num_engineers,
                    deploy=w.get("deploy"),
                    llm=copy.deepcopy(effective_llm),
                    pipeline_file=pipeline_file,
                ))
    return tasks
```

Update `watch()` to call `_build_watch_tasks()` instead of the inline loop, and pass `pipeline_file` from the task dict to `run_pipeline()`.

- [ ] **Step 6: Run tests — expect pass**

```bash
python -m pytest tests/test_pipeline_file_feature.py -v
```
Expected: all tests pass.

Also run watcher tests for regressions:
```bash
python -m pytest tests/test_watcher*.py -v --timeout=30 2>&1 | tail -20
```

- [ ] **Step 7: Commit**

```bash
git add watcher.py tests/test_pipeline_file_feature.py
git commit -m "feat: pipeline_file — load pipeline YAML from target repo via GitHub API

When a repo config has pipeline_file: set, the watcher fetches the named
YAML file from the tracker repo using GitHubClient.get_file_content() and
applies it to the orchestrator before running the pipeline. Falls back
gracefully to label-based lookup if the file is not found.

- _dispatch(): new pipeline_file parameter; fetches and applies YAML
- run_pipeline(): threads pipeline_file through to _dispatch()
- _build_watch_tasks(): extracted helper; reads pipeline_file from config

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 5 (PR 5): `rss_watcher.py`

**Files:**
- Create: `rss_watcher.py`
- Modify: `requirements.txt` — add `feedparser>=6.0`
- Test: `tests/test_rss_watcher.py`

- [ ] **Step 1: Add `feedparser` to `requirements.txt`**

Append to `requirements.txt`:
```
feedparser>=6.0
```

Install:
```bash
pip install feedparser>=6.0
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_rss_watcher.py
"""Tests for rss_watcher.py."""
from __future__ import annotations
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest


def _make_entry(url: str, title: str = "Test Article", summary: str = "A summary.") -> MagicMock:
    e = MagicMock()
    e.link = url
    e.title = title
    e.summary = summary
    return e


def test_new_entry_creates_github_issue():
    import rss_watcher
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "rss_seen.db"
        cfg = {
            "press_repo": "wanleung/ai-it-press",
            "label": "news-article",
            "max_age_hours": 48,
            "feeds": [{"url": "https://example.com/feed.rss", "source": "Example"}],
        }
        with patch("rss_watcher.feedparser") as mock_fp, \
             patch("rss_watcher._create_github_issue") as mock_create:
            mock_fp.parse.return_value = MagicMock(
                entries=[_make_entry("https://example.com/article-1")]
            )
            rss_watcher.process_feeds(cfg, db_path=db_path)
        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["repo"] == "wanleung/ai-it-press"
        assert "https://example.com/article-1" in call_kwargs["body"]


def test_duplicate_entry_skipped():
    import rss_watcher
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "rss_seen.db"
        cfg = {
            "press_repo": "wanleung/ai-it-press",
            "label": "news-article",
            "max_age_hours": 48,
            "feeds": [{"url": "https://example.com/feed.rss", "source": "Example"}],
        }
        with patch("rss_watcher.feedparser") as mock_fp, \
             patch("rss_watcher._create_github_issue") as mock_create:
            mock_fp.parse.return_value = MagicMock(
                entries=[_make_entry("https://example.com/article-1")]
            )
            rss_watcher.process_feeds(cfg, db_path=db_path)
            rss_watcher.process_feeds(cfg, db_path=db_path)
        # Second run: same URL should be skipped
        assert mock_create.call_count == 1


def test_github_issue_body_contains_url_and_source():
    import rss_watcher
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "rss_seen.db"
        cfg = {
            "press_repo": "wanleung/ai-it-press",
            "label": "news-article",
            "max_age_hours": 48,
            "feeds": [{"url": "https://feeds.linux.com/feed", "source": "Linux.com"}],
        }
        with patch("rss_watcher.feedparser") as mock_fp, \
             patch("rss_watcher._create_github_issue") as mock_create:
            mock_fp.parse.return_value = MagicMock(
                entries=[_make_entry("https://linux.com/story", title="Linux 6.9 Released", summary="Details here")]
            )
            rss_watcher.process_feeds(cfg, db_path=db_path)
        body = mock_create.call_args[1]["body"]
        assert "https://linux.com/story" in body
        assert "Linux.com" in body
        assert "Linux 6.9 Released" in body


def test_db_persists_seen_urls():
    import rss_watcher
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "rss_seen.db"
        rss_watcher._mark_seen(db_path, "https://example.com/article-1")
        assert rss_watcher._is_seen(db_path, "https://example.com/article-1")
        assert not rss_watcher._is_seen(db_path, "https://example.com/new-article")
```

- [ ] **Step 3: Run test — expect failure**

```bash
python -m pytest tests/test_rss_watcher.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError: No module named 'rss_watcher'`

- [ ] **Step 4: Create `rss_watcher.py`**

```python
#!/usr/bin/env python3
"""
rss_watcher.py — Poll RSS feeds and create GitHub Issues for new articles.

Usage (cron, every 15 min):
    */15 * * * * cd /path/to/ai-software-house && python rss_watcher.py

Config in config.local.yaml:
    rss_watcher:
      press_repo: wanleung/ai-it-press
      label: news-article
      max_age_hours: 48
      feeds:
        - url: https://feeds.feedburner.com/oreilly/radar
          source: O'Reilly Radar
        - url: https://www.linux.com/feed/
          source: Linux.com
"""
from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Any

import feedparser
import requests
import yaml

_log = logging.getLogger(__name__)

_DEFAULT_DB = Path(__file__).parent / "rss_seen.db"
_DEFAULT_CONFIG = Path(__file__).parent / "config.local.yaml"


def _load_config(config_path: Path = _DEFAULT_CONFIG) -> dict:
    """Load rss_watcher section from config.local.yaml."""
    if not config_path.exists():
        return {}
    with open(config_path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data.get("rss_watcher", {})


def _ensure_db(db_path: Path) -> None:
    """Create the seen-URLs table if it doesn't exist."""
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS seen_urls "
            "(url TEXT PRIMARY KEY, seen_at TEXT NOT NULL)"
        )
        conn.commit()


def _is_seen(db_path: Path, url: str) -> bool:
    """Return True if this URL has already been processed."""
    _ensure_db(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT 1 FROM seen_urls WHERE url = ?", (url,)).fetchone()
    return row is not None


def _mark_seen(db_path: Path, url: str) -> None:
    """Record a URL as processed."""
    _ensure_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO seen_urls (url, seen_at) VALUES (?, ?)",
            (url, datetime.utcnow().isoformat()),
        )
        conn.commit()


def _create_github_issue(
    repo: str,
    title: str,
    body: str,
    label: str,
    token: str | None = None,
) -> None:
    """Create a GitHub issue via REST API."""
    tok = token or os.environ.get("GITHUB_TOKEN", "")
    headers = {
        "Authorization": f"Bearer {tok}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    url = f"https://api.github.com/repos/{repo}/issues"
    resp = requests.post(
        url,
        headers=headers,
        json={"title": title, "body": body, "labels": [label]},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    _log.info("Created issue #%d: %s", data["number"], title)


def process_feeds(
    cfg: dict,
    db_path: Path = _DEFAULT_DB,
    token: str | None = None,
) -> int:
    """Process all RSS feeds and create GitHub issues for new entries.

    Returns the number of issues created.
    """
    press_repo = cfg.get("press_repo", "")
    label = cfg.get("label", "news-article")
    max_age_hours = int(cfg.get("max_age_hours", 48))
    feeds = cfg.get("feeds", [])

    if not press_repo:
        _log.warning("rss_watcher: press_repo not configured — skipping")
        return 0

    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=max_age_hours)
    created = 0

    for feed_cfg in feeds:
        feed_url = feed_cfg.get("url", "")
        source_name = feed_cfg.get("source", feed_url)
        if not feed_url:
            continue

        _log.info("Fetching feed: %s", feed_url)
        try:
            parsed = feedparser.parse(feed_url)
        except Exception as exc:  # noqa: BLE001
            _log.error("Failed to parse feed %s: %s", feed_url, exc)
            continue

        for entry in parsed.entries:
            url = getattr(entry, "link", "")
            if not url:
                continue
            if _is_seen(db_path, url):
                continue

            # Age filter (feedparser returns struct_time; convert to datetime)
            published = getattr(entry, "published_parsed", None)
            if published:
                pub_dt = datetime(*published[:6], tzinfo=timezone.utc)
                if pub_dt < cutoff:
                    _mark_seen(db_path, url)  # Don't re-check old entries
                    continue

            title = getattr(entry, "title", "No title")
            summary = getattr(entry, "summary", "")[:500]

            issue_title = f"Article: {title}"
            issue_body = (
                f"**Source:** {source_name}\n"
                f"**URL:** {url}\n\n"
                f"**Summary:**\n{summary}\n"
            )

            try:
                _create_github_issue(
                    repo=press_repo,
                    title=issue_title,
                    body=issue_body,
                    label=label,
                    token=token,
                )
                _mark_seen(db_path, url)
                created += 1
            except Exception as exc:  # noqa: BLE001
                _log.error("Failed to create issue for %s: %s", url, exc)

    return created


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = _load_config()
    if not cfg:
        _log.warning("rss_watcher: no rss_watcher config found in config.local.yaml")
        return
    token = os.environ.get("GITHUB_TOKEN")
    n = process_feeds(cfg, token=token)
    _log.info("rss_watcher: created %d new issues", n)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests — expect pass**

```bash
python -m pytest tests/test_rss_watcher.py -v
```
Expected: 4 tests pass.

- [ ] **Step 6: Commit**

```bash
git add rss_watcher.py requirements.txt tests/test_rss_watcher.py
git commit -m "feat: add rss_watcher.py — RSS feed poller that creates GitHub issues

Polls RSS feeds from rss_watcher config in config.local.yaml.
Deduplicates by URL (sqlite rss_seen.db). Creates GitHub issues in the
configured press repo with news-article label. Age filter (max_age_hours).

New dependency: feedparser>=6.0

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 6 (PR 6): `repos-available/ai-it-press.yaml`

**Files:**
- Create: `repos-available/ai-it-press.yaml`

No tests — this is a config file. Verified by running a dry-run watch cycle.

- [ ] **Step 1: Create the repo config**

```yaml
# repos-available/ai-it-press.yaml
# Press team configuration for the ai-it-press GitHub repo.
#
# Activate by symlinking:
#   ln -s ../repos-available/ai-it-press.yaml repos-enabled/ai-it-press.yaml
#
# The pipeline YAML is read from the ai-it-press repo itself (pipeline_file:).
# All press-specific logic (stages, discussion presets) lives there.

tracker_repo: wanleung/ai-it-press
default_target: ~
pipeline_file: pipelines/news-article.yaml
parallel_issues: 2
enabled: true

labels:
  news-article: {}          # pipeline loaded from pipeline_file (above)

settings:
  watch_prs: false          # press team does not auto-fix PRs

# LLM config for the press pipeline.
# Uncomment and adjust to override global settings.
# llm:
#   model: "opencode-go/qwen3.6-plus"
#   homework_llm: "ollama/qwen3:8b"
#   overrides:
#     news_writer: "opencode-go/qwen3.6-plus"
#     news_editor: "opencode-go/qwen3.6-plus"
#     discussion: "opencode-go/qwen3.6-plus"
```

- [ ] **Step 2: Verify config parses correctly**

```bash
python -c "
import yaml
with open('repos-available/ai-it-press.yaml') as f:
    cfg = yaml.safe_load(f)
print('tracker_repo:', cfg['tracker_repo'])
print('pipeline_file:', cfg.get('pipeline_file'))
print('labels:', list(cfg.get('labels', {}).keys()))
"
```
Expected output:
```
tracker_repo: wanleung/ai-it-press
pipeline_file: pipelines/news-article.yaml
labels: ['news-article']
```

- [ ] **Step 3: Commit**

```bash
git add repos-available/ai-it-press.yaml
git commit -m "config: add repos-available/ai-it-press.yaml for press team

Press team repo config. Reads pipeline from ai-it-press/pipelines/news-article.yaml.
Activate with: ln -s ../repos-available/ai-it-press.yaml repos-enabled/

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 7 (PR 7 — in ai-it-press): Repo initialisation

**Repo:** `wanleung/ai-it-press`  
**Clone target:** `~/Projects/ai-it-press`

**Files to create:**
- `roles/news_writer.md` → (press-specific override; can differ from ai-software-house default)
- `roles/news_editor.md`
- `discussions/news-analysis.yaml`
- `discussions/news-draft.yaml`
- `pipelines/news-article.yaml`
- `articles/.gitkeep`
- `README.md`

Note: The discussion YAML presets in ai-it-press are loaded by the discussion agent's `DiscussionAgent.from_file()` — but wait, the discussion presets in ai-it-press need to be discovered by the orchestrator. Currently, `_make_stage_registry()` auto-discovers presets from `ai-software-house/discussions/`. The `discuss_news_analysis` and `discuss_news_draft` stages must exist in ai-software-house's `discussions/` directory.

**Important:** Create discussion preset files in `ai-software-house/discussions/` (not in ai-it-press). The `pipelines/news-article.yaml` in ai-it-press references these by stage name (`discuss_news_analysis`, `discuss_news_draft`), and the orchestrator resolves them from its own discussions/ dir.

- [ ] **Step 1: Create `discussions/news-analysis.yaml` in ai-software-house**

```yaml
# discussions/news-analysis.yaml
# Pre-write news analysis discussion.
# Suitable for: researching a news story's angle, key facts, and scope before writing.
#
# Usage in press pipeline:
#   stages:
#     - discuss_news_analysis
#     - news_writer

topic: "News story analysis: what is the real story, what angle should we take, what facts need verification"
max_rounds: 2
early_exit: CONSENSUS_REACHED

participants:
  - role: news_writer
    persona_file: roles/news_writer.md

  - role: news_editor
    persona_file: roles/news_editor.md

homework_round: true    # participants research the story independently first

moderator:
  persona_file: roles/moderator.md

output_mode: both

context_fields:
  - issue_body
```

- [ ] **Step 2: Create `discussions/news-draft.yaml` in ai-software-house**

```yaml
# discussions/news-draft.yaml
# Post-draft news article review discussion.
# Suitable for: writer/editor back-and-forth on draft quality before final edit.
#
# Usage in press pipeline:
#   stages:
#     - news_writer
#     - discuss_news_draft
#     - news_editor

topic: "Draft review: accuracy, clarity, headline quality, and completeness"
max_rounds: 2
early_exit: CONSENSUS_REACHED

participants:
  - role: news_writer
    persona_file: roles/news_writer.md

  - role: news_editor
    persona_file: roles/news_editor.md

homework_round: false   # both agents already have the draft; no research needed

moderator:
  persona_file: roles/moderator.md

output_mode: both

context_fields:
  - issue_body
  - article_draft    # news_writer's draft (PipelineResult.article_draft)
```

- [ ] **Step 3: Commit discussion presets to ai-software-house**

```bash
cd /home/wanleung/Projects/ai-software-house
git add discussions/news-analysis.yaml discussions/news-draft.yaml
git commit -m "feat: add news-analysis and news-draft discussion presets

- discuss_news_analysis: pre-write angle/research debate (homework_round: true)
- discuss_news_draft: post-draft writer/editor review (uses article_draft context)

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

- [ ] **Step 4: Clone ai-it-press**

```bash
cd ~/Projects
git clone https://github.com/wanleung/ai-it-press.git
cd ai-it-press
```

- [ ] **Step 5: Create `pipelines/news-article.yaml`**

```bash
mkdir -p pipelines articles
```

```yaml
# pipelines/news-article.yaml
# Press team pipeline: research → write → review → edit → PR
#
# Stages are resolved against ai-software-house's stage registry.
# Discussions (discuss_news_analysis, discuss_news_draft) auto-discovered
# from ai-software-house/discussions/.

stages:
  - discuss_news_analysis   # research + angle debate (homework round)
  - news_writer             # write article draft
  - discuss_news_draft      # writer/editor review of draft
  - news_editor             # final polish + frontmatter
  - news_article_pr         # commit article, open PR in this repo
```

- [ ] **Step 6: Create `articles/.gitkeep`**

```bash
touch articles/.gitkeep
```

- [ ] **Step 7: Create `README.md`**

```markdown
# ai-it-press

Automated IT press team powered by [ai-software-house](https://github.com/wanleung/ai-dev-team).

## How it works

1. RSS feeds → `rss_watcher.py` creates GitHub issues with `news-article` label
2. ai-software-house picks up the issue and runs the press pipeline:
   - Pre-write analysis discussion (angle, key facts)
   - News writer (first draft)
   - Writer/editor draft review discussion
   - News editor (final polish)
   - Opens PR with the article in `articles/`
3. Human editor reviews and merges the PR
4. GitHub Action converts the article to [hklug-sitegen](https://github.com/wanleung/hklug-sitegen) format and pushes

## Setup

See [ai-software-house case study](https://github.com/wanleung/ai-dev-team/blob/master/docs/case-study-press-team.md).

## Article format

Articles use YAML frontmatter:

\`\`\`markdown
---
title: "Headline"
date: 2026-01-15T10:30:00
author: AI Press Team
source_url: https://original-source
tags: [ai, linux, security]
---

Article body...
\`\`\`
```

- [ ] **Step 8: Commit and push ai-it-press repo init**

```bash
cd ~/Projects/ai-it-press
git add pipelines/ articles/.gitkeep README.md
git commit -m "init: press team pipeline and repo structure

- pipelines/news-article.yaml: 5-stage press pipeline
- articles/.gitkeep: placeholder for article PR files
- README.md: setup and usage guide

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
git push origin main
```

Then open a PR on GitHub for this branch (or push directly to main if it's the initial setup).

---

## Task 8 (PR 8 — in ai-it-press): GitHub Action

**Repo:** `wanleung/ai-it-press`  
**Files:**
- Create: `scripts/convert_articles.py`
- Create: `.github/workflows/publish.yml`
- Test: `tests/test_convert_articles.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_convert_articles.py
"""Tests for the article conversion script."""
from __future__ import annotations
import sys
import tempfile
from pathlib import Path
import pytest


def test_frontmatter_parsed_correctly():
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from convert_articles import parse_article

    md = """---
title: "Linux 6.9 Released"
date: 2026-01-15T10:30:00
author: AI Press Team
source_url: https://linux.com/story
tags: [linux, kernel]
---

The Linux kernel 6.9 has been released...
"""
    meta, body = parse_article(md)
    assert meta["title"] == "Linux 6.9 Released"
    assert "2026-01-15" in meta["date"]
    assert "linux kernel 6.9" in body.lower()


def test_to_sitegen_format():
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from convert_articles import to_sitegen_txt

    meta = {
        "title": "Test Article",
        "date": "2026-01-15T10:30:00",
        "author": "AI Press Team",
    }
    body_md = "## Headline\n\nSome content."
    result = to_sitegen_txt(meta, body_md)
    assert result.startswith("Date: 2026-01-15")
    assert "Author: AI Press Team" in result
    assert "Title: Test Article" in result
    assert "content" in result.lower() or "Headline" in result


def test_output_filename_format():
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from convert_articles import get_output_filename

    meta = {"date": "2026-01-15T10:30:00", "title": "Linux 6.9 Released"}
    name = get_output_filename(meta)
    assert name.startswith("20260115")
    assert name.endswith(".txt")


def test_markdown_body_converted_to_html():
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from convert_articles import to_sitegen_txt

    meta = {"title": "Test", "date": "2026-01-15T10:00:00", "author": "AI Press Team"}
    body = "## Section\n\n**Bold text** and `code`."
    result = to_sitegen_txt(meta, body)
    assert "<h2" in result or "<strong" in result or "<code" in result
```

- [ ] **Step 2: Run test — expect failure**

```bash
cd ~/Projects/ai-it-press
mkdir -p scripts tests
python -m pytest tests/test_convert_articles.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError: No module named 'convert_articles'`

- [ ] **Step 3: Create `scripts/convert_articles.py`**

```python
#!/usr/bin/env python3
"""
convert_articles.py — Convert ai-it-press markdown articles to hklug-sitegen .txt format.

Usage:
    python scripts/convert_articles.py new_articles.txt

    Where new_articles.txt contains one file path per line (relative to repo root).

Pushes converted .txt files to wanleung/hklug-sitegen/data/news/ via GitHub API.
Requires SITEGEN_PAT environment variable.
"""
from __future__ import annotations

import base64
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
import yaml

try:
    import markdown as _md_lib
    _HAS_MARKDOWN = True
except ImportError:
    _HAS_MARKDOWN = False


def parse_article(content: str) -> tuple[dict, str]:
    """Split markdown content into (frontmatter_dict, body_markdown)."""
    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if not fm_match:
        return {}, content
    try:
        meta = yaml.safe_load(fm_match.group(1)) or {}
    except yaml.YAMLError:
        meta = {}
    body = content[fm_match.end():].strip()
    return meta, body


def to_sitegen_txt(meta: dict, body_md: str) -> str:
    """Convert parsed frontmatter + markdown body to hklug-sitegen .txt format."""
    raw_date = str(meta.get("date", ""))
    # Normalise ISO datetime to 'YYYY-MM-DD HH:MM:SS'
    date_str = raw_date[:10] + " " + raw_date[11:19] if len(raw_date) >= 19 else raw_date[:10] + " 00:00:00"

    author = str(meta.get("author", "AI Press Team"))
    title = str(meta.get("title", "Untitled"))

    if _HAS_MARKDOWN:
        body_html = _md_lib.markdown(body_md, extensions=["tables", "fenced_code"])
    else:
        # Minimal fallback: convert ## headers and **bold** without external dep
        body_html = re.sub(r"^## (.+)$", r"<h2>\1</h2>", body_md, flags=re.MULTILINE)
        body_html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", body_html)
        body_html = re.sub(r"`(.+?)`", r"<code>\1</code>", body_html)

    return (
        f"Date: {date_str}\n"
        f"Author: {author}\n"
        f"Title: {title}\n"
        f"\n"
        f"{body_html}\n"
    )


def get_output_filename(meta: dict) -> str:
    """Generate hklug-sitegen filename: YYYYMMDD-HHMMSS.txt"""
    raw_date = str(meta.get("date", datetime.utcnow().isoformat()))
    # Parse datetime
    try:
        dt = datetime.fromisoformat(raw_date[:19])
    except ValueError:
        dt = datetime.utcnow()
    return dt.strftime("%Y%m%d-%H%M%S") + ".txt"


def push_to_sitegen(filename: str, content: str, sitegen_repo: str, pat: str) -> None:
    """Push a .txt file to hklug-sitegen/data/news/ via GitHub API."""
    path = f"data/news/{filename}"
    url = f"https://api.github.com/repos/{sitegen_repo}/contents/{path}"
    headers = {
        "Authorization": f"Bearer {pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    # Check if file exists (for update)
    sha = None
    existing = requests.get(url, headers=headers, timeout=10)
    if existing.status_code == 200:
        sha = existing.json().get("sha")

    body: dict[str, Any] = {
        "message": f"article: publish {filename}",
        "content": base64.b64encode(content.encode()).decode(),
        "branch": "master",
    }
    if sha:
        body["sha"] = sha

    resp = requests.put(url, headers=headers, json=body, timeout=15)
    resp.raise_for_status()
    print(f"Pushed {filename} to {sitegen_repo}")


def main(articles_list_file: str) -> None:
    sitegen_repo = os.environ.get("SITEGEN_REPO", "wanleung/hklug-sitegen")
    pat = os.environ.get("SITEGEN_PAT", "")
    if not pat:
        print("ERROR: SITEGEN_PAT environment variable not set", file=sys.stderr)
        sys.exit(1)

    list_path = Path(articles_list_file)
    if not list_path.exists():
        print(f"ERROR: {articles_list_file} not found", file=sys.stderr)
        sys.exit(1)

    article_paths = [p.strip() for p in list_path.read_text().splitlines() if p.strip()]
    if not article_paths:
        print("No articles to publish.")
        return

    for article_path in article_paths:
        p = Path(article_path)
        if not p.exists():
            print(f"WARNING: {article_path} not found — skipping")
            continue
        content = p.read_text(encoding="utf-8")
        meta, body = parse_article(content)
        txt = to_sitegen_txt(meta, body)
        filename = get_output_filename(meta)
        push_to_sitegen(filename, txt, sitegen_repo, pat)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <articles-list-file>")
        sys.exit(1)
    main(sys.argv[1])
```

- [ ] **Step 4: Run tests — expect pass**

```bash
pip install markdown  # if not already installed
python -m pytest tests/test_convert_articles.py -v
```
Expected: 4 tests pass.

- [ ] **Step 5: Create `.github/workflows/publish.yml`**

```yaml
name: Publish articles to hklug-sitegen

on:
  pull_request:
    types: [closed]
    branches: [main]

jobs:
  publish:
    if: github.event.pull_request.merged == true
    runs-on: ubuntu-latest

    steps:
      - name: Checkout ai-it-press
        uses: actions/checkout@v4
        with:
          fetch-depth: 2

      - name: Find articles added in this PR
        id: find
        run: |
          git diff --name-only HEAD~1 HEAD -- 'articles/*.md' > /tmp/new_articles.txt
          echo "Found articles:"
          cat /tmp/new_articles.txt

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install requests pyyaml markdown

      - name: Convert and push to hklug-sitegen
        env:
          SITEGEN_PAT: ${{ secrets.SITEGEN_PAT }}
          SITEGEN_REPO: wanleung/hklug-sitegen
        run: python scripts/convert_articles.py /tmp/new_articles.txt
```

- [ ] **Step 6: Add SITEGEN_PAT secret to ai-it-press**

In the GitHub UI:
- Go to `wanleung/ai-it-press` → Settings → Secrets → Actions
- Add secret: `SITEGEN_PAT` = a GitHub PAT with `contents:write` scope on `wanleung/hklug-sitegen`

- [ ] **Step 7: Commit and push**

```bash
cd ~/Projects/ai-it-press
git add scripts/convert_articles.py .github/workflows/publish.yml tests/test_convert_articles.py
git commit -m "feat: GitHub Action to publish articles to hklug-sitegen

On PR merge, find new articles/, convert markdown+frontmatter to
hklug-sitegen .txt format, push to wanleung/hklug-sitegen/data/news/.

scripts/convert_articles.py: standalone converter (markdown→HTML, sitegen format)
tests/test_convert_articles.py: parse, convert, filename tests

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
git push origin main
```

---

## Self-Review Checklist

- [x] Spec coverage: fetch_url ✓, news_writer ✓, news_editor ✓, discuss presets ✓, pipeline_file ✓, rss_watcher ✓, repo config ✓, ai-it-press init ✓, GitHub Action ✓
- [x] No placeholders: all code blocks complete
- [x] Type consistency: `article_draft`/`article` named consistently across Tasks 2, 3 and discussion YAML
- [x] `discuss_news_analysis` and `discuss_news_draft` are in ai-software-house `discussions/` (not ai-it-press) — this is required for the orchestrator's auto-discovery to find them
- [x] `pipeline_file:` feature correctly uses `tracker_gh.get_file_content()` (tracker_repo = ai-it-press, so it fetches from the right place)
- [x] `news_article_pr` opens PR via `_commit_and_open_pr()` which uses `self.target_github or self.github`; for press pipeline `github` is the ai-it-press client — correct
- [x] `rss_watcher.py` is a standalone script, not imported by orchestrator — no circular deps
