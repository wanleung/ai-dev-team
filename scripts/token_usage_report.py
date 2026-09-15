#!/usr/bin/env python3
"""Report token usage from token_usage.db."""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Any


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(row[1] == column for row in conn.execute(f"PRAGMA table_info({table})"))


def daily_issue_rows(db_path: str, repo: str = "", day: str = "") -> list[dict[str, Any]]:
    """Return usage rows grouped by issue/job for an optional UTC day."""
    with sqlite3.connect(db_path) as conn:
        issue_expr = "issue_number" if _has_column(conn, "runs", "issue_number") else "NULL"
        issue_url_expr = "issue_url" if _has_column(conn, "runs", "issue_url") else "''"
        label_expr = "pipeline_label" if _has_column(conn, "runs", "pipeline_label") else "''"
        job_expr = "job_type" if _has_column(conn, "runs", "job_type") else "''"
        pr_url_expr = "pr_url" if _has_column(conn, "runs", "pr_url") else "''"
        where = []
        params: list[Any] = []
        if repo:
            where.append("github_repo = ?")
            params.append(repo)
        if day:
            where.append("substr(started_at, 1, 10) = ?")
            params.append(day)
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        rows = conn.execute(
            f"""
            SELECT
                {issue_expr} AS issue_number,
                github_repo,
                COALESCE({label_expr}, '') AS pipeline_label,
                COALESCE({job_expr}, '') AS job_type,
                COUNT(*) AS runs,
                COALESCE(SUM(total_prompt_tokens), 0) AS input_tokens,
                COALESCE(SUM(total_completion_tokens), 0) AS output_tokens,
                COALESCE(SUM(total_cost_usd), 0.0) AS cost_usd,
                COALESCE(MAX({issue_url_expr}), '') AS issue_url,
                COALESCE(MAX({pr_url_expr}), '') AS pr_url
            FROM runs
            {where_sql}
            GROUP BY issue_number, github_repo, pipeline_label, job_type
            ORDER BY cost_usd DESC, runs DESC, issue_number
            """,
            params,
        ).fetchall()

    keys = [
        "issue_number", "github_repo", "pipeline_label", "job_type", "runs",
        "input_tokens", "output_tokens", "cost_usd", "issue_url", "pr_url",
    ]
    return [dict(zip(keys, row)) for row in rows]


def _fmt_int(value: int | None) -> str:
    return f"{int(value or 0):,}"


def _print_rows(rows: list[dict[str, Any]]) -> None:
    headers = ["Issue", "Repo", "Label", "Job", "Runs", "Input", "Output", "Cost"]
    print("\t".join(headers))
    total_in = total_out = 0
    total_cost = 0.0
    for row in rows:
        issue = f"#{row['issue_number']}" if row["issue_number"] is not None else "-"
        total_in += int(row["input_tokens"] or 0)
        total_out += int(row["output_tokens"] or 0)
        total_cost += float(row["cost_usd"] or 0.0)
        print("\t".join([
            issue,
            row["github_repo"],
            row["pipeline_label"],
            row["job_type"],
            str(row["runs"]),
            _fmt_int(row["input_tokens"]),
            _fmt_int(row["output_tokens"]),
            f"${float(row['cost_usd'] or 0.0):.6f}",
        ]))
    print("\t".join(["TOTAL", "", "", "", str(sum(int(r["runs"]) for r in rows)), _fmt_int(total_in), _fmt_int(total_out), f"${total_cost:.6f}"]))


def main() -> None:
    parser = argparse.ArgumentParser(description="Report token usage by repo/date/ticket")
    parser.add_argument("--db", default="token_usage.db", help="Path to token_usage.db")
    parser.add_argument("--repo", default="", help="Filter by GitHub repo, e.g. wanleung/ai-it-press")
    parser.add_argument("--date", default="", help="Filter by UTC date, YYYY-MM-DD")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.is_file():
        raise SystemExit(f"token usage DB not found: {db_path}")
    _print_rows(daily_issue_rows(str(db_path), repo=args.repo, day=args.date))


if __name__ == "__main__":
    main()
