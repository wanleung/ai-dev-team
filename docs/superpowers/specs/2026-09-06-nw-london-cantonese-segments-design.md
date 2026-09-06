# NW London Cantonese Segment Pipeline Design

Date: 2026-09-06

## Objective

Add an isolated local-news workflow to `ai-software-house` that turns a
confirmed, critical structured event from
`wanleung/nw-london-canto-news` into one standalone spoken Hong Kong
Cantonese broadcast segment. The segment is reviewed as a pull request in the
local-news repository and can later be selected by a separate programme
assembly pipeline.

This phase generates text scripts only. It does not implement TTS, ASR,
programme assembly, video, or publishing.

## Safety Boundary

`ai-software-house` is shared by the existing `ai-it-press` newsroom. The new
workflow is additive and must not change any `ai-it-press` repository config,
labels, tracker/target routing, pipeline YAML, prompts, stage behavior, or
article output paths.

The local-news watcher remains disabled after implementation. Enabling its
`repos-enabled` entry, restarting a watcher, or processing a live Issue is a
separate controlled rollout action.

## Considered Approaches

### Dedicated local segment pipeline (selected)

Add local-news-specific triage, script generation, fact validation, and PR
stages. This keeps local resident information out of the technology-news
prompts and gives scripts their own data and artifact contracts.

### Extend the IT press pipeline

Reuse `news_writer`, `news_editor`, and the formal Traditional Chinese
translation flow before generating a broadcast script. This was rejected
because those roles are technology-specific, add unnecessary transformations,
and increase factual drift risk.

### Generate scripts in the collector

Run the LLM inside `nw-london-canto-news` collection. This was rejected because
it couples deterministic source extraction to editorial generation and weakens
the collector's fail-closed trust boundary.

## System Flows

The product has two separate editorial flows.

### Story-to-segment flow (this phase)

```text
official council source
  -> deterministic collector
  -> structured GitHub Issue
  -> local-news watcher dispatch
  -> deterministic local_news_triage
  -> broadcast_cantonese agent
  -> deterministic fact validation
  -> broadcast_script_pr
  -> reviewed standalone segment
```

### Programme assembly flow (future)

```text
reviewed standalone segments
  -> editorial selection and ordering
  -> intro, transitions, and outro
  -> complete programme script
  -> audio and media pipeline
```

Programme assembly must consume approved segment artifacts rather than raw
collector Issues. It is outside this design's implementation scope.

## Repository Responsibilities

### `nw-london-canto-news`

Owns:

- deterministic council collection and structured event Issues;
- `pipelines/local-news.yaml`;
- local geography, terminology, and pronunciation configuration;
- standalone segment artifacts under `broadcast/segments/`;
- future programme manifests and media assets.

Confirmed critical events receive the `local-news` trigger label. Review
events receive a non-triggering `needs-review` label and must not receive
`local-news`. A `council-alert` classification label may remain on both, but it
must not be mapped to a watcher pipeline.

### `ai-software-house`

Owns:

- the generic `BroadcastCantoneseAgent`;
- local-news triage, validation, and PR stage implementations;
- stage registry entries and checkpoint serialization;
- the available but initially disabled local-news watcher configuration;
- regression tests proving separation from `ai-it-press`.

### `ai-it-press`

No files or behavior change. Its current tracker-owned six-stage pipeline
continues to run independently:

```text
discuss_news_analysis
news_writer
discuss_news_draft
news_editor
translate_zh_traditional
news_article_pr
```

## Watcher Configuration

Add `repos-available/nw-london-canto-news.yaml` with this effective contract:

```yaml
tracker_repo: wanleung/nw-london-canto-news
default_target: ~
pipeline_file: pipelines/local-news.yaml
parallel_issues: 1
enabled: true

labels:
  local-news: local-news

settings:
  watch_prs: false

llm:
  overrides:
    broadcast_cantonese:
      model: mimo/mimo-v2.5-pro
```

The override selects the existing MiMo text backend and inherits credentials
from the engine's external configuration. No token is stored in either
repository. The local-news config is not symlinked into `repos-enabled` during
implementation.

The engine fetches `pipelines/local-news.yaml` from the tracker repository.
There must be no engine-side `pipelines/local-news.yaml`, because the current
label lookup can supersede a fetched tracker pipeline with a same-label local
pipeline.

## Tracker Pipeline

The initial tracker-owned pipeline is intentionally narrow:

```yaml
stages:
  - local_news_triage
  - broadcast_cantonese
  - broadcast_script_validate
  - broadcast_script_pr
```

General local-news analysis, article writing, and discussion stages are not
needed for deterministic waste alerts. They may be introduced later for
non-critical editorial stories under a separately reviewed contract.

## Structured Issue Input

`local_news_triage` parses the fenced YAML event block from the Issue body with
a structured YAML parser. It never asks an LLM to interpret missing fields.

For this phase, an event passes only when all of these conditions hold:

- `event_type` is `waste_collection_change`;
- `status` is `confirmed`;
- Issue priority is `critical`;
- `borough` is an allowed supported borough;
- `normal_date` and `revised_date` are valid ISO local dates;
- `waste_streams` is a non-empty list of supported values;
- `source_url` is an official HTTPS council URL.

