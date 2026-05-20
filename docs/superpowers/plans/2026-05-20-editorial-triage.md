# Editorial Triage Stage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `news_triage` stage as the first step in the press pipeline so a 3-editor AI team can vote PUBLISH or SKIP on each story, closing irrelevant issues and passing angle guidance to the writer on approval.

**Architecture:** A `discussions/news-triage.yaml` preset drives the existing `_stage_discuss()` mechanism with three participants (`editorial_director`, `audience_specialist`, `news_editor`). A thin wrapper `_stage_news_triage()` parses the structured verdict from the discussion synthesis, posts a comment + closes the GitHub issue on SKIP, and uses the existing `PipelineStage.stop_if` mechanism to abort the pipeline. On PUBLISH, `editorial_notes` stored on `PipelineResult` are prepended to the writer's prompt in `_stage_news_writer()`.

**Tech Stack:** Python 3.11, Pydantic v2, PyYAML, pytest, existing `DiscussionAgent`, `GitHubClient`, `PipelineStage.stop_if`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `discussions/news-triage.yaml` | Create | Discussion preset: participants, rounds, context_fields, verdict_format |
| `roles/editorial_director.md` | Create | Role prompt: strategic IT relevance, story substance |
| `roles/audience_specialist.md` | Create | Role prompt: HK Cantonese tech audience fit |
| `config_schema.py` | Modify | `TriageConfig`, `PressConfig` Pydantic models; add `press` field to `AppConfig` |
| `config.yaml` | Modify | Add `press.triage` section with scope |
| `orchestrator.py` | Modify | `PipelineResult` fields, `_parse_triage_verdict()`, `_stage_news_triage()`, stage registry, `_stage_news_writer()` editorial notes injection |
| `pipelines/news-article.yaml` | Modify | Prepend `news_triage` stage (wrapper, not discuss_news_triage) |
| `tests/test_news_triage.py` | Create | Unit tests for `_parse_triage_verdict()` and discussion YAML validity |
| `tests/test_news_stages.py` | Modify | Stage tests for `_stage_news_triage()` PUBLISH/SKIP/fail-open + editorial notes injection |

---

## Task 1: Config files — discussion YAML, role prompts, config schema

**Files:**
- Create: `discussions/news-triage.yaml`
- Create: `roles/editorial_director.md`
- Create: `roles/audience_specialist.md`
- Modify: `config_schema.py` (add `TriageConfig`, `PressConfig`, update `AppConfig`)
- Modify: `config.yaml` (add `press:` section)

- [ ] **Step 1: Create `discussions/news-triage.yaml`**

Match the format used in `discussions/news-analysis.yaml` — the existing `DiscussionAgent.from_file()` parser requires `topic`, `participants` list with `role`/`persona_file`, `homework_round`, `max_rounds`, `early_exit`, `moderator`, `output_mode`, and `context_fields`.

```yaml
# discussions/news-triage.yaml
# Editorial triage discussion — vote PUBLISH or SKIP before pipeline runs.
#
# Usage in press pipeline:
#   stages:
#     - discuss_news_triage   # ← first stage; pipeline aborts on SKIP
#     - discuss_news_analysis
#     - news_writer

topic: "Editorial triage: should we publish this story? Vote PUBLISH or SKIP with brief rationale."
max_rounds: 2
early_exit: CONSENSUS_REACHED

participants:
  - role: editorial_director
    persona_file: roles/editorial_director.md
    homework_llm: "ollama/thinker"

  - role: audience_specialist
    persona_file: roles/audience_specialist.md
    homework_llm: "ollama/thinker"

  - role: news_editor
    persona_file: roles/news_editor.md

homework_round: true

moderator:
  persona_file: roles/moderator.md

output_mode: both

context_fields:
  - issue_body
  - triage_scope

verdict_format: |
  At the end of your final message, include exactly:
  VERDICT: PUBLISH
  EDITORIAL_NOTES: <one sentence: the angle or focus the writer should take>

  OR if the story should be skipped:
  VERDICT: SKIP
  EDITORIAL_NOTES: <one sentence: why this story was skipped>
```

