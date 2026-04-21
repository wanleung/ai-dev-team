"""Tests for rag-mcp/indexer.py — chunking logic and upsert behaviour."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "rag-mcp"))

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
import requests


# ── Chunking ──────────────────────────────────────────────────────────────────

def test_chunk_code_produces_correct_size_and_overlap():
    """Code chunks are 40 lines with 10-line overlap."""
    from indexer import chunk_code

    lines = [f"line {i}" for i in range(100)]
    text = "\n".join(lines)
    chunks = chunk_code(text, chunk_size=40, overlap=10)

    # First chunk: lines 0-39
    assert chunks[0].startswith("line 0")
    # Second chunk starts at line 30 (40-10 overlap)
    assert chunks[1].startswith("line 30")
    # All chunks have at most 40 lines
    for c in chunks:
        assert len(c.splitlines()) <= 40


def test_chunk_text_produces_correct_token_count():
    """Text chunks are ~500 tokens with 50-token overlap (approximated by words)."""
    from indexer import chunk_text

    # ~1200 words → should produce multiple chunks
    words = ["word"] * 1200
    text = " ".join(words)
    chunks = chunk_text(text, chunk_size=500, overlap=50)

    assert len(chunks) >= 2
    # Each chunk is at most chunk_size words
    for c in chunks:
        assert len(c.split()) <= 500


def test_chunk_code_single_chunk_when_file_is_small():
    """Files shorter than chunk_size produce exactly one chunk."""
    from indexer import chunk_code

    text = "\n".join(f"line {i}" for i in range(10))
    chunks = chunk_code(text)
    assert len(chunks) == 1


def test_chunk_code_raises_on_invalid_overlap():
    """chunk_code raises ValueError when overlap >= chunk_size."""
    from indexer import chunk_code

    with pytest.raises(ValueError, match="overlap"):
        chunk_code("line1\nline2\n", chunk_size=5, overlap=5)
    with pytest.raises(ValueError, match="overlap"):
        chunk_code("line1\nline2\n", chunk_size=5, overlap=10)


def test_chunk_text_raises_on_invalid_overlap():
    """chunk_text raises ValueError when overlap >= chunk_size."""
    from indexer import chunk_text

    with pytest.raises(ValueError, match="overlap"):
        chunk_text("word " * 100, chunk_size=50, overlap=50)
    with pytest.raises(ValueError, match="overlap"):
        chunk_text("word " * 100, chunk_size=50, overlap=100)


# ── Indexing ──────────────────────────────────────────────────────────────────

def test_index_codebase_upserts_chunks_for_each_file():
    """index_codebase() calls upsert_chunk for each chunk of each file."""
    from indexer import index_codebase

    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "a.py").write_text("\n".join(f"line {i}" for i in range(5)))
        (Path(tmpdir) / "b.py").write_text("\n".join(f"line {i}" for i in range(5)))

        mock_embedder = MagicMock()
        mock_embedder.embed.return_value = [0.1] * 768

        with patch("indexer.upsert_chunk") as mock_upsert:
            index_codebase(tmpdir, mock_embedder, extensions=["py"])

    # 2 files × 1 chunk each = 2 upsert calls
    assert mock_upsert.call_count == 2
    calls_args = [c[1] for c in mock_upsert.call_args_list]
    source_ids = {a["source_id"] for a in calls_args}
    assert any("a.py" in sid for sid in source_ids)
    assert any("b.py" in sid for sid in source_ids)


def test_index_codebase_is_idempotent():
    """Calling index_codebase twice on the same file calls upsert (not insert) — upsert handles idempotency."""
    from indexer import index_codebase

    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "c.py").write_text("x = 1\n")

        mock_embedder = MagicMock()
        mock_embedder.embed.return_value = [0.0] * 768

        with patch("indexer.upsert_chunk") as mock_upsert:
            index_codebase(tmpdir, mock_embedder, extensions=["py"])
            index_codebase(tmpdir, mock_embedder, extensions=["py"])

    # Both runs call upsert — idempotency is enforced by ON CONFLICT in db.py
    assert mock_upsert.call_count == 2


def test_index_codebase_skips_unreadable_files():
    """index_codebase() skips files that fail to read (logs warning, continues)."""
    from indexer import index_codebase

    with tempfile.TemporaryDirectory() as tmpdir:
        good_file = Path(tmpdir) / "good.py"
        good_file.write_text("x = 1\n")

        mock_embedder = MagicMock()
        mock_embedder.embed.return_value = [0.1] * 768

        with patch("indexer.upsert_chunk") as mock_upsert, \
             patch.object(Path, "read_text", side_effect=OSError("Permission denied")):
            # Should not raise — just log and skip
            index_codebase(tmpdir, mock_embedder, extensions=["py"])

    # No upserts because read_text failed for all files
    assert mock_upsert.call_count == 0


def test_index_codebase_skips_embedder_errors():
    """index_codebase() skips chunks that fail to embed (logs warning, continues)."""
    from indexer import index_codebase
    from embedder import EmbedderError

    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "fail.py").write_text("x = 1\n")

        mock_embedder = MagicMock()
        mock_embedder.embed.side_effect = EmbedderError("backend down")

        with patch("indexer.upsert_chunk") as mock_upsert:
            # Should not raise — just log and skip
            index_codebase(tmpdir, mock_embedder, extensions=["py"])

    # No upserts because embedding failed
    assert mock_upsert.call_count == 0


def test_index_codebase_calls_delete_stale_chunks_on_clean():
    """index_codebase() with clean=True calls delete_stale_chunks after indexing."""
    from indexer import index_codebase

    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "a.py").write_text("x = 1\n")

        mock_embedder = MagicMock()
        mock_embedder.embed.return_value = [0.1] * 768

        with patch("indexer.upsert_chunk"), \
             patch("indexer.delete_stale_chunks") as mock_delete:
            index_codebase(tmpdir, mock_embedder, extensions=["py"], clean=True)

    mock_delete.assert_called_once()
    call_args = mock_delete.call_args
    assert call_args[0][0] == "codebase"  # source_type
    assert any("a.py" in sid for sid in call_args[0][1])  # live_ids contains the file


def test_index_codebase_handles_delete_stale_chunks_error():
    """index_codebase() with clean=True logs error but succeeds if delete_stale_chunks fails."""
    from indexer import index_codebase

    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "a.py").write_text("x = 1\n")

        mock_embedder = MagicMock()
        mock_embedder.embed.return_value = [0.1] * 768

        with patch("indexer.upsert_chunk") as mock_upsert, \
             patch("indexer.delete_stale_chunks", side_effect=Exception("DB error")):
            # Should not raise — just log error
            index_codebase(tmpdir, mock_embedder, extensions=["py"], clean=True)

    # Indexing succeeded even though cleanup failed
    assert mock_upsert.call_count == 1


# ── URL indexing ──────────────────────────────────────────────────────────────

def _make_html_response(text: str, links: list[str] = None, status_code: int = 200) -> MagicMock:
    """Build a mock requests.Response for HTML pages."""
    html_links = "".join(f'<a href="{href}">link</a>' for href in (links or []))
    html = f"""
    <html><body>
      <nav>Navigation</nav>
      <p>{text}</p>
      {html_links}
      <footer>Footer</footer>
    </body></html>
    """
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = {"Content-Type": "text/html; charset=utf-8"}
    resp.text = html
    return resp


def test_index_url_single_page(monkeypatch):
    """index_url crawls seed page, follows same-domain links, ignores external links."""
    from indexer import index_url

    seed_url = "https://docs.example.com/start"
    same_domain_link = "https://docs.example.com/page2"
    external_link = "https://other.com/page"

    visible_text = "A " * 60  # > 100 chars

    seed_resp = _make_html_response(visible_text, links=[same_domain_link, external_link])
    child_resp = _make_html_response(visible_text, links=[])

    def fake_get(url, timeout=10):
        if url == seed_url:
            return seed_resp
        if url == same_domain_link:
            return child_resp
        raise AssertionError(f"Unexpected GET: {url}")

    mock_session = MagicMock()
    mock_session.get.side_effect = fake_get
    mock_session.headers = {}

    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [0.1] * 768

    with patch("indexer.requests.Session", return_value=mock_session), \
         patch("indexer.upsert_chunk") as mock_upsert, \
         patch("indexer.delete_stale_chunks"):
        index_url(seed_url, mock_embedder, max_depth=3)

    # Both seed and same-domain child should be upserted
    upserted_ids = {c[1]["source_id"] for c in mock_upsert.call_args_list}
    assert seed_url in upserted_ids
    assert same_domain_link in upserted_ids
    # External link should NOT be upserted
    assert external_link not in upserted_ids

    # External link should never be fetched
    fetched_urls = [call.args[0] for call in mock_session.get.call_args_list]
    assert external_link not in fetched_urls


def test_index_url_depth_limit(monkeypatch):
    """index_url with max_depth=1 crawls seed + depth-1 children, not grandchildren."""
    from indexer import index_url

    seed_url = "https://docs.example.com/"
    child_url = "https://docs.example.com/child"
    grandchild_url = "https://docs.example.com/grandchild"

    visible_text = "B " * 60

    seed_resp = _make_html_response(visible_text, links=[child_url])
    child_resp = _make_html_response(visible_text, links=[grandchild_url])
    grandchild_resp = _make_html_response(visible_text, links=[])

    def fake_get(url, timeout=10):
        mapping = {
            "https://docs.example.com": seed_resp,
            seed_url.rstrip("/"): seed_resp,
            seed_url: seed_resp,
            child_url: child_resp,
            grandchild_url: grandchild_resp,
        }
        return mapping.get(url, grandchild_resp)

    mock_session = MagicMock()
    mock_session.get.side_effect = fake_get
    mock_session.headers = {}

    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [0.1] * 768

    with patch("indexer.requests.Session", return_value=mock_session), \
         patch("indexer.upsert_chunk") as mock_upsert, \
         patch("indexer.delete_stale_chunks"):
        index_url(seed_url, mock_embedder, max_depth=1)

    fetched_urls = [call.args[0] for call in mock_session.get.call_args_list]
    # Grandchild must NOT be fetched
    assert grandchild_url not in fetched_urls
    # Seed and child should be fetched
    assert child_url in fetched_urls


def test_index_url_skips_non_html(monkeypatch):
    """index_url does not fetch .pdf or .zip links from the seed page."""
    from indexer import index_url

    seed_url = "https://docs.example.com/start"
    pdf_link = "https://docs.example.com/doc.pdf"
    zip_link = "https://docs.example.com/archive.zip"

    visible_text = "C " * 60

    seed_resp = _make_html_response(visible_text, links=[pdf_link, zip_link])

    mock_session = MagicMock()
    mock_session.get.return_value = seed_resp
    mock_session.headers = {}

    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [0.1] * 768

    with patch("indexer.requests.Session", return_value=mock_session), \
         patch("indexer.upsert_chunk"), \
         patch("indexer.delete_stale_chunks"):
        index_url(seed_url, mock_embedder, max_depth=3)

    fetched_urls = [call.args[0] for call in mock_session.get.call_args_list]
    assert pdf_link not in fetched_urls
    assert zip_link not in fetched_urls


def test_index_url_request_error(monkeypatch):
    """index_url logs a warning and does not crash when requests.get raises ConnectionError."""
    from indexer import index_url
    import logging

    mock_session = MagicMock()
    mock_session.get.side_effect = requests.ConnectionError("refused")
    mock_session.headers = {}

    mock_embedder = MagicMock()

    with patch("indexer.requests.Session", return_value=mock_session), \
         patch("indexer.upsert_chunk") as mock_upsert, \
         patch("indexer.delete_stale_chunks"):
        # Must not raise
        index_url("https://docs.example.com/", mock_embedder, max_depth=0)

    mock_upsert.assert_not_called()


def test_index_url_short_text_skipped(monkeypatch):
    """index_url does not call upsert_chunk when page text is < 100 chars."""
    from indexer import index_url

    short_html = "<html><body><p>Too short.</p></body></html>"
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {"Content-Type": "text/html"}
    resp.text = short_html

    mock_session = MagicMock()
    mock_session.get.return_value = resp
    mock_session.headers = {}

    mock_embedder = MagicMock()

    with patch("indexer.requests.Session", return_value=mock_session), \
         patch("indexer.upsert_chunk") as mock_upsert, \
         patch("indexer.delete_stale_chunks"):
        index_url("https://docs.example.com/", mock_embedder, max_depth=0)

    mock_upsert.assert_not_called()


def test_normalise_url():
    """_normalise_url strips trailing slash, drops fragment, preserves scheme and host."""
    from indexer import _normalise_url

    # Trailing slash stripped (non-root path)
    assert _normalise_url("https://example.com/docs/") == "https://example.com/docs"

    # Root slash preserved
    assert _normalise_url("https://example.com/") == "https://example.com/"

    # Fragment dropped
    assert _normalise_url("https://example.com/page#section") == "https://example.com/page"

    # Both trailing slash and fragment
    assert _normalise_url("https://example.com/docs/#anchor") == "https://example.com/docs"

    # Scheme and host preserved
    result = _normalise_url("https://docs.example.com/path/to/page")
    assert result.startswith("https://docs.example.com")
    assert result == "https://docs.example.com/path/to/page"
