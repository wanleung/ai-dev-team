# NW London Cantonese Segments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn each confirmed critical NW London waste-change Issue into one fact-checked spoken Hong Kong Cantonese segment PR without changing the existing IT press workflow.

**Architecture:** The local-news tracker owns a four-stage pipeline. `ai-software-house` deterministically parses and validates the Issue, calls a dedicated text agent, validates protected facts, then writes one `broadcast/segments/*.cantonese.md` artifact through the existing PR helper. Review events never receive the trigger label, and the new watcher configuration remains available but disabled.

**Tech Stack:** Python 3.11+, dataclasses, PyYAML, existing `BaseAgent`/`Orchestrator`/watcher contracts, pytest, GitHub Issues and pull requests.

**Spec:** `docs/superpowers/specs/2026-09-06-nw-london-cantonese-segments-design.md`

## Global Constraints

- Never ask an LLM to derive or repair collection dates.
- Only `status: confirmed`, `priority: critical`, complete `waste_collection_change` events may reach the agent.
- `needs_review` Issues must omit the `local-news` trigger label.
- Keep `wanleung/ai-it-press` config, labels, pipeline, roles, output paths, and behavior unchanged.
- Use `mimo/mimo-v2.5-pro` only through the `broadcast_cantonese` repository override; keep `MIMO_API_KEY` external.
- Generate text scripts only; do not add TTS, ASR, audio, video, programme assembly, or publishing.
- Do not create `repos-enabled/nw-london-canto-news.yaml`, restart services, or process a live Issue.
- Normal tests must remain offline.
- Preserve all unrelated dirty files in the existing checkouts.

## File Structure

### `ai-software-house`

- Create `local_news.py`: structured Issue parsing, event validation, script fact validation, artifact construction, and deterministic path generation.
- Create `agents/broadcast_cantonese.py`: generic spoken-Cantonese segment agent.
- Create `roles/broadcast_cantonese.md`: script style and factual constraints.
- Modify `orchestrator.py`: result fields, agent construction, four stages, correction retry, and PR handoff.
- Create `repos-available/nw-london-canto-news.yaml`: disabled-by-directory watcher definition.
- Create `tests/test_local_news.py`: pure parser, validator, path, and artifact tests.
- Create `tests/test_broadcast_cantonese.py`: agent prompt/output tests.
- Create `tests/test_local_news_stages.py`: stage wiring, retry, checkpoint, and PR tests.
- Create `tests/test_local_news_watcher_config.py`: new config and IT press isolation regression tests.

### `nw-london-canto-news`

- Modify `src/nwlondon_news/outputs/github_issue.py`: status-specific labels and sink allow-list enforcement.
- Modify `config/sources.yaml`: permit the `needs-review` label.
- Modify `tests/test_github_issue.py`: confirmed/review label and sink tests.
- Modify `tests/test_cli.py`: run-mode label allow-list expectations.
- Create `pipelines/local-news.yaml`: tracker-owned four-stage pipeline.
- Create `broadcast/segments/.gitkeep`: establish the segment artifact directory.
- Modify `README.md`, `docs/architecture.md`, `docs/integration-plan.md`, `docs/STATUS.md`, and `docs/ROADMAP.md`: document the implemented but disabled integration.

---

### Task 1: Structured Local-News Contract

**Files:**
- Create: `local_news.py`
- Create: `tests/test_local_news.py`

**Interfaces:**
- Consumes: GitHub Issue Markdown with `**Priority:** critical` and one fenced `yaml` event mapping.
- Produces: `LocalNewsEvent`, `parse_local_news_issue(issue_body: str) -> LocalNewsEvent`, `validate_broadcast_script(event: LocalNewsEvent, script: str) -> list[str]`, `build_broadcast_artifact(event: LocalNewsEvent, issue_number: int, script: str) -> str`, and `broadcast_segment_path(event: LocalNewsEvent, issue_number: int) -> str`.

- [ ] **Step 1: Create failing parser tests**

Add fixtures inline in `tests/test_local_news.py` and assert the exact immutable event:

