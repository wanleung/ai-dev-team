"""Extended tests for MemoryStore — consolidation, recall, search, DB migration."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from memory_store import MemoryStore


@pytest.fixture
def store(tmp_path):
    """MemoryStore backed by a temp file DB."""
    db = tmp_path / "mem.db"
    ms = MemoryStore(db_path=db)
    yield ms
    ms.close()


# ── DB migration ──────────────────────────────────────────────────────────────

class TestDbMigration:
    def test_migration_adds_missing_columns_to_existing_db(self, tmp_path):
        """Opening a DB that lacks tier/period_label/consolidated triggers migration."""
        db = tmp_path / "legacy.db"
        # Create DB with only the original columns (no tier etc.)
        conn = sqlite3.connect(db)
        conn.execute("""CREATE TABLE runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repo TEXT NOT NULL,
            run_id TEXT,
            created_at TEXT,
            mode TEXT,
            summary TEXT NOT NULL,
            tags TEXT DEFAULT ''
        )""")
        conn.commit()
        conn.close()

        # Opening with MemoryStore should migrate without error
        ms = MemoryStore(db_path=db)
        cols = {row[1] for row in ms._conn.execute("PRAGMA table_info(runs)")}
        assert "tier" in cols
        assert "period_label" in cols
        assert "consolidated" in cols
        assert "indexed" in cols
        assert "fact_type" in cols
        assert "entity" in cols
        assert "resolved" in cols
        ms.close()

    def test_migration_adds_fact_columns_to_a_db_with_only_the_earlier_columns(self, tmp_path):
        """Regression test: a DB with tier/period_label/consolidated/indexed but
        not yet fact_type/entity/resolved/is_latest/supersedes_id must migrate
        cleanly, not crash.

        This is the exact shape that broke in production: CREATE INDEX
        idx_runs_fact ON runs(..., fact_type, ...) ran inside the same
        executescript() as CREATE TABLE IF NOT EXISTS, which is a no-op on an
        existing table — so the index creation hit "no such column: fact_type"
        before the ALTER TABLE loop below it ever got a chance to add the
        column. Every other migration test in this file built its legacy
        table from complete scratch (missing tier/indexed too), which doesn't
        exercise this — a table that already has tier/indexed but not the
        fact columns is what real deployments actually look like: incremental,
        not built fresh each time a new column gets added.
        """
        db = tmp_path / "memory.db"  # exact path _isolate_memory_store leaves alone when passed explicitly
        conn = sqlite3.connect(db)
        conn.execute("""CREATE TABLE runs (
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
            indexed         INTEGER DEFAULT 0
        )""")
        conn.execute(
            "INSERT INTO runs (repo, created_at, summary) VALUES (?, ?, ?)",
            ("owner/repo", "2026-09-01T00:00:00Z", "a run from before fact extraction existed"),
        )
        conn.commit()
        conn.close()

        ms = MemoryStore(db_path=db)  # must not raise
        cols = {row[1] for row in ms._conn.execute("PRAGMA table_info(runs)")}
        assert {"fact_type", "entity", "resolved", "is_latest", "supersedes_id"} <= cols

        # The pre-existing row must survive the migration untouched.
        row = ms._conn.execute("SELECT summary FROM runs WHERE repo='owner/repo'").fetchone()
        assert row[0] == "a run from before fact extraction existed"
        ms.close()


# ── save_static / list_static / forget_static ───────────────────────────────
# The static/dynamic split: static facts (tier='static') are the "profile"
# half of memory — always recalled in full, never consolidated, never
# time-decayed. Modeled on supermemory's static profile.

class TestSaveStatic:
    def test_creates_a_static_fact(self, store):
        """save_static() persists a fact with tier='static'."""
        row_id = store.save_static("owner/repo", "Target DB is Postgres 16 + PostGIS", key="tech-stack")
        facts = store.list_static("owner/repo")
        assert len(facts) == 1
        assert facts[0]["id"] == row_id
        assert facts[0]["fact"] == "Target DB is Postgres 16 + PostGIS"
        assert facts[0]["key"] == "tech-stack"

    def test_same_key_updates_in_place_instead_of_duplicating(self, store):
        """A second save_static() with the same key overwrites, does not append."""
        id1 = store.save_static("owner/repo", "Postgres 16", key="tech-stack")
        id2 = store.save_static("owner/repo", "Postgres 17 + pgvector", key="tech-stack")

        assert id1 == id2
        facts = store.list_static("owner/repo")
        assert len(facts) == 1
        assert facts[0]["fact"] == "Postgres 17 + pgvector"

    def test_omitting_key_always_appends(self, store):
        """save_static() without a key never collides — always a new fact."""
        store.save_static("owner/repo", "fact one")
        store.save_static("owner/repo", "fact two")
        assert len(store.list_static("owner/repo")) == 2

    def test_update_by_key_resets_indexed_flag(self, store):
        """Updating a static fact marks it unindexed so pgvector picks up the change."""
        store.save_static("owner/repo", "Postgres 16", key="tech-stack")
        row_id = store.list_static("owner/repo")[0]["id"]
        store.mark_indexed([row_id])
        assert store.unindexed() == []

        store.save_static("owner/repo", "Postgres 17", key="tech-stack")
        unindexed_ids = {r["id"] for r in store.unindexed()}
        assert row_id in unindexed_ids

    def test_static_facts_excluded_from_needs_consolidation(self, store):
        """Static facts never count toward the run-tier consolidation threshold."""
        for i in range(3):
            store.save_static("owner/repo", f"fact {i}")
        assert store.needs_consolidation("owner/repo") is False

    def test_static_facts_excluded_from_consolidate_monthly(self, store):
        """consolidate_monthly() never rolls up static facts."""
        store.save_static("owner/repo", "a standing fact", key="fact")
        store.save("owner/repo", "run summary", mode="feature")

        llm = MagicMock(return_value="monthly text")
        store.consolidate_monthly("owner/repo", llm)

        # The static fact must still be a single, unconsolidated row.
        facts = store.list_static("owner/repo")
        assert len(facts) == 1
        assert facts[0]["fact"] == "a standing fact"

    def test_forget_static_removes_by_key(self, store):
        """forget_static() deletes the fact and returns True."""
        store.save_static("owner/repo", "outdated fact", key="old")
        assert store.forget_static("owner/repo", "old") is True
        assert store.list_static("owner/repo") == []

    def test_forget_static_returns_false_when_key_not_found(self, store):
        """forget_static() is a no-op returning False for an unknown key."""
        assert store.forget_static("owner/repo", "nonexistent") is False

    def test_list_static_scoped_per_repo(self, store):
        """list_static() never leaks facts across repos."""
        store.save_static("owner/repo-a", "fact for repo A", key="k")
        store.save_static("owner/repo-b", "fact for repo B", key="k")

        assert [f["fact"] for f in store.list_static("owner/repo-a")] == ["fact for repo A"]
        assert [f["fact"] for f in store.list_static("owner/repo-b")] == ["fact for repo B"]


# ── save_fact / save_facts / list_facts / resolve_fact ─────────────────────
# Atomic fact extraction: the structured counterpart to the prose run
# summary — one row per fact (tier='fact') instead of a clause buried in a
# paragraph that might not survive two rounds of LLM compression.

class TestSaveFact:
    def test_creates_a_fact_row(self, store):
        """save_fact() persists a fact with tier='fact' and the given metadata."""
        row_id = store.save_fact(
            "owner/repo", "403 errors from GitHub Search API", fact_type="issue",
            entity="RSS watcher", resolved=False, run_id="run-1",
        )
        facts = store.list_facts("owner/repo")
        assert len(facts) == 1
        assert facts[0]["id"] == row_id
        assert facts[0]["fact"] == "403 errors from GitHub Search API"
        assert facts[0]["type"] == "issue"
        assert facts[0]["entity"] == "RSS watcher"
        assert facts[0]["resolved"] is False
        assert facts[0]["run_id"] == "run-1"

    def test_defaults_to_status_type_and_resolved_true(self, store):
        """save_fact() with no explicit type/resolved uses sensible defaults."""
        store.save_fact("owner/repo", "ComfyUI integration shipped")
        facts = store.list_facts("owner/repo")
        assert facts[0]["type"] == "status"
        assert facts[0]["resolved"] is True

    def test_save_facts_persists_a_batch_with_shared_run_id(self, store):
        """save_facts() saves a list of facts (FactExtractorAgent's output shape)."""
        facts_in = [
            {"type": "issue", "entity": "RSS watcher", "fact": "403 errors", "resolved": False},
            {"type": "decision", "entity": "database", "fact": "Switched to raw SQL", "resolved": True},
        ]
        ids = store.save_facts("owner/repo", facts_in, run_id="run-42")
        assert len(ids) == 2

        saved = store.list_facts("owner/repo")
        assert {f["run_id"] for f in saved} == {"run-42"}
        assert {f["fact"] for f in saved} == {"403 errors", "Switched to raw SQL"}


class TestListFacts:
    def test_filters_by_type(self, store):
        store.save_fact("owner/repo", "an issue", fact_type="issue")
        store.save_fact("owner/repo", "a decision", fact_type="decision")
        result = store.list_facts("owner/repo", fact_type="issue")
        assert len(result) == 1
        assert result[0]["fact"] == "an issue"

    def test_filters_by_entity(self, store):
        store.save_fact("owner/repo", "fact about watcher", entity="RSS watcher")
        store.save_fact("owner/repo", "fact about db", entity="database")
        result = store.list_facts("owner/repo", entity="RSS watcher")
        assert len(result) == 1
        assert result[0]["fact"] == "fact about watcher"

    def test_filters_by_resolved_false_answers_whats_still_open(self, store):
        """The core payoff: 'is this tech debt still open?' as a query."""
        store.save_fact("owner/repo", "open issue", fact_type="issue", resolved=False)
        store.save_fact("owner/repo", "closed issue", fact_type="issue", resolved=True)
        result = store.list_facts("owner/repo", fact_type="issue", resolved=False)
        assert len(result) == 1
        assert result[0]["fact"] == "open issue"

    def test_respects_limit(self, store):
        for i in range(5):
            store.save_fact("owner/repo", f"fact {i}")
        assert len(store.list_facts("owner/repo", limit=2)) == 2

    def test_scoped_per_repo(self, store):
        store.save_fact("owner/repo-a", "fact A")
        store.save_fact("owner/repo-b", "fact B")
        assert [f["fact"] for f in store.list_facts("owner/repo-a")] == ["fact A"]


class TestResolveFact:
    def test_marks_a_fact_resolved(self, store):
        row_id = store.save_fact("owner/repo", "an open issue", fact_type="issue", resolved=False)
        assert store.resolve_fact(row_id) is True

        facts = store.list_facts("owner/repo", fact_type="issue", resolved=False)
        assert facts == []
        facts = store.list_facts("owner/repo", fact_type="issue", resolved=True)
        assert len(facts) == 1

    def test_resets_indexed_flag_so_pgvector_picks_up_the_change(self, store):
        row_id = store.save_fact("owner/repo", "an open issue", fact_type="issue", resolved=False)
        store.mark_indexed([row_id])
        assert store.unindexed() == []

        store.resolve_fact(row_id)
        assert row_id in {r["id"] for r in store.unindexed()}

    def test_returns_false_for_unknown_id(self, store):
        assert store.resolve_fact(99999) is False

    def test_only_touches_fact_tier_rows(self, store):
        """resolve_fact() must not accidentally resolve a static fact or a run row."""
        static_id = store.save_static("owner/repo", "a standing fact", key="k")
        assert store.resolve_fact(static_id) is False


class TestFactsExcludedFromConsolidation:
    def test_needs_consolidation_ignores_facts(self, store):
        for i in range(15):
            store.save_fact("owner/repo", f"fact {i}")
        assert store.needs_consolidation("owner/repo") is False

    def test_consolidate_monthly_never_touches_facts(self, store):
        from unittest.mock import MagicMock as _MM

        store.save_fact("owner/repo", "a standing fact")
        store.save("owner/repo", "run summary", mode="feature")

        store.consolidate_monthly("owner/repo", _MM(return_value="monthly text"))

        facts = store.list_facts("owner/repo")
        assert len(facts) == 1
        assert facts[0]["fact"] == "a standing fact"


# ── Supersession (isLatest / supersedes_id) ─────────────────────────────────
# Contradiction handling: a new fact can name an older one it updates. The
# old row is marked is_latest=0 rather than rewritten or deleted, so history
# stays queryable while the default view only ever shows current truth.

class TestSupersession:
    def test_new_fact_is_latest_by_default(self, store):
        row_id = store.save_fact("owner/repo", "a fact")
        facts = store.list_facts("owner/repo", include_superseded=True)
        assert facts[0]["is_latest"] is True
        assert facts[0]["supersedes_id"] is None

    def test_supersede_marks_old_fact_not_latest(self, store):
        old_id = store.save_fact("owner/repo", "DB is Postgres 16")
        store.save_fact("owner/repo", "DB is Postgres 17 + pgvector", supersedes_id=old_id)

        all_facts = store.list_facts("owner/repo", include_superseded=True)
        old_row = next(f for f in all_facts if f["id"] == old_id)
        assert old_row["is_latest"] is False

    def test_default_list_facts_excludes_superseded(self, store):
        old_id = store.save_fact("owner/repo", "DB is Postgres 16")
        new_id = store.save_fact("owner/repo", "DB is Postgres 17", supersedes_id=old_id)

        current = store.list_facts("owner/repo")
        assert [f["id"] for f in current] == [new_id]

    def test_include_superseded_returns_full_history(self, store):
        old_id = store.save_fact("owner/repo", "DB is Postgres 16")
        new_id = store.save_fact("owner/repo", "DB is Postgres 17", supersedes_id=old_id)

        full = store.list_facts("owner/repo", include_superseded=True)
        assert {f["id"] for f in full} == {old_id, new_id}

    def test_new_fact_records_supersedes_id(self, store):
        old_id = store.save_fact("owner/repo", "DB is Postgres 16")
        new_id = store.save_fact("owner/repo", "DB is Postgres 17", supersedes_id=old_id)

        new_row = next(f for f in store.list_facts("owner/repo", include_superseded=True) if f["id"] == new_id)
        assert new_row["supersedes_id"] == old_id

    def test_supersede_resets_old_facts_indexed_flag(self, store):
        """A superseded fact's changed is_latest status should re-enter the pgvector index sweep."""
        old_id = store.save_fact("owner/repo", "DB is Postgres 16")
        store.mark_indexed([old_id])
        assert store.unindexed() == []

        store.save_fact("owner/repo", "DB is Postgres 17", supersedes_id=old_id)
        assert old_id in {r["id"] for r in store.unindexed()}

    def test_nonexistent_supersede_target_does_not_raise(self, store):
        """A hallucinated/stale supersedes_id must not block saving the new fact."""
        new_id = store.save_fact("owner/repo", "a fact", supersedes_id=999999)
        assert new_id is not None
        assert len(store.list_facts("owner/repo")) == 1

    def test_supersede_scoped_to_repo(self, store):
        """A supersedes_id from a different repo must not mark that row is_latest=0."""
        other_repo_id = store.save_fact("owner/repo-a", "fact in repo A")
        store.save_fact("owner/repo-b", "unrelated fact", supersedes_id=other_repo_id)

        facts_a = store.list_facts("owner/repo-a", include_superseded=True)
        assert facts_a[0]["is_latest"] is True

    def test_open_issue_recall_excludes_superseded_issue_facts(self, store):
        """recall()'s open-issues section only shows the current version of an issue."""
        old_id = store.save_fact("owner/repo", "vague issue description", fact_type="issue", resolved=False)
        store.save_fact("owner/repo", "precise issue description", fact_type="issue",
                         resolved=False, supersedes_id=old_id)

        result = store.recall("owner/repo")
        assert "precise issue description" in result
        assert "vague issue description" not in result

    def test_save_facts_passes_through_supersedes_key(self, store):
        """save_facts() honors a 'supersedes' key on individual fact dicts (FactExtractorAgent's output shape)."""
        old_id = store.save_fact("owner/repo", "DB is Postgres 16")
        store.save_facts("owner/repo", [
            {"type": "decision", "entity": "db", "fact": "DB is Postgres 17", "resolved": True, "supersedes": old_id},
        ])

        current = store.list_facts("owner/repo")
        assert len(current) == 1
        assert current[0]["fact"] == "DB is Postgres 17"
        assert current[0]["supersedes_id"] == old_id


# ── consolidate_monthly ───────────────────────────────────────────────────────

class TestConsolidateMonthly:
    def test_returns_none_when_no_unconsolidated_runs(self, store):
        """consolidate_monthly returns None when there are no run-tier rows."""
        llm = MagicMock(return_value="summary text")
        result = store.consolidate_monthly("owner/repo", llm)
        assert result is None
        llm.assert_not_called()

    def test_returns_row_id_and_calls_llm(self, store):
        """consolidate_monthly calls llm_fn, saves snapshot, marks rows consolidated."""
        store.save("owner/repo", "run 1 summary", mode="feature")
        store.save("owner/repo", "run 2 summary", mode="bugfix")

        llm = MagicMock(return_value="monthly consolidated text")
        new_id = store.consolidate_monthly("owner/repo", llm)

        assert new_id is not None
        assert isinstance(new_id, int)
        llm.assert_called_once()
        prompt = llm.call_args[0][0]
        assert "run 1 summary" in prompt
        assert "run 2 summary" in prompt

    def test_marks_source_rows_as_consolidated(self, store):
        """After consolidate_monthly, source run rows are marked consolidated=1."""
        store.save("owner/repo", "run A", mode="feature")
        store.save("owner/repo", "run B", mode="feature")

        store.consolidate_monthly("owner/repo", MagicMock(return_value="consolidated"))

        rows = store._conn.execute(
            "SELECT consolidated FROM runs WHERE repo=? AND tier='run'",
            ("owner/repo",),
        ).fetchall()
        assert all(r[0] == 1 for r in rows)

    def test_monthly_snapshot_saved_with_correct_tier(self, store):
        """The monthly snapshot row has tier='monthly'."""
        store.save("owner/repo", "run A", mode="feature")
        new_id = store.consolidate_monthly("owner/repo", MagicMock(return_value="snap"))

        row = store._conn.execute(
            "SELECT tier FROM runs WHERE id=?", (new_id,)
        ).fetchone()
        assert row[0] == "monthly"

    def test_period_label_uses_provided_value(self, store):
        """period_label argument is stored when explicitly provided."""
        store.save("owner/repo", "run X", mode="feature")
        new_id = store.consolidate_monthly(
            "owner/repo", MagicMock(return_value="snap"), period_label="2026-05"
        )
        row = store._conn.execute(
            "SELECT period_label FROM runs WHERE id=?", (new_id,)
        ).fetchone()
        assert row[0] == "2026-05"

    def test_returns_none_when_all_runs_already_consolidated(self, store):
        """A second call to consolidate_monthly returns None (no double-consolidation)."""
        store.save("owner/repo", "run A", mode="feature")
        store.save("owner/repo", "run B", mode="feature")
        store.consolidate_monthly("owner/repo", MagicMock(return_value="first"))

        llm2 = MagicMock(return_value="second")
        result = store.consolidate_monthly("owner/repo", llm2)

        assert result is None
        llm2.assert_not_called()


# ── consolidate_quarterly ─────────────────────────────────────────────────────

class TestConsolidateQuarterly:
    def test_returns_none_when_no_monthly_rows(self, store):
        """consolidate_quarterly returns None when there are no monthly rows."""
        llm = MagicMock(return_value="quarterly")
        result = store.consolidate_quarterly("owner/repo", llm)
        assert result is None
        llm.assert_not_called()

    def test_returns_row_id_and_calls_llm(self, store):
        """consolidate_quarterly calls llm_fn and saves a quarterly snapshot."""
        store._conn.execute(
            "INSERT INTO runs (repo, summary, mode, tier, consolidated, created_at) VALUES (?,?,?,?,?,?)",
            ("owner/repo", "may monthly", "consolidation", "monthly", 0, "2026-05-01T12:00:00+00:00"),
        )
        store._conn.execute(
            "INSERT INTO runs (repo, summary, mode, tier, consolidated, created_at) VALUES (?,?,?,?,?,?)",
            ("owner/repo", "apr monthly", "consolidation", "monthly", 0, "2026-04-01T12:00:00+00:00"),
        )
        store._conn.commit()

        llm = MagicMock(return_value="Q2 quarterly snapshot")
        new_id = store.consolidate_quarterly("owner/repo", llm)

        assert new_id is not None
        llm.assert_called_once()
        prompt = llm.call_args[0][0]
        assert "may monthly" in prompt
        assert "apr monthly" in prompt

    def test_quarterly_snapshot_saved_with_correct_tier(self, store):
        """The quarterly row has tier='quarterly'."""
        store._conn.execute(
            "INSERT INTO runs (repo, summary, mode, tier, consolidated, created_at) VALUES (?,?,?,?,?,?)",
            ("owner/repo", "monthly snap", "consolidation", "monthly", 0, "2026-04-01T12:00:00+00:00"),
        )
        store._conn.commit()

        new_id = store.consolidate_quarterly("owner/repo", MagicMock(return_value="q"))
        row = store._conn.execute(
            "SELECT tier FROM runs WHERE id=?", (new_id,)
        ).fetchone()
        assert row[0] == "quarterly"

    def test_marks_source_rows_as_consolidated(self, store):
        """After consolidate_quarterly, source monthly rows are marked consolidated=1."""
        store._conn.execute(
            "INSERT INTO runs (repo, summary, mode, tier, consolidated, created_at) VALUES (?,?,?,?,?,?)",
            ("owner/repo", "monthly snap", "consolidation", "monthly", 0, "2026-04-01T12:00:00+00:00"),
        )
        store._conn.commit()

        store.consolidate_quarterly("owner/repo", MagicMock(return_value="q"))

        rows = store._conn.execute(
            "SELECT consolidated FROM runs WHERE repo=? AND tier='monthly'",
            ("owner/repo",),
        ).fetchall()
        assert all(r[0] == 1 for r in rows)


# ── recall ────────────────────────────────────────────────────────────────────

class TestRecall:
    def test_recall_returns_empty_string_when_no_runs(self, store):
        """recall() returns '' when there are no rows for the repo."""
        result = store.recall("owner/repo")
        assert result == ""

    def test_recall_includes_recent_runs(self, store):
        """recall() includes recent run-tier summaries."""
        store.save("owner/repo", "ran the feature pipeline", mode="feature")
        result = store.recall("owner/repo")
        assert "ran the feature pipeline" in result

    def test_recall_includes_quarterly_snapshot(self, store):
        """recall() includes quarterly snapshot when one exists."""
        store._conn.execute(
            "INSERT INTO runs (repo, summary, mode, tier, period_label, created_at) VALUES (?,?,?,?,?,?)",
            ("owner/repo", "Q1 summary text", "consolidation", "quarterly", "Q1-2026", "2026-03-31T12:00:00+00:00"),
        )
        store._conn.commit()

        result = store.recall("owner/repo")
        assert "Q1 summary text" in result
        assert "Quarterly snapshot" in result

    def test_recall_includes_monthly_snapshot(self, store):
        """recall() includes monthly snapshot when one exists."""
        store._conn.execute(
            "INSERT INTO runs (repo, summary, mode, tier, period_label, created_at) VALUES (?,?,?,?,?,?)",
            ("owner/repo", "May monthly summary", "consolidation", "monthly", "2026-05", "2026-05-31T12:00:00+00:00"),
        )
        store._conn.commit()

        result = store.recall("owner/repo")
        assert "May monthly summary" in result
        assert "Monthly snapshot" in result

    def test_recall_respects_recent_runs_limit(self, store):
        """recall() only shows the N most recent run-tier entries."""
        for i in range(5):
            store.save("owner/repo", f"run {i}", mode="feature")

        result = store.recall("owner/repo", recent_runs=2)
        assert "run 4" in result
        assert "run 3" in result
        assert "run 0" not in result

    def test_recall_includes_static_facts_unconditionally(self, store):
        """recall() always includes static facts, with no recency/relevance filter."""
        store.save_static("owner/repo", "Target DB is Postgres 16 + PostGIS", key="tech-stack")
        result = store.recall("owner/repo")
        assert "Target DB is Postgres 16 + PostGIS" in result
        assert "Static facts" in result

    def test_recall_lists_static_facts_before_dynamic_history(self, store):
        """Static facts appear before the quarterly/monthly/recent-run sections."""
        store.save_static("owner/repo", "Always use HK Cantonese terminology", key="tone")
        store.save("owner/repo", "shipped the feature", mode="feature")

        result = store.recall("owner/repo")
        assert result.index("Static facts") < result.index("Recent runs")

    def test_recall_includes_unresolved_issue_facts(self, store):
        """recall() surfaces open issue-type facts under their own section."""
        store.save_fact("owner/repo", "403 errors from dedup", fact_type="issue",
                         entity="RSS watcher", resolved=False)
        result = store.recall("owner/repo")
        assert "403 errors from dedup" in result
        assert "Known open issues" in result

    def test_recall_excludes_resolved_issue_facts(self, store):
        """A resolved issue fact must not appear in the open-issues section."""
        store.save_fact("owner/repo", "an already-fixed bug", fact_type="issue", resolved=True)
        result = store.recall("owner/repo")
        assert "an already-fixed bug" not in result

    def test_recall_excludes_non_issue_facts_from_open_issues_section(self, store):
        """Decision/status/learning facts don't clutter the open-issues section."""
        store.save_fact("owner/repo", "a routine status update", fact_type="status")
        result = store.recall("owner/repo")
        assert "Known open issues" not in result

    def test_recall_orders_open_issues_before_dynamic_history(self, store):
        store.save_fact("owner/repo", "an open issue", fact_type="issue", resolved=False)
        store.save("owner/repo", "shipped the feature", mode="feature")

        result = store.recall("owner/repo")
        assert result.index("Known open issues") < result.index("Recent runs")


# ── recall_issues ─────────────────────────────────────────────────────────────

class TestRecallIssues:
    def test_returns_empty_when_no_tagged_entries(self, store):
        """recall_issues() returns '' when no entries have 'issue' tag and no fact rows exist."""
        store.save("owner/repo", "clean run", mode="feature")
        result = store.recall_issues("owner/repo")
        assert result == ""

    def test_returns_tagged_issues(self, store):
        """recall_issues() falls back to the tag-based convention when no fact rows exist."""
        store.save("owner/repo", "flaky auth bug", mode="feature", tags=["issue", "auth"])
        result = store.recall_issues("owner/repo")
        assert "flaky auth bug" in result
        assert "Known issues" in result

    def test_prefers_atomic_issue_facts_over_tag_based_entries(self, store):
        """When fact-tier issue rows exist, they're used instead of the tag-based fallback."""
        store.save("owner/repo", "an old tag-based issue mention", mode="feature", tags=["issue"])
        store.save_fact("owner/repo", "a precise atomic issue", fact_type="issue",
                         entity="RSS watcher", resolved=False)

        result = store.recall_issues("owner/repo")
        assert "a precise atomic issue" in result
        assert "an old tag-based issue mention" not in result

    def test_excludes_resolved_atomic_issues(self, store):
        store.save_fact("owner/repo", "a fixed issue", fact_type="issue", resolved=True)
        result = store.recall_issues("owner/repo")
        assert result == ""


# ── search ───────────────────────────────────────────────────────────────────

class TestSearch:
    def test_returns_empty_for_empty_keywords(self, store):
        """search() returns '' immediately when keywords list is empty."""
        store.save("owner/repo", "something", mode="feature")
        result = store.search("owner/repo", [])
        assert result == ""

    def test_finds_entry_by_keyword(self, store):
        """search() returns entries whose summary matches a keyword."""
        store.save("owner/repo", "JWT token expiry bug fixed", mode="bugfix")
        store.save("owner/repo", "added pagination to list endpoint", mode="feature")

        result = store.search("owner/repo", ["JWT"])
        assert "JWT token expiry bug fixed" in result
        assert "pagination" not in result

    def test_returns_empty_when_no_match(self, store):
        """search() returns '' when no entries match the keywords."""
        store.save("owner/repo", "pagination feature added", mode="feature")
        result = store.search("owner/repo", ["authentication"])
        assert result == ""


# ── unindexed / mark_indexed ─────────────────────────────────────────────────
# Feeds rag-mcp/indexer.py's search_memory (pgvector) indexing.

class TestUnindexed:
    def test_new_rows_are_unindexed_by_default(self, store):
        """A freshly saved row has indexed=0 and shows up in unindexed()."""
        store.save("owner/repo", "did a thing", mode="feature")
        rows = store.unindexed()
        assert len(rows) == 1
        assert rows[0]["repo"] == "owner/repo"
        assert rows[0]["summary"] == "did a thing"

    def test_excludes_rows_with_empty_summary(self, store):
        """A row with no summary yet is never returned — nothing to embed."""
        store.save("owner/repo", "", mode="feature")
        assert store.unindexed() == []

    def test_respects_limit(self, store):
        """unindexed(limit=N) caps the number of rows returned."""
        for i in range(5):
            store.save("owner/repo", f"run {i}", mode="feature")
        assert len(store.unindexed(limit=2)) == 2

    def test_orders_oldest_first(self, store):
        """unindexed() returns rows in ascending id order (FIFO for the indexer)."""
        store.save("owner/repo", "first", mode="feature")
        store.save("owner/repo", "second", mode="feature")
        rows = store.unindexed()
        assert [r["summary"] for r in rows] == ["first", "second"]


class TestMarkIndexed:
    def test_marks_rows_no_longer_unindexed(self, store):
        """mark_indexed() removes the given ids from future unindexed() results."""
        store.save("owner/repo", "run 1", mode="feature")
        store.save("owner/repo", "run 2", mode="feature")
        rows = store.unindexed()

        store.mark_indexed([rows[0]["id"]])

        remaining = store.unindexed()
        assert len(remaining) == 1
        assert remaining[0]["summary"] == "run 2"

    def test_empty_list_is_a_noop(self, store):
        """mark_indexed([]) does nothing and does not raise."""
        store.save("owner/repo", "run 1", mode="feature")
        store.mark_indexed([])
        assert len(store.unindexed()) == 1
