"""Indexer CLI — chunks source files and upserts embeddings into pgvector.

Usage:
    python indexer.py --source codebase --path /path/to/repo [--ext py,ts,go] [--clean]
    python indexer.py --source docs --path /path/to/docs [--ext md,txt,rst]
    python indexer.py --source memory --db /path/to/memory.db
    python indexer.py --source url --url https://docs.example.com [--depth 3] [--clean]

Environment variables required:
    DATABASE_URL  — Postgres connection string
    EMBED_BACKEND, OLLAMA_BASE_URL, etc. — see embedder.py
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import deque
from pathlib import Path
from urllib.parse import urlparse, urlunparse, urljoin

import requests
from bs4 import BeautifulSoup

from db import upsert_chunk, delete_stale_chunks
from embedder import Embedder, EmbedderError

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

_CHUNK_SIZE_CODE = int(os.environ.get("CHUNK_SIZE_CODE", "40"))
_CHUNK_OVERLAP_CODE = int(os.environ.get("CHUNK_OVERLAP_CODE", "10"))
_CHUNK_SIZE_TEXT = int(os.environ.get("CHUNK_SIZE_TEXT", "500"))
_CHUNK_OVERLAP_TEXT = int(os.environ.get("CHUNK_OVERLAP_TEXT", "50"))


def chunk_code(text: str, chunk_size: int = _CHUNK_SIZE_CODE, overlap: int = _CHUNK_OVERLAP_CODE) -> list[str]:
    """Split text into chunks of chunk_size lines with overlap lines of overlap."""
    if overlap >= chunk_size:
        raise ValueError(f"overlap ({overlap}) must be less than chunk_size ({chunk_size})")
    lines = text.splitlines()
    if len(lines) <= chunk_size:
        return [text]
    chunks = []
    step = chunk_size - overlap
    start = 0
    while start < len(lines):
        end = min(start + chunk_size, len(lines))
        chunks.append("\n".join(lines[start:end]))
        if end == len(lines):
            break
        start += step
    return chunks


def chunk_text(text: str, chunk_size: int = _CHUNK_SIZE_TEXT, overlap: int = _CHUNK_OVERLAP_TEXT) -> list[str]:
    """Split text into chunks of ~chunk_size words with ~overlap words of overlap.

    Uses words as a proxy for tokens (1 word ≈ 1.3 tokens on average).
    """
    if overlap >= chunk_size:
        raise ValueError(f"overlap ({overlap}) must be less than chunk_size ({chunk_size})")
    words = text.split()
    if len(words) <= chunk_size:
        return [text]
    chunks = []
    step = chunk_size - overlap
    start = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start += step
    return chunks


def index_codebase(
    path: str,
    embedder: Embedder,
    extensions: list[str] | None = None,
    clean: bool = False,
) -> None:
    """Index all source files under path into the 'codebase' source type."""
    exts = {f".{e.lstrip('.')}" for e in (extensions or ["py", "ts", "js", "go", "java"])}
    root = Path(path)
    live_ids: list[str] = []

    for fpath in sorted(root.rglob("*")):
        if fpath.suffix not in exts or not fpath.is_file():
            continue
        source_id = str(fpath)
        live_ids.append(source_id)
        try:
            text = fpath.read_text(errors="replace")
        except OSError as exc:
            log.warning("Skipping unreadable file %s: %s", fpath, exc)
            live_ids.pop()  # don't count unreadable file as live
            continue
        chunks = chunk_code(text)
        for i, chunk in enumerate(chunks):
            try:
                embedding = embedder.embed(chunk)
            except EmbedderError as exc:
                log.warning("Skipping %s chunk %d: %s", source_id, i, exc)
                continue
            upsert_chunk(
                source_type="codebase",
                source_id=source_id,
                chunk_index=i,
                content=chunk,
                embedding=embedding,
                metadata={"ext": fpath.suffix, "path": source_id},
            )
            log.info("Indexed codebase %s chunk %d", source_id, i)

    if clean:
        try:
            deleted = delete_stale_chunks("codebase", live_ids)
            log.info("Cleaned %d stale codebase chunks", deleted)
        except Exception as exc:
            log.error("Failed to delete stale chunks (indexing itself succeeded): %s", exc)


def index_docs(
    path: str,
    embedder: Embedder,
    extensions: list[str] | None = None,
    clean: bool = False,
) -> None:
    """Index documentation files under path into the 'docs' source type."""
    exts = {f".{e.lstrip('.')}" for e in (extensions or ["md", "txt", "rst"])}
    root = Path(path)
    live_ids: list[str] = []

    for fpath in sorted(root.rglob("*")):
        if fpath.suffix not in exts or not fpath.is_file():
            continue
        source_id = str(fpath)
        live_ids.append(source_id)
        try:
            text = fpath.read_text(errors="replace")
        except OSError as exc:
            log.warning("Skipping unreadable file %s: %s", fpath, exc)
            live_ids.pop()  # don't count unreadable file as live
            continue
        chunks = chunk_text(text)
        for i, chunk in enumerate(chunks):
            try:
                embedding = embedder.embed(chunk)
            except EmbedderError as exc:
                log.warning("Skipping %s chunk %d: %s", source_id, i, exc)
                continue
            upsert_chunk(
                source_type="docs",
                source_id=source_id,
                chunk_index=i,
                content=chunk,
                embedding=embedding,
                metadata={"ext": fpath.suffix, "path": source_id},
            )
            log.info("Indexed docs %s chunk %d", source_id, i)

    if clean:
        try:
            deleted = delete_stale_chunks("docs", live_ids)
            log.info("Cleaned %d stale docs chunks", deleted)
        except Exception as exc:
            log.error("Failed to delete stale chunks (indexing itself succeeded): %s", exc)


_NON_HTML_EXTS = {".pdf", ".zip", ".png", ".jpg", ".jpeg", ".gif", ".css", ".js"}


def _normalise_url(url: str) -> str:
    """Normalise a URL by dropping fragment and stripping trailing slash from path.

    Preserves scheme, netloc, query string. The path trailing slash is stripped
    unless the path is exactly '/'.
    """
    parsed = urlparse(url)
    path = parsed.path
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    normalised = urlunparse((parsed.scheme, parsed.netloc, path, parsed.params, parsed.query, ""))
    return normalised


def index_url(
    start_url: str,
    embedder: Embedder,
    max_depth: int = 3,
    clean: bool = False,
) -> None:
    """Crawl start_url (BFS up to max_depth) and index visible text into the 'docs' source type.

    Args:
        start_url: Seed URL to begin crawling from.
        embedder: Embedder instance used to generate chunk embeddings.
        max_depth: Maximum crawl depth (0 = seed page only).
        clean: When True, delete stale 'docs' embeddings for URLs not found during crawl.
    """
    start_url = _normalise_url(start_url)
    base_domain = urlparse(start_url).netloc

    visited: set[str] = set()
    live_ids: list[str] = []
    queue: deque[tuple[str, int]] = deque([(start_url, 0)])

    session = requests.Session()
    session.headers["User-Agent"] = "RAG-Indexer/1.0"

    while queue:
        url, depth = queue.popleft()

        if url in visited:
            continue
        visited.add(url)

        if depth > max_depth:
            continue

        parsed = urlparse(url)

        # Stay on the same domain
        if parsed.netloc != base_domain:
            continue

        # Skip non-HTML resource extensions
        path_lower = parsed.path.lower()
        if any(path_lower.endswith(ext) for ext in _NON_HTML_EXTS):
            continue

        try:
            response = session.get(url, timeout=10)
        except requests.RequestException as exc:
            log.warning("Request failed for %s: %s", url, exc)
            continue

        if response.status_code != 200:
            log.warning("Non-200 status %d for %s", response.status_code, url)
            continue

        content_type = response.headers.get("Content-Type", "")
        if "text/html" not in content_type:
            log.warning("Skipping non-HTML content type '%s' for %s", content_type, url)
            continue

        soup = BeautifulSoup(response.text, "lxml")

        # Remove noise tags before extracting text
        for tag in soup.find_all(["script", "style", "nav", "footer"]):
            tag.decompose()

        text = soup.get_text(separator=" ", strip=True)

        if len(text) < 100:
            log.warning("Skipping %s — extracted text too short (%d chars)", url, len(text))
        else:
            live_ids.append(url)
            chunks = chunk_text(text)
            for i, chunk in enumerate(chunks):
                try:
                    embedding = embedder.embed(chunk)
                except EmbedderError as exc:
                    log.warning("Skipping %s chunk %d: %s", url, i, exc)
                    continue
                upsert_chunk(
                    source_type="docs",
                    source_id=url,
                    chunk_index=i,
                    content=chunk,
                    embedding=embedding,
                    metadata={"url": url, "depth": depth},
                )
                log.info("Indexed url %s chunk %d", url, i)

        # Enqueue discovered links for next depth level
        if depth < max_depth:
            for anchor in soup.find_all("a", href=True):
                href = anchor["href"]
                child_url = _normalise_url(urljoin(url, href))
                if child_url not in visited:
                    queue.append((child_url, depth + 1))

    if clean:
        try:
            deleted = delete_stale_chunks("docs", live_ids)
            log.info("Cleaned %d stale docs chunks", deleted)
        except Exception as exc:
            log.error("Failed to delete stale chunks (indexing itself succeeded): %s", exc)


def index_memory(db_path: str, embedder: Embedder) -> None:
    """Index past pipeline runs from the MemoryStore SQLite database.

    Reads the 'runs' table and indexes PRD + design + summary for each run.
    """
    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "SELECT id, prd, design, summary, created_at FROM runs WHERE summary IS NOT NULL"
        )
        for row in cur.fetchall():
            run_id, prd, design, summary, created_at = row
            parts = [
                ("prd", prd or ""),
                ("design", design or ""),
                ("summary", summary or ""),
            ]
            chunk_index = 0
            for part_name, text in parts:
                if not text.strip():
                    continue
                for chunk in chunk_text(text):
                    try:
                        embedding = embedder.embed(chunk)
                    except EmbedderError as exc:
                        log.warning("Skipping memory run=%s part=%s: %s", run_id, part_name, exc)
                        chunk_index += 1  # advance so subsequent chunks keep correct positions
                        continue
                    upsert_chunk(
                        source_type="memory",
                        source_id=str(run_id),
                        chunk_index=chunk_index,
                        content=chunk,
                        embedding=embedding,
                        metadata={"part": part_name, "ts": created_at},
                    )
                    log.info("Indexed memory run=%s chunk %d", run_id, chunk_index)
                    chunk_index += 1
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG indexer — populate pgvector knowledge base")
    parser.add_argument("--source", choices=["codebase", "docs", "memory", "url"], required=True)
    parser.add_argument("--path", help="Root directory for codebase/docs sources")
    parser.add_argument("--db", help="Path to MemoryStore SQLite file (--source memory)")
    parser.add_argument("--ext", help="Comma-separated file extensions to index (e.g. py,ts,go)")
    parser.add_argument("--clean", action="store_true", help="Delete embeddings for removed files")
    parser.add_argument("--url", help="Seed URL to crawl (--source url)")
    parser.add_argument("--depth", type=int, default=3, help="Maximum crawl depth (default: 3)")
    args = parser.parse_args()

    embedder = Embedder()
    exts = args.ext.split(",") if args.ext else None

    if args.source == "codebase":
        if not args.path:
            parser.error("--path required for --source codebase")
        index_codebase(args.path, embedder, extensions=exts, clean=args.clean)
    elif args.source == "docs":
        if not args.path:
            parser.error("--path required for --source docs")
        index_docs(args.path, embedder, extensions=exts, clean=args.clean)
    elif args.source == "memory":
        if not args.db:
            parser.error("--db required for --source memory")
        index_memory(args.db, embedder)
    elif args.source == "url":
        if not args.url:
            parser.error("--url required for --source url")
        index_url(args.url, embedder, max_depth=args.depth, clean=args.clean)

    log.info("Indexing complete.")


if __name__ == "__main__":
    main()
