"""Tests for rag-mcp/db.py — mocked psycopg2, no live DB required."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "rag-mcp"))

import json
from unittest.mock import MagicMock, patch
import pytest


def make_mock_conn(rows=None):
    """Return a mock psycopg2 connection whose cursor returns rows."""
    rows = rows or []
    cursor = MagicMock()
    cursor.fetchall.return_value = rows
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = lambda s: cursor
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn, cursor


def test_search_chunks_returns_search_results():
    """search_chunks() maps pgvector rows to SearchResult objects."""
    from db import search_chunks
    from models import SearchResult

    row = ("hello world", "src/main.py", 0, 0.92, json.dumps({"lang": "python"}))
    conn, cursor = make_mock_conn(rows=[row])
    embedding = [0.0] * 768

    with patch("db._get_conn", return_value=conn):
        results = search_chunks("codebase", embedding, top_k=3)

    assert len(results) == 1
    r = results[0]
    assert isinstance(r, SearchResult)
    assert r.content == "hello world"
    assert r.source_id == "src/main.py"
    assert r.chunk_index == 0
    assert abs(r.score - 0.92) < 0.001
    assert r.metadata == {"lang": "python"}


def test_search_chunks_filters_by_source_type():
    """search_chunks() passes source_type as a WHERE filter."""
    from db import search_chunks

    conn, cursor = make_mock_conn(rows=[])
    embedding = [0.0] * 768

    with patch("db._get_conn", return_value=conn):
        search_chunks("memory", embedding, top_k=5)

    sql_called = cursor.execute.call_args[0][0]
    assert "source_type" in sql_called


def test_upsert_chunk_calls_execute_and_commit():
    """upsert_chunk() inserts or updates a chunk row."""
    from db import upsert_chunk

    conn, cursor = make_mock_conn()

    with patch("db._get_conn", return_value=conn):
        upsert_chunk(
            source_type="codebase",
            source_id="src/foo.py",
            chunk_index=0,
            content="def foo(): pass",
            embedding=[0.1] * 768,
            metadata={"lang": "python"},
        )

    assert cursor.execute.called
    assert conn.commit.called