- [ ] **Step 2: Create `roles/editorial_director.md`**

```markdown
# Editorial Director

You are the Editorial Director of an independent Hong Kong IT press outlet.

Your job in the editorial triage meeting is to evaluate whether a news story is worth publishing.

## Your evaluation criteria

**Publish if:**
- The story is in-scope for IT/technology (AI, software development, cybersecurity, cloud, open-source, enterprise software, Hong Kong tech scene)
- The story has genuine news value — something new happened, was released, or was announced
- There is enough substance to write a 400–700 word article

**Skip if:**
- The story is off-topic (entertainment, sports, general business news with no tech angle)
- The story is purely promotional content with no real news hook
- The source is unreliable or the story has no verifiable facts
- A nearly identical story was recently published

## Triage context

The current editorial scope and audience is described in the `triage_scope` context above.
Use this to calibrate your relevance judgment.

## Discussion format

- State your PUBLISH or SKIP position clearly
- Give a one-sentence rationale
- In your final message, end with exactly:
  `VERDICT: PUBLISH` or `VERDICT: SKIP`
  `EDITORIAL_NOTES: <angle for writer, or reason for skip>`
```

- [ ] **Step 3: Create `roles/audience_specialist.md`**

```markdown
# Audience Specialist

You are the Audience Specialist for an independent Hong Kong IT press outlet targeting Cantonese-speaking technology professionals.

Your job in the editorial triage meeting is to evaluate whether a story will resonate with the target audience.

## Target audience profile

- Location: Hong Kong, Macau, and the Cantonese-speaking diaspora
- Professional background: software engineers, IT managers, DevOps, security professionals, tech entrepreneurs
- Language preference: reads Traditional Chinese (繁體中文) and Cantonese (廣東話)
- Interests: practical tools, career-relevant technology, regional tech developments, open-source

## Your evaluation criteria

**Publish if:**
- HK/regional professionals will find this directly useful or interesting
- The story has a local angle (affects HK companies, regulations, the regional tech ecosystem)
- The technology is mainstream enough that a generalist IT professional will care

**Skip if:**
- The story is only relevant to a niche academic or research audience
- It's US/EU-centric with no relevance to the HK market
- It duplicates coverage the audience already gets from mainstream tech media

## Triage context

The current editorial scope and audience is described in the `triage_scope` context above.
Use this to calibrate your relevance judgment.

## Discussion format

- State your PUBLISH or SKIP position clearly
- Give a one-sentence rationale
- In your final message, end with exactly:
  `VERDICT: PUBLISH` or `VERDICT: SKIP`
  `EDITORIAL_NOTES: <audience angle for writer, or reason for skip>`
```

- [ ] **Step 4: Add `TriageConfig` and `PressConfig` to `config_schema.py`**

`AppConfig` uses `model_config = {"extra": "forbid"}` so a new `press` field requires proper Pydantic models. Add these classes **before** the `AppConfig` class definition (around line 155). Then add `press: Optional[PressConfig] = None` to `AppConfig`.

Find the line `class AppConfig(BaseModel):` and insert before it:

```python
class TriageConfig(BaseModel):
    model_config = {"extra": "allow"}

    scope: str = (
        "Focus areas: AI, software development tools, cybersecurity, Hong Kong tech scene, "
        "enterprise software, open-source.\n"
        "Audience: HK Cantonese-speaking tech professionals."
    )
    min_score: int = 2


class PressConfig(BaseModel):
    model_config = {"extra": "allow"}

    triage: TriageConfig = Field(default_factory=TriageConfig)
```

Then add `press: Optional[PressConfig] = None` to the `AppConfig` field list.

- [ ] **Step 5: Add `press:` section to `config.yaml`**

Find the `pipeline:` section (around line 270) and add the `press:` section after it:

```yaml
press:
  triage:
    scope: |
      Focus areas: AI, software development tools, cybersecurity, Hong Kong tech scene,
      enterprise software, open-source.
      Audience: HK Cantonese-speaking tech professionals.
    min_score: 2
```

- [ ] **Step 6: Verify config loads without errors**

