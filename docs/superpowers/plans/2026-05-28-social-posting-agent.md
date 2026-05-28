# Social Posting Agent — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `pr_social_post` stage to the PR campaign pipeline that posts social content to X/Twitter, Instagram, and Threads via MCP servers, triggered by a `/post-social` GitHub issue comment.

**Architecture:** When `pr_proposal` completes, it posts a special issue comment embedding the creative JSON as an HTML comment block. The watcher detects `/post-social` comments on `agent-complete` issues, adds an `ai-social-post` label, which triggers the single-stage `pr-social-post` pipeline. `PRSocialPostAgent` reads the creative data from prior context, refines it per platform via LLM, then posts via MCP tool calls. Each platform is enabled/disabled via `mcp_servers:` entries in `repos.yaml`.

**Tech Stack:** Python (existing agent pattern), MCP stdio servers (npx), GitHub Issues API (existing client), `MCPToolRegistry` (already in codebase)

**Branch:** `feature/social-posting-agent`

---

## File Map

| File | Change |
|------|--------|
| `agents/pr_social_post.py` | **Create** — new `PRSocialPostAgent` |
| `roles/pr_social_post.md` | **Create** — system prompt for the agent |
| `orchestrator.py` | **Modify** — store `_mcp_servers`, add `_stage_pr_social_post`, build PR stage registry, add `_build_social_mcp_registry` |
| `watcher.py` | **Modify** — add `_check_social_post_commands()` and call in `watch()` |
| `pipelines/pr-social-post.yaml` | **Create** — single-stage pipeline for social posting |
| `pipelines/pr-campaign.yaml` | No change (social post runs via its own pipeline) |
| `tests/test_social_posting.py` | **Create** — unit tests for the new agent and watcher function |

---

## Task 1: Switch to `feature/social-posting-agent`

- [ ] **Step 1: Check out the feature branch**

```bash
cd /home/wanleung/Projects/ai-software-house
git checkout feature/social-posting-agent
```

Expected: `Switched to branch 'feature/social-posting-agent'`

---

## Task 2: Create the role prompt

**Files:**
- Create: `roles/pr_social_post.md`

- [ ] **Step 1: Write the role prompt**

Create `roles/pr_social_post.md`:

```markdown
# Role: PR Social Post Agent (Alex)

You are Alex, a social media specialist who adapts PR campaign concepts into
platform-native posts. You receive a campaign's creative brief and produce
concise, engaging content tailored to each platform's constraints.

## Your Outputs

For each enabled platform, you return a JSON object:

```json
{
  "x_twitter": {
    "text": "...",
    "posted": false,
    "url": null,
    "error": null
  },
  "instagram": {
    "caption": "...",
    "posted": false,
    "url": null,
    "error": null
  },
  "threads": {
    "text": "...",
    "posted": false,
    "url": null,
    "error": null
  }
}
```

## Platform Constraints

**X/Twitter:** ≤280 characters. Include 1–3 hashtags. Open with a hook.
End with a CTA. No line breaks in the middle of sentences.

**Instagram:** ≤2200 characters. Include 5–10 hashtags at the end (separated
by newlines). Conversational, visual language. Include an emoji or two.

**Threads:** ≤500 characters. Conversational and direct. 1–2 hashtags max.
Feels like a genuine post, not a press release.

## Source Material

You receive a PR campaign creative brief containing concepts and a
`social_copy_example`. Use these as your starting point. Adapt, do not
copy verbatim. The copy should feel authentic on each platform.

## Output Format

Return ONLY a valid JSON object (no markdown fences, no explanation).
The keys must be exactly: `x_twitter`, `instagram`, `threads`.
Omit a platform key entirely if it is not enabled.
```

---

## Task 3: Write failing tests

**Files:**
- Create: `tests/test_social_posting.py`

- [ ] **Step 1: Write the test file**

Create `tests/test_social_posting.py`:

