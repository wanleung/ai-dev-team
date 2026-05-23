# tests/test_rss_watcher.py
"""Tests for rss_watcher.py."""
from __future__ import annotations
import sqlite3
import tempfile
from datetime import datetime, timezone, timedelta
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


def test_fetch_open_issues_returns_list():
    """_fetch_open_issues should return a list of issue dicts on success."""
    import rss_watcher
    issues = [
        {"number": 1, "title": "Test Issue", "body": "body", "created_at": "2024-01-01T00:00:00Z", "html_url": "https://github.com/owner/repo/issues/1"},
    ]
    with patch("rss_watcher.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = issues
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp
        
        result = rss_watcher._fetch_open_issues("owner/repo", "news-article", token="test-token")
        assert result == issues


def test_fetch_open_issues_returns_empty_on_error():
    """_fetch_open_issues should return [] gracefully on HTTP error."""
    import rss_watcher
    with patch("rss_watcher.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("HTTP 403 Forbidden")
        mock_get.return_value = mock_resp
        
        result = rss_watcher._fetch_open_issues("owner/repo", "news-article", token="test-token")
        assert result == []


def test_post_source_comment_calls_api():
    """_post_source_comment should POST a comment to the correct endpoint."""
    import rss_watcher
    with patch("rss_watcher.requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"id": 1}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp
        
        rss_watcher._post_source_comment("owner/repo", 42, "TechCrunch", "https://tc.com/story", token="test-token")
        
        assert mock_post.called
        call_args = mock_post.call_args
        assert "comments" in call_args[0][0]
        assert call_args[1]["json"]["body"] is not None
        assert "TechCrunch" in call_args[1]["json"]["body"]
        assert "https://tc.com/story" in call_args[1]["json"]["body"]


def test_process_feeds_dedup_add_source(tmp_path):
    """When dedup is enabled and a matching open issue exists (recent), ADD_SOURCE path fires."""
    import rss_watcher
    from rss_watcher import process_feeds
    cfg = {
        "press_repo": "owner/repo",
        "label": "news-article",
        "feeds": [{"url": "http://feed.test/rss", "source": "TechBlog"}],
        "dedup": {"enabled": True, "method": "keyword", "keyword_min_overlap": 2, "add_source_max_age_hours": 48},
    }
    open_issues = [
        {
            "number": 10,
            "title": "Article: OpenAI launches GPT-5",
            "body": "",
            "created_at": (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat(),
            "html_url": "https://github.com/owner/repo/issues/10",
        }
    ]
    feed_xml = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>OpenAI releases GPT-5 model</title>
    <link>http://techblog.test/gpt5</link>
    <summary>New model release.</summary>
  </item>
</channel></rss>"""

    with patch("rss_watcher.requests.get") as mock_get, \
         patch("rss_watcher._fetch_open_issues", return_value=open_issues), \
         patch("rss_watcher._post_source_comment") as mock_comment, \
         patch("rss_watcher._create_github_issue") as mock_create:
        feed_resp = MagicMock()
        feed_resp.content = feed_xml.encode()
        feed_resp.raise_for_status = MagicMock()
        mock_get.return_value = feed_resp

        count = process_feeds(cfg, db_path=tmp_path / "test.db", token="tok")

    assert count == 1
    mock_comment.assert_called_once()
    mock_create.assert_not_called()


def test_process_feeds_dedup_create_followup(tmp_path):
    """When dedup is enabled and matching issue is old, CREATE_FOLLOWUP path fires."""
    import rss_watcher
    from rss_watcher import process_feeds
    cfg = {
        "press_repo": "owner/repo",
        "label": "news-article",
        "feeds": [{"url": "http://feed.test/rss", "source": "TechBlog"}],
        "dedup": {"enabled": True, "method": "keyword", "keyword_min_overlap": 2, "add_source_max_age_hours": 48, "followup_mode": "time", "min_age_hours": 24},
    }
    old_issues = [
        {
            "number": 5,
            "title": "Article: OpenAI launches GPT-5",
            "body": "",
            "created_at": (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat(),
            "html_url": "https://github.com/owner/repo/issues/5",
        }
    ]
    feed_xml = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>OpenAI releases GPT-5 model</title>
    <link>http://techblog.test/gpt5-update</link>
    <summary>Follow-up coverage.</summary>
  </item>
</channel></rss>"""

    with patch("rss_watcher.requests.get") as mock_get, \
         patch("rss_watcher._fetch_open_issues", return_value=old_issues), \
         patch("rss_watcher._post_source_comment") as mock_comment, \
         patch("rss_watcher._create_github_issue") as mock_create:
        feed_resp = MagicMock()
        feed_resp.content = feed_xml.encode()
        feed_resp.raise_for_status = MagicMock()
        mock_get.return_value = feed_resp

        count = process_feeds(cfg, db_path=tmp_path / "test.db", token="tok")

    assert count == 1
    mock_comment.assert_not_called()
    call_kwargs = mock_create.call_args[1]
    assert "follow-up" in call_kwargs.get("extra_labels", [])
    assert "#5" in call_kwargs["body"]


def test_process_feeds_dedup_disabled_creates_new(tmp_path):
    """When dedup is disabled, process_feeds behaves as before (CREATE_NEW always)."""
    import rss_watcher
    from rss_watcher import process_feeds
    cfg = {
        "press_repo": "owner/repo",
        "label": "news-article",
        "feeds": [{"url": "http://feed.test/rss", "source": "TechBlog"}],
        # no dedup key
    }
    feed_xml = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>Some new article</title>
    <link>http://techblog.test/article1</link>
    <summary>Content here.</summary>
  </item>
</channel></rss>"""

    with patch("rss_watcher.requests.get") as mock_get, \
         patch("rss_watcher._create_github_issue") as mock_create:
        feed_resp = MagicMock()
        feed_resp.content = feed_xml.encode()
        feed_resp.raise_for_status = MagicMock()
        mock_get.return_value = feed_resp

        count = process_feeds(cfg, db_path=tmp_path / "test.db", token="tok")

    assert count == 1
    mock_create.assert_called_once()
    call_kwargs = mock_create.call_args[1]
    assert call_kwargs["title"] == "Article: Some new article"


def test_process_feeds_multi_target(tmp_path):
    """Multi-target config routes feeds to correct repos independently."""
    import rss_watcher
    from rss_watcher import process_feeds
    cfg = {
        "targets": [
            {
                "press_repo": "owner/repo-a",
                "label": "topic-a",
                "feeds": [{"url": "http://feed.test/a", "source": "FeedA"}],
            },
            {
                "press_repo": "owner/repo-b",
                "label": "topic-b",
                "feeds": [{"url": "http://feed.test/b", "source": "FeedB"}],
            },
        ]
    }
    feed_xml = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>Test Article</title>
    <link>http://example.test/article-{slug}</link>
    <summary>Content.</summary>
  </item>
</channel></rss>"""

    with patch("rss_watcher.requests.get") as mock_get, \
         patch("rss_watcher._create_github_issue") as mock_create:
        def feed_side_effect(url, **kwargs):
            slug = "a" if "feed.test/a" in url else "b"
            resp = MagicMock()
            resp.content = feed_xml.replace("{slug}", slug).encode()
            resp.raise_for_status = MagicMock()
            return resp
        mock_get.side_effect = feed_side_effect

        count = process_feeds(cfg, db_path=tmp_path / "test.db", token="tok")

    assert count == 2
    repos_called = [call[1]["repo"] for call in mock_create.call_args_list]
    assert "owner/repo-a" in repos_called
    assert "owner/repo-b" in repos_called