```bash
cd /home/wanleung/Projects/ai-software-house
python3 -c "from config_schema import load_config; c = load_config('config.yaml'); print('OK', c.press)"
```

Expected: `OK triage=TriageConfig(scope=..., min_score=2)`

- [ ] **Step 7: Commit**

```bash
git add discussions/news-triage.yaml roles/editorial_director.md roles/audience_specialist.md config_schema.py config.yaml
git commit -m "feat: add editorial triage YAML, role files, and config schema

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 2: PipelineResult fields

**Files:**
- Modify: `orchestrator.py` — `PipelineResult` dataclass, `to_dict()`, `from_dict()`
- Modify: `tests/test_news_triage.py` — create with serialisation tests

- [ ] **Step 1: Write the failing test first**

Create `tests/test_news_triage.py`:

```python
"""Tests for editorial triage — verdict parsing and PipelineResult fields."""
import pytest
import yaml
from pathlib import Path


# ── PipelineResult field tests ───────────────────────────────────────────────

def test_pipeline_result_has_triage_fields():
    """PipelineResult must expose editorial_verdict, editorial_notes, triage_scope."""
    from orchestrator import PipelineResult
    r = PipelineResult(requirement="test")
    assert r.editorial_verdict == ""
    assert r.editorial_notes == ""
    assert r.triage_scope == ""


def test_pipeline_result_triage_fields_serialise():
    """editorial_verdict, editorial_notes, triage_scope round-trip through to_dict/from_dict."""
    from orchestrator import PipelineResult
    r = PipelineResult(requirement="test")
    r.editorial_verdict = "PUBLISH"
    r.editorial_notes = "Focus on the security implications"
    r.triage_scope = "AI, cybersecurity"
    d = r.to_dict()
    assert d["editorial_verdict"] == "PUBLISH"
    assert d["editorial_notes"] == "Focus on the security implications"
    assert d["triage_scope"] == "AI, cybersecurity"
    r2 = PipelineResult.from_dict(d)
    assert r2.editorial_verdict == "PUBLISH"
    assert r2.editorial_notes == "Focus on the security implications"
    assert r2.triage_scope == "AI, cybersecurity"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/wanleung/Projects/ai-software-house
python3 -m pytest tests/test_news_triage.py::test_pipeline_result_has_triage_fields -v
```

Expected: FAIL with `AttributeError: 'PipelineResult' object has no attribute 'editorial_verdict'`

- [ ] **Step 3: Add fields to `PipelineResult` dataclass in `orchestrator.py`**

Find the comment `# News reviewer stage outputs` (around line 422) and add after the `article_review_retry_count` line:

```python
    # Editorial triage stage outputs
    editorial_verdict: str = ""   # "PUBLISH" or "SKIP"
    editorial_notes: str = ""     # angle/focus for writer, or reason for skip
    triage_scope: str = ""        # injected from config; passed to discussion as context
```

- [ ] **Step 4: Add fields to `to_dict()` in `orchestrator.py`**

Find the line `"article_review_retry_count": self.article_review_retry_count,` in `to_dict()` and add after it:

```python
            "editorial_verdict": self.editorial_verdict,
            "editorial_notes": self.editorial_notes,
            "triage_scope": self.triage_scope,
```

- [ ] **Step 5: Add fields to `from_dict()` in `orchestrator.py`**

`from_dict()` uses a `for key in [...]` loop with `setattr(r, key, data.get(key, getattr(r, key)))`.
Find the line `"article_reviewer_notes", "article_review_retry_count",` in the key list and add after it:

```python
                    "editorial_verdict", "editorial_notes", "triage_scope",
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
cd /home/wanleung/Projects/ai-software-house
python3 -m pytest tests/test_news_triage.py -v
```

Expected: 2 passed

- [ ] **Step 7: Confirm existing tests still pass**

```bash
python3 -m pytest tests/test_news_stages.py tests/test_news_reviewer.py -q
```

Expected: 37 passed

- [ ] **Step 8: Commit**