```python
"""Tests for PRSocialPostAgent and watcher /post-social command detection."""
from __future__ import annotations
import json
from unittest.mock import MagicMock, patch

import pytest


# ── PRSocialPostAgent unit tests ─────────────────────────────────────────────

class TestPRSocialPostAgentParse:
    """Test that the agent parses social data correctly from prior context."""

    def _make_agent(self):
        from agents.pr_social_post import PRSocialPostAgent
        agent = PRSocialPostAgent.__new__(PRSocialPostAgent)
        agent._tool_registry = None
        return agent

    def test_extract_social_data_found(self):
        from agents.pr_social_post import extract_social_copy_data
        creative = {"social_copy_example": "Big news!", "angle": "test"}
        payload = json.dumps(creative)
        prior_ctx = f"Some text\n<!-- social-copy-data\n{payload}\n-->\nMore text"
        result = extract_social_copy_data(prior_ctx)
        assert result is not None
        assert result["social_copy_example"] == "Big news!"

    def test_extract_social_data_missing(self):
        from agents.pr_social_post import extract_social_copy_data
        assert extract_social_copy_data("no data here") is None

    def test_build_prompt_includes_platforms(self):
        from agents.pr_social_post import PRSocialPostAgent
        agent = PRSocialPostAgent.__new__(PRSocialPostAgent)
        creative = {"social_copy_example": "Example copy", "angle": "test angle"}
        prompt = agent._build_prompt(creative, ["x_twitter", "instagram"])
        assert "x_twitter" in prompt.lower() or "x/twitter" in prompt.lower()
        assert "instagram" in prompt.lower()
        assert "Example copy" in prompt

    def test_parse_llm_output_valid_json(self):
        from agents.pr_social_post import PRSocialPostAgent
        agent = PRSocialPostAgent.__new__(PRSocialPostAgent)
        raw = json.dumps({
            "x_twitter": {"text": "Hello world! #test", "posted": False, "url": None, "error": None},
            "instagram": {"caption": "Hello world! #test #social", "posted": False, "url": None, "error": None},
        })
        result = agent._parse_llm_output(raw)
        assert result["x_twitter"]["text"] == "Hello world! #test"
        assert "instagram" in result

    def test_parse_llm_output_strips_fences(self):
        from agents.pr_social_post import PRSocialPostAgent
        agent = PRSocialPostAgent.__new__(PRSocialPostAgent)
        raw = '```json\n{"x_twitter": {"text": "Hi!", "posted": false, "url": null, "error": null}}\n```'
        result = agent._parse_llm_output(raw)
        assert result["x_twitter"]["text"] == "Hi!"

    def test_parse_llm_output_invalid_returns_empty(self):
        from agents.pr_social_post import PRSocialPostAgent
        agent = PRSocialPostAgent.__new__(PRSocialPostAgent)
        result = agent._parse_llm_output("not json at all")
        assert result == {}


class TestPRSocialPostAgentRun:
    """Test agent.run() end-to-end with a mocked LLM call."""

    def test_run_posts_to_enabled_platforms(self):
        from agents.pr_social_post import PRSocialPostAgent, extract_social_copy_data
        creative = {
            "social_copy_example": "Big announcement today!",
            "angle": "innovation",
            "Opportunity": "New product launch",
        }
        prior_ctx_payload = json.dumps(creative)
        prior_ctx = f"<!-- social-copy-data\n{prior_ctx_payload}\n-->"

        llm_output = json.dumps({
            "x_twitter": {"text": "Big announcement! #launch", "posted": False, "url": None, "error": None},
        })

        with patch.object(PRSocialPostAgent, "call", return_value=llm_output) as mock_call:
            agent = PRSocialPostAgent.__new__(PRSocialPostAgent)
            agent._tool_registry = None
            # Simulate _post_platform returning a URL
            with patch.object(PRSocialPostAgent, "_post_platform", return_value="https://x.com/status/1") as mock_post:
                context = {
                    "prior_context": prior_ctx,
                    "enabled_platforms": ["x_twitter"],
                    "issue_number": 42,
                    "github_client": None,
                }
                result = agent.run(context)

        assert "pr_social_post" in result
        output = result["pr_social_post"]
        assert "x_twitter" in output

    def test_run_fails_gracefully_when_no_social_data(self):
        from agents.pr_social_post import PRSocialPostAgent
        agent = PRSocialPostAgent.__new__(PRSocialPostAgent)
        agent._tool_registry = None
        context = {
            "prior_context": "no social data here",
            "enabled_platforms": ["x_twitter"],
            "issue_number": 42,
            "github_client": None,
        }
        result = agent.run(context)
        assert "pr_social_post" in result
        assert "error" in result["pr_social_post"]


# ── Watcher command detection tests ──────────────────────────────────────────

class TestCheckSocialPostCommands:
    """Test _check_social_post_commands watcher function."""

    def test_detects_post_social_comment(self):
        """Returns a task when an agent-complete issue has /post-social comment."""
        from watcher import _check_social_post_commands

        mock_issues = [
            {
                "number": 10,
                "title": "Campaign X",
                "body": "Launch brief",
                "labels": [
                    {"name": "agent-complete"},
                    {"name": "pr-campaign"},
                ],
            }
        ]
        mock_comments = [
            {"body": "/post-social", "user": {"login": "wanleung"}},
        ]

        watchers = [
            {
                "tracker_repo": "owner/tracker",
                "enabled": True,
                "labels": {"pr-campaign": {"pipeline": "pr-campaign"}},
                "mcp_servers": [
                    {"name": "x-twitter", "enabled": True, "command": "npx", "args": ["-y", "@modelcontextprotocol/server-twitter"]},
                ],
            }
        ]

        with patch("watcher.get_open_issues", return_value=mock_issues), \
             patch("watcher._get_issue_comments", return_value=mock_comments), \
             patch("watcher.add_label") as mock_add_label, \
             patch("watcher.remove_label") as mock_remove_label:
            tasks = _check_social_post_commands(watchers, "fake-token")

        assert len(tasks) == 1
        assert tasks[0]["issue"]["number"] == 10
        assert tasks[0]["tracker_repo"] == "owner/tracker"
        mock_add_label.assert_called_once_with("owner/tracker", 10, "ai-social-post")

    def test_skips_already_posted_issues(self):
        """Does not return a task when ai-social-post label already applied."""
        from watcher import _check_social_post_commands

        mock_issues = [
            {
                "number": 11,
                "title": "Campaign Y",
                "body": "Brief",
                "labels": [
                    {"name": "agent-complete"},
                    {"name": "ai-social-post"},  # already labelled
                ],
            }
        ]
        mock_comments = [{"body": "/post-social", "user": {"login": "wanleung"}}]
        watchers = [
            {
                "tracker_repo": "owner/tracker",
                "enabled": True,
                "labels": {"pr-campaign": {"pipeline": "pr-campaign"}},
                "mcp_servers": [
                    {"name": "x-twitter", "enabled": True, "command": "npx", "args": ["-y", "@modelcontextprotocol/server-twitter"]},
                ],
            }
        ]

        with patch("watcher.get_open_issues", return_value=mock_issues), \
             patch("watcher._get_issue_comments", return_value=mock_comments), \
             patch("watcher.add_label") as mock_add_label:
            tasks = _check_social_post_commands(watchers, "fake-token")

        assert tasks == []
        mock_add_label.assert_not_called()

    def test_skips_watchers_without_social_mcp(self):
        """Does not scan issues when watcher has no enabled social MCP servers."""
        from watcher import _check_social_post_commands

        watchers = [
            {
                "tracker_repo": "owner/tracker",
                "enabled": True,
                "labels": {"pr-campaign": {}},
                "mcp_servers": [],  # no social servers
            }
        ]

        with patch("watcher.get_open_issues") as mock_get:
            tasks = _check_social_post_commands(watchers, "fake-token")

        mock_get.assert_not_called()
        assert tasks == []
```