```python
def test_parse_confirmed_critical_waste_issue():
    event = parse_local_news_issue(CONFIRMED_ISSUE)
    assert event == LocalNewsEvent(
        borough="Hillingdon",
        event_type="waste_collection_change",
        normal_date=date(2026, 12, 25),
        revised_date=date(2026, 12, 27),
        waste_streams=("general_waste", "recycling"),
        source_url="https://pre.hillingdon.gov.uk/rubbish-recycling/bank-holiday-collections",
        status="confirmed",
    )

@pytest.mark.parametrize("body", [
    NEEDS_REVIEW_ISSUE,
    MISSING_REVISED_DATE_ISSUE,
    UNKNOWN_STREAM_ISSUE,
    NON_CRITICAL_ISSUE,
    MALFORMED_YAML_ISSUE,
    UNTRUSTED_HOST_ISSUE,
])
def test_parse_rejects_non_publishable_issue(body):
    with pytest.raises(LocalNewsValidationError):
        parse_local_news_issue(body)
```

- [ ] **Step 2: Run parser tests and verify failure**

Run: `python3 -m pytest tests/test_local_news.py -v`

Expected: collection fails because `local_news` does not exist.

- [ ] **Step 3: Implement strict Issue parsing**

Create `LocalNewsEvent` as a frozen dataclass. Use `yaml.safe_load`,
`date.fromisoformat`, `urllib.parse.urlparse`, exact allowed borough/host pairs,
and these stream values:

```python
SUPPORTED_STREAMS = frozenset({
    "general_waste", "recycling", "food_waste",
    "garden_waste", "bulky_waste", "other",
})
OFFICIAL_HOSTS = {
    "Hillingdon": frozenset({"pre.hillingdon.gov.uk", "www.hillingdon.gov.uk"}),
    "Harrow": frozenset({"www.harrow.gov.uk"}),
    "Brent": frozenset({"www.brent.gov.uk"}),
}
```

Reject missing or multiple event blocks, non-mapping YAML, non-critical
priority, unknown keys, invalid types, `needs_review`, invalid dates, empty or
duplicate streams, credentials in URLs, non-HTTPS URLs, fragments, and hosts
outside the borough allow-list. Error text must contain safe field names only.

- [ ] **Step 4: Run parser tests**

Run: `python3 -m pytest tests/test_local_news.py -v`

Expected: parser tests pass.

- [ ] **Step 5: Add failing script-validation and artifact tests**

Cover natural Cantonese and ISO date forms, full Cantonese dates using `日` or
`號`, missing borough, missing stream, missing date, conflicting third date,
model commentary, deterministic path, and exact frontmatter round-trip:

```python
def test_validate_accepts_spoken_cantonese_with_exact_facts(event):
    script = (
        "今日提提 Hillingdon 嘅居民，原定 2026年12月25號嘅"
        "一般垃圾同回收 collection，改到 2026年12月27號。"
        "記住跟新日期擺出去。"
    )
    assert validate_broadcast_script(event, script) == []

def test_validate_rejects_conflicting_date(event):
    errors = validate_broadcast_script(
        event,
        "Hillingdon 一般垃圾同回收由2026年12月25號改到"
        "2026年12月27號，另外2026年12月28號再收。",
    )
    assert "unexpected_date" in errors

def test_artifact_frontmatter_is_copied_from_event(event):
    artifact = build_broadcast_artifact(event, 42, VALID_SCRIPT)
    frontmatter = yaml.safe_load(artifact.split("---", 2)[1])
    assert frontmatter["normal_date"] == "2026-12-25"
    assert frontmatter["revised_date"] == "2026-12-27"
    assert frontmatter["language"] == "yue-Hant-HK"
```

- [ ] **Step 6: Implement deterministic validation and artifact helpers**

Normalize only these date forms to `date`: `YYYY-MM-DD`,
`YYYY年M月D日`, and `YYYY年M月D號`. Extract every full date from the script;
require both event dates and reject any other extracted date. Match the exact
English borough name case-insensitively. Use a constant alias map for streams:

```python
STREAM_TERMS = {
    "general_waste": ("general waste", "一般垃圾", "家居垃圾"),
    "recycling": ("recycling", "回收"),
    "food_waste": ("food waste", "廚餘", "食物垃圾"),
    "garden_waste": ("garden waste", "園林廢物", "花園垃圾"),
    "bulky_waste": ("bulky waste", "大型垃圾", "大型廢物"),
    "other": ("other waste", "其他垃圾", "其他廢物"),
}
```