```bash
git add orchestrator.py tests/test_news_triage.py
git commit -m "feat: add editorial_verdict, editorial_notes, triage_scope to PipelineResult

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 3: `_parse_triage_verdict()` — unit tests first

**Files:**
- Modify: `orchestrator.py` — add `_parse_triage_verdict()` method
- Modify: `tests/test_news_triage.py` — add verdict parsing tests

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_news_triage.py`:

```python
# ── _parse_triage_verdict() tests ────────────────────────────────────────────

def _make_minimal_orchestrator():
    """Create the smallest Orchestrator that lets us call _parse_triage_verdict."""
    from unittest.mock import MagicMock, patch
    with patch("orchestrator.Orchestrator.__init__", return_value=None):
        from orchestrator import Orchestrator
        orch = Orchestrator.__new__(Orchestrator)
    return orch


def test_parse_verdict_publish():
    """Standard PUBLISH output returns verdict=PUBLISH and notes."""
    orch = _make_minimal_orchestrator()
    text = (
        "This story is highly relevant to our HK tech audience.\n"
        "VERDICT: PUBLISH\n"
        "EDITORIAL_NOTES: Focus on the open-source tooling implications for local DevOps teams."
    )
    result = orch._parse_triage_verdict(text)
    assert result["verdict"] == "PUBLISH"
    assert "open-source" in result["notes"]


def test_parse_verdict_skip():
    """Standard SKIP output returns verdict=SKIP and notes."""
    orch = _make_minimal_orchestrator()
    text = (
        "This story is off-topic for our readership.\n"
        "VERDICT: SKIP\n"
        "EDITORIAL_NOTES: Story covers US sports industry with no tech angle."
    )
    result = orch._parse_triage_verdict(text)
    assert result["verdict"] == "SKIP"
    assert "sports" in result["notes"]


def test_parse_verdict_case_insensitive():
    """Lowercase 'publish' is accepted (fail-open)."""
    orch = _make_minimal_orchestrator()
    text = "verdict: publish\nEDITORIAL_NOTES: Good story."
    result = orch._parse_triage_verdict(text)
    assert result["verdict"] == "PUBLISH"


def test_parse_verdict_malformed_no_verdict_line():
    """Missing VERDICT line → fail-open: PUBLISH."""
    orch = _make_minimal_orchestrator()
    text = "The discussion was inconclusive. No clear consensus."
    result = orch._parse_triage_verdict(text)
    assert result["verdict"] == "PUBLISH"
    assert result["notes"] == ""


def test_parse_verdict_fail_open_on_exception():
    """Non-string input → fail-open: PUBLISH (never raises)."""
    orch = _make_minimal_orchestrator()
    result = orch._parse_triage_verdict(None)  # type: ignore[arg-type]
    assert result["verdict"] == "PUBLISH"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /home/wanleung/Projects/ai-software-house
python3 -m pytest tests/test_news_triage.py::test_parse_verdict_publish -v
```

Expected: FAIL with `AttributeError: '_parse_triage_verdict'`

- [ ] **Step 3: Implement `_parse_triage_verdict()` in `orchestrator.py`**

Add this method to the `Orchestrator` class, just before `_stage_news_writer()` (around line 4217):

```python
    @staticmethod
    def _parse_triage_verdict(text) -> dict:
        """Parse VERDICT and EDITORIAL_NOTES from triage discussion synthesis.

        Returns {"verdict": "PUBLISH"|"SKIP", "notes": str}.
        Always returns PUBLISH on any parse failure (fail-open — never silently drops a story).
        """
        try:
            if not isinstance(text, str):
                return {"verdict": "PUBLISH", "notes": ""}
            verdict_match = re.search(r"VERDICT\s*:\s*(PUBLISH|SKIP)", text, re.IGNORECASE)
            if not verdict_match:
                return {"verdict": "PUBLISH", "notes": ""}
            verdict = verdict_match.group(1).upper()
            notes_match = re.search(r"EDITORIAL_NOTES\s*:\s*(.+)", text, re.IGNORECASE)
            notes = notes_match.group(1).strip() if notes_match else ""
            return {"verdict": verdict, "notes": notes}
        except Exception:
            return {"verdict": "PUBLISH", "notes": ""}
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd /home/wanleung/Projects/ai-software-house
python3 -m pytest tests/test_news_triage.py -v
```