- [ ] **Step 2: Run the tests to confirm they fail (agent doesn't exist yet)**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_social_posting.py -v 2>&1 | head -40
```

Expected: Most tests fail with `ModuleNotFoundError: No module named 'agents.pr_social_post'` or `ImportError`. A few may error with `cannot import name '_check_social_post_commands' from 'watcher'`. That's correct.

---

## Task 4: Create `agents/pr_social_post.py`

**Files:**
- Create: `agents/pr_social_post.py`

- [ ] **Step 1: Write the agent**

Create `agents/pr_social_post.py`:

```python
"""PR Social Post Agent — posts campaign social copy to configured platforms via MCP."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

_SOCIAL_DATA_RE = re.compile(
    r"<!--\s*social-copy-data\s*\n(.*?)\n-->",
    re.DOTALL,
)

_PLATFORM_CHAR_LIMITS = {
    "x_twitter":  280,
    "instagram": 2200,
    "threads":    500,
}


def extract_social_copy_data(text: str) -> dict | None:
    """Extract the JSON payload from a <!-- social-copy-data ... --> HTML comment block.

    Returns the parsed dict, or None if the block is absent or malformed.
    """
    m = _SOCIAL_DATA_RE.search(text or "")
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        logger.warning("social-copy-data block is not valid JSON: %s", exc)
        return None


class PRSocialPostAgent(BaseAgent):
    """
    PR Social Post Agent (Alex) — Publishes campaign content to social platforms.

    Reads creative brief data from prior issue context, generates platform-specific
    copy via LLM, then posts each piece via MCP tool calls.
    """

    role_name = "pr_social_post"

    def __init__(self, *args, tool_registry=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._tool_registry = tool_registry

    # ── Public entry point ────────────────────────────────────────────────────

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        """Execute the social posting stage.

        Expects context keys:
            prior_context     str   — issue body + prior comments (contains social-copy-data)
            enabled_platforms list  — e.g. ["x_twitter", "instagram", "threads"]
            issue_number      int   — GitHub issue number for the reply comment
            github_client     obj   — GitHub client with add_issue_comment()
        """
        prior_ctx      = context.get("prior_context", "")
        platforms      = context.get("enabled_platforms", [])
        issue_number   = context.get("issue_number")
        github_client  = context.get("github_client")

        creative = extract_social_copy_data(prior_ctx)
        if not creative:
            logger.error("No social-copy-data block found in issue context. Was pr_proposal run?")
            context["pr_social_post"] = {
                "error": "No social-copy-data found. Run the pr-campaign pipeline first, then comment /post-social."
            }
            return context

        logger.info("Generating social copy for platforms: %s", platforms)
        platform_copy = self._generate_platform_copy(creative, platforms)
        results = {}
        for platform, copy_data in platform_copy.items():
            if not copy_data.get("text") and not copy_data.get("caption"):
                results[platform] = {"posted": False, "url": None, "error": "LLM returned no content"}
                continue
            content = copy_data.get("text") or copy_data.get("caption") or ""
            url, error = self._post_platform(platform, content)
            results[platform] = {
                "content": content,
                "posted": url is not None,
                "url": url,
                "error": error,
            }
            logger.info("Platform %s: posted=%s url=%s", platform, url is not None, url)

        # Post a summary comment back to the issue
        if github_client and issue_number:
            summary = self._build_summary_comment(results)
            try:
                github_client.add_issue_comment(issue_number, summary)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not post summary comment to issue #%d: %s", issue_number, exc)

        context["pr_social_post"] = results
        return context

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _generate_platform_copy(
        self, creative: dict, platforms: list[str]
    ) -> dict[str, dict]:
        """Ask LLM to produce platform-specific copy. Returns dict keyed by platform."""
        prompt = self._build_prompt(creative, platforms)
        try:
            raw = self.call(prompt)
            parsed = self._parse_llm_output(raw)
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM call failed (%s); using social_copy_example as fallback", exc)
            fallback = creative.get("social_copy_example", "")
            parsed = {p: {"text": fallback[:_PLATFORM_CHAR_LIMITS.get(p, 500)]} for p in platforms}
        return parsed

    def _build_prompt(self, creative: dict, platforms: list[str]) -> str:
        platform_list = "\n".join(f"- {p}" for p in platforms)
        return (
            f"Campaign creative brief:\n"
            f"- Opportunity: {creative.get('Opportunity', creative.get('opportunity', ''))}\n"
            f"- Angle: {creative.get('Angle', creative.get('angle', ''))}\n"
            f"- Audience: {creative.get('Audience', creative.get('audience', ''))}\n"
            f"- Draft copy: {creative.get('social_copy_example', '')}\n\n"
            f"Enabled platforms:\n{platform_list}\n\n"
            f"Platform character limits — x_twitter: 280, instagram: 2200, threads: 500.\n\n"
            f"Return ONLY a valid JSON object (no markdown fences) with one key per enabled "
            f"platform. Each value must have: text (or caption for instagram), posted=false, "
            f"url=null, error=null."
        )

    def _parse_llm_output(self, raw: str) -> dict:
        """Parse LLM output to a dict of platform→copy. Returns {} on failure."""
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # Try extracting the first JSON object from the string
            m = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group())
                except json.JSONDecodeError:
                    pass
        return {}

    def _post_platform(self, platform: str, content: str) -> tuple[str | None, str | None]:
        """Post content to a single platform via MCP tool call.

        Returns (url, error). One of them will be None.
        """
        if not self._tool_registry:
            return None, "No tool registry configured — MCP server not available"

        try:
            if platform == "x_twitter":
                result = self._tool_registry.call_tool(
                    "create_tweet", {"text": content}
                )
                url = (result or {}).get("url") or (result or {}).get("tweet_url")
                return url, None

            elif platform == "instagram":
                media_result = self._tool_registry.call_tool(
                    "create_media_post",
                    {"caption": content, "media_type": "IMAGE"},
                )
                creation_id = (media_result or {}).get("id")
                if not creation_id:
                    return None, "create_media_post returned no id"
                publish_result = self._tool_registry.call_tool(
                    "publish_media", {"creation_id": creation_id}
                )
                url = (publish_result or {}).get("id") or (publish_result or {}).get("url")
                return str(url) if url else None, None

            elif platform == "threads":
                result = self._tool_registry.call_tool(
                    "create_thread", {"text": content}
                )
                url = (result or {}).get("url") or (result or {}).get("permalink")
                return url, None

            else:
                return None, f"Unknown platform: {platform}"

        except Exception as exc:  # noqa: BLE001
            logger.warning("MCP post failed for %s: %s", platform, exc)
            return None, str(exc)

    def _build_summary_comment(self, results: dict[str, dict]) -> str:
        lines = ["## 📣 Social Post Results\n"]
        for platform, data in results.items():
            icon = "✅" if data.get("posted") else "❌"
            display_name = {
                "x_twitter": "X/Twitter",
                "instagram": "Instagram",
                "threads": "Threads",
            }.get(platform, platform)
            if data.get("url"):
                lines.append(f"{icon} **{display_name}**: [{data['url']}]({data['url']})")
            elif data.get("error"):
                lines.append(f"{icon} **{display_name}**: {data['error']}")
            else:
                lines.append(f"{icon} **{display_name}**: posted (no URL returned)")
        return "\n".join(lines)
```

- [ ] **Step 2: Run the agent tests**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_social_posting.py::TestPRSocialPostAgentParse tests/test_social_posting.py::TestPRSocialPostAgentRun -v
```

Expected: All 7 agent tests pass. Watcher tests still fail.

---

## Task 5: Create `pipelines/pr-social-post.yaml`

**Files:**
- Create: `pipelines/pr-social-post.yaml`

- [ ] **Step 1: Write the pipeline file**

Create `pipelines/pr-social-post.yaml`:

```yaml
# PR Social Post pipeline — runs ONLY when /post-social is detected by watcher.
# Triggered by the ai-social-post label added to completed pr-campaign issues.
stages:
  - pr_social_post
```

---

## Task 6: Update `orchestrator.py` — store `_mcp_servers` + add social stage

**Files:**
- Modify: `orchestrator.py` — `_init_tool_registries`, `_stage_pr_social_post`, `_build_product_stages_pr`

### 6a: Store `_mcp_servers` as an attribute

The social posting stage needs to build a platform-specific MCP registry at runtime. We store the raw server list when the orchestrator is initialised.

- [ ] **Step 1: Store `_mcp_servers` in `_init_tool_registries`**

Find (in `_init_tool_registries`, line 903):
```python
    def _init_tool_registries(self, mcp_servers: "list[dict] | None") -> None:
        """Build MCP, RAG and Google Search tool registries; also initialises repo_auto_indexer."""
        # Combined tool registry (builtin + optional MCP)
```

Replace with:
```python
    def _init_tool_registries(self, mcp_servers: "list[dict] | None") -> None:
        """Build MCP, RAG and Google Search tool registries; also initialises repo_auto_indexer."""
        self._mcp_servers: list[dict] = mcp_servers or []
        # Combined tool registry (builtin + optional MCP)
```

### 6b: Add `_build_social_mcp_registry` helper

- [ ] **Step 2: Add helper method right after `_init_tool_registries`**

Find the line starting with `    # ── LLM config + agent kwargs helpers` (after `_init_tool_registries`):

```python
    # ── LLM config + agent kwargs helpers ────────────────────────────────────
```

Insert before that line:

```python
    def _build_social_mcp_registry(self) -> "MCPToolRegistry | None":
        """Build an MCP registry containing only enabled social platform servers."""
        social_names = {"x-twitter", "instagram", "threads"}
        social_servers = [
            s for s in self._mcp_servers
            if s.get("name") in social_names and s.get("enabled", True)
        ]
        if not social_servers:
            return None
        try:
            return MCPToolRegistry(social_servers)
        except Exception as exc:
            logger.warning("[orchestrator] Social MCP registry init failed: %s", exc)
            return None

```

### 6c: Add `_stage_pr_social_post` method

- [ ] **Step 3: Add the stage method after `_stage_pr_proposal` (line 1575)**

Find the line:
```python
    def _stage_validation_gate(self, result: "PipelineResult") -> None:
```

Insert before it:

```python
    def _stage_pr_social_post(self, result: "PipelineResult") -> None:
        """Post campaign social copy to configured social platforms via MCP.

        Reads creative data from the social-copy-data block embedded in the
        issue's prior comment context by _stage_pr_proposal. Posts to each
        enabled social platform via MCP tool calls.
        """
        import json as _json
        from agents.pr_social_post import PRSocialPostAgent

        prior_ctx = getattr(self, "_issue_prior_context", "") or ""
        social_registry = self._build_social_mcp_registry()
        enabled_platforms = [
            s["name"].replace("-", "_")
            for s in self._mcp_servers
            if s.get("name") in ("x-twitter", "instagram", "threads") and s.get("enabled", True)
        ]
        # Map hyphenated names to underscore (x-twitter → x_twitter)
        enabled_platforms = [p.replace("-", "_") for p in enabled_platforms]

        if not enabled_platforms:
            result.add_error("pr_social_post: no enabled social MCP servers found in config")
            return

        agent = PRSocialPostAgent(
            model=self._resolve_agent_model("pr_social_post"),
            github_token=self._github_token,
            ollama_url=self.ollama_url,
            tool_registry=social_registry,
        )
        gh = self.target_github or self.github
        context = {
            "prior_context": prior_ctx,
            "enabled_platforms": enabled_platforms,
            "issue_number": result.issue_number,
            "github_client": gh,
        }
        updated = agent.run(context)
        setattr(result, "pr_social_post_output", updated.get("pr_social_post"))
        post_output = updated.get("pr_social_post", {})
        if post_output.get("error"):
            result.add_error(f"pr_social_post: {post_output['error']}")
        else:
            posted = [p for p, d in post_output.items() if isinstance(d, dict) and d.get("posted")]
            logger.info("Social posts published to: %s", ", ".join(posted) or "none")

```

### 6d: Register the stage in `_build_product_stages_pr`

- [ ] **Step 4: Add `pr_social_post` stage to `_build_product_stages_pr`**

Find:
```python
        stages["pr_proposal"] = PipelineStage(
            name="pr_proposal",
            label="📋 PR Proposal",
            description="Assembling proposal and opening PR...",
            checkpoint_key="pr_proposal",
            fn=lambda r: self._stage_pr_proposal(r),
        )
        return stages
```

Replace with:
```python
        stages["pr_proposal"] = PipelineStage(
            name="pr_proposal",
            label="📋 PR Proposal",
            description="Assembling proposal and opening PR...",
            checkpoint_key="pr_proposal",
            fn=lambda r: self._stage_pr_proposal(r),
        )
        stages["pr_social_post"] = PipelineStage(
            name="pr_social_post",
            label="📣 Social Post",
            description="Publishing social copy to configured platforms...",
            checkpoint_key="pr_social_post",
            fn=lambda r: self._stage_pr_social_post(r),
        )
        return stages
```

---

## Task 7: Update `_stage_pr_proposal` to embed social copy data

**Files:**
- Modify: `orchestrator.py` — `_stage_pr_proposal`

When `pr_proposal` completes, we post a special issue comment that:
1. Shows a human-readable social copy preview (so the team can review before posting)
2. Embeds the full creative JSON in a `<!-- social-copy-data ... -->` HTML comment block

This comment will be picked up by `_collect_issue_prior_context` in the next watcher cycle and made available to `_stage_pr_social_post` via `self._issue_prior_context`.

- [ ] **Step 1: Add social copy comment posting to `_stage_pr_proposal`**

Find:
```python
        if proposal.get("pr_url"):
            result.pr_url = proposal["pr_url"]
        if proposal.get("pr_number"):
            result.pr_number = proposal["pr_number"]
        if proposal.get("branch_name"):
            result.branch = proposal["branch_name"]
```

Replace with:
```python
        if proposal.get("pr_url"):
            result.pr_url = proposal["pr_url"]
        if proposal.get("pr_number"):
            result.pr_number = proposal["pr_number"]
        if proposal.get("branch_name"):
            result.branch = proposal["branch_name"]

        # Post social copy preview so /post-social can use it
        if creative_output and result.issue_number:
            import json as _json
            gh_client = self.target_github or self.github
            social_example = ""
            if isinstance(creative_output, list) and creative_output:
                social_example = creative_output[0].get("social_copy_example", "")
            elif isinstance(creative_output, dict):
                social_example = creative_output.get("social_copy_example", "")
            payload = _json.dumps(creative_output, ensure_ascii=False)
            comment_body = (
                "## 📣 Campaign Social Copy Ready\n\n"
                + (f"> {social_example}\n\n" if social_example else "")
                + "_Comment `/post-social` to publish to configured platforms._\n\n"
                + f"<!-- social-copy-data\n{payload}\n-->"
            )
            try:
                gh_client.add_issue_comment(result.issue_number, comment_body)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not post social copy preview comment: %s", exc)
```

---

## Task 8: Add `/post-social` command detection to `watcher.py`

**Files:**
- Modify: `watcher.py` — add `_check_social_post_commands()` and call in `watch()`

The function scans `agent-complete` issues on pr-campaign-related watchers, checks for a `/post-social` comment, and applies the `ai-social-post` label to trigger the social post pipeline.

### 8a: Add `_get_issue_comments` helper (if not already present)

- [ ] **Step 1: Check whether `_get_issue_comments` exists as a module-level function**

```bash
grep -n "^def _get_issue_comments\|^def get_open_issues" watcher.py
```

If `_get_issue_comments` does not exist at module level (it may only exist inside `_collect_issue_prior_context` via `tracker_gh.get_issue_comments`), add it:

Find the line `def post_comment(repo: str, issue_number: int, body: str) -> None:` and insert before it:

```python
@_retry_github
def _get_issue_comments(repo: str, issue_number: int, token: str) -> list[dict]:
    """Fetch all comments on a GitHub issue."""
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments"
    resp = requests.get(url, headers=_gh_headers(), params={"per_page": 100}, timeout=10)
    resp.raise_for_status()
    return resp.json()

```

### 8b: Add `_check_social_post_commands` function

- [ ] **Step 2: Add the command detection function**

Find `def _build_watch_tasks(` and insert before it:

```python
def _check_social_post_commands(
    watchers: list[dict],
    github_token: str,  # noqa: ARG001 — kept for future auth needs
) -> list[dict]:
    """Scan agent-complete issues on pr-campaign repos for /post-social comments.

    For each watcher entry that has at least one enabled social MCP server,
    fetches open issues with the ``agent-complete`` label, checks their comments
    for a bare ``/post-social`` line, and — when found — applies the
    ``ai-social-post`` label so the next watcher cycle picks it up as a
    ``pr-social-post`` pipeline task.

    Returns a list of dicts (same shape as ``_build_watch_tasks`` tasks) for
    issues that were just labelled, so the caller can optionally log them.
    """
    _SOCIAL_SERVER_NAMES = {"x-twitter", "instagram", "threads"}
    _SKIP_LABELS = {"ai-social-post", "agent-running", "agent-social-posted"}
    labelled: list[dict] = []

    for w in watchers:
        if not w.get("enabled", True):
            continue
        mcp_servers = w.get("mcp_servers", [])
        social_servers = [
            s for s in mcp_servers
            if s.get("name") in _SOCIAL_SERVER_NAMES and s.get("enabled", True)
        ]
        if not social_servers:
            continue

        tracker_repo = w["tracker_repo"]
        try:
            complete_issues = get_open_issues(tracker_repo, LABEL_COMPLETE)
        except Exception as exc:  # noqa: BLE001
            _log.warning(
                "_check_social_post_commands: could not fetch issues from %s: %s",
                tracker_repo, exc,
            )
            continue

        for issue in complete_issues:
            issue_labels = {lbl["name"] for lbl in issue.get("labels", [])}
            if issue_labels & _SKIP_LABELS:
                continue  # already processing or already posted

            issue_number = issue["number"]
            try:
                comments = _get_issue_comments(tracker_repo, issue_number, github_token)
            except Exception as exc:  # noqa: BLE001
                _log.warning(
                    "_check_social_post_commands: could not fetch comments for #%d: %s",
                    issue_number, exc,
                )
                continue

            has_command = any(
                (c.get("body") or "").strip() == "/post-social"
                for c in comments
            )
            if not has_command:
                continue

            _log.info(
                "  /post-social detected on %s #%d — applying ai-social-post label",
                tracker_repo, issue_number,
            )
            try:
                add_label(tracker_repo, issue_number, "ai-social-post")
            except Exception as exc:  # noqa: BLE001
                _log.warning(
                    "_check_social_post_commands: could not label #%d: %s",
                    issue_number, exc,
                )
                continue
            labelled.append({"tracker_repo": tracker_repo, "issue": issue})

    return labelled

```

### 8c: Call `_check_social_post_commands` in `watch()`

- [ ] **Step 3: Call the function in the `watch()` main loop**

Find (in `watch()` function, line ~1663):
```python
    watcher_tasks = _build_watch_tasks(watchers, global_model, global_num_engineers, github_token)
    tasks.extend(watcher_tasks)
```

Replace with:
```python
    # Detect /post-social commands and apply ai-social-post label to eligible issues
    if not dry_run:
        _check_social_post_commands(watchers, github_token)

    watcher_tasks = _build_watch_tasks(watchers, global_model, global_num_engineers, github_token)
    tasks.extend(watcher_tasks)
```

---

## Task 9: Run the watcher tests

- [ ] **Step 1: Run all social posting tests**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_social_posting.py -v
```

Expected: All tests pass (or document any skips).

If `_get_issue_comments` does not have the same signature expected by the test (`(repo, issue_number, token)`), adjust the mock target accordingly.

- [ ] **Step 2: Run full test suite to check for regressions**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/ -x -q 2>&1 | tail -20
```

Expected: No new failures.

---

## Task 10: Update `repos.yaml` documentation (example config)

**Files:**
- Modify: `repos.yaml` (example/demo section, not user credentials — or `repos.yaml.example` if it exists)

- [ ] **Step 1: Check for a sample/example repos.yaml**

```bash
ls /home/wanleung/Projects/ai-software-house/repos.yaml* 2>/dev/null
```

If `repos.yaml.example` or a documentation section in `repos.yaml` exists, add the social MCP config pattern there. If only a real `repos.yaml` exists, add a comment block showing the pattern.

Find the watcher entry for a pr-campaign pipeline (look for `pr-campaign` label in labels:) and show the MCP server config alongside it. Insert after the existing labels config:

```yaml
    # Social posting — enable/disable per platform via enabled: flag
    mcp_servers:
      - name: x-twitter
        enabled: true   # set to false to disable X/Twitter posting
        command: npx
        args: ["-y", "@modelcontextprotocol/server-twitter"]
        env:
          TWITTER_API_KEY: "${TWITTER_API_KEY}"
          TWITTER_API_SECRET: "${TWITTER_API_SECRET}"
          TWITTER_ACCESS_TOKEN: "${TWITTER_ACCESS_TOKEN}"
          TWITTER_ACCESS_TOKEN_SECRET: "${TWITTER_ACCESS_TOKEN_SECRET}"
      - name: instagram
        enabled: false  # disabled by default — requires Instagram Graph API app
        command: npx
        args: ["-y", "mcp-instagram"]
        env:
          INSTAGRAM_ACCESS_TOKEN: "${INSTAGRAM_ACCESS_TOKEN}"
          INSTAGRAM_BUSINESS_ACCOUNT_ID: "${INSTAGRAM_BUSINESS_ACCOUNT_ID}"
      - name: threads
        enabled: false  # disabled by default — requires Meta Threads API access
        command: npx
        args: ["-y", "mcp-threads"]
        env:
          THREADS_ACCESS_TOKEN: "${THREADS_ACCESS_TOKEN}"
          THREADS_USER_ID: "${THREADS_USER_ID}"
```

---

## Task 11: Commit and open PR

- [ ] **Step 1: Commit all changes**

```bash
cd /home/wanleung/Projects/ai-software-house
git add \
  agents/pr_social_post.py \
  roles/pr_social_post.md \
  pipelines/pr-social-post.yaml \
  tests/test_social_posting.py \
  orchestrator.py \
  watcher.py
git commit -m "feat: Social Posting Agent — post campaign content via MCP on /post-social

New agent: PRSocialPostAgent
- Reads creative data from social-copy-data block embedded in issue by pr_proposal
- Generates platform-specific copy via LLM (X ≤280, Instagram ≤2200, Threads ≤500)
- Posts via MCP tool calls (x-twitter, instagram, threads)
- Per-platform enable/disable via mcp_servers.enabled in repos.yaml
- Falls back to social_copy_example if LLM fails

Orchestrator changes:
- _stage_pr_social_post: new stage method
- _build_social_mcp_registry: filtered MCP registry for social servers
- _mcp_servers stored as instance attr for runtime access
- _stage_pr_proposal: posts social-copy-data HTML comment for downstream use
- _build_product_stages_pr: registers pr_social_post stage

Watcher changes:
- _check_social_post_commands(): scans agent-complete issues for /post-social
- Applies ai-social-post label to trigger pr-social-post pipeline
- Called from watch() main loop (skipped in dry-run mode)

New pipeline: pipelines/pr-social-post.yaml (single pr_social_post stage)"
```

- [ ] **Step 2: Push branch and open PR**

```bash
git push -u origin feature/social-posting-agent
gh pr create \
  --title "feat: Social Posting Agent — post campaign content to X/Twitter, Instagram, Threads" \
  --body "## Summary

Adds a social posting stage to the PR campaign pipeline, triggered by a \`/post-social\` GitHub issue comment.

## How it works

1. \`pr_proposal\` posts a \`<!-- social-copy-data ... -->\` comment on the issue
2. Watcher detects \`/post-social\` on completed campaign issues → applies \`ai-social-post\` label
3. Next watcher cycle picks up the label → runs \`pr-social-post\` pipeline
4. \`PRSocialPostAgent\` reads creative data, generates platform copy via LLM, posts via MCP

## Platforms

- **X/Twitter** via \`@modelcontextprotocol/server-twitter\`
- **Instagram** via \`mcp-instagram\`
- **Threads** via \`mcp-threads\`

Each platform is independently enabled/disabled via \`mcp_servers:\` in \`repos.yaml\`.

## Files changed

- \`agents/pr_social_post.py\` — new agent
- \`roles/pr_social_post.md\` — system prompt
- \`pipelines/pr-social-post.yaml\` — single-stage pipeline
- \`tests/test_social_posting.py\` — unit tests
- \`orchestrator.py\` — stage method, registry builder, proposal stage update
- \`watcher.py\` — /post-social command detection

Closes Social Posting Agent spec: \`docs/superpowers/specs/2026-05-28-social-posting-agent-design.md\`" \
  --base master \
  --head feature/social-posting-agent
```

---

## Self-review

### Spec coverage

| Spec requirement | Covered by |
|---|---|
| /post-social trigger via issue comment | Task 8 (`_check_social_post_commands`) |
| ai-social-post label → pipeline dispatch | Task 8c + `repos.yaml` config in Task 10 |
| Per-platform enable/disable | `_mcp_servers` filtering in Task 6b + Task 10 |
| X/Twitter via MCP | `_post_platform` in Task 4 |
| Instagram via MCP (create_media_post + publish_media) | `_post_platform` in Task 4 |
| Threads via MCP | `_post_platform` in Task 4 |
| LLM content refinement per platform with char limits | `_generate_platform_copy` in Task 4 |
| Fallback to social_copy_example on LLM failure | `_generate_platform_copy` fallback in Task 4 |
| Post summary comment back to issue | `_build_summary_comment` in Task 4 |
| Creative data persistence between pipeline runs | `_stage_pr_proposal` social comment in Task 7 |
| Idempotency (don't post twice) | `_SKIP_LABELS` check in Task 8 |
| Role prompt | Task 2 |
| Tests | Task 3 |
| repos.yaml example config | Task 10 |

### Notes for implementation

- MCP server package names (`mcp-instagram`, `mcp-threads`) are community packages. Verify actual npm package names and MCP tool names (`create_media_post`, `publish_media`, `create_thread`) before assuming they match — check the packages' README on npm. The `_post_platform` code may need tool name adjustments.
- The `_NOISE_PREFIXES` check in `_collect_issue_prior_context` uses `body.startswith(p)`. The social copy comment starts with `## 📣 Campaign Social Copy Ready` which does NOT match any noise prefix — it will be included in prior context correctly.
- `extract_social_copy_data` uses a DOTALL regex on `<!-- social-copy-data ... -->`. The comment body posted by `_stage_pr_proposal` uses literal `\n` for the block separator — ensure the comment is rendered with real newlines (not `\n` literals) by the GitHub Issues API.