Return stable codes such as `empty_script`, `model_commentary`,
`missing_borough`, `missing_normal_date`, `missing_revised_date`,
`missing_stream:<stream>`, and `unexpected_date` without mutating the script.
Build YAML with `yaml.safe_dump(sort_keys=False, allow_unicode=True)` from code,
then append the stripped script body.

- [ ] **Step 7: Run the pure contract tests**

Run: `python3 -m pytest tests/test_local_news.py -v`

Expected: all tests pass without network access.

- [ ] **Step 8: Commit the contract**

```bash
git add local_news.py tests/test_local_news.py
git commit -m "feat(local-news): validate segment facts"
```

### Task 2: Broadcast Cantonese Agent

**Files:**
- Create: `agents/broadcast_cantonese.py`
- Create: `roles/broadcast_cantonese.md`
- Create: `tests/test_broadcast_cantonese.py`

**Interfaces:**
- Consumes: `LocalNewsEvent`, optional bounded `summary`, optional repository pronunciation YAML text, and optional validation error codes.
- Produces: `BroadcastCantoneseAgent.run(...) -> {"broadcast_script": str}`.

- [ ] **Step 1: Write failing agent tests**

Inject a `MagicMock` backend and assert the prompt contains the serialized
validated event, spoken-language requirements, pronunciation guidance, and
correction codes without asking for frontmatter:

```python
def test_agent_returns_script_body_from_backend(event):
    backend = MagicMock()
    backend.call.return_value = "Hillingdon 嘅垃圾收集日期有改動。"
    agent = BroadcastCantoneseAgent(llm=backend)
    result = agent.run(event, summary="Christmas change")
    assert result == {"broadcast_script": "Hillingdon 嘅垃圾收集日期有改動。"}
    messages = backend.call.call_args.args[0]
    prompt = messages[-1]["content"]
    assert '"normal_date": "2026-12-25"' in prompt
    assert "Output the script body only" in prompt

def test_agent_includes_bounded_correction_codes(event):
    agent.run(event, correction_codes=["missing_revised_date"])
    messages = backend.call.call_args.args[0]
    assert "missing_revised_date" in messages[-1]["content"]
```

- [ ] **Step 2: Run agent tests and verify failure**

Run: `python3 -m pytest tests/test_broadcast_cantonese.py -v`

Expected: collection fails because the agent module does not exist.

- [ ] **Step 3: Implement the agent and role**

Set `role_name = "broadcast_cantonese"`. Serialize the dataclass with
`dataclasses.asdict`, convert dates to ISO strings, and use JSON with
`ensure_ascii=False` inside `<VALIDATED_EVENT>` tags. Limit summary and
pronunciation text to bounded lengths before prompt construction. Never accept
raw Issue Markdown in this agent.

The role must require natural spoken Hong Kong Cantonese, direct resident
actions, short standalone delivery, exact protected facts, and no invented
context. It must explicitly distinguish this output from formal Traditional
Chinese translation.

- [ ] **Step 4: Run agent tests**

Run: `python3 -m pytest tests/test_broadcast_cantonese.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit the agent**

```bash
git add agents/broadcast_cantonese.py roles/broadcast_cantonese.md tests/test_broadcast_cantonese.py
git commit -m "feat(local-news): add Cantonese segment agent"
```

### Task 3: Orchestrator Segment Stages

**Files:**
- Modify: `orchestrator.py`
- Create: `tests/test_local_news_stages.py`

**Interfaces:**
- Consumes: Task 1 helpers and Task 2 `BroadcastCantoneseAgent`.
- Produces: four registered stages and checkpoint fields `local_news_event: dict`, `broadcast_script: str`, and `broadcast_validation_errors: list[str]`.

- [ ] **Step 1: Write failing registry and checkpoint tests**

```python
def test_local_news_stages_are_registered(orch_stub):
    registry = orch_stub._make_stage_registry()
    assert {
        "local_news_triage", "broadcast_cantonese",
        "broadcast_script_validate", "broadcast_script_pr",
    } <= registry.keys()