Expected: 7 passed (2 from Task 2 + 5 new)

- [ ] **Step 5: Commit**

```bash
git add orchestrator.py tests/test_news_triage.py
git commit -m "feat: add _parse_triage_verdict() with fail-open logic

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 4: `_stage_news_triage()` — PUBLISH path + stage tests

**Files:**
- Modify: `orchestrator.py` — add `_stage_news_triage()` method
- Modify: `tests/test_news_stages.py` — add triage stage tests

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_news_stages.py` (after the existing `_make_minimal_orchestrator` helper at the top of the file — check the file, it likely already has a similar helper):

```python
# ── _stage_news_triage() tests ───────────────────────────────────────────────

def test_stage_triage_publish_path(make_orch):
    """PUBLISH verdict: editorial_notes stored, no abort, issue not closed."""
    from unittest.mock import patch, MagicMock
    from orchestrator import PipelineResult

    result = PipelineResult(requirement="test story brief")
    result.issue_number = 42

    # Synthesized output from discuss_news_triage
    synthesis = (
        "After discussion, the team agrees this story is relevant.\n"
        "VERDICT: PUBLISH\n"
        "EDITORIAL_NOTES: Emphasise the open-source licensing implications."
    )

    orch = make_orch()
    orch._cfg = {"press": {"triage": {"scope": "AI, cybersecurity", "min_score": 2}}}

    def fake_discuss(r, config_path):
        r.discussion_synthesis = synthesis

    with patch.object(orch, "_stage_discuss", side_effect=fake_discuss):
        orch._stage_news_triage(result)

    assert result.editorial_verdict == "PUBLISH"
    assert "open-source" in result.editorial_notes
    assert result.triage_scope == "AI, cybersecurity"


def test_stage_triage_skip_path(make_orch):
    """SKIP verdict: editorial_verdict=SKIP, GitHub issue closed with comment."""
    from unittest.mock import patch, MagicMock, call
    from orchestrator import PipelineResult

    result = PipelineResult(requirement="test story brief")
    result.issue_number = 99

    synthesis = (
        "This story has no tech angle.\n"
        "VERDICT: SKIP\n"
        "EDITORIAL_NOTES: Off-topic — covers entertainment, not IT."
    )

    orch = make_orch()
    orch._cfg = {"press": {"triage": {"scope": "AI, cybersecurity", "min_score": 2}}}
    mock_gh = MagicMock()
    orch.github = mock_gh
    orch.target_github = mock_gh

    def fake_discuss(r, config_path):
        r.discussion_synthesis = synthesis

    with patch.object(orch, "_stage_discuss", side_effect=fake_discuss):
        orch._stage_news_triage(result)

    assert result.editorial_verdict == "SKIP"
    assert "entertainment" in result.editorial_notes
    mock_gh.add_issue_comment.assert_called_once()
    comment_body = mock_gh.add_issue_comment.call_args[0][1]
    assert "SKIP" in comment_body
    mock_gh.close_issue.assert_called_once_with(99)


def test_stage_triage_fail_open(make_orch):
    """If _stage_discuss raises, verdict defaults to PUBLISH (never blocks pipeline)."""
    from unittest.mock import patch
    from orchestrator import PipelineResult

    result = PipelineResult(requirement="test")
    result.issue_number = 1
    orch = make_orch()
    orch._cfg = {"press": {"triage": {"scope": "AI", "min_score": 2}}}

    with patch.object(orch, "_stage_discuss", side_effect=RuntimeError("LLM timeout")):
        orch._stage_news_triage(result)

    assert result.editorial_verdict == "PUBLISH"
    assert result.editorial_notes == ""
```

