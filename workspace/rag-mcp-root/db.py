"""pgvector connection and search/upsert helpers."""
from __future__ import annotations

import json
import os
from typing import Any

import psycopg2
from pgvector.psycopg2 import register_vector

from models import SearchResult

_DATABASE_URL = os.environ.get("DATABASE_URL", "")


def _get_conn():
    """Return a new psycopg2 connection with pgvector registered."""
    if not _DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL environment variable is not set. "
            "Example: postgresql://user:pass@localhost:5432/ragdb"
        )
    conn = psycopg2.connect(_DATABASE_URL)
    register_vector(conn)
    return conn


def apply_migration(sql_path: str) -> None:
    """Run a SQL file against the database (idempotent — uses IF NOT EXISTS)."""
    with open(sql_path) as f:
        sql = f.read()
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
    finally:
        conn.rollback()  # no-op on success; rolls back aborted transaction on failure
        conn.close()


def search_chunks(
    source_type: str,
    query_embedding: list[float],
    top_k: int = 5,
) -> list[SearchResult]:
    """Return top-k chunks by cosine similarity filtered by source_type.

    Args:
        source_type: 'codebase' | 'memory' | 'docs'
        query_embedding: Embedding vector for the query string.
        top_k: Maximum number of results to return.

    Returns:
        List of SearchResult ordered by score descending.
    """
    sql = """
        SELECT content, source_id, chunk_index,
               1 - (embedding <=> %s::vector) AS score,
               metadata
        FROM rag_embeddings
        WHERE source_type = %s
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (query_embedding, source_type, query_embedding, top_k))
            rows = cur.fetchall()
    finally:
        conn.close()

    return [
        SearchResult(
            content=row[0],
            source_id=row[1],
            chunk_index=row[2],
            score=max(0.0, min(1.0, float(row[3]))),
            metadata=row[4] if isinstance(row[4], dict) else json.loads(row[4] or "{}"),
        )
        for row in rows
    ]


def upsert_chunk(
    source_type: str,
    source_id: str,
    chunk_index: int,
    content: str,
    embedding: list[float],
    metadata: dict[str, Any] | None = None,
) -> None:
    """Insert or update a single chunk row (idempotent by source_type+source_id+chunk_index)."""
    sql = """
        INSERT INTO rag_embeddings (source_type, source_id, chunk_index, content, embedding, metadata)
        VALUES (%s, %s, %s, %s, %s::vector, %s)
        ON CONFLICT (source_type, source_id, chunk_index)
        DO UPDATE SET
            content   = EXCLUDED.content,
            embedding = EXCLUDED.embedding,
            metadata  = EXCLUDED.metadata
    """
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    source_type,
                    source_id,
                    chunk_index,
                    content,
                    embedding,
                    json.dumps(metadata or {}),
                ),
            )
        conn.commit()
    finally:
        conn.rollback()  # no-op on success; rolls back aborted transaction on failure
        conn.close()


def delete_stale_chunks(source_type: str, live_source_ids: list[str]) -> int:
    """Delete chunks whose source_id is no longer in the live set.

    Used by indexer --clean flag to remove embeddings for deleted files.

    Returns:
        Number of rows deleted.
    """
    if not live_source_ids:
        return 0
    sql = """
        DELETE FROM rag_embeddings
        WHERE source_type = %s
          AND source_id NOT IN %s
    """
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (source_type, tuple(live_source_ids)))
            deleted = cur.rowcount
        conn.commit()
    finally:
        conn.rollback()  # no-op on success; rolls back aborted transaction on failure
        conn.close()
    return deleted