Malformed YAML, unknown fields that affect resident instructions, ambiguous or
missing dates, unknown streams, `needs_review`, and untrusted source hosts stop
the pipeline before an LLM call or PR write.

The parsed and validated event is stored in a dedicated `PipelineResult` field
and included in checkpoint serialization.

## Cantonese Agent

`BroadcastCantoneseAgent` is a text-generation agent with a dedicated role
prompt. It accepts only:

- the validated event object;
- bounded source summary and notes already present in the Issue;
- optional local terminology/pronunciation guidance read from the tracker
  repository.

It produces a concise standalone segment in natural spoken Hong Kong
Cantonese. It must:

- lead with the resident-relevant change;
- state the borough and affected collection date clearly;
- distinguish every affected waste stream;
- give a direct resident action using only confirmed facts;
- preserve names, dates, road numbers, postcodes, and other protected values;
- use natural English/Cantonese code-switching where appropriate;
- avoid formal newspaper-style Chinese;
- avoid adding background facts, causes, or advice absent from the event.

The output is a script body only. Frontmatter is constructed deterministically
by engine code.

## Artifact Contract

The PR stage writes one file per Issue:

```text
broadcast/segments/YYYYMMDD-<issue>-<slug>.cantonese.md
```

The ASCII filename is derived deterministically from the normal collection
date, Issue number, borough, and event type. The file begins with frontmatter
copied from the validated event:

```yaml
---
type: broadcast_segment
issue_number: 42
borough: Hillingdon
event_type: waste_collection_change
normal_date: 2026-12-25
revised_date: 2026-12-27
waste_streams: [general_waste, recycling]
source_url: https://example.gov.uk/official-page
status: confirmed
language: yue-Hant-HK
---
```

The LLM cannot set or alter these fields. The body follows the frontmatter and
contains only the presenter script.

## Fact Validation

`broadcast_script_validate` is deterministic. It validates the stored event,
generated body, and constructed artifact before a PR can be opened.

At minimum it verifies:

- the script is non-empty and contains no model commentary;
- the borough or configured spoken equivalent is present;
- normal and revised dates are both present with the correct year, month, and
  day after supported Cantonese/ISO date normalization;
- all affected waste streams are represented by configured terms;
- conflicting dates or unsupported waste streams are absent;
- frontmatter exactly matches the validated event;
- the source URL and status remain unchanged.

On validation failure, the generation stage receives one bounded correction
request listing only the failed constraints. The validator runs again. A
second failure stops the pipeline and opens no PR. Validation never repairs or
guesses facts itself.

## Error Handling

- Input validation failures stop before LLM invocation.
- MiMo/backend failures use the engine's existing retry and fallback behavior,
  subject to the local per-agent configuration.
- Empty or malformed agent output is a stage failure.
- Fact-validation failure after one correction attempt is a stage failure.
- PR creation failure leaves the Issue retryable under existing watcher error
  handling.
- Error messages identify the stage and safe field names without logging
  credentials or complete authorization headers.

No failed or review event is marked as a publishable segment artifact.

## Testing

Engine tests must cover:

- all four new stage names are registered and validate;
- confirmed critical waste events pass deterministic triage;
- `needs_review`, malformed YAML, missing dates, invalid source hosts, unknown
  streams, and non-critical items stop before LLM use;
- the agent receives only validated facts and local guidance;
- the per-agent MiMo override does not affect other agents;
- date, borough, stream, number, and frontmatter preservation;
- correction retry followed by success;
- repeated validation failure creates no PR;
- deterministic filename and artifact content;
- checkpoint round-trip for new result fields;
- local watcher config parsing and tracker/target routing;
- absence of a local-news entry in `repos-enabled` after implementation.

Regression tests must pin the current `ai-it-press` tracker repo, labels,
pipeline file, `parallel_issues: 2`, `watch_prs: false`, six tracker-owned
stages, and article output behavior.

Local-news repository tests must cover:

- confirmed events include the `local-news` trigger;
- review events use `needs-review` and omit `local-news`;
- the tracker pipeline contains only registered stage names;
- normal tests remain offline.

## Rollout

1. Implement tests and engine additions without touching pre-existing dirty
   files unrelated to this feature.
2. Add the tracker pipeline and label behavior in `nw-london-canto-news`.
3. Run focused tests and both repositories' full offline suites.
4. Confirm `ai-it-press` has no tracked changes and its pinned integration
   tests pass.
5. Add the available local-news watcher config, but do not enable it.
6. Commit and push each repository independently.
7. In a later explicitly approved operation, inspect open local-news Issues,
   run one controlled fixture-backed watcher execution, and inspect the PR.
8. Only after that review, create the `repos-enabled` symlink and intentionally
   restart or reload the production watcher if its deployment requires it.

## Explicit Non-Goals

- TTS, ASR, voice cloning, and voice design;
- complete programme assembly;
- audio, video, YouTube, podcast, or social publication;
- changes to `ai-it-press`;
- LLM interpretation of missing collection dates;
- automatic production watcher activation.

