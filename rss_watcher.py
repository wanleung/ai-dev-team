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
            (url, datetime.now(timezone.utc).isoformat()),
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

    _ensure_db(db_path)
    with sqlite3.connect(db_path) as conn:
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

                # Age filter (feedparser returns struct_time; convert to datetime)
                # Old entries are skipped but NOT marked seen — allows retry if they
                # were previously unseen but issue creation failed transiently.
                published = getattr(entry, "published_parsed", None)
                if published:
                    pub_dt = datetime(*published[:6], tzinfo=timezone.utc)
                    if pub_dt < cutoff:
                        continue

                title = getattr(entry, "title", "No title")
                summary = getattr(entry, "summary", "")[:500]

                issue_title = f"Article: {title}"
                issue_body = (
                    f"**Source:** {source_name}\n"
                    f"**URL:** {url}\n"
                    f"**Title:** {title}\n\n"
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
                    conn.execute(
                        "INSERT OR IGNORE INTO seen_urls (url, seen_at) VALUES (?, ?)",
                        (url, datetime.now(timezone.utc).isoformat()),
                    )
                    conn.commit()
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
