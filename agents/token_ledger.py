"""Token usage tracking and cost accounting for pipeline runs."""
from __future__ import annotations

import sqlite3
import threading
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

# ContextVar that backends read to tag records with the current stage name.
# Set by Orchestrator._run_stage() before calling each stage fn.
current_stage: ContextVar[str] = ContextVar("current_stage", default="unknown")


class BudgetExceededError(Exception):
    """Raised by TokenLedger.record() when the run's cost exceeds max_cost_usd."""


@dataclass
class UsageRecord:
    run_id: str
    stage: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class TokenLedger:
    """Accumulates LLM token usage across a pipeline run."""

    def __init__(self, pricing: dict[str, list[float]] | None = None, max_cost_usd: float | None = None) -> None:
        self._lock: threading.Lock = threading.Lock()
        # pricing: model_name -> [input_price_per_1M, output_price_per_1M]
        self._pricing: dict[str, list[float]] = pricing or {}
        self._max_cost_usd: float | None = max_cost_usd
        self._runs: dict[str, dict] = {}          # run_id -> metadata
        self._events: dict[str, list[UsageRecord]] = {}  # run_id -> events
        self._totals: dict[str, float] = {}       # run_id -> running cost total

    # ── Public API ─────────────────────────────────────────────────────────

    def start_run(self, run_id: str, project_name: str, repo: str) -> None:
        """Register a new pipeline run and prepare it for recording."""
        with self._lock:
            self._runs[run_id] = {
                "run_id": run_id,
                "project_name": project_name,
                "repo": repo,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "finished_at": None,
            }
            self._events[run_id] = []
            self._totals[run_id] = 0.0

    def record(
        self,
        run_id: str,
        stage: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        """Record a single LLM call's token usage for the given run and stage."""
        with self._lock:
            if run_id not in self._runs:
                return  # tracking disabled or run not started
            cost = self._calculate_cost(model, prompt_tokens, completion_tokens)
            self._events[run_id].append(
                UsageRecord(
                    run_id=run_id,
                    stage=stage,
                    model=model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cost_usd=cost,
                )
            )
            self._totals[run_id] = self._totals.get(run_id, 0.0) + cost
            if self._max_cost_usd is not None:
                total = self._totals[run_id]
                if total > self._max_cost_usd:
                    raise BudgetExceededError(
                        f"Pipeline cost ${total:.4f} exceeds budget ${self._max_cost_usd:.4f}"
                    )

    def finish_run(self, run_id: str) -> None:
        """Mark a run as finished by recording its completion timestamp."""
        with self._lock:
            if run_id in self._runs:
                self._runs[run_id]["finished_at"] = datetime.now(timezone.utc).isoformat()

    def active_run_id(self) -> str | None:
        """Return the most recently started unfinished run_id, or None.

        Iterates a snapshot of ``self._runs`` under the lock to avoid
        ``RuntimeError: dictionary changed size during iteration`` in threaded
        contexts where other methods may mutate ``_runs`` concurrently.
        """
        with self._lock:
            items = list(self._runs.items())
        for run_id, meta in reversed(items):
            if meta.get("finished_at") is None:
                return run_id
        return None

    def summary(self, run_id: str) -> dict:
        """Return a summary dict with totals, per-stage, and per-model breakdowns."""
        with self._lock:
            events = list(self._events.get(run_id, []))
            run_meta = dict(self._runs.get(run_id, {}))
        total_prompt = sum(e.prompt_tokens for e in events)
        total_completion = sum(e.completion_tokens for e in events)
        total_cost = sum(e.cost_usd for e in events)

        # Aggregate by stage
        by_stage: dict[str, dict] = {}
        for e in events:
            s = by_stage.setdefault(
                e.stage,
                {
                    "stage": e.stage,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "cost_usd": 0.0,
                    "models": set(),
                },
            )
            s["prompt_tokens"] += e.prompt_tokens
            s["completion_tokens"] += e.completion_tokens
            s["cost_usd"] += e.cost_usd
            s["models"].add(e.model)
        for s in by_stage.values():
            s["models"] = sorted(s["models"])

        # Aggregate by model
        by_model: dict[str, dict] = {}
        for e in events:
            m = by_model.setdefault(
                e.model,
                {"model": e.model, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0},
            )
            m["prompt_tokens"] += e.prompt_tokens
            m["completion_tokens"] += e.completion_tokens
            m["cost_usd"] += e.cost_usd

        return {
            "run_id": run_id,
            "project_name": run_meta.get("project_name", ""),
            "total_events": len(events),
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
            "total_cost_usd": total_cost,
            "by_stage": list(by_stage.values()),
            "by_model": list(by_model.values()),
        }

    def format_github_comment(self, run_id: str) -> str:
        """Format a Markdown table suitable for posting as a GitHub PR comment."""
        s = self.summary(run_id)
        project = s["project_name"] or run_id
        lines = [f"## 💰 Token Usage — {project}", ""]
        lines.append("| Stage | Model | In (tokens) | Out (tokens) | Cost (USD) |")
        lines.append("|-------|-------|-------------|--------------|------------|")
        for row in s["by_stage"]:
            model_str = ", ".join(row["models"]) if row["models"] else "—"
            lines.append(
                f"| {row['stage']} | {model_str} "
                f"| {row['prompt_tokens']:,} | {row['completion_tokens']:,} "
                f"| ${row['cost_usd']:.4f} |"
            )
        lines.append(
            f"| **Total** | | **{s['total_prompt_tokens']:,}** "
            f"| **{s['total_completion_tokens']:,}** "
            f"| **${s['total_cost_usd']:.4f}** |"
        )
        lines.append("")
        lines.append(f"_Tracked by AI Software House · Run ID: `{run_id}`_")
        return "\n".join(lines)

    def flush_to_db(self, db_path: str) -> None:
        """Persist all run metadata and usage events to a SQLite database.

        Idempotent: calling flush_to_db multiple times will not duplicate rows.
        Each event is identified by a stable event_id and inserted with
        INSERT OR IGNORE so re-flushing is safe.
        """
        with sqlite3.connect(db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    project_name TEXT,
                    github_repo TEXT,
                    started_at TEXT,
                    finished_at TEXT,
                    total_prompt_tokens INTEGER,
                    total_completion_tokens INTEGER,
                    total_cost_usd REAL
                );
                CREATE TABLE IF NOT EXISTS usage_events (
                    event_id TEXT PRIMARY KEY,
                    run_id TEXT,
                    stage TEXT,
                    model TEXT,
                    prompt_tokens INTEGER,
                    completion_tokens INTEGER,
                    cost_usd REAL,
                    timestamp TEXT
                );
            """)
            for run_id, meta in self._runs.items():
                s = self.summary(run_id)
                conn.execute(
                    """INSERT OR REPLACE INTO runs
                       (run_id, project_name, github_repo, started_at, finished_at,
                        total_prompt_tokens, total_completion_tokens, total_cost_usd)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        run_id,
                        meta["project_name"],
                        meta["repo"],
                        meta["started_at"],
                        meta["finished_at"],
                        s["total_prompt_tokens"],
                        s["total_completion_tokens"],
                        s["total_cost_usd"],
                    ),
                )
                for e in self._events.get(run_id, []):
                    ts = e.timestamp.isoformat()
                    event_id = f"{e.run_id}:{e.stage}:{e.model}:{ts}"
                    conn.execute(
                        """INSERT OR IGNORE INTO usage_events
                           (event_id, run_id, stage, model, prompt_tokens,
                            completion_tokens, cost_usd, timestamp)
                           VALUES (?,?,?,?,?,?,?,?)""",
                        (
                            event_id,
                            e.run_id,
                            e.stage,
                            e.model,
                            e.prompt_tokens,
                            e.completion_tokens,
                            e.cost_usd,
                            ts,
                        ),
                    )

    # ── Internal ────────────────────────────────────────────────────────────

    def _calculate_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """Compute cost in USD using pricing table with exact, prefix, and default fallback."""
        # Try exact match, then longest-prefix match (e.g. "ollama/*"), then default
        prices = self._pricing.get(model) or next(
            (v for k, v in sorted(self._pricing.items(), key=lambda x: len(x[0]), reverse=True)
             if model.startswith(k[:-1] if k.endswith("*") else k)),
            None,
        ) or self._pricing.get("default")
        if not prices:
            return 0.0
        input_price, output_price = prices[0], prices[1]
        return (prompt_tokens * input_price + completion_tokens * output_price) / 1_000_000


