"""
memory_store.py — Tiered SQLite memory for the AI software house.

Memory is organised in three tiers to keep context windows small and fast
even as the project grows over months:

  run      — individual pipeline run summaries (full detail, ~400 words each)
  monthly  — AI-consolidated rollup of all runs in a calendar month (~600 words)
  quarterly — AI-consolidated rollup of all monthlies in a quarter (~400 words)

recall() returns:
  • Latest quarterly snapshot   (big-picture history)
  • Latest monthly snapshot     (recent theme / issues)
  • Last N individual runs      (exact recent detail)

This keeps injected context to ~1 500 words regardless of how many runs exist.

Auto-consolidation is triggered when the number of unprocessed run-tier entries
exceeds MONTHLY_THRESHOLD (default 10).  Call consolidate() from the orchestrator
after saving each run summary.

Usage:
    store = MemoryStore("./workspace/memory.db")
    store.save(repo="owner/repo", summary="...", mode="feature")

    # Check and consolidate if needed (pass a callable that calls the LLM)
    if store.needs_consolidation(repo):
        store.consolidate_monthly(repo, llm_fn=my_summarise_fn)

    context = store.recall(repo)   # tiered, compact, ready to inject
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, date
from pathlib import Path
from typing import Callable, Optional


# How many run-tier entries before we roll them up into a monthly snapshot
MONTHLY_THRESHOLD = 10
# How many monthly snapshots before we roll them up into a quarterly
QUARTERLY_THRESHOLD = 3


class MemoryStore:
    """Tiered persistent per-repo memory using SQLite."""

    def __init__(self, db_path: str | Path = "./workspace/memory.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._init_schema()

    # ── Schema ────────────────────────────────────────────────────────────────

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                repo            TEXT NOT NULL,
                run_id          TEXT DEFAULT '',
                created_at      TEXT NOT NULL,
                summary         TEXT NOT NULL,
                tags            TEXT DEFAULT '[]',
                mode            TEXT DEFAULT 'feature',
                tier            TEXT DEFAULT 'run',
                period_label    TEXT DEFAULT '',
                consolidated    INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_runs_repo  ON runs(repo);
            CREATE INDEX IF NOT EXISTS idx_runs_tier  ON runs(repo, tier);
            CREATE INDEX IF NOT EXISTS idx_runs_cons  ON runs(repo, tier, consolidated);
        """)
        # Migrate existing DB that may lack the new columns
        existing = {row[1] for row in self._conn.execute("PRAGMA table_info(runs)")}
        for col, dflt in [("tier", "'run'"), ("period_label", "''"), ("consolidated", "0")]:
            if col not in existing:
                self._conn.execute(f"ALTER TABLE runs ADD COLUMN {col} TEXT DEFAULT {dflt}")
        self._conn.commit()

    # ── Write ─────────────────────────────────────────────────────────────────

    def save(
        self,
        repo: str,
        summary: str,
        run_id: Optional[str] = None,
        tags: Optional[list[str]] = None,
        mode: str = "feature",
        tier: str = "run",
        period_label: str = "",
    ) -> int:
        """Persist a summary entry. Returns the row ID."""
        cur = self._conn.execute(
            """INSERT INTO runs
               (repo, run_id, created_at, summary, tags, mode, tier, period_label)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                repo,
                run_id or "",
                datetime.utcnow().isoformat(),
                summary,
                json.dumps(tags or []),
                mode,
                tier,
                period_label or "",
            ),
        )
        self._conn.commit()
        return cur.lastrowid

    # ── Consolidation ─────────────────────────────────────────────────────────

    def needs_consolidation(self, repo: str, threshold: int = MONTHLY_THRESHOLD) -> bool:
        """Return True if enough unconsolidated run-tier entries exist to warrant a rollup."""
        count = self._conn.execute(
            "SELECT COUNT(*) FROM runs WHERE repo=? AND tier='run' AND consolidated=0",
            (repo,),
        ).fetchone()[0]
        return count >= threshold

    def needs_quarterly(self, repo: str, threshold: int = QUARTERLY_THRESHOLD) -> bool:
        """Return True if enough unconsolidated monthly snapshots exist for a quarterly rollup."""
        count = self._conn.execute(
            "SELECT COUNT(*) FROM runs WHERE repo=? AND tier='monthly' AND consolidated=0",
            (repo,),
        ).fetchone()[0]
        return count >= threshold

    def consolidate_monthly(
        self,
        repo: str,
        llm_fn: Callable[[str], str],
        period_label: str = "",
    ) -> int | None:
        """
        Roll up all unconsolidated run-tier entries into a single monthly snapshot.

        Args:
            repo:         The repo slug.
            llm_fn:       Callable(prompt_text) -> str — calls your LLM to summarise.
            period_label: Human label for this period (e.g. "2026-03"). Auto-set if blank.

        Returns:
            Row ID of the new monthly entry, or None if nothing to consolidate.
        """
        rows = self._conn.execute(
            """SELECT id, created_at, mode, summary
               FROM runs WHERE repo=? AND tier='run' AND consolidated=0
               ORDER BY id ASC""",
            (repo,),
        ).fetchall()
        if not rows:
            return None

        ids = [r[0] for r in rows]
        period_label = period_label or date.today().strftime("%Y-%m")

        # Build a prompt for the LLM to consolidate
        entries = "\n\n".join(
            f"[{r[1][:10]}] ({r[2]})\n{r[3]}" for r in rows
        )
        prompt = f"""You are consolidating {len(rows)} individual AI pipeline run summaries
for repo '{repo}' into a single monthly memory snapshot.

## Individual run summaries:
{entries}

---

Write a consolidated monthly snapshot (max 600 words) covering:
1. **What was built this month** — list key features/components added
2. **Recurring issues** — problems that appeared more than once
3. **Key decisions** — architectural or design choices made
4. **Tech debt carried forward** — incomplete items that must be addressed
5. **Overall health** — is the project improving or accumulating debt?

Be concise and factual. Future AI agents will read this to understand the project's history.
Output plain text only."""

        consolidated_text = llm_fn(prompt)

        # Save monthly snapshot
        new_id = self.save(
            repo=repo,
            summary=consolidated_text,
            mode="consolidation",
            tier="monthly",
            period_label=period_label,
        )
        # Mark source run entries as consolidated
        self._conn.execute(
            f"UPDATE runs SET consolidated=1 WHERE id IN ({','.join('?' * len(ids))})",
            ids,
        )
        self._conn.commit()
        return new_id

    def consolidate_quarterly(
        self,
        repo: str,
        llm_fn: Callable[[str], str],
        period_label: str = "",
    ) -> int | None:
        """
        Roll up unconsolidated monthly snapshots into a single quarterly snapshot.

        Returns:
            Row ID of the new quarterly entry, or None if nothing to consolidate.
        """
        rows = self._conn.execute(
            """SELECT id, created_at, period_label, summary
               FROM runs WHERE repo=? AND tier='monthly' AND consolidated=0
               ORDER BY id ASC""",
            (repo,),
        ).fetchall()
        if not rows:
            return None

        ids = [r[0] for r in rows]
        period_label = period_label or f"Q{((date.today().month - 1) // 3) + 1}-{date.today().year}"

        entries = "\n\n".join(
            f"[{r[2] or r[1][:7]}]\n{r[3]}" for r in rows
        )
        prompt = f"""You are consolidating {len(rows)} monthly AI pipeline snapshots
for repo '{repo}' into a single quarterly memory index.

## Monthly snapshots:
{entries}

---

Write a quarterly project index (max 400 words) covering:
1. **Project trajectory** — what direction is the codebase heading?
2. **Major milestones** — most significant things built this quarter
3. **Persistent problems** — issues that keep coming up (must be fixed)
4. **Architecture evolution** — how has the design changed?
5. **Priorities for next quarter** — what must be tackled first?

Be strategic. This is the highest-level memory that future agents rely on for big-picture context.
Output plain text only."""

        consolidated_text = llm_fn(prompt)

        new_id = self.save(
            repo=repo,
            summary=consolidated_text,
            mode="consolidation",
            tier="quarterly",
            period_label=period_label,
        )
        self._conn.execute(
            f"UPDATE runs SET consolidated=1 WHERE id IN ({','.join('?' * len(ids))})",
            ids,
        )
        self._conn.commit()
        return new_id

    # ── Recall (tiered) ───────────────────────────────────────────────────────

    def recall(
        self,
        repo: str,
        recent_runs: int = 3,
    ) -> str:
        """Return a compact tiered memory context string for prompt injection.

        Strategy:
          1. Latest quarterly snapshot  (big-picture, ~400 words)
          2. Latest monthly snapshot    (recent theme, ~600 words)
          3. Last `recent_runs` run-tier entries (exact detail)

        Total injected context stays bounded regardless of total run count.
        """
        parts: list[str] = []

        # Quarterly
        quarterly = self._conn.execute(
            """SELECT created_at, period_label, summary FROM runs
               WHERE repo=? AND tier='quarterly'
               ORDER BY id DESC LIMIT 1""",
            (repo,),
        ).fetchone()
        if quarterly:
            label = quarterly[1] or quarterly[0][:7]
            parts.append(f"### 🗓️ Quarterly snapshot [{label}]\n{quarterly[2]}")

        # Monthly
        monthly = self._conn.execute(
            """SELECT created_at, period_label, summary FROM runs
               WHERE repo=? AND tier='monthly'
               ORDER BY id DESC LIMIT 1""",
            (repo,),
        ).fetchone()
        if monthly:
            label = monthly[1] or monthly[0][:7]
            parts.append(f"### 📅 Monthly snapshot [{label}]\n{monthly[2]}")

        # Recent individual runs
        recent = self._conn.execute(
            """SELECT created_at, mode, summary FROM runs
               WHERE repo=? AND tier='run'
               ORDER BY id DESC LIMIT ?""",
            (repo, recent_runs),
        ).fetchall()
        if recent:
            run_parts = []
            for created_at, mode, summary in reversed(recent):
                run_parts.append(f"#### [{created_at[:10]}] ({mode})\n{summary}")
            parts.append("### 🔍 Recent runs\n" + "\n\n".join(run_parts))

        if not parts:
            return ""

        return "## 📚 Memory: previous work on this repo\n\n" + "\n\n---\n\n".join(parts)

    def recall_issues(self, repo: str, limit: int = 10) -> str:
        """Return known issues from past runs to help agents avoid repeating them."""
        rows = self._conn.execute(
            "SELECT created_at, summary FROM runs WHERE repo=? AND tags LIKE '%issue%' ORDER BY id DESC LIMIT ?",
            (repo, limit),
        ).fetchall()
        if not rows:
            return ""
        parts = ["## ⚠️ Known issues from previous runs\n"]
        for created_at, summary in rows:
            parts.append(f"- [{created_at[:10]}] {summary[:300]}")
        return "\n".join(parts)

    def search(self, repo: str, keywords: list[str], limit: int = 5) -> str:
        """Search memory entries by keywords (simple substring match across all tiers)."""
        if not keywords:
            return ""
        conditions = " OR ".join("summary LIKE ?" for _ in keywords)
        params = [repo] + [f"%{kw}%" for kw in keywords] + [limit]
        rows = self._conn.execute(
            f"""SELECT created_at, tier, mode, summary FROM runs
                WHERE repo=? AND ({conditions})
                ORDER BY id DESC LIMIT ?""",
            params,
        ).fetchall()
        if not rows:
            return ""
        parts = [f"## 🔎 Memory search: {', '.join(keywords)}\n"]
        for created_at, tier, mode, summary in rows:
            parts.append(f"- [{created_at[:10]}] ({tier}/{mode})\n  {summary[:400]}")
        return "\n".join(parts)

    def stats(self, repo: str) -> dict:
        """Return memory statistics for a repo."""
        rows = self._conn.execute(
            "SELECT tier, COUNT(*) FROM runs WHERE repo=? GROUP BY tier",
            (repo,),
        ).fetchall()
        result = {tier: count for tier, count in rows}
        result["total"] = sum(result.values())
        return result

    def list_repos(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT repo FROM runs ORDER BY repo"
        ).fetchall()
        return [r[0] for r in rows]

    def close(self) -> None:
        self._conn.close()