**Note:** Check how `make_orch` or `_make_minimal_orchestrator` is defined in `tests/test_news_stages.py` (look for an existing fixture or helper at the top of the file). If it's a `pytest.fixture` named `make_orch`, use the pattern above. If it's a standalone function named `_make_minimal_orchestrator()`, call it directly instead.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /home/wanleung/Projects/ai-software-house
python3 -m pytest tests/test_news_stages.py::test_stage_triage_publish_path -v
```

Expected: FAIL with `AttributeError: 'Orchestrator' object has no attribute '_stage_news_triage'`

- [ ] **Step 3: Implement `_stage_news_triage()` in `orchestrator.py`**

Add this method immediately after `_parse_triage_verdict()` and before `_stage_news_writer()`:

```python
    def _stage_news_triage(self, result: "PipelineResult") -> None:
        """Run the editorial triage discussion and act on the verdict.

        PUBLISH: stores editorial_verdict + editorial_notes on result; pipeline continues.
        SKIP:    posts a comment to the GitHub issue, closes it, sets editorial_verdict=SKIP.
                 The stage registry's stop_if=lambda r: r.editorial_verdict=="SKIP" halts the pipeline.
        Fail-open: any exception → PUBLISH; story is never silently dropped.
        """
        # Inject triage scope from config into PipelineResult (DiscussionAgent reads it via context_fields)
        press_cfg = (self._cfg or {}).get("press", {}) or {}
        triage_cfg = press_cfg.get("triage", {}) or {}
        result.triage_scope = str(triage_cfg.get("scope", "")).strip()

        config_path = str(Path(__file__).parent / "discussions" / "news-triage.yaml")
        try:
            self._stage_discuss(result, config_path=config_path)
        except Exception as exc:
            log.warning("_stage_news_triage: discussion failed (%s) — defaulting to PUBLISH (fail-open)", exc)
            result.editorial_verdict = "PUBLISH"
            result.editorial_notes = ""
            return

        synthesis = result.discussion_synthesis or ""
        parsed = self._parse_triage_verdict(synthesis)
        result.editorial_verdict = parsed["verdict"]
        result.editorial_notes = parsed["notes"]

        if parsed["verdict"] == "SKIP":
            log.info("Editorial triage SKIP: %s", parsed["notes"])
            console.print(f"  🚫 [bold yellow]Editorial triage: SKIP[/bold yellow] — {parsed['notes']}")
            # Close the GitHub issue with an explanation comment
            gh = self.target_github or self.github
            if gh and result.issue_number:
                comment = (
                    f"## 🚫 Editorial Triage: SKIP\n\n"
                    f"**Reason:** {parsed['notes']}\n\n"
                    f"<details><summary>Discussion summary</summary>\n\n{synthesis}\n\n</details>\n\n"
                    f"_This story was reviewed by the editorial team and will not be published._"
                )
                try:
                    gh.add_issue_comment(result.issue_number, comment)
                except Exception as exc:
                    log.warning("_stage_news_triage: failed to post skip comment: %s", exc)
                try:
                    gh.close_issue(result.issue_number)
                except Exception as exc:
                    log.warning("_stage_news_triage: failed to close issue: %s", exc)
        else:
            console.print(f"  ✅ [green]Editorial triage: PUBLISH[/green] — {parsed['notes']}")
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd /home/wanleung/Projects/ai-software-house
python3 -m pytest tests/test_news_stages.py::test_stage_triage_publish_path tests/test_news_stages.py::test_stage_triage_skip_path tests/test_news_stages.py::test_stage_triage_fail_open -v
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add orchestrator.py tests/test_news_stages.py
git commit -m "feat: implement _stage_news_triage() with PUBLISH/SKIP/fail-open paths

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 5: Wire up — stage registry, pipeline YAML, editorial notes in writer

**Files:**
- Modify: `orchestrator.py` — stage registry entry, `_stage_news_writer()` editorial notes injection
- Modify: `pipelines/news-article.yaml` — prepend `discuss_news_triage`
- Modify: `tests/test_news_stages.py` — test editorial notes injection + YAML test
- Modify: `tests/test_news_triage.py` — YAML validity test

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_news_triage.py`:

```python
# ── Discussion YAML validity test ────────────────────────────────────────────

