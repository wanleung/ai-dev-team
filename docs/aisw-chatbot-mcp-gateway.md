# AISW Chatbot MCP Gateway

## Purpose

This document describes how to integrate `ai-software-house` with a chat bot so users can trigger and monitor software delivery pipelines from chat apps, similar in spirit to OpenClaw.

The first target is not a full personal assistant. The practical first target is:

> A chat bot that controls `ai-software-house` pipeline jobs through the existing MCP server.

## Current Foundation

`ai-software-house` already exposes an integration server in `aisw_server.py`.

When `fastapi-mcp` is installed, the server mounts MCP tools from the FastAPI routes:

- `POST /runs` — submit a pipeline job
- `GET /runs` — list recent jobs
- `GET /runs/{run_id}` — get status, result, PR URL, test status
- `DELETE /runs/{run_id}` — cancel a job
- `GET /runs/{run_id}/stream` — stream logs with Server-Sent Events

This is enough for a bot to submit work, report progress, and return GitHub PR links.

## Target Architecture

```text
Chat app
  ↓
Bot gateway
  ↓
Intent parser / LLM router
  ↓
AISW MCP client
  ↓
aisw_server.py /mcp
  ↓
JobRunner
  ↓
Orchestrator pipeline
  ↓
GitHub Issue / Branch / PR / Tests
```

## User Experience

Example:

```text
User:
Build a FastAPI booking API in wanleung/mybooking using the TDD pipeline.

Bot:
Submitted run 8f2c...
Repo: wanleung/mybooking
Pipeline: tdd
I will post progress here.

Bot:
PM stage complete.
Architecture stage complete.
Tests written.
PR opened: https://github.com/wanleung/mybooking/pull/12
Tests: failed, test-fix loop running.
```

Recommended commands:

- `/run <repo> <pipeline> <requirement>`
- `/status <run_id>`
- `/logs <run_id>`
- `/cancel <run_id>`
- `/jobs`
- `/help`

Natural language can be added on top:

```text
"Run q-test in TDD mode for a BilliHub notification preference fix"
```

The bot should convert this into a structured `RunRequest`.

## Minimum Bot Responsibilities

The bot gateway should handle:

- Chat platform authentication
- User allowlist
- Repo allowlist
- Pipeline allowlist
- Mapping chat users to permissions
- Parsing commands into AISW run requests
- Calling the AISW MCP tools
- Polling or streaming job status
- Posting PR URLs, test results, and failure summaries

The bot should not directly run shell commands or edit repos. That remains the job of `ai-software-house`.

## MCP Request Shape

The existing `RunRequest` supports:

```json
{
  "requirement": "Build a FastAPI todo API",
  "repo": "owner/repo",
  "pipeline": "tdd",
  "engineers": 2
}
```

The response returns:

```json
{
  "run_id": "uuid",
  "status": "queued",
  "stream_url": "/runs/{run_id}/stream"
}
```

## Security Model

This layer needs explicit security before exposing it to real chat apps.

Required controls:

- Set `AISW_API_KEY`; never use the default `change-me`.
- Only allow known chat user IDs.
- Only allow approved repos.
- Only allow approved pipelines.
- Require confirmation before expensive runs.
- Require confirmation before pipelines that can push code.
- Rate-limit per user.
- Log every command with user ID, repo, pipeline, and run ID.
- Do not expose raw logs to users who cannot access the target repo.

Recommended approval flow:

```text
User:
Run TDD pipeline on wanleung/q-test: fix notification tests.

Bot:
This will create branches/PRs in wanleung/q-test.
Pipeline: tdd
Engineers: 2
Confirm? yes/no
```

## Phase 1: Command Bot

Build a simple bot with command parsing only.

Scope:

- Telegram, Discord, or Slack only
- `/run`
- `/status`
- `/cancel`
- `/jobs`
- simple polling for status
- final PR/test summary

No LLM router yet.

Implementation options:

- `bot/telegram_bot.py`
- `bot/discord_bot.py`
- `bot/slack_bot.py`

The bot can call the REST API directly or use MCP. REST is simpler for the first version; MCP is better if the bot itself is an LLM agent with tool calling.

## Phase 2: Natural Language Router

Add an LLM router that converts user text into structured actions.

Example output:

```json
{
  "action": "submit_run",
  "repo": "wanleung/q-test",
  "pipeline": "tdd",
  "engineers": 2,
  "requirement": "Fix notification preference tests and generated pytest issues"
}
```

The router must be constrained to a fixed action schema:

- `submit_run`
- `get_status`
- `list_runs`
- `cancel_run`
- `get_logs`
- `help`
- `unknown`

Never let the LLM invent arbitrary tools or shell commands.

## Phase 3: Streaming Updates

Use `/runs/{run_id}/stream` to post progress into chat.

Recommended behavior:

- Send important stage transitions.
- Collapse noisy logs.
- Post failure summaries.
- Post final PR URL and test status.
- Keep raw logs behind `/logs <run_id>` or an admin-only command.

## Phase 4: OpenClaw-Like Features

After the command bot is stable, add:

- Per-user sessions
- Chat memory
- Multi-channel support
- Channel pairing / allowlist flow
- Per-repo permissions
- Bot dashboard
- Saved presets, e.g. `q-test-tdd`, `ai-it-press-news`
- Scheduled jobs
- Voice input, if useful

## Gaps Compared With OpenClaw

This design does not initially provide:

- General personal assistant behavior
- Email/calendar/message management
- Mobile node support
- Voice/camera/media workflows
- A broad skill marketplace
- A full chat/session dashboard

It does provide a narrower but practical equivalent:

> Chat-controlled software delivery automation.

## Recommended First Implementation

Start with a Telegram or Discord command bot.

Why:

- Smallest integration surface
- Easy user ID allowlisting
- Good enough for mobile control
- No need to solve multi-channel routing immediately

Suggested first milestones:

1. Start `aisw_server.py` with a real `AISW_API_KEY`.
2. Build `/health` and `/jobs` bot commands.
3. Build `/run` with explicit repo/pipeline args.
4. Add confirmation before submit.
5. Add `/status` and final PR summary.
6. Add SSE-based progress updates.
7. Add natural language routing.

## Example Command Contract

```text
/run repo=wanleung/q-test pipeline=tdd engineers=2 requirement="Fix BilliHub notification preference tests"
```

Bot validation:

- `repo` must be in allowlist.
- `pipeline` must be one of configured pipeline names.
- `engineers` must be within configured limit.
- `requirement` must be non-empty and below size limit.

AISW request:

```json
{
  "repo": "wanleung/q-test",
  "pipeline": "tdd",
  "engineers": 2,
  "requirement": "Fix BilliHub notification preference tests"
}
```

## Operational Notes

- Run the bot and `aisw_server.py` as separate processes.
- Keep `aisw_server.py` private on localhost or behind Tailscale/VPN.
- Store bot tokens outside git.
- Use one SQLite `jobs.db` per deployment.
- Monitor `logs/jobs/`.
- Avoid exposing `workspace/` files directly through chat.

## Summary

The current MCP server is enough to build a first useful chatbot integration.

The right first product is:

> A secure chat gateway for submitting and monitoring AISW pipeline jobs.

This gives the project an OpenClaw-like interaction surface while preserving the existing strength of `ai-software-house`: structured GitHub-based software delivery.