def test_segment_fields_round_trip_checkpoint_dict():
    result = PipelineResult(
        local_news_event={"borough": "Hillingdon"},
        broadcast_script="稿",
        broadcast_validation_errors=["missing_stream:recycling"],
    )
    restored = PipelineResult.from_dict(result.to_dict())
    assert restored.broadcast_script == "稿"
    assert restored.local_news_event == {"borough": "Hillingdon"}
```

- [ ] **Step 2: Run stage tests and verify failure**

Run: `python3 -m pytest tests/test_local_news_stages.py -v`

Expected: tests fail because fields and stages are absent.

- [ ] **Step 3: Add result fields and agent construction**

Import `BroadcastCantoneseAgent`, instantiate it in `_init_standard_agents`
with `mk("broadcast_cantonese")`, and include it in the original-prompt map.
Add all three fields to the dataclass, `to_dict`, and existing `from_dict`
allow-list flow. Store `local_news_event` as JSON-safe scalars; reconstruct the
typed dataclass only inside stage methods.

- [ ] **Step 4: Register four content stages**

Add the stages in a focused `_build_content_stages_broadcast` builder called
from `_build_content_stages`. Mark triage and validation critical:

```python
stages["local_news_triage"] = PipelineStage(
    name="local_news_triage",
    label="Local News Triage",
    description="Validating structured resident information...",
    checkpoint_key="local_news_triage",
    fn=lambda r: self._stage_local_news_triage(r),
    required_output_fields=["local_news_event"],
    is_critical=True,
)
```

Register generation, validation, and PR in the same builder with their own
checkpoint keys. Do not change existing stage definitions.

- [ ] **Step 5: Implement triage and initial generation tests**

Assert `_stage_local_news_triage` parses `result.issue_body` or
`result.requirement`, stores a JSON-safe event, and never calls the agent on
rejection. Assert `_stage_broadcast_cantonese` reconstructs the typed event,
loads at most `config/pronunciation.yaml` through `target_github` when
available, and stores a stripped non-empty body.

- [ ] **Step 6: Implement triage and initial generation**

Use only `parse_local_news_issue` for selection. Fetch pronunciation guidance
with `self.target_github.get_file_content("config/pronunciation.yaml")`, catch
read failures as non-critical, and cap the text before passing it to the agent.
Extract the human Summary section with a bounded deterministic Markdown helper;
do not pass the entire Issue to the agent.

- [ ] **Step 7: Add failing correction-loop tests**

Cover first-pass success, correction success, and final failure:

```python
def test_validate_retries_agent_once_then_passes(orch, event_result):
    orch.broadcast_cantonese.run.return_value = {
        "broadcast_script": VALID_CORRECTED_SCRIPT,
    }
    event_result.broadcast_script = SCRIPT_MISSING_REVISED_DATE
    orch._stage_broadcast_script_validate(event_result)
    assert event_result.broadcast_validation_errors == []
    orch.broadcast_cantonese.run.assert_called_once()

def test_validate_raises_after_failed_correction(orch, event_result):
    orch.broadcast_cantonese.run.return_value = {
        "broadcast_script": SCRIPT_MISSING_REVISED_DATE,
    }
    with pytest.raises(RuntimeError, match="fact validation failed"):
        orch._stage_broadcast_script_validate(event_result)
```

- [ ] **Step 8: Implement one bounded correction attempt**

Run `validate_broadcast_script`. If errors exist, store the codes and call the
agent once with the same validated event plus `correction_codes=errors`. Strip
the replacement and validate it once. Clear errors on success; otherwise store
the final codes and raise `RuntimeError` before any PR stage.

- [ ] **Step 9: Run orchestrator stage tests**

Run: `python3 -m pytest tests/test_local_news_stages.py tests/test_pipeline_registry.py tests/test_news_stages.py -v`

Expected: local stages pass and all existing news stages remain present.

- [ ] **Step 10: Commit stage wiring**

```bash
git add orchestrator.py tests/test_local_news_stages.py
git commit -m "feat(local-news): add segment pipeline stages"
```

### Task 4: Segment Pull Request Output

**Files:**
- Modify: `orchestrator.py`
- Modify: `tests/test_local_news_stages.py`

**Interfaces:**
- Consumes: validated typed event, Issue number, and `broadcast_script`.
- Produces: `result.all_files` containing one deterministic segment and invokes `_commit_and_open_pr` with a `broadcast` branch prefix.

- [ ] **Step 1: Write failing PR-stage tests**

```python
def test_broadcast_script_pr_builds_one_segment(orch, event_result):
    event_result.issue_number = 42
    event_result.broadcast_script = VALID_SCRIPT
    with patch.object(orch, "_commit_and_open_pr") as commit_pr:
        orch._stage_broadcast_script_pr(event_result)
    assert list(event_result.all_files) == [
        "broadcast/segments/20261225-42-hillingdon-waste-collection-change.cantonese.md"
    ]
    assert "normal_date: '2026-12-25'" in next(iter(event_result.all_files.values()))
    commit_pr.assert_called_once()