def test_news_triage_yaml_valid():
    """discussions/news-triage.yaml must load cleanly and reference existing role files."""
    from pathlib import Path
    import yaml

    yaml_path = Path("discussions/news-triage.yaml")
    assert yaml_path.is_file(), "discussions/news-triage.yaml not found"
    data = yaml.safe_load(yaml_path.read_text())

    assert "participants" in data
    assert len(data["participants"]) >= 2
    assert "context_fields" in data
    assert "issue_body" in data["context_fields"]
    assert "triage_scope" in data["context_fields"]

    roles_dir = Path("roles")
    for participant in data["participants"]:
        persona_file = participant.get("persona_file", "")
        assert persona_file, f"participant {participant} missing persona_file"
        assert Path(persona_file).is_file(), f"Role file not found: {persona_file}"
```

Add to `tests/test_news_stages.py`:

```python
def test_stage_news_writer_prepends_editorial_notes(make_orch):
    """If result.editorial_notes is set, news_writer prompt includes the notes."""
    from unittest.mock import patch, MagicMock
    from orchestrator import PipelineResult

    result = PipelineResult(requirement="brief")
    result.editorial_notes = "Focus on the security angle for HK enterprises."
    result.discussion_synthesis = ""

    orch = make_orch()
    captured_prompt = []

    def fake_call(prompt):
        captured_prompt.append(prompt)
        return "---\ntitle: Test\n---\n\nArticle body."

    with patch.object(orch.news_writer, "call", side_effect=fake_call):
        orch._stage_news_writer(result)

    assert result.article_draft.strip()
    assert len(captured_prompt) == 1
    assert "EDITORIAL NOTES" in captured_prompt[0]
    assert "security angle" in captured_prompt[0]
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /home/wanleung/Projects/ai-software-house
python3 -m pytest tests/test_news_triage.py::test_news_triage_yaml_valid tests/test_news_stages.py::test_stage_news_writer_prepends_editorial_notes -v
```

Expected: both FAIL

- [ ] **Step 3: Register `news_triage` stage in `_build_stage_registry()`**

Find the stage registry block in `orchestrator.py` (around line 1920 where `news_writer` is registered). Add the `news_triage` entry **before** `news_writer`:

```python
            "news_triage": PipelineStage(
                name="news_triage",
                label="🗞️  Editorial Triage",
                description="Editorial team voting: publish or skip?",
                checkpoint_key="news_triage",
                fn=lambda r: self._stage_news_triage(r),
                stop_if=lambda r: r.editorial_verdict == "SKIP",
                stop_message="🚫 Editorial triage: story skipped — pipeline aborted.",
            ),
```

- [ ] **Step 4: Add `discuss_news_triage` to `pipelines/news-article.yaml`**

The pipeline YAML uses stage names from the stage registry. The discussion preset auto-registers as `discuss_<name>` (from the YAML filename). But `news_triage` is a custom wrapper stage registered directly. Add it as the first entry:

Open `pipelines/news-article.yaml` and prepend:

```yaml
  - news_triage                 # editorial triage: PUBLISH continues, SKIP closes issue + aborts
```

The file currently starts with:
```yaml
# Discussions (discuss_news_analysis, discuss_news_draft) auto-discovered
```

The stages list begins after that comment. Prepend `- news_triage` as the first stage.

- [ ] **Step 5: Modify `_stage_news_writer()` to inject editorial notes**

Find `_stage_news_writer()` in `orchestrator.py`:

```python
    def _stage_news_writer(self, result: PipelineResult) -> None:
        """Write a first-draft news article from the issue brief."""
        issue_body = getattr(result, "issue_body", "") or result.requirement
        synthesis = result.discussion_synthesis or ""
        wr = self.news_writer.run(issue_body, discussion_synthesis=synthesis)
```

Replace the body with:

```python
    def _stage_news_writer(self, result: PipelineResult) -> None:
        """Write a first-draft news article from the issue brief."""
        issue_body = getattr(result, "issue_body", "") or result.requirement
        synthesis = result.discussion_synthesis or ""
        # Prepend editorial triage notes to the issue body so the writer knows the agreed angle
        if result.editorial_notes:
            issue_body = (
                f"[EDITORIAL NOTES]\n{result.editorial_notes}\n\n"
                + issue_body
            )
        wr = self.news_writer.run(issue_body, discussion_synthesis=synthesis)
        if not wr.get("article_draft", "").strip():
            raise RuntimeError("NewsWriter produced an empty draft — LLM may have returned no content.")
        result.article_draft = wr["article_draft"]
        # Do NOT clear discussion_synthesis here — if discuss_news_draft runs next it
        # will overwrite it; if it doesn't run the editor should still see the
        # pre-write analysis synthesis from discuss_news_analysis.
