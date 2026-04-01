"""
memory_store.py — SQLite-backed long-term memory for the AI software house.

Stores per-repo run summaries so agents can recall what was built,
what problems occurred, and what was cleaned up in previous runs.

Usage:
    store = MemoryStore("./workspace/memory.db")
    store.save(repo="wanleung/gaswhatuk", summary=..., run_id=..., tags=[...])
    context = store.recall(repo="wanleung/gaswhatuk", limit=3)
"""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Optional


class MemoryStore:
    """Persistent per-repo memory using SQLite."""

    def __init__(self, db_path: str | Path = "./workspace/memory.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                repo        TEXT NOT NULL,
                run_id      TEXT,
                created_at  TEXT NOT NULL,
                summary     TEXT NOT NULL,
                tags        TEXT DEFAULT '[]',
                mode        TEXT DEFAULT 'feature'
            );
            CREATE INDEX IF NOT EXISTS idx_runs_repo ON runs(repo);
        """)
        self._conn.commit()

    def save(
        self,
        repo: str,
        summary: str,
        run_id: Optional[str] = None,
        tags: Optional[list[str]] = None,
        mode: str = "feature",
    ) -> int:
        """Persist a run summary. Returns the row ID."""
        cur = self._conn.execute(
            "INSERT INTO runs (repo, run_id, created_at, summary, tags, mode) VALUES (?,?,?,?,?,?)",
            (
                repo,
                run_id or "",
                datetime.utcnow().isoformat(),
                summary,
                json.dumps(tags or []),
                mode,
            ),
        )
        self._conn.commit()
        return cur.lastrowid

    def recall(self, repo: str, limit: int = 5, mode: Optional[str] = None) -> str:
        """Return the last N summaries for a repo as a formatted string for prompt injection."""
        query = "SELECT created_at, mode, summary FROM runs WHERE repo = ?"
        params: list = [repo]
        if mode:
            query += " AND mode = ?"
            params.append(mode)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(query, params).fetchall()
        if not rows:
            return ""

        parts = ["## 📚 Memory: previous runs for this repo\n"]
        for created_at, run_mode, summary in reversed(rows):
            date = created_at[:10]
            parts.append(f"### [{date}] ({run_mode} mode)\n{summary}\n")
        return "\n".join(parts)

    def recall_issues(self, repo: str, limit: int = 10) -> str:
        """Return known issues/failures from past runs to help agents avoid repeating them."""
        rows = self._conn.execute(
            "SELECT created_at, summary FROM runs WHERE repo = ? AND tags LIKE '%issue%' ORDER BY id DESC LIMIT ?",
            (repo, limit),
        ).fetchall()
        if not rows:
            return ""
        parts = ["## ⚠️ Known issues from previous runs\n"]
        for created_at, summary in rows:
            parts.append(f"- [{created_at[:10]}] {summary[:300]}")
        return "\n".join(parts)

    def list_repos(self) -> list[str]:
        """Return all repos that have saved memories."""
        rows = self._conn.execute(
            "SELECT DISTINCT repo FROM runs ORDER BY repo"
        ).fetchall()
        return [r[0] for r in rows]

    def close(self) -> None:
        self._conn.close()