def estimate_tokens(
    messages: list[dict],
    reply: str,
    model: str = "",
) -> tuple[int, int]:
    """Estimate prompt + completion token counts.

    Dispatches by model family:
    - OpenAI (gpt-*, text-*, o1*, o3*): uses tiktoken cl100k_base for precise counts
    - Anthropic (claude-*): char // 3.5 approximation (~3.5 chars/token)
    - Google (gemini-*): char // 4 approximation (~4 chars/token)
    - All others (Ollama, unknown): char // 4 safe fallback

    Used as a fallback when response.usage is not available (streaming calls).
    Returns (prompt_tokens, completion_tokens).

    Args:
        messages: List of message dicts with 'content' keys.
        reply: The completion text.
        model: Optional model identifier string for dispatch. Defaults to OpenAI
               tiktoken path when empty (backward compatible).
    """
    model_lower = model.lower()

    # OpenAI models (or no model specified): use tiktoken for precise counts
    if not model_lower or any(model_lower.startswith(p) for p in ("gpt-", "text-", "o1", "o3")):
        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            prompt_text = " ".join(
                m.get("content", "") or "" for m in messages if isinstance(m.get("content"), str)
            )
            return len(enc.encode(prompt_text)), len(enc.encode(reply))
        except Exception:
            pass  # fall through to char-based fallback

    # Extract prompt text for char-based estimation
    prompt_text = " ".join(
        m.get("content", "") or "" for m in messages if isinstance(m.get("content"), str)
    )

    # Anthropic Claude: ~3.5 chars per token
    if "claude" in model_lower:
        divisor = 3.5
    else:
        # Gemini, Ollama, and all other unknown models: ~4 chars per token (conservative)
        divisor = 4.0

    return (
        max(0, int(len(prompt_text) / divisor)),
        max(0, int(len(reply) / divisor)),
    )


# Global ledger instance — replaced by Orchestrator with a configured instance.
_ledger: TokenLedger = TokenLedger()
_ledger_lock: threading.Lock = threading.Lock()


def get_ledger() -> TokenLedger:
    """Return the global TokenLedger instance."""
    with _ledger_lock:
        return _ledger


def set_ledger(ledger: TokenLedger) -> None:
    """Replace the global TokenLedger instance (used by Orchestrator at startup)."""
    global _ledger
    with _ledger_lock:
        _ledger = ledger
