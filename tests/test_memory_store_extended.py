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
        ms.close()


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


# ── recall_issues ─────────────────────────────────────────────────────────────

class TestRecallIssues:
    def test_returns_empty_when_no_tagged_entries(self, store):
        """recall_issues() returns '' when no entries have 'issue' tag."""
        store.save("owner/repo", "clean run", mode="feature")
        result = store.recall_issues("owner/repo")
        assert result == ""

    def test_returns_tagged_issues(self, store):
        """recall_issues() returns entries that have 'issue' in their tags."""
        store.save("owner/repo", "flaky auth bug", mode="feature", tags=["issue", "auth"])
        result = store.recall_issues("owner/repo")
        assert "flaky auth bug" in result
        assert "Known issues" in result


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