```

- [ ] **Step 6: Run the new tests**

```bash
cd /home/wanleung/Projects/ai-software-house
python3 -m pytest tests/test_news_triage.py::test_news_triage_yaml_valid tests/test_news_stages.py::test_stage_news_writer_prepends_editorial_notes -v
```

Expected: 2 passed

- [ ] **Step 7: Run the full test suites**

```bash
python3 -m pytest tests/test_news_triage.py tests/test_news_stages.py tests/test_news_reviewer.py -v
```

Expected: all passing (8 triage + 31 stages + 10 reviewer = ~49 tests)

- [ ] **Step 8: Commit**

```bash
git add orchestrator.py pipelines/news-article.yaml tests/test_news_triage.py tests/test_news_stages.py
git commit -m "feat: wire up news_triage stage — registry, pipeline YAML, editorial notes in writer

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 6: Full test suite run + open PR

**Files:**
- No new files — verification + PR only

- [ ] **Step 1: Run the full test suite**

```bash
cd /home/wanleung/Projects/ai-software-house
python3 -m pytest --ignore=tests/test_deployment.py -x -q 2>&1 | tail -20
```

Expected: all tests pass except the known pre-existing failures in `tests/test_deployment.py` (require live server) and `tests/test_qa_clarification.py::test_full_qa_round_trip` (pre-existing mock mismatch).

If any new failures appear, fix them before proceeding.

- [ ] **Step 2: Confirm baseline is preserved**

```bash
python3 -m pytest tests/test_news_stages.py tests/test_news_reviewer.py tests/test_news_triage.py -q
```

Expected: 49+ passed, 0 failed

- [ ] **Step 3: Push branch and open PR**

We're working on master directly (no worktree was set up for this feature — check with `git branch`). If on master, push and open the PR with a `feature/` branch:

```bash
git checkout -b feature/editorial-triage
git push -u origin feature/editorial-triage
gh pr create \
  --title "feat: editorial triage stage — filter news stories before pipeline runs" \
  --body "## Summary

Adds a \`news_triage\` stage as the first step in the press pipeline. A 3-editor AI team (editorial_director, audience_specialist, news_editor) votes PUBLISH or SKIP on each incoming story before the expensive writing and translation stages run.

### Changes
- \`discussions/news-triage.yaml\` — triage discussion preset
- \`roles/editorial_director.md\` — new role: strategic IT relevance
- \`roles/audience_specialist.md\` — new role: HK Cantonese audience fit
- \`orchestrator.py\` — \`PipelineResult\` fields, \`_parse_triage_verdict()\`, \`_stage_news_triage()\`, stage registry entry, editorial notes in writer
- \`pipelines/news-article.yaml\` — \`news_triage\` prepended as first stage
- \`config_schema.py\` — \`TriageConfig\`, \`PressConfig\` models
- \`config.yaml\` — \`press.triage\` scope config

### Behaviour
- **PUBLISH**: stores editorial notes → passed to news writer as angle guidance
- **SKIP**: posts comment + closes GitHub issue → pipeline aborts via \`stop_if\`
- **Fail-open**: any LLM/discussion failure → PUBLISH (never silently drops a story)
- **Tuning**: edit \`config.yaml\` \`press.triage.scope\` or role \`.md\` files; no code changes needed

Closes #<issue>" \
  --head feature/editorial-triage \
  --base master
```

If already on a feature branch, just push and create the PR normally.

---

## Pre-existing known failures (do NOT fix)

These failures exist on master before this feature and are unrelated:

- `tests/test_deployment.py` — 6 tests require a live running server
- `tests/test_qa_clarification.py::test_full_qa_round_trip` — pre-existing mock mismatch with `discussion_synthesis` kwarg

Do not attempt to fix these. Confirm they fail in the same way as on master.