def test_broadcast_script_pr_refuses_unvalidated_script(orch, event_result):
    event_result.broadcast_validation_errors = ["missing_revised_date"]
    with pytest.raises(RuntimeError, match="not validated"):
        orch._stage_broadcast_script_pr(event_result)
```

- [ ] **Step 2: Run PR tests and verify failure**

Run: `python3 -m pytest tests/test_local_news_stages.py -k broadcast_script_pr -v`

Expected: failure because `_stage_broadcast_script_pr` is not implemented.

- [ ] **Step 3: Implement the PR stage**

Re-run deterministic validation, construct the artifact and path with Task 1
helpers, set `result.all_files`, then call:

```python
self._commit_and_open_pr(
    result,
    branch_prefix="broadcast",
    title_prefix="broadcast segment",
    body_header="## Cantonese Local-News Segment",
    commit_msg_prefix="broadcast",
)
```

Reject missing Issue numbers, missing event data, missing scripts, or any
remaining validation errors before setting files.

- [ ] **Step 4: Run local stage and existing article PR tests**

Run: `python3 -m pytest tests/test_local_news_stages.py tests/test_news_stages.py -v`

Expected: both local segment and existing article PR tests pass.

- [ ] **Step 5: Commit PR output**

```bash
git add orchestrator.py tests/test_local_news_stages.py
git commit -m "feat(local-news): open segment pull requests"
```

### Task 5: Available Watcher Configuration And Isolation

**Files:**
- Create: `repos-available/nw-london-canto-news.yaml`
- Create: `tests/test_local_news_watcher_config.py`

**Interfaces:**
- Consumes: existing watcher schema and global external MiMo credentials.
- Produces: a loadable but not enabled repository definition mapping only `local-news` to the tracker pipeline.

- [ ] **Step 1: Write failing configuration regression tests**

Read YAML from disk and assert exact contracts:

```python
def test_local_news_config_is_available_but_not_enabled(repo_root):
    cfg = yaml.safe_load((repo_root / "repos-available/nw-london-canto-news.yaml").read_text())
    assert cfg["tracker_repo"] == "wanleung/nw-london-canto-news"
    assert cfg["labels"] == {"local-news": "local-news"}
    assert cfg["parallel_issues"] == 1
    assert cfg["settings"]["watch_prs"] is False
    assert not (repo_root / "repos-enabled/nw-london-canto-news.yaml").exists()

def test_ai_it_press_contract_is_unchanged(repo_root):
    cfg = yaml.safe_load((repo_root / "repos-available/ai-it-press.yaml").read_text())
    assert cfg["tracker_repo"] == "wanleung/ai-it-press"
    assert cfg["pipeline_file"] == "pipelines/news-article.yaml"
    assert cfg["parallel_issues"] == 2
    assert cfg["labels"]["news-article"] == "news-article"
    assert cfg["labels"]["press"] == "news-article"
```

Also parse the sibling read-only
`/home/wanleung/Projects/ai-it-press/pipelines/news-article.yaml` when present
and assert its six stages exactly. Skip that single assertion when the sibling
checkout is unavailable; never modify it.

- [ ] **Step 2: Run config tests and verify failure**

Run: `python3 -m pytest tests/test_local_news_watcher_config.py -v`

Expected: failure because the local-news available config is absent.

- [ ] **Step 3: Add the available watcher configuration**

Use the exact contract from the design, including:

```yaml
labels:
  local-news: local-news
llm:
  overrides:
    broadcast_cantonese:
      model: mimo/mimo-v2.5-pro
