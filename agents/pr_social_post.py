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
        # creative_output from PRCreativeAgent may be serialised as a list;
        # normalise to the first element (the primary concept dict).
        if isinstance(creative, list):
            creative = creative[0] if creative else {}
        if not creative or not isinstance(creative, dict):
            logger.error("social-copy-data payload is not a dict: %r", type(creative))
            context["pr_social_post"] = {"error": "social-copy-data payload has unexpected format."}
            return context

        logger.info("Generating social copy for platforms: %s", platforms)
        platform_copy = self._generate_platform_copy(creative, platforms)
        results = {}
        for platform, copy_data in platform_copy.items():
            if not copy_data.get("text") and not copy_data.get("caption"):
                results[platform] = {"posted": False, "url": None, "error": "LLM returned no content"}
                continue
            content = copy_data.get("text") or copy_data.get("caption") or ""
            try:
                post_result = self._post_platform(platform, content)
                url, error = post_result
            except Exception as exc:  # noqa: BLE001
                url, error = None, str(exc)
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
            if not parsed:
                raise ValueError("LLM output parsed to empty dict — no platform copy generated")
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM call failed (%s); using social_copy_example as fallback", exc)
            fallback = creative.get("social_copy_example", "")
            parsed = {p: {"text": fallback[:_PLATFORM_CHAR_LIMITS.get(p, 500)]} for p in platforms}
        return parsed

    def _build_prompt(self, creative: dict, platforms: list[str]) -> str:
        """Build the LLM prompt for generating platform-specific social copy."""
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
                raw = self._tool_registry.call(
                    "create_tweet", json.dumps({"text": content})
                )
                result = json.loads(raw) if raw else {}
                url = (result or {}).get("url") or (result or {}).get("tweet_url")
                return url, None

            elif platform == "instagram":
                raw = self._tool_registry.call(
                    "create_media_post",
                    json.dumps({"caption": content, "media_type": "IMAGE"}),
                )
                media_result = json.loads(raw) if raw else {}
                creation_id = (media_result or {}).get("id")
                if not creation_id:
                    return None, "create_media_post returned no id"
                raw2 = self._tool_registry.call(
                    "publish_media", json.dumps({"creation_id": creation_id})
                )
                publish_result = json.loads(raw2) if raw2 else {}
                url = (publish_result or {}).get("url")
                if not url and (publish_result or {}).get("id"):
                    url = f"https://www.instagram.com/p/{publish_result['id']}/"
                return url, None

            elif platform == "threads":
                raw = self._tool_registry.call(
                    "create_thread", json.dumps({"text": content})
                )
                result = json.loads(raw) if raw else {}
                url = (result or {}).get("url") or (result or {}).get("permalink")
                return url, None

            else:
                return None, f"Unknown platform: {platform}"

        except Exception as exc:  # noqa: BLE001
            logger.warning("MCP post failed for %s: %s", platform, exc)
            return None, str(exc)

    def _build_summary_comment(self, results: dict[str, dict]) -> str:
        """Build a GitHub issue comment summarising the social posting results."""
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
