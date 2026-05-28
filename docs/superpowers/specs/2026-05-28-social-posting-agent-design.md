# Social Posting Agent — PR Campaign Social Publishing

**Date:** 2026-05-28  
**Status:** Approved  
**Depends on:** PR/Marketing Campaign Pipeline (PR #64, already implemented)

---

## Overview

Add a `pr_social_post` stage to the existing `pr-campaign` pipeline. After the PR proposal stage creates the GitHub PR with campaign content, a human reviewer posts `/post-social` as a GitHub issue comment. The watcher picks this up and triggers the social posting agent, which refines platform-specific content via LLM (using `pr_creative` output as draft) and posts to the enabled social platforms.

**Supported platforms:** X/Twitter, Instagram, Threads  
**Each platform is individually enable/disable-able via `repos.yaml`.**

---

## Flow

```
Campaign issue created
       │
       ▼
  pr_analyst ──► pr_creative ──► pr_proposal (creates GitHub PR)
                                       │
                               Posts preview comment
                               to original issue
                                       │
                               Human reviews PR + preview
                                       │
                               Posts /post-social comment
                                       │
                               Watcher detects command
                                       │
                                       ▼
                               pr_social_post
                               ┌──────────────────────┐
                               │ Read pr_creative data │
                               │ For each enabled      │
                               │ platform:             │
                               │  - Refine via LLM     │
                               │  - Post via API       │
                               │  - Collect post URL   │
                               └──────────────────────┘
                                       │
                               Comment back to issue
                               with post links
```

---

## Configuration (`repos.yaml`)

Social credentials are stored per-repo entry in `repos.yaml` under a top-level `social:` key:

```yaml
repos:
  - name: my-project
    # ... existing fields ...
    social:
      x:
        enabled: true
        api_key: "..."
        api_secret: "..."
        access_token: "..."
        access_secret: "..."
      instagram:
        enabled: false
        access_token: "..."
        ig_user_id: "..."
      threads:
        enabled: true
        access_token: "..."
        threads_user_id: "..."
```

- All three platform blocks are optional. Missing block = platform disabled.
- `enabled: false` disables a platform without removing its credentials.
- Values can reference environment variables via `${ENV_VAR}` syntax (consistent with existing grok/openai credential handling).

---

## New Files

| File | Purpose |
|------|---------|
| `agents/pr_social_post.py` | `PRSocialPostAgent` — reads creative output, refines + posts per platform |
| `roles/pr_social_post.md` | Role prompt for content refinement per platform |

---

## `PRSocialPostAgent`

Subclasses `BaseAgent`. Role name: `pr_social_post`.

### Input

Reads from the campaign issue context (passed in as part of the orchestrator stage run, same pattern as other PR campaign agents):
- `pr_creative_output` — the full structured output from `PRCreativeAgent`, specifically:
  - `social_copy_example` — ready-to-post draft caption
  - `platform_tactics` — per-platform tactics dict
  - `big_idea`, `headline_hook` from the chosen campaign concept

### Per-platform content refinement

For each enabled platform, calls `self.call()` with the platform-specific prompt from `pr_social_post.md`. The LLM is given the `pr_creative` draft and asked to refine it to platform requirements:

| Platform | Constraints |
|----------|------------|
| X/Twitter | ≤280 characters, 1–3 relevant hashtags, punchy hook first |
| Instagram | Caption up to 2200 chars, 5–10 hashtags at end, conversational tone, emoji-friendly |
| Threads | ≤500 characters, conversational/informal tone, 1–2 hashtags max |

LLM output: JSON with `{ "content": "...", "hashtags": [...] }` per platform.

### Posting

Each enabled platform posts via its respective API:

**X/Twitter — Twitter API v2**
- Endpoint: `POST https://api.twitter.com/2/tweets`
- Auth: OAuth 1.0a (api_key, api_secret, access_token, access_secret)
- Library: `tweepy` (add to `requirements.txt`)

**Instagram — Meta Graph API**
- Endpoint: `POST /{ig_user_id}/media` then `POST /{ig_user_id}/media_publish`
- Auth: Bearer `access_token`
- Caption: `content + "\n\n" + " ".join(hashtags)`
- Note: Requires Instagram Business or Creator account with API access

**Threads — Threads API**
- Endpoint: `POST https://graph.threads.net/v1.0/{threads_user_id}/threads` then `.../threads_publish`
- Auth: Bearer `access_token`
- Same two-step create + publish flow as Instagram

### Output

Returns a dict:
```python
{
    "posted": {
        "x": {"url": "https://x.com/...", "id": "..."},
        "instagram": {"url": "https://www.instagram.com/p/...", "id": "..."},
        "threads": {"url": "https://www.threads.net/...", "id": "..."}
    },
    "skipped": ["instagram"],   # disabled or failed
    "errors": {}                 # platform -> error message if any
}
```

Posts to as many enabled platforms as possible; failures on one platform do not stop others.

### Issue comment

After posting, the agent comments back on the original campaign issue:

```
✅ Social posts published:
- X/Twitter: https://x.com/...
- Threads: https://www.threads.net/...

⏭️ Skipped: instagram (disabled in config)
```

---

## Orchestrator Changes

### Watcher — `/post-social` command

Extend `watcher.py` to detect `/post-social` in issue comments on repos that have a `pr-campaign` watcher entry. When detected:
1. Retrieve campaign context from the issue (same as how `pr_analyst` reads the brief)
2. Trigger `pr_social_post` stage via `orchestrator.run_stage()`

### `orchestrator.py`

- Add `_stage_pr_social_post()` method (same pattern as `_stage_pr_analyst` etc.)
- Add `pr_social_post` to `_make_stage_registry()`
- `pr-campaign.yaml` gains the 4th stage: `pr_social_post`

```yaml
# pipelines/pr-campaign.yaml
stages:
  - pr_analyst
  - pr_creative
  - pr_proposal
  - pr_social_post    # runs only on /post-social trigger
```

The orchestrator runs stages sequentially but `pr_social_post` only executes when explicitly triggered by the watcher command — it does not run automatically after `pr_proposal`.

---

## `roles/pr_social_post.md`

The role prompt receives:
- The `pr_creative` social copy draft
- Platform name and constraints
- The campaign's `big_idea` and `headline_hook`

It returns platform-optimized JSON: `{ "content": "...", "hashtags": [...] }`.

---

## Error Handling

- API auth failure: log error, add to `errors` dict, continue with other platforms
- Rate limit (HTTP 429): retry once after 10 seconds; if still failing, add to `errors`
- Missing credentials for enabled platform: log warning, treat as skipped
- LLM content generation failure: fall back to `social_copy_example` from `pr_creative` directly

---

## Dependencies

Add to `requirements.txt`:
- `tweepy>=4.14` — Twitter API v2 client
- `requests` — already present; used for Instagram and Threads Graph API calls

---

## Testing

- Unit tests in `tests/test_social_posting.py`:
  - `test_platform_content_refinement` — mock LLM, verify per-platform constraints (length, hashtag count)
  - `test_post_x_success` — mock tweepy, verify tweet posted
  - `test_post_instagram_success` — mock requests, verify two-step create+publish
  - `test_post_threads_success` — mock requests, verify two-step create+publish
  - `test_disabled_platform_skipped` — verify skipped platforms not posted to
  - `test_one_platform_failure_continues` — verify other platforms still post if one fails
  - `test_fallback_to_creative_draft` — verify fallback when LLM fails
- Integration test: `test_post_social_command_trigger` — mock watcher event, verify `pr_social_post` stage runs
