# Case Study: Batch Intake Triage with ai-it-press

A real-world walkthrough of using the Batch Intake Triage module to filter incoming news stories before they reach the expensive writing pipeline.

---

## The problem

The RSS watcher creates one GitHub issue per new story. With several active feeds, that's 20–50 new issues every few hours. Before batch intake triage existed, every story was fed directly into the full pipeline: discussion → writer → editor → translations → reviewer → PR. At ~0.10–0.30 USD per story, and with many stories being off-topic or thin, most of that cost was waste.

Worse, per-story triage evaluated each story in isolation. A mediocre story would sometimes pass triage because it looked reasonable on its own. Seen next to five stronger stories, it would obviously be skipped.

Batch intake triage solves both problems: it groups pending stories into a batch, has three AI editors compare and rank them together, and only the strongest ones advance to the pipeline.

---

## Architecture

```
RSS feeds
    ↓
rss_watcher.py → creates GitHub issue with label: triage-pending
                                        ↓
                            intake_triage.py (cron / manual)
                                        ↓
                            [batch of up to N issues]
                                        ↓
                         AI batch editorial discussion
                          (editorial_director,
                           audience_specialist,
                           news_editor)
                                        ↓
              APPROVE ────────────────────────────── SKIP
                 ↓                                     ↓
   remove triage-pending                   add triage-skipped
   add triage-approved                     close issue
   add press (trigger label)               post reason comment
   post editorial notes
                 ↓
   watcher sees "press" label
                 ↓
   full pipeline runs
   (news_triage fast-pass → already approved)
```

---

## Setup

### 1. Labels in ai-it-press

Create these labels in your `ai-it-press` GitHub repo:

| Label | Colour | Purpose |
|---|---|---|
| `triage-pending` | `#e4e669` | RSS watcher applies this on issue creation |
| `triage-approved` | `#0075ca` | Batch triage sets this on approve |
| `triage-skipped` | `#cfd3d7` | Batch triage sets this on skip |
| `press` | `#d93f0b` | Triggers the writing pipeline (existing) |

### 2. RSS watcher config

Tell the RSS watcher to apply `triage-pending` instead of the pipeline trigger label directly:

```yaml
# config.local.yaml (ai-software-house)
rss_watcher:
  press_repo: wanleung/ai-it-press
  label: triage-pending      # ← was "press"; now goes to triage queue
  max_age_hours: 48
  feeds:
    - url: https://feeds.feedburner.com/TheHackersNews
      source: The Hacker News
    - url: https://www.linux.com/feed/
      source: Linux.com
    - url: https://feeds.arstechnica.com/arstechnica/index
      source: Ars Technica
```

### 3. Batch intake triage config

```yaml
# config.yaml (ai-software-house)
intake_triage:
  enabled: true
  tracker: github

  scope: >
    Tech news relevant to HK Cantonese-speaking professionals in IT,
    software development, cybersecurity, and open source. Must have
    enough substance to write a 400-word article.

  labels:
    pending:  triage-pending
    approved: triage-approved
    skipped:  triage-skipped
    trigger:  press            # added on approve → kicks off writing pipeline

  trigger:
    min_count: 5               # fire when 5+ stories are waiting
    max_age_hours: 6           # or when oldest is 6 hours old
    schedule: "0 7,13,19 * * *"  # or at 7am, 1pm, 7pm regardless

  batch:
    max_size: 10               # cap at 10 per session; overflow waits
    body_preview_chars: 300    # characters of story body shown to editors

  discussion:
    preset: discussions/intake-triage.yaml
```

### 4. Cron setup

```cron
# Run every 30 minutes; intake_triage.py checks trigger conditions internally
*/30 * * * * cd /path/to/ai-software-house && python intake_triage.py \
    --config config.yaml 2>> /var/log/intake_triage.log
```

---

## Walkthrough: a typical session

### Step 1 — Stories accumulate

Over three hours the RSS watcher creates 8 issues in `ai-it-press`, each labelled `triage-pending`:

```
#201 — "Linux 6.14 released with new scheduler improvements"       (2h 15m old)
#202 — "OpenAI cuts API prices by 40%"                             (2h 10m old)
#203 — "Celebrity uses iPhone, says it's great"                    (2h 00m old)
#204 — "GitHub Copilot now supports voice input"                   (1h 45m old)
#205 — "New Python packaging standard PEP 775 approved"            (1h 30m old)
#206 — "Local HK startup raises Series A for fintech app"          (1h 00m old)
#207 — "Rust memory safety paper wins award"                       (0h 30m old)
#208 — "US weather forecast: sunny weekend ahead"                  (0h 10m old)
```

### Step 2 — Trigger fires

At the next cron tick, `intake_triage.py` runs:

```bash
$ python intake_triage.py
[intake_triage] 8 pending items found
[intake_triage] trigger: min_count=5 reached (8 >= 5) — firing
[intake_triage] batch size capped at 10, processing 8 items
```

### Step 3 — Batch discussion

