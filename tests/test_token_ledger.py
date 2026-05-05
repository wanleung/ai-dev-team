"""Tests for TokenLedger — token usage tracking and cost calculation."""
from __future__ import annotations
import pytest
from agents.token_ledger import TokenLedger, UsageRecord


PRICING = {
    "gpt-4.1":      [2.00, 8.00],
    "qwen3.6-plus": [0.50, 1.50],
    "thinker":      [0.00, 0.00],
    "default":      [2.00, 8.00],
}


def test_record_calculates_cost():
    ledger = TokenLedger(pricing=PRICING)
    ledger.start_run("run-1", "MyProject", "org/repo")
    ledger.record("run-1", "pm", "gpt-4.1", prompt_tokens=1000, completion_tokens=500)
    summary = ledger.summary("run-1")
    # cost = (1000 * 2.00 + 500 * 8.00) / 1_000_000 = 0.006
    assert abs(summary["total_cost_usd"] - 0.006) < 1e-9


def test_record_free_model():
    ledger = TokenLedger(pricing=PRICING)
    ledger.start_run("run-2", "Proj", "org/repo")
    ledger.record("run-2", "architect", "thinker", prompt_tokens=5000, completion_tokens=2000)
    summary = ledger.summary("run-2")
    assert summary["total_cost_usd"] == 0.0


def test_record_unlisted_model_uses_default():
    ledger = TokenLedger(pricing=PRICING)
    ledger.start_run("run-3", "Proj", "org/repo")
    ledger.record("run-3", "pm", "unknown-model-xyz", prompt_tokens=1000, completion_tokens=0)
    summary = ledger.summary("run-3")
    # default input price = 2.00 per 1M
    assert abs(summary["total_cost_usd"] - 0.002) < 1e-9


def test_summary_per_stage_and_model():
    ledger = TokenLedger(pricing=PRICING)
    ledger.start_run("run-4", "Proj", "org/repo")
    ledger.record("run-4", "pm", "gpt-4.1", 1000, 200)
    ledger.record("run-4", "architect", "qwen3.6-plus", 3000, 800)
    ledger.record("run-4", "pm", "gpt-4.1", 500, 100)  # second call in same stage
    summary = ledger.summary("run-4")
    assert len(summary["by_stage"]) == 2
    pm_stage = next(s for s in summary["by_stage"] if s["stage"] == "pm")
    assert pm_stage["prompt_tokens"] == 1500
    arch_stage = next(s for s in summary["by_stage"] if s["stage"] == "architect")
    assert arch_stage["completion_tokens"] == 800
    assert len(summary["by_model"]) == 2


def test_format_github_comment_contains_total():
    ledger = TokenLedger(pricing=PRICING)
    ledger.start_run("run-5", "My CMS", "org/repo")
    ledger.record("run-5", "pm", "gpt-4.1", 1000, 500)
    ledger.finish_run("run-5")
    comment = ledger.format_github_comment("run-5")
    assert "Total" in comment
    assert "My CMS" in comment
    assert "gpt-4.1" in comment


def test_flush_to_db_creates_rows(tmp_path):
    db_path = str(tmp_path / "usage.db")
    ledger = TokenLedger(pricing=PRICING)
    ledger.start_run("run-6", "Proj", "org/repo")
    ledger.record("run-6", "pm", "gpt-4.1", 100, 50)
    ledger.finish_run("run-6")
    ledger.flush_to_db(db_path)

    import sqlite3
    conn = sqlite3.connect(db_path)
    runs = conn.execute("SELECT * FROM runs WHERE run_id='run-6'").fetchall()
    events = conn.execute("SELECT * FROM usage_events WHERE run_id='run-6'").fetchall()
    conn.close()
    assert len(runs) == 1
    assert len(events) == 1


def test_flush_to_db_idempotent(tmp_path):
    """Calling flush_to_db twice must not duplicate event rows."""
    import sqlite3

    db_path = str(tmp_path / "usage.db")
    ledger = TokenLedger(pricing=PRICING)
    ledger.start_run("run-7", "Proj", "org/repo")
    ledger.record("run-7", "pm", "gpt-4.1", 100, 50)
    ledger.record("run-7", "architect", "qwen3.6-plus", 200, 80)
    ledger.finish_run("run-7")

    # Flush twice — second flush must be a no-op for event rows
    ledger.flush_to_db(db_path)
    ledger.flush_to_db(db_path)

    conn = sqlite3.connect(db_path)
    count = conn.execute(
        "SELECT COUNT(*) FROM usage_events WHERE run_id='run-7'"
    ).fetchone()[0]
    conn.close()

    # There are exactly 2 recorded events; double-flush must not produce 4
    assert count == 2, f"Expected 2 event rows after double flush, got {count}"


def test_estimate_tokens_returns_int():
    from agents.token_ledger import estimate_tokens
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What is 2+2?"},
    ]
    reply = "4"
    prompt_est, completion_est = estimate_tokens(messages, reply)
    assert isinstance(prompt_est, int)
    assert isinstance(completion_est, int)
    assert prompt_est > 0
    assert completion_est == 1  # "4" is one token
