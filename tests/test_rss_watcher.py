# tests/test_rss_watcher.py
"""Tests for rss_watcher.py."""
from __future__ import annotations
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest


def _make_entry(url: str, title: str = "Test Article", summary: str = "A summary.") -> MagicMock:
    e = MagicMock()
    e.link = url
    e.title = title
    e.summary = summary
    e.published_parsed = None  # No age filter in these tests
    return e


def _mock_feed_response() -> MagicMock:
    """Mock requests.Response for feed fetching."""
    mock_resp = MagicMock()
    mock_resp.content = b"<rss/>"
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


def test_new_entry_creates_github_issue():
    import rss_watcher
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "rss_seen.db"
        cfg = {
            "press_repo": "wanleung/ai-it-press",
            "label": "news-article",
            "max_age_hours": 48,
            "feeds": [{"url": "https://example.com/feed.rss", "source": "Example"}],
        }
        with patch("rss_watcher.requests.get", return_value=_mock_feed_response()), \
             patch("rss_watcher.feedparser") as mock_fp, \
             patch("rss_watcher._create_github_issue") as mock_create:
            mock_fp.parse.return_value = MagicMock(
                entries=[_make_entry("https://example.com/article-1")]
            )
            rss_watcher.process_feeds(cfg, db_path=db_path)
        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["repo"] == "wanleung/ai-it-press"
        assert "https://example.com/article-1" in call_kwargs["body"]


def test_duplicate_entry_skipped():
    import rss_watcher
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "rss_seen.db"
        cfg = {
            "press_repo": "wanleung/ai-it-press",
            "label": "news-article",
            "max_age_hours": 48,
            "feeds": [{"url": "https://example.com/feed.rss", "source": "Example"}],
        }
        with patch("rss_watcher.requests.get", return_value=_mock_feed_response()), \
             patch("rss_watcher.feedparser") as mock_fp, \
             patch("rss_watcher._create_github_issue") as mock_create:
            mock_fp.parse.return_value = MagicMock(
                entries=[_make_entry("https://example.com/article-1")]
            )
            rss_watcher.process_feeds(cfg, db_path=db_path)
            rss_watcher.process_feeds(cfg, db_path=db_path)
        # Second run: same URL should be skipped
        assert mock_create.call_count == 1


def test_github_issue_body_contains_url_and_source():
    import rss_watcher
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "rss_seen.db"
        cfg = {
            "press_repo": "wanleung/ai-it-press",
            "label": "news-article",
            "max_age_hours": 48,
            "feeds": [{"url": "https://feeds.linux.com/feed", "source": "Linux.com"}],
        }
        with patch("rss_watcher.requests.get", return_value=_mock_feed_response()), \
             patch("rss_watcher.feedparser") as mock_fp, \
             patch("rss_watcher._create_github_issue") as mock_create:
            mock_fp.parse.return_value = MagicMock(
                entries=[_make_entry("https://linux.com/story", title="Linux 6.9 Released", summary="Details here")]
            )
            rss_watcher.process_feeds(cfg, db_path=db_path)
        body = mock_create.call_args[1]["body"]
        assert "https://linux.com/story" in body
        assert "Linux.com" in body
        assert "Linux 6.9 Released" in body


def test_db_persists_seen_urls():
    import rss_watcher
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "rss_seen.db"
        rss_watcher._mark_seen(db_path, "https://example.com/article-1")
        assert rss_watcher._is_seen(db_path, "https://example.com/article-1")
        assert not rss_watcher._is_seen(db_path, "https://example.com/new-article")