The module builds a context block and passes it to `DiscussionAgent` with the `discussions/intake-triage.yaml` preset:

```
## Pending Items for Editorial Review
Triage scope: Tech news relevant to HK Cantonese-speaking professionals in IT...
Item count: 8

---
ITEM 1: Linux 6.14 released with new scheduler improvements
Source: Linux.com | Age: 2h 15m
The 6.14 kernel includes a new energy-aware scheduler, improved Rust driver
bindings, and a redesigned memory reclaim path. Linus Torvalds noted...
[300 chars]

ITEM 2: OpenAI cuts API prices by 40%
Source: The Hacker News | Age: 2h 10m
GPT-4.1 and GPT-4.1 mini pricing reduced effective immediately. Input tokens
now $2/M, output $8/M. Batch API gets additional 30% discount...
[300 chars]

ITEM 3: Celebrity uses iPhone, says it's great
...
```

Three editors each write a homework analysis, then debate in up to 2 rounds. The moderator synthesises and emits verdicts:

```
ITEM 1: PUBLISH
NOTES: Angle on the Rust driver improvements — relevant to HK dev community building systems software.

ITEM 2: PUBLISH
NOTES: Focus on cost impact for local AI startups and developers using the API.

ITEM 3: SKIP
NOTES: No tech substance — celebrity lifestyle piece, not IT news.

ITEM 4: PUBLISH
NOTES: Practical angle: how voice input changes the workflow for non-English speakers.

ITEM 5: PUBLISH
NOTES: Cover the packaging unification story — affects every Python dev.

ITEM 6: SKIP
NOTES: Interesting local angle but insufficient public information for a full article.

ITEM 7: SKIP
NOTES: Academic award story — low news value without a practical takeaway.

ITEM 8: SKIP
NOTES: Off-topic — weather, not tech.
```

### Step 4 — Labels and comments applied

For each PUBLISH verdict, the module:
1. Removes `triage-pending`
2. Adds `triage-approved`
3. Adds `press` (the pipeline trigger label)
4. Posts a structured comment with editorial notes

```markdown
## ✅ Intake Triage: APPROVED

**Editorial notes:** Angle on the Rust driver improvements — relevant to HK dev
community building systems software.

_Approved by the batch editorial team. The writing pipeline will start shortly._
```

For each SKIP verdict:
1. Adds `triage-skipped`
2. Posts reason comment
3. Closes the issue

### Step 5 — Watcher picks up approved stories

The repo watcher polls `ai-it-press` and sees four issues now labelled `press`. It fires the writing pipeline for each. The `news_triage` stage runs but immediately fast-passes:

```
[orchestrator] news_triage: batch intake triage already approved #201 — fast-pass
[orchestrator] news_triage: batch intake triage already approved #202 — fast-pass
```

The editorial notes are injected into the writer's prompt:

```
> Angle on the Rust driver improvements — relevant to HK dev community building systems software.
```

The full pipeline runs: writer → editor → Cantonese translation → Traditional Chinese translation → news reviewer → PR.

---

## Manual override

### Force a run (ignore trigger conditions)

```bash
python intake_triage.py --run
```

Useful when you want to process the queue now, regardless of `min_count` or `max_age_hours`.

### Preview without changes

```bash
python intake_triage.py --dry-run
```

Prints what would be processed and what the batch context looks like, but makes no API calls.

### Human approval

Add `triage-approved` and `press` labels manually on any issue in GitHub — the system respects it and the `news_triage` stage will fast-pass it automatically.

### Human rejection

Add `triage-skipped` and close the issue manually. No further action needed.

---

## Overflow behaviour

If more than `max_size` items are pending, the oldest N are processed. The remainder stay labelled `triage-pending` and are picked up next session.

```
[intake_triage] 15 pending items found, max_size=10
[intake_triage] processing oldest 10; 5 items deferred to next run
```

---

## Costs

| Stage | Cost per session |
|---|---|
| Batch discussion (10 items, 2 rounds, 3 editors) | ~$0.05–0.15 |
| Per-story pipeline (writer + editor + translations + reviewer) | ~$0.10–0.30 |
| **Without triage** (10 stories → 10 pipelines) | ~$1.00–3.00 |
| **With triage** (10 stories → 4 approved → 4 pipelines) | ~$0.45–1.35 |

Typical savings: 40–60% of pipeline cost, plus higher quality throughput.

---

## Troubleshooting

### "disabled in config" logged, nothing runs
`intake_triage.enabled` is `false`. Either set it to `true` or use `--run` flag to force.

### Trigger conditions not met
Use `--run` to force. Check `trigger.min_count` and `trigger.max_age_hours` settings.

### PUBLISH/SKIP verdicts not parsed
The moderator output didn't match the expected format. The module fails open — all items default to PUBLISH and a warning is logged. Check logs for `[INTAKE TRIAGE] parse_batch_verdicts` warnings.

### GitHub rate limit errors
Reduce `batch.max_size` or add a delay between API calls. The adapter uses `requests` with a 15-second timeout per call.