```

Do not add `council-alert` to the label map. Do not create an enabled symlink.

- [ ] **Step 4: Test config loading and LLM isolation**

Add a temporary-directory test using `load_watcher_config` and
`_deep_merge_llm`. Assert the local override changes only
`broadcast_cantonese`, while `news_writer`, `translator`, and the global model
remain unchanged.

- [ ] **Step 5: Run watcher/config tests**

Run: `python3 -m pytest tests/test_local_news_watcher_config.py tests/test_watcher_config.py tests/test_pipeline_file_feature.py -v`

Expected: all pass.

- [ ] **Step 6: Commit the available configuration**

```bash
git add repos-available/nw-london-canto-news.yaml tests/test_local_news_watcher_config.py
git commit -m "feat(watcher): add disabled local newsroom"
```

### Task 6: Status-Specific Collector Labels

**Files:**
- Modify: `src/nwlondon_news/outputs/github_issue.py`
- Modify: `config/sources.yaml`
- Modify: `tests/test_github_issue.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: `WasteCollectionChange.status` and configured allowed Issue labels.
- Produces: confirmed payload labels `("local-news", "council-alert")`; review payload labels `("needs-review", "council-alert")`; GitHub sink posts the payload labels only after allow-list validation.

- [ ] **Step 1: Update tests first**

Change the review assertion and add sink allow-list tests:

```python
def test_review_payload_uses_non_triggering_labels():
    payload = render_issue(make_review_event(), SurfaceDecision(True, "initial"))
    assert payload.labels == ("needs-review", "council-alert")
    assert "local-news" not in payload.labels

def test_github_sink_posts_payload_labels(monkeypatch):
    sink = GitHubIssueOutput(
        CONFIGURED_REPOSITORY,
        "secret-token",
        ("local-news", "council-alert", "needs-review"),
    )
    sink.emit(IssuePayload("review", "body", ("needs-review", "council-alert")))
    assert posted_json["labels"] == ["needs-review", "council-alert"]

def test_github_sink_rejects_label_outside_allow_list():
    sink = GitHubIssueOutput(CONFIGURED_REPOSITORY, "secret", ("local-news",))
    result = sink.emit(IssuePayload("title", "body", ("unexpected",)))
    assert result.success is False
    assert result.error == "GitHub issue output failed"
```

Adjust CLI mocks to expect the three-label allow-list.

- [ ] **Step 2: Run focused tests and verify failure**

Run: `python3 -m pytest tests/test_github_issue.py tests/test_cli.py -v`

Expected: the new review-label and payload-label tests fail.

- [ ] **Step 3: Implement conditional labels and sink enforcement**

Add:

```python
CONFIRMED_LABELS = ("local-news", "council-alert")
REVIEW_LABELS = ("needs-review", "council-alert")
```

Select labels in `render_issue`. Treat constructor `labels` as the sink's
allowed label set. In `emit`, reject when any payload label is outside that set
and otherwise send `list(payload.labels)`. Do not include tokens or label
contents in error messages.

Set:

```yaml
issue_labels: [local-news, council-alert, needs-review]
```

- [ ] **Step 4: Run collector label tests**

Run: `python3 -m pytest tests/test_github_issue.py tests/test_cli.py tests/test_config.py -v`

Expected: all pass.

- [ ] **Step 5: Commit collector routing**

```bash
git add config/sources.yaml src/nwlondon_news/outputs/github_issue.py tests/test_github_issue.py tests/test_cli.py
git commit -m "fix(output): isolate review issues from watcher"
```

### Task 7: Tracker Pipeline And Product Documentation

**Files:**
- Create: `pipelines/local-news.yaml`
- Create: `broadcast/segments/.gitkeep`
- Create: `tests/test_local_news_pipeline.py`
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/integration-plan.md`
- Modify: `docs/STATUS.md`
- Modify: `docs/ROADMAP.md`

**Interfaces:**
- Consumes: the four engine stage names from Task 3.
- Produces: the repository-owned ordered pipeline and an empty artifact destination.

- [ ] **Step 1: Write the pipeline contract test**

```python
def test_local_news_pipeline_is_narrow_and_ordered(project_root):
    pipeline = yaml.safe_load((project_root / "pipelines/local-news.yaml").read_text())
    assert pipeline["stages"] == [
        "local_news_triage",
        "broadcast_cantonese",
        "broadcast_script_validate",
        "broadcast_script_pr",
    ]
