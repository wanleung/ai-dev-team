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


# ── Budget enforcement tests (T2-C Task 2) ────────────────────────────────

def test_budget_exceeded_raises():
    from agents.token_ledger import BudgetExceededError
    # 1000 input tokens @ $2/M = $0.002; budget is $0.001
    ledger = TokenLedger(pricing=PRICING, max_cost_usd=0.001)
    ledger.start_run("budget-1", "Proj", "org/repo")
    with pytest.raises(BudgetExceededError, match="budget"):
        ledger.record("budget-1", "pm", "gpt-4.1", prompt_tokens=1000, completion_tokens=0)


def test_budget_not_exceeded_passes():
    from agents.token_ledger import BudgetExceededError
    ledger = TokenLedger(pricing=PRICING, max_cost_usd=1.00)
    ledger.start_run("budget-2", "Proj", "org/repo")
    # cost ~ $0.006 — well under $1.00
    ledger.record("budget-2", "pm", "gpt-4.1", prompt_tokens=1000, completion_tokens=500)
    # No exception raised


def test_no_budget_limit_never_raises():
    """TokenLedger with no max_cost_usd should never raise BudgetExceededError."""
    from agents.token_ledger import BudgetExceededError
    ledger = TokenLedger(pricing=PRICING)  # max_cost_usd=None
    ledger.start_run("budget-3", "Proj", "org/repo")
    # Very expensive call — should not raise
    ledger.record("budget-3", "pm", "gpt-4.1", prompt_tokens=10_000_000, completion_tokens=10_000_000)


# ── Model-aware token estimation tests (T4-B Task 1) ─────────────────────────

def test_openai_model_uses_tiktoken():
    """GPT model should use tiktoken encoding, not char-based estimation."""
    tiktoken = pytest.importorskip("tiktoken", reason="tiktoken not installed")
    from agents.token_ledger import estimate_tokens
    # Use repeated text so tiktoken and chars//4 reliably diverge:
    # "The quick brown fox..." ×4 = ~180 chars → chars//4=45, tiktoken≈40
    text = "The quick brown fox jumps over the lazy dog. " * 4
    messages = [{"role": "user", "content": text}]
    tiktoken_count, _ = estimate_tokens(messages, "", model="gpt-4")
    char_estimate = len(text) // 4
    # tiktoken gives lower counts than chars // 4 for common English words
    assert tiktoken_count != char_estimate, (
        f"OpenAI path should use tiktoken, not char-based estimation "
        f"(tiktoken={tiktoken_count}, chars//4={char_estimate})"
    )
    assert tiktoken_count > 0


def test_claude_model_uses_char_estimate():
    """Claude model should use char-based estimation (~3.5 chars/token)."""
    from agents.token_ledger import estimate_tokens
    messages = [{"role": "user", "content": "A" * 350}]  # 350 chars → ~100 tokens
    prompt_tok, _ = estimate_tokens(messages, "", model="claude-3-opus")
    # char // 3.5 ≈ 100; tiktoken would give ~88
    assert 90 <= prompt_tok <= 110


def test_gemini_model_uses_char_estimate():
    """Gemini model should use char-based estimation (~4 chars/token)."""
    from agents.token_ledger import estimate_tokens
    messages = [{"role": "user", "content": "B" * 400}]  # 400 chars → ~100 tokens
    prompt_tok, _ = estimate_tokens(messages, "", model="gemini-pro")
    assert 90 <= prompt_tok <= 110


def test_unknown_model_uses_char_fallback():
    """Unknown/Ollama model should use safe char-based fallback."""
    from agents.token_ledger import estimate_tokens
    messages = [{"role": "user", "content": "C" * 400}]
    prompt_tok, _ = estimate_tokens(messages, "", model="llama3:70b")
    # char // 4 = 100
    assert 90 <= prompt_tok <= 110


def test_no_model_arg_still_works():
    """Calling estimate_tokens without model arg must still return counts (backward compat)."""
    from agents.token_ledger import estimate_tokens
    messages = [{"role": "user", "content": "Hello"}]
    prompt_tok, comp_tok = estimate_tokens(messages, "Hi")
    assert prompt_tok >= 0 and comp_tok >= 0


# ── Short-string token estimation fix (T3-C Task 3) ──────────────────────────

@pytest.mark.parametrize("text,model", [
    ("4", "claude-3-sonnet"),       # 1 char, Claude path: round(1/3.5) = 0 → fixed to 1
    ("hi", "gemini-pro"),           # 2 chars, Gemini path: round(0.5)→0 (banker's rounding), max(1,0)→1
    ("x", "llama3"),                # 1 char, fallback path: round(1/4) = 0 → fixed to 1
    ("abc", "gemini-flash"),        # 3 chars, Gemini path: round(3/4) = 1
    ("ok", "gpt-4"),                # 2 chars, OpenAI tiktoken path (if available, else char-based)
])
def test_estimate_tokens_short_string_returns_at_least_one(text, model):
    """Non-empty short strings must yield >= 1 token. Guards against int() floor returning 0."""
    from agents.token_ledger import estimate_tokens
    prompt_est, completion_est = estimate_tokens(
        [{"role": "user", "content": text}], text, model=model
    )
    assert prompt_est >= 1, f"prompt_est={prompt_est} for text={text!r} model={model}"
    assert completion_est >= 1, f"completion_est={completion_est} for text={text!r} model={model}"


def test_estimate_tokens_empty_string_returns_zero():
    """Empty string must yield 0 tokens (no content = no cost)."""
    from agents.token_ledger import estimate_tokens
    prompt_est, completion_est = estimate_tokens(
        [{"role": "user", "content": ""}], "", model="gemini-pro"
    )
    assert prompt_est == 0
    assert completion_est == 0


def test_estimate_tokens_multiple_empty_messages_returns_zero():
    """Two empty-content messages joined by space must not count as 1 token."""
    from agents.token_ledger import estimate_tokens
    prompt_est, completion_est = estimate_tokens(
        [{"role": "user", "content": ""}, {"role": "assistant", "content": ""}],
        "", model="gemini-pro"
    )
    assert prompt_est == 0
    assert completion_est == 0


def test_estimate_tokens_whitespace_only_returns_zero():
    """Whitespace-only strings are treated as empty — no meaningful content, no tokens."""
    from agents.token_ledger import estimate_tokens
    prompt_est, completion_est = estimate_tokens(
        [{"role": "user", "content": " "}], " ", model="claude-3-haiku"
    )
    assert prompt_est == 0
    assert completion_est == 0


_ISOLATION_CUSTOM_LEDGER: object = None


def test_ledger_isolation_first():
    """Set a custom ledger — should not bleed into the next test."""
    global _ISOLATION_CUSTOM_LEDGER
    from agents.token_ledger import set_ledger, get_ledger, TokenLedger
    _ISOLATION_CUSTOM_LEDGER = TokenLedger(max_cost_usd=999.0)
    set_ledger(_ISOLATION_CUSTOM_LEDGER)
    assert get_ledger() is _ISOLATION_CUSTOM_LEDGER


def test_ledger_isolation_second():
    """Ledger must be a fresh instance, not the one set in test_ledger_isolation_first."""
    from agents.token_ledger import get_ledger
    assert get_ledger() is not _ISOLATION_CUSTOM_LEDGER, (
        "Global ledger leaked from test_ledger_isolation_first — autouse fixture not working"
    )
