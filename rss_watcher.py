#!/usr/bin/env python3
"""
rss_watcher.py — Poll RSS feeds and create GitHub Issues for new articles.

Usage (cron, every 15 min):
    */15 * * * * cd /path/to/ai-software-house && python rss_watcher.py

Config in config.local.yaml (flat mode - backward compatible):
    rss_watcher:
      press_repo: wanleung/ai-it-press
      label: news-article
      max_age_hours: 48
      feeds:
        - url: https://feeds.feedburner.com/oreilly/radar
          source: O'Reilly Radar
        - url: https://www.linux.com/feed/
          source: Linux.com
      dedup:
        enabled: true
        method: keyword

Or multi-target mode (multiple repos with independent dedup settings):
    rss_watcher:
      targets:
        - press_repo: owner/security-press
          label: security
          max_age_hours: 48
          feeds:
            - url: https://feeds.example.com/security
              source: Security Blog
          dedup:
            enabled: true
            method: keyword
        - press_repo: owner/software-press
          label: software
          feeds:
            - url: https://feeds.example.com/software
              source: Software Blog
          dedup:
            enabled: true
            method: fuzzy
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

from topic_dedup import TopicDeduplicator
from agents.base_agent import BaseAgent

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
            (url, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()


def _fetch_open_issues(
    repo: str,
    label: str,
    token: str | None = None,
) -> list[dict]:
    """Fetch open GitHub issues for *repo* filtered by *label*.

    Returns a list of normalized issue dicts with keys:
    ``number``, ``title``, ``body``, ``created_at``, ``html_url``.
    Pull requests are excluded. Returns an empty list on any error.

    Note: GitHub's API returns at most 100 items per page. This function
    fetches only the first page; issues beyond the first 100 open issues
    (sorted by creation date, newest first) will not be considered for dedup.
    """
    tok = token or os.environ.get("GITHUB_TOKEN", "")
    headers = {
        "Authorization": f"Bearer {tok}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    url = f"https://api.github.com/repos/{repo}/issues"
    params = {"state": "open", "labels": label, "per_page": 100, "sort": "created", "direction": "desc"}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        raw = resp.json()
        return [
            {
                "number": item["number"],
                "title": item.get("title", ""),
                "body": item.get("body", "") or "",
                "created_at": item.get("created_at", ""),
                "html_url": item.get("html_url", ""),
            }
            for item in raw
            if "pull_request" not in item
        ]
    except Exception as exc:  # noqa: BLE001
        _log.warning("Could not fetch open issues for %s: %s", repo, exc)
        return []


def _post_source_comment(
    repo: str,
    issue_number: int,
    source_name: str,
    url: str,
    summary: str = "",
    token: str | None = None,
) -> None:
    """Add a source-link comment to an existing GitHub issue."""
    tok = token or os.environ.get("GITHUB_TOKEN", "")
    headers = {
        "Authorization": f"Bearer {tok}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    comment_url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments"
    body = f"🔗 Additional source: {source_name}\n{url}"
    if summary:
        body += f"\n\n**Summary:** {summary}"
    try:
        resp = requests.post(comment_url, headers=headers, json={"body": body}, timeout=15)
        resp.raise_for_status()
        _log.info("Added source comment to issue #%d", issue_number)
    except Exception as exc:  # noqa: BLE001
        _log.warning("Could not post source comment to #%d: %s", issue_number, exc)


def _create_github_issue(
    repo: str,
    title: str,
    body: str,
    label: str,
    token: str | None = None,
    extra_labels: list[str] | None = None,
) -> dict:
    """Create a GitHub issue via REST API."""
    tok = token or os.environ.get("GITHUB_TOKEN", "")
    if not tok:
        raise ValueError("GITHUB_TOKEN not set and no token parameter provided")
    headers = {
        "Authorization": f"Bearer {tok}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    url = f"https://api.github.com/repos/{repo}/issues"
    resp = requests.post(
        url,
        headers=headers,
        json={"title": title, "body": body, "labels": [label, *(extra_labels or [])]},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    _log.info("Created issue #%d: %s", data["number"], title)
    return data


def _process_target(
    target_cfg: dict,
    conn: sqlite3.Connection,
    token: str | None = None,
) -> int:
    """Process one target's feeds and return count of issues created/updated."""
    press_repo = target_cfg.get("press_repo", "")
    label = target_cfg.get("label", "news-article")
    max_age_hours = int(target_cfg.get("max_age_hours", 48))
    feeds = target_cfg.get("feeds", [])
    dedup_cfg = target_cfg.get("dedup", {})

    if not press_repo:
        _log.warning("rss_watcher: press_repo not configured in target — skipping")
        return 0

    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=max_age_hours)
    created = 0

    # Build deduplicator if configured
    dedup: TopicDeduplicator | None = None
    if dedup_cfg.get("enabled", False):
        # Only create an LLM agent when the configured method actually needs one
        llm_agent: BaseAgent | None = None
        method = dedup_cfg.get("method", "all")
        followup_mode = dedup_cfg.get("followup_mode", "time")
        needs_llm = method in ("llm", "all") or followup_mode in ("content", "both")
        if needs_llm:
            model = dedup_cfg.get("llm_model") or dedup_cfg.get("followup_llm_model") or "dashscope/qwen3-plus"
            llm_agent = BaseAgent(
                model=model,
                dashscope_api_key=os.environ.get("DASHSCOPE_API_KEY", ""),
                github_token=token,
            )
        dedup = TopicDeduplicator(
            method=method,
            fuzzy_threshold=float(dedup_cfg.get("fuzzy_threshold", 0.85)),
            keyword_min_overlap=int(dedup_cfg.get("keyword_min_overlap", 2)),
            add_source_max_age_hours=int(dedup_cfg.get("add_source_max_age_hours", 48)),
            followup_mode=followup_mode,
            min_age_hours=int(dedup_cfg.get("min_age_hours", 168)),
            llm=llm_agent,
        )
        open_issues = _fetch_open_issues(press_repo, label, token)
    else:
        open_issues = []

    for feed_cfg in feeds:
        feed_url = feed_cfg.get("url", "")
        source_name = feed_cfg.get("source", feed_url)
        if not feed_url:
            continue

        _log.info("Fetching feed: %s", feed_url)
        try:
            resp = requests.get(
                feed_url,
                timeout=30,
                headers={"User-Agent": "ai-software-house-rss/1.0"},
            )
            resp.raise_for_status()
            parsed = feedparser.parse(resp.content)
        except requests.RequestException as exc:
            _log.error("Failed to fetch feed %s: %s", feed_url, exc)
            continue
        except Exception as exc:  # noqa: BLE001
            _log.error("Failed to parse feed %s: %s", feed_url, exc)
            continue

        for entry in parsed.entries:
            url = getattr(entry, "link", "")
            if not url:
                continue
            if conn.execute("SELECT 1 FROM seen_urls WHERE url = ?", (url,)).fetchone():
                continue

            published = getattr(entry, "published_parsed", None)
            if published:
                pub_dt = datetime(*published[:6], tzinfo=timezone.utc)
                if pub_dt < cutoff:
                    continue

            title = getattr(entry, "title", "No title")
            summary = getattr(entry, "summary", "")[:500]

            entry_dict = {"title": title, "summary": summary, "url": url}

            # Deduplication check
            if dedup is not None:
                result = dedup.check(entry_dict, open_issues)
                action = result.action
            else:
                action = "CREATE_NEW"
                result = None

            issue_body = (
                f"**Source:** {source_name}\n"
                f"**URL:** {url}\n"
                f"**Title:** {title}\n\n"
                f"**Summary:**\n{summary}\n"
            )

            try:
                if action == "ADD_SOURCE":
                    matched = result.matched_issue
                    _post_source_comment(
                        repo=press_repo,
                        issue_number=matched["number"],
                        source_name=source_name,
                        url=url,
                        summary=summary,
                        token=token,
                    )
                    _log.info("Added source to issue #%d for: %s", matched["number"], title)
                elif action == "CREATE_FOLLOWUP":
                    matched = result.matched_issue
                    orig_title = matched.get("title", "")
                    followup_body = (
                        f"⚡ Follow-up to #{matched['number']} (original: \"{orig_title}\")\n\n"
                        + issue_body
                    )
                    new_issue = _create_github_issue(
                        repo=press_repo,
                        title=f"Article: {title}",
                        body=followup_body,
                        label=label,
                        token=token,
                        extra_labels=["follow-up"],
                    )
                    open_issues.append(new_issue)
                else:  # CREATE_NEW
                    new_issue = _create_github_issue(
                        repo=press_repo,
                        title=f"Article: {title}",
                        body=issue_body,
                        label=label,
                        token=token,
                    )
                    open_issues.append(new_issue)

                conn.execute(
                    "INSERT OR IGNORE INTO seen_urls (url, seen_at) VALUES (?, ?)",
                    (url, datetime.now(timezone.utc).isoformat()),
                )
                conn.commit()
                created += 1
            except Exception as exc:  # noqa: BLE001
                _log.error("Failed to process entry %s: %s", url, exc)

    return created


def process_feeds(
    cfg: dict,
    db_path: Path = _DEFAULT_DB,
    token: str | None = None,
) -> int:
    """Process all RSS feeds and create GitHub issues for new entries.

    Supports both flat config (press_repo at top level) and multi-target
    config (list of targets, each with their own press_repo, label, feeds, dedup).

    Returns the total number of issues created or updated across all targets.
    """
    _ensure_db(db_path)
    total = 0

    # Multi-target mode: cfg has a 'targets' list
    if "targets" in cfg:
        with sqlite3.connect(db_path) as conn:
            for target_cfg in cfg.get("targets", []):
                total += _process_target(target_cfg, conn, token)
        return total

    # Backward-compat: flat config with press_repo at top level
    if not cfg.get("press_repo"):
        _log.warning("rss_watcher: press_repo not configured — skipping")
        return 0

    with sqlite3.connect(db_path) as conn:
        total = _process_target(cfg, conn, token)
    return total


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
