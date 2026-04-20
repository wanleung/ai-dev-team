"""Tests for rag-mcp/indexer.py — chunking logic and upsert behaviour."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "rag-mcp"))

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest


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
        assert len(c.split()) <= 560  # 500 + small tolerance


def test_chunk_code_single_chunk_when_file_is_small():
    """Files shorter than chunk_size produce exactly one chunk."""
    from indexer import chunk_code

    text = "\n".join(f"line {i}" for i in range(10))
    chunks = chunk_code(text)
    assert len(chunks) == 1


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