```

Assert the pipeline has no `news_writer`, `translate_zh_traditional`, TTS, ASR,
or publishing stage.

- [ ] **Step 2: Run the pipeline test and verify failure**

Run: `python3 -m pytest tests/test_local_news_pipeline.py -v`

Expected: failure because the tracker pipeline does not exist.

- [ ] **Step 3: Add the pipeline and segment directory**

Create the exact four-stage YAML and `broadcast/segments/.gitkeep`. Do not add
generated content.

- [ ] **Step 4: Update operational documentation**

Document:

- the two-flow model: Issue-to-segment now, segment-to-programme later;
- `needs-review` as non-triggering;
- the `broadcast/segments` artifact contract;
- MiMo is used for text only and credentials remain external;
- `repos-available` exists but `repos-enabled` does not;
- the separate controlled rollout checklist, including creating the
  `needs-review` GitHub label before deploying the updated collector;
- Milestone 2 as implemented but disabled, and Milestone 3 as partially
  implemented for standalone segments only;
- TTS and programme assembly remain planned.

- [ ] **Step 5: Run repository tests**

Run: `python3 -m pytest -m "not live" -v`

Expected: all offline tests pass and live tests remain deselected.

- [ ] **Step 6: Commit tracker pipeline and docs**

```bash
git add pipelines/local-news.yaml broadcast/segments/.gitkeep tests/test_local_news_pipeline.py README.md docs/architecture.md docs/integration-plan.md docs/STATUS.md docs/ROADMAP.md
git commit -m "feat: add Cantonese segment pipeline"
```

### Task 8: Full Regression And Safety Verification

**Files:**
- Modify only if a test reveals a defect in files already listed above.

**Interfaces:**
- Consumes: completed engine and tracker changes.
- Produces: verified commits with no activation or sibling modification.

- [ ] **Step 1: Run the complete engine suite**

Run from the isolated `ai-software-house` worktree:

```bash
python3 -m pytest -v
```

Expected: all tests pass.

- [ ] **Step 2: Run the complete local-news offline suite**

Run from the isolated `nw-london-canto-news` worktree:

```bash
python3 -m pytest -m "not live" -v
```

Expected: all offline tests pass with live tests deselected.

- [ ] **Step 3: Validate the tracker pipeline against the engine registry**

Run a local Python command that loads `pipelines/local-news.yaml`, builds an
offline `Orchestrator`, and calls `_validate_pipeline_stages` with the loaded
stage list. It must not construct GitHub clients or call MiMo.

Expected: validation succeeds for all four names.

- [ ] **Step 4: Run fixture collector dry-runs**

```bash
python3 scripts/collect_local.py --council hillingdon --fixture-dir tests/fixtures --dry-run
python3 scripts/collect_local.py --council harrow --fixture-dir tests/fixtures --dry-run
python3 scripts/collect_local.py --council brent --fixture-dir tests/fixtures --dry-run
```

Expected: confirmed fixture payloads show `local-news, council-alert`; review
fixture payloads show `needs-review, council-alert`; no GitHub writes occur.

- [ ] **Step 5: Confirm watcher remains disabled**

```bash
test ! -e repos-enabled/nw-london-canto-news.yaml
```

Expected: exit status 0 in `ai-software-house`.

- [ ] **Step 6: Confirm `ai-it-press` is untouched**

```bash
git -C /home/wanleung/Projects/ai-it-press status --short
git -C /home/wanleung/Projects/ai-it-press diff -- pipelines/news-article.yaml config.publish.yaml
```

Expected: only its pre-existing untracked `__pycache__` entries, with no diff
to tracked press files.

- [ ] **Step 7: Review both feature diffs**

Inspect `git diff <base>...HEAD` in each worktree. Confirm no secrets, runtime
databases, enabled symlinks, production service files, IT press changes, TTS,
or media publishing code entered either commit series.

- [ ] **Step 8: Report readiness without activation**

Report engine and local test counts, dry-run behavior, created commits,
remaining rollout actions, parser/agent risks, secret handling, and exactly:

```text
AI-IT-PRESS MODIFIED: NO
LOCAL-NEWS WATCHER ENABLED: NO
TTS IMPLEMENTED: NO
```
