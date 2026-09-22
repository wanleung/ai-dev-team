"""Tests for rag-mcp/indexer.py — chunking logic and upsert behaviour."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "rag-mcp"))

import sqlite3
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


# ── Standards indexing ────────────────────────────────────────────────────────

def test_index_standards_indexes_md_files():
    """index_standards() calls upsert_chunk with source_type='standards' for .md files."""
    from indexer import index_standards

    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "style.md").write_text("# Style Guide\n\nUse snake_case for functions.\n")

        mock_embedder = MagicMock()
        mock_embedder.embed.return_value = [0.1] * 768

        with patch("indexer.upsert_chunk") as mock_upsert:
            index_standards(tmpdir, mock_embedder)

    assert mock_upsert.call_count >= 1
    call_kwargs = mock_upsert.call_args_list[0][1]
    assert call_kwargs["source_type"] == "standards"
    assert "style.md" in call_kwargs["source_id"]


def test_index_standards_default_extensions():
    """index_standards() includes .adoc by default but excludes .py files."""
    from indexer import index_standards

    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "guide.adoc").write_text("= Architecture Guide\n\nFollow these patterns.\n")
        (Path(tmpdir) / "helper.py").write_text("def foo(): pass\n")

        mock_embedder = MagicMock()
        mock_embedder.embed.return_value = [0.1] * 768

        with patch("indexer.upsert_chunk") as mock_upsert:
            index_standards(tmpdir, mock_embedder)

    upserted_ids = {c[1]["source_id"] for c in mock_upsert.call_args_list}
    # .adoc should be indexed
    assert any("guide.adoc" in sid for sid in upserted_ids)
    # .py should NOT be indexed (not in default extensions)
    assert not any("helper.py" in sid for sid in upserted_ids)


# ── Memory indexing ───────────────────────────────────────────────────────────
# Regression coverage for the schema drift where index_memory() selected
# prd/design columns that memory_store.py's runs table no longer has.

def test_index_memory_reads_current_memory_store_schema(tmp_path):
    """index_memory() only reads columns MemoryStore.runs actually has.

    Note: MemoryStore() is force-redirected to tmp_path/memory.db by the
    autouse _isolate_memory_store fixture in conftest.py, regardless of
    what path is passed to it — so index_memory() must point at that same
    path, not at a caller-chosen temp dir.
    """
    from indexer import index_memory
    from memory_store import MemoryStore

    db_path = str(tmp_path / "memory.db")
    store = MemoryStore(db_path)
    store.save(repo="wanleung/ai-it-press", summary="Fixed RSS dedup false positives", mode="fix")
    store.close()

    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [0.1] * 768

    with patch("indexer.upsert_chunk") as mock_upsert:
        index_memory(db_path, mock_embedder)

    assert mock_upsert.call_count == 1
    call_kwargs = mock_upsert.call_args_list[0][1]
    assert call_kwargs["source_type"] == "memory"
    assert call_kwargs["source_id"] == "1"
    assert call_kwargs["metadata"]["repo"] == "wanleung/ai-it-press"


def test_index_memory_skips_rows_with_empty_summary(tmp_path):
    """A run with no summary yet is never chunked/embedded."""
    from indexer import index_memory
    from memory_store import MemoryStore

    db_path = str(tmp_path / "memory.db")
    store = MemoryStore(db_path)
    store.save(repo="wanleung/q-test", summary="", mode="feature")
    store.close()

    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [0.1] * 768

    with patch("indexer.upsert_chunk") as mock_upsert:
        index_memory(db_path, mock_embedder)

    assert mock_upsert.call_count == 0


def test_index_memory_marks_rows_indexed_and_is_incremental(tmp_path):
    """A second incremental pass skips rows already marked indexed=1."""
    from indexer import index_memory
    from memory_store import MemoryStore

    db_path = str(tmp_path / "memory.db")
    store = MemoryStore(db_path)
    store.save(repo="wanleung/ai-it-press", summary="Added ComfyUI image generation", mode="feature")
    store.close()

    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [0.1] * 768

    with patch("indexer.upsert_chunk") as mock_upsert:
        index_memory(db_path, mock_embedder)
        assert mock_upsert.call_count == 1

        mock_upsert.reset_mock()
        index_memory(db_path, mock_embedder)  # incremental=True by default
        assert mock_upsert.call_count == 0

    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT indexed FROM runs").fetchone()[0] == 1
    finally:
        conn.close()


def test_index_memory_full_reindexes_already_indexed_rows(tmp_path):
    """incremental=False (the --full CLI flag) re-embeds every row, indexed or not."""
    from indexer import index_memory
    from memory_store import MemoryStore

    db_path = str(tmp_path / "memory.db")
    store = MemoryStore(db_path)
    store.save(repo="wanleung/ai-it-press", summary="Added ComfyUI image generation", mode="feature")
    store.close()

    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [0.1] * 768

    with patch("indexer.upsert_chunk") as mock_upsert:
        index_memory(db_path, mock_embedder)
        mock_upsert.reset_mock()
        index_memory(db_path, mock_embedder, incremental=False)

    assert mock_upsert.call_count == 1


def test_index_memory_does_not_mark_indexed_on_embedder_failure(tmp_path):
    """A row whose embedding fails stays indexed=0 so it's retried next pass."""
    from indexer import index_memory
    from embedder import EmbedderError
    from memory_store import MemoryStore

    db_path = str(tmp_path / "memory.db")
    store = MemoryStore(db_path)
    store.save(repo="wanleung/ai-it-press", summary="Fixed RSS dedup false positives", mode="fix")
    store.close()

    mock_embedder = MagicMock()
    mock_embedder.embed.side_effect = EmbedderError("Ollama unreachable")

    with patch("indexer.upsert_chunk") as mock_upsert:
        index_memory(db_path, mock_embedder)

    assert mock_upsert.call_count == 0

    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT indexed FROM runs").fetchone()[0] == 0
    finally:
        conn.close()


def test_index_memory_migrates_db_missing_indexed_column():
    """A memory.db from before the 'indexed' column existed is migrated in place."""
    from indexer import index_memory

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "memory.db")
        # Build a pre-migration runs table by hand (no 'indexed' column).
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                repo TEXT NOT NULL,
                run_id TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                summary TEXT NOT NULL,
                tags TEXT DEFAULT '[]',
                mode TEXT DEFAULT 'feature',
                tier TEXT DEFAULT 'run',
                period_label TEXT DEFAULT '',
                consolidated INTEGER DEFAULT 0
            )
        """)
        conn.execute(
            "INSERT INTO runs (repo, created_at, summary) VALUES (?, ?, ?)",
            ("wanleung/ai-it-press", "2026-09-22T00:00:00Z", "Legacy run predating the indexed column"),
        )
        conn.commit()
        conn.close()

        mock_embedder = MagicMock()
        mock_embedder.embed.return_value = [0.1] * 768

        with patch("indexer.upsert_chunk") as mock_upsert:
            index_memory(db_path, mock_embedder)  # must not raise OperationalError

        assert mock_upsert.call_count == 1
