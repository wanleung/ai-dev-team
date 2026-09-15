"""Tests for token usage report CLI helpers."""
from __future__ import annotations

import sqlite3


def test_daily_issue_report_groups_by_ticket(tmp_path):
    from scripts.token_usage_report import daily_issue_rows

    db_path = tmp_path / "usage.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE runs (
            run_id TEXT PRIMARY KEY,
            project_name TEXT,
            github_repo TEXT,
            started_at TEXT,
            finished_at TEXT,
            total_prompt_tokens INTEGER,
            total_completion_tokens INTEGER,
            total_cost_usd REAL,
            issue_number INTEGER,
            issue_url TEXT,
            pipeline_label TEXT,
            job_type TEXT,
            pr_url TEXT
        );
        """
    )
    conn.executemany(
        """INSERT INTO runs VALUES
           (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                "r1", "Article A", "wanleung/ai-it-press",
                "2026-09-13T01:00:00+00:00", "2026-09-13T01:10:00+00:00",
                100, 50, 0.01, 10, "issue-url-10", "news-article", "pipeline", "pr-url-10",
            ),
            (
                "r2", "Article A retry", "wanleung/ai-it-press",
                "2026-09-13T02:00:00+00:00", "2026-09-13T02:10:00+00:00",
                200, 80, 0.02, 10, "issue-url-10", "news-article", "pipeline", "pr-url-10",
            ),
            (
                "r3", "Intake", "wanleung/ai-it-press",
                "2026-09-13T03:00:00+00:00", "2026-09-13T03:10:00+00:00",
                300, 90, 0.03, None, "", "intake-triage", "intake_triage", "",
            ),
            (
                "r4", "Other", "wanleung/ai-it-press",
                "2026-09-14T01:00:00+00:00", "2026-09-14T01:10:00+00:00",
                999, 999, 9.99, 11, "issue-url-11", "news-article", "pipeline", "",
            ),
        ],
    )
    conn.commit()
    conn.close()

    rows = daily_issue_rows(str(db_path), repo="wanleung/ai-it-press", day="2026-09-13")

    assert rows == [
        {
            "issue_number": 10,
            "github_repo": "wanleung/ai-it-press",
            "pipeline_label": "news-article",
            "job_type": "pipeline",
            "runs": 2,
            "input_tokens": 300,
            "output_tokens": 130,
            "cost_usd": 0.03,
            "issue_url": "issue-url-10",
            "pr_url": "pr-url-10",
        },
        {
            "issue_number": None,
            "github_repo": "wanleung/ai-it-press",
            "pipeline_label": "intake-triage",
            "job_type": "intake_triage",
            "runs": 1,
            "input_tokens": 300,
            "output_tokens": 90,
            "cost_usd": 0.03,
            "issue_url": "",
            "pr_url": "",
        },
    ]
