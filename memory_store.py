"""
memory_store.py — Tiered SQLite memory for the AI software house.

Memory has two orthogonal axes:

  Scope (does this decay?):
    dynamic — the normal, time-tiered flow described below (default)
    static  — a standing fact that never decays and is never consolidated
              away; always included by recall() in full, regardless of
              recency or relevance, the same way a "profile" is meant to
              always be known rather than left to a lucky search match
              (e.g. "target DB is Postgres 16 + PostGIS", "always use HK
              Cantonese terminology"). Represented as tier='static'.

  Tier (how much has a dynamic entry been compressed?), run/monthly/quarterly:
    run      — individual pipeline run summaries (full detail, ~400 words each)
    monthly  — AI-consolidated rollup of all runs in a calendar month (~600 words)
    quarterly — AI-consolidated rollup of all monthlies in a quarter (~400 words)

recall() returns:
  • All static facts             (always known — the "profile" half of memory)
  • Latest quarterly snapshot    (big-picture history)
  • Latest monthly snapshot      (recent theme / issues)
  • Last N individual runs       (exact recent detail)

This keeps injected context bounded regardless of how many runs exist —
static facts are meant to stay few and curated, not to grow with every run.

Auto-consolidation is triggered when the number of unprocessed run-tier entries
exceeds MONTHLY_THRESHOLD (default 10).  Call consolidate() from the orchestrator
after saving each run summary. Static facts are never swept into consolidation —
they're never tier='run', so needs_consolidation()/consolidate_monthly() never see them.

Usage:
    store = MemoryStore("./workspace/memory.db")
    store.save(repo="owner/repo", summary="...", mode="feature")

    # A standing fact that should always be recalled, not just when relevant
    store.save_static(repo="owner/repo", fact="Target DB is Postgres 16 + PostGIS",
                       key="tech-stack")

    # Check and consolidate if needed (pass a callable that calls the LLM)
    if store.needs_consolidation(repo):
        store.consolidate_monthly(repo, llm_fn=my_summarise_fn)

    context = store.recall(repo)   # static facts + tiered dynamic, ready to inject
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, date, timezone
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
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.commit()
        self._lock = threading.Lock()
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
                consolidated    INTEGER DEFAULT 0,
                indexed         INTEGER DEFAULT 0,
                fact_type       TEXT DEFAULT '',
                entity          TEXT DEFAULT '',
                resolved        INTEGER DEFAULT 0,
                is_latest       INTEGER DEFAULT 1,
                supersedes_id   INTEGER DEFAULT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_runs_repo  ON runs(repo);
            CREATE INDEX IF NOT EXISTS idx_runs_tier  ON runs(repo, tier);
            CREATE INDEX IF NOT EXISTS idx_runs_cons  ON runs(repo, tier, consolidated);
            CREATE INDEX IF NOT EXISTS idx_runs_idx   ON runs(indexed);
            CREATE INDEX IF NOT EXISTS idx_runs_fact  ON runs(repo, tier, fact_type, resolved, is_latest);
        """)
        # Migrate existing DB that may lack the new columns
        existing = {row[1] for row in self._conn.execute("PRAGMA table_info(runs)")}
        for col, dflt, col_type in [
            ("tier", "'run'", "TEXT"),
            ("period_label", "''", "TEXT"),
            ("consolidated", "0", "INTEGER"),
            ("indexed", "0", "INTEGER"),
            ("fact_type", "''", "TEXT"),
            ("entity", "''", "TEXT"),
            ("resolved", "0", "INTEGER"),
            ("is_latest", "1", "INTEGER"),
            ("supersedes_id", "NULL", "INTEGER"),
        ]:
            if col not in existing:
                self._conn.execute(f"ALTER TABLE runs ADD COLUMN {col} {col_type} DEFAULT {dflt}")
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
        with self._lock:
            with self._conn:
                cur = self._conn.execute(
                    """INSERT INTO runs
                       (repo, run_id, created_at, summary, tags, mode, tier, period_label)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        repo,
                        run_id or "",
                        datetime.now(timezone.utc).isoformat(),
                        summary,
                        json.dumps(tags or []),
                        mode,
                        tier,
                        period_label or "",
                    ),
                )
            return cur.lastrowid

    def save_static(
        self,
        repo: str,
        fact: str,
        key: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> int:
        """Persist or update a standing fact — recall() always includes these in full.

        Static facts (tier='static') are the "profile" half of memory: things
        that should be known regardless of what's being asked, not left to a
        lucky recency or relevance match. They never decay and are never
        touched by consolidation (needs_consolidation()/consolidate_monthly()
        only ever look at tier='run').

        Args:
            repo: Repo slug this fact applies to.
            fact: The fact text.
            key: Optional stable identifier (e.g. "tech-stack",
                "cantonese-terminology"). When given and a static fact with
                the same key already exists for this repo, it is updated in
                place instead of duplicated — reuses the run_id column,
                which is otherwise unused for static facts. Omit key to
                always append a new fact.
            tags: Optional tags.

        Returns:
            The row ID (existing row's ID if this was an update by key).
        """
        if key:
            with self._lock:
                existing = self._conn.execute(
                    "SELECT id FROM runs WHERE repo=? AND tier='static' AND run_id=?",
                    (repo, key),
                ).fetchone()
                if existing:
                    with self._conn:
                        self._conn.execute(
                            # indexed=0 so the updated text gets re-embedded into
                            # pgvector on the next search_memory indexer pass.
                            "UPDATE runs SET summary=?, tags=?, created_at=?, indexed=0 WHERE id=?",
                            (
                                fact,
                                json.dumps(tags or []),
                                datetime.now(timezone.utc).isoformat(),
                                existing[0],
                            ),
                        )
                    return existing[0]
        return self.save(repo=repo, summary=fact, run_id=key, tags=tags, mode="static", tier="static")

    def list_static(self, repo: str) -> list[dict]:
        """Return all static facts for a repo, oldest first."""
        rows = self._conn.execute(
            """SELECT id, run_id, summary, tags, created_at FROM runs
               WHERE repo=? AND tier='static' ORDER BY id ASC""",
            (repo,),
        ).fetchall()
        return [
            {"id": r[0], "key": r[1], "fact": r[2], "tags": json.loads(r[3] or "[]"), "created_at": r[4]}
            for r in rows
        ]

    def forget_static(self, repo: str, key: str) -> bool:
        """Delete a static fact by key. Returns True if a row was deleted."""
        with self._lock:
            with self._conn:
                cur = self._conn.execute(
                    "DELETE FROM runs WHERE repo=? AND tier='static' AND run_id=?",
                    (repo, key),
                )
            return cur.rowcount > 0

    # ── Atomic facts ──────────────────────────────────────────────────────────
    # The structured counterpart to the prose run summary — one row per fact
    # instead of a clause buried in a paragraph, so "is this tech debt still
    # open?" is a query (list_facts(fact_type="issue", resolved=False))
    # instead of a hope that the last compression pass kept the sentence.
    # Populated by FactExtractorAgent; tier='fact' keeps these out of the
    # run/monthly/quarterly consolidation cycle the same way tier='static' does.
    #
    # Contradiction handling (supermemory calls this the "updates" relation):
    # a new fact can name an older one it supersedes via supersedes_id. The
    # old row is marked is_latest=0 rather than deleted or rewritten — the
    # history stays queryable (list_facts(include_superseded=True)) while
    # list_facts()'s default view only ever shows the current truth.

    def save_fact(
        self,
        repo: str,
        fact: str,
        fact_type: str = "status",
        entity: str = "",
        resolved: bool = True,
        run_id: Optional[str] = None,
        tags: Optional[list[str]] = None,
        supersedes_id: Optional[int] = None,
    ) -> int:
        """Persist one atomic fact. Returns the row ID.

        Args:
            repo: Repo slug this fact applies to.
            fact: The fact text — one sentence, self-contained.
            fact_type: One of "decision", "issue", "learning", "status".
            entity: What/who the fact is about (a component, module, stage).
            resolved: For fact_type="issue", whether it's already fixed.
                Ignored in spirit (but still stored) for other types.
            run_id: The originating pipeline run's run_id, for traceability
                back to the source run this fact was extracted from.
            tags: Optional tags.
            supersedes_id: ID of an older fact this one updates/replaces.
                When given and the target exists (same repo, tier='fact'),
                the target is marked is_latest=0 — its content stays in the
                table for history, but list_facts()'s default view no
                longer returns it. Silently ignored if the target doesn't
                exist or belongs to a different repo — the new fact is
                still saved either way.
        """
        with self._lock:
            with self._conn:
                cur = self._conn.execute(
                    """INSERT INTO runs
                       (repo, run_id, created_at, summary, tags, mode, tier,
                        fact_type, entity, resolved, supersedes_id)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        repo,
                        run_id or "",
                        datetime.now(timezone.utc).isoformat(),
                        fact,
                        json.dumps(tags or []),
                        "fact",
                        "fact",
                        fact_type,
                        entity,
                        1 if resolved else 0,
                        supersedes_id,
                    ),
                )
                new_id = cur.lastrowid
                if supersedes_id is not None:
                    self._conn.execute(
                        """UPDATE runs SET is_latest=0, indexed=0
                           WHERE id=? AND repo=? AND tier='fact'""",
                        (supersedes_id, repo),
                    )
            return new_id

    def save_facts(self, repo: str, facts: list[dict], run_id: Optional[str] = None) -> list[int]:
        """Persist multiple atomic facts from one extraction pass. Returns row IDs.

        Args:
            facts: list of {"type", "entity", "fact", "resolved"} dicts,
                optionally with a "supersedes" int key — the shape
                FactExtractorAgent.extract() returns.
            run_id: originating pipeline run_id, applied to every fact.
        """
        return [
            self.save_fact(
                repo=repo,
                fact=f["fact"],
                fact_type=f.get("type", "status"),
                entity=f.get("entity", ""),
                resolved=f.get("resolved", True),
                run_id=run_id,
                supersedes_id=f.get("supersedes"),
            )
            for f in facts
        ]

    def list_facts(
        self,
        repo: str,
        fact_type: Optional[str] = None,
        entity: Optional[str] = None,
        resolved: Optional[bool] = None,
        include_superseded: bool = False,
        limit: int = 100,
    ) -> list[dict]:
        """Query atomic facts with optional filters, newest first.

        This is the structured-query payoff of atomic extraction:
        list_facts(repo, fact_type="issue", resolved=False) answers
        "what's still open" directly instead of grepping prose summaries.

        By default only returns is_latest=1 rows — the current truth, with
        anything a newer fact superseded left out. Pass
        include_superseded=True for the full history, e.g. to show how a
        fact's stated value changed over time.
        """
        conditions = ["repo=?", "tier='fact'"]
        params: list = [repo]
        if not include_superseded:
            conditions.append("is_latest=1")
        if fact_type:
            conditions.append("fact_type=?")
            params.append(fact_type)
        if entity:
            conditions.append("entity=?")
            params.append(entity)
        if resolved is not None:
            conditions.append("resolved=?")
            params.append(1 if resolved else 0)
        params.append(limit)

        rows = self._conn.execute(
            f"""SELECT id, run_id, fact_type, entity, summary, resolved,
                       created_at, is_latest, supersedes_id
                FROM runs WHERE {' AND '.join(conditions)}
                ORDER BY id DESC LIMIT ?""",
            params,
        ).fetchall()
        return [
            {
                "id": r[0], "run_id": r[1], "type": r[2], "entity": r[3],
                "fact": r[4], "resolved": bool(r[5]), "created_at": r[6],
                "is_latest": bool(r[7]), "supersedes_id": r[8],
            }
            for r in rows
        ]

    def resolve_fact(self, fact_id: int, repo: Optional[str] = None) -> bool:
        """Mark an issue-type fact as resolved. Returns True if a row was updated.

        Args:
            fact_id: The fact's row id.
            repo: Optional scoping check — when given, the update only
                applies if the fact belongs to this repo. Callers that
                don't already know the fact belongs to their repo (an MCP
                tool taking untrusted input, for example) should pass this.
        """
        conditions = "id=? AND tier='fact'"
        params: list = [fact_id]
        if repo is not None:
            conditions += " AND repo=?"
            params.append(repo)
        with self._lock:
            with self._conn:
                cur = self._conn.execute(
                    f"UPDATE runs SET resolved=1, indexed=0 WHERE {conditions}",
                    params,
                )
            return cur.rowcount > 0

    def forget_fact(self, fact_id: int, repo: Optional[str] = None) -> bool:
        """Delete a fact outright. Returns True if a row was deleted.

        Distinct from resolve_fact(): resolving means the fact happened and
        is now closed (an issue got fixed); forgetting means the fact never
        should have been kept at all (noise, a duplicate, something wrong).

        Args:
            fact_id: The fact's row id.
            repo: Optional scoping check — see resolve_fact().
        """
        conditions = "id=? AND tier='fact'"
        params: list = [fact_id]
        if repo is not None:
            conditions += " AND repo=?"
            params.append(repo)
        with self._lock:
            with self._conn:
                cur = self._conn.execute(f"DELETE FROM runs WHERE {conditions}", params)
            return cur.rowcount > 0

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

        Note:
            The LLM call is performed *outside* the lock so we never hold the write
            lock for the potentially multi-second network round-trip.  Only the DB
            reads and writes are protected by ``self._lock``.
        """
        with self._lock:
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

        # LLM call happens OUTSIDE the lock — may take several seconds
        consolidated_text = llm_fn(prompt)

        # Save monthly snapshot and mark source rows as consolidated — both under lock
        with self._lock:
            # Re-verify rows haven't been consolidated by a concurrent caller
            placeholders = ",".join("?" * len(ids))
            still_raw = self._conn.execute(
                f"SELECT COUNT(*) FROM runs WHERE id IN ({placeholders}) AND consolidated=0",
                ids,
            ).fetchone()[0]
            if still_raw == 0:
                return None  # already handled by a concurrent thread

            with self._conn:
                cur = self._conn.execute(
                    """INSERT INTO runs
                       (repo, run_id, created_at, summary, tags, mode, tier, period_label)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        repo,
                        "",
                        datetime.now(timezone.utc).isoformat(),
                        consolidated_text,
                        json.dumps([]),
                        "consolidation",
                        "monthly",
                        period_label,
                    ),
                )
                new_id = cur.lastrowid
                self._conn.execute(
                    f"UPDATE runs SET consolidated=1 WHERE id IN ({placeholders}) AND consolidated=0",
                    ids,
                )
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

        Note:
            The LLM call is performed *outside* the lock so we never hold the write
            lock for the potentially multi-second network round-trip.  Only the DB
            reads and writes are protected by ``self._lock``.
        """
        with self._lock:
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

        # LLM call happens OUTSIDE the lock — may take several seconds
        consolidated_text = llm_fn(prompt)

        # Save quarterly snapshot and mark source rows as consolidated — both under lock
        with self._lock:
            # Re-verify rows haven't been consolidated by a concurrent caller
            placeholders = ",".join("?" * len(ids))
            still_raw = self._conn.execute(
                f"SELECT COUNT(*) FROM runs WHERE id IN ({placeholders}) AND consolidated=0",
                ids,
            ).fetchone()[0]
            if still_raw == 0:
                return None  # already handled by a concurrent thread

            with self._conn:
                cur = self._conn.execute(
                    """INSERT INTO runs
                       (repo, run_id, created_at, summary, tags, mode, tier, period_label)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        repo,
                        "",
                        datetime.now(timezone.utc).isoformat(),
                        consolidated_text,
                        json.dumps([]),
                        "consolidation",
                        "quarterly",
                        period_label,
                    ),
                )
                new_id = cur.lastrowid
                self._conn.execute(
                    f"UPDATE runs SET consolidated=1 WHERE id IN ({placeholders}) AND consolidated=0",
                    ids,
                )
        return new_id

    # ── Recall (tiered) ───────────────────────────────────────────────────────

    def recall(
        self,
        repo: str,
        recent_runs: int = 3,
    ) -> str:
        """Return a compact memory context string for prompt injection.

        Strategy:
          1. All static facts           (always known — the profile half of memory)
          2. Unresolved issue facts     (up to 10 — precise, not a lucky substring match)
          3. Latest quarterly snapshot   (big-picture, ~400 words)
          4. Latest monthly snapshot     (recent theme, ~600 words)
          5. Last `recent_runs` run-tier entries (exact detail)

        Total injected context stays bounded regardless of total run count —
        static facts and open issues are meant to stay few and curated, not
        to grow with every run the way the tiered dynamic history does.
        """
        parts: list[str] = []

        # Static facts — unconditional, not scored by recency or relevance.
        # This is the "profile" pattern: some facts (standing conventions,
        # architecture choices) should always be present, not left to a
        # lucky match the way search or a recency window would require.
        static_rows = self._conn.execute(
            """SELECT summary FROM runs
               WHERE repo=? AND tier='static' ORDER BY id ASC""",
            (repo,),
        ).fetchall()
        if static_rows:
            facts = "\n".join(f"- {r[0]}" for r in static_rows)
            parts.append(f"### 📌 Static facts (always apply)\n{facts}")

        # Unresolved issue facts — the atomic-extraction counterpart to a
        # paragraph mentioning a bug in passing. Capped at 10: this is meant
        # to surface a short, current punch list, not the entire backlog.
        open_issues = self._conn.execute(
            """SELECT entity, summary FROM runs
               WHERE repo=? AND tier='fact' AND fact_type='issue'
                     AND resolved=0 AND is_latest=1
               ORDER BY id DESC LIMIT 10""",
            (repo,),
        ).fetchall()
        if open_issues:
            issue_lines = "\n".join(
                f"- {(entity + ': ') if entity else ''}{summary}" for entity, summary in open_issues
            )
            parts.append(f"### ⚠️ Known open issues\n{issue_lines}")

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
        """Return known unresolved issues to help agents avoid repeating them.

        Prefers atomic issue-type facts (tier='fact', fact_type='issue',
        resolved=False) — precise and structured, unlike a substring that
        has to have survived intact through prose compression. Falls back
        to the older tag-based convention (a "issue" tag on a run-tier
        summary) when no fact-tier data exists yet, so repos saved before
        atomic fact extraction still get something.
        """
        fact_rows = self._conn.execute(
            """SELECT created_at, entity, summary FROM runs
               WHERE repo=? AND tier='fact' AND fact_type='issue'
                     AND resolved=0 AND is_latest=1
               ORDER BY id DESC LIMIT ?""",
            (repo, limit),
        ).fetchall()
        if fact_rows:
            parts = ["## ⚠️ Known issues from previous runs\n"]
            for created_at, entity, summary in fact_rows:
                label = f"{entity}: " if entity else ""
                parts.append(f"- [{created_at[:10]}] {label}{summary[:300]}")
            return "\n".join(parts)

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

    # ── Vector indexing (rag-mcp) ────────────────────────────────────────────
    # rag-mcp/indexer.py embeds unindexed rows into pgvector for the
    # search_memory MCP tool.  These methods are the schema-aware surface
    # for that — the indexer still talks to the SQLite file directly (it's a
    # separately deployed service and must stay loosely coupled), but any
    # in-process caller (orchestrator, tests, diagnostics) should use these
    # instead of hand-rolling the same SQL against a column the indexer owns.

    def unindexed(self, limit: int = 500) -> list[dict]:
        """Return up to *limit* rows not yet embedded into pgvector, oldest first.

        Only rows with a non-empty summary are eligible — nothing else is
        chunked/embedded by the indexer.
        """
        rows = self._conn.execute(
            """SELECT id, repo, tier, summary, created_at FROM runs
               WHERE indexed=0 AND summary IS NOT NULL AND summary != ''
               ORDER BY id ASC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [
            {"id": r[0], "repo": r[1], "tier": r[2], "summary": r[3], "created_at": r[4]}
            for r in rows
        ]

    def mark_indexed(self, ids: list[int]) -> None:
        """Mark the given row ids as embedded. No-op on an empty list."""
        if not ids:
            return
        with self._lock:
            placeholders = ",".join("?" * len(ids))
            with self._conn:
                self._conn.execute(
                    f"UPDATE runs SET indexed=1 WHERE id IN ({placeholders})", ids,
                )

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

