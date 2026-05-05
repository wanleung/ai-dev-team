# Token Counter & Cost Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Track LLM token usage and USD cost per pipeline run (by stage and model), persist to SQLite, and post a summary to the GitHub issue.

**Architecture:** A `TokenLedger` singleton in `agents/token_ledger.py` accumulates `UsageRecord` events emitted by the backend `call()` / `_stream_call()` methods. The orchestrator starts and finishes runs; backends emit records via a global ledger reference. A `contextvars.ContextVar` carries the current stage name so backends can self-report without explicit wiring.

**Tech Stack:** Python 3.11+, `sqlite3` (stdlib), `tiktoken` (new dep for streaming token estimation), `openai` response `.usage` for non-streaming exact counts, `rich` for terminal table already present.

**Branch:** `feature/token-counter` (create from master before starting)

**Venv:** `/home/wanleung/Projects/ai-software-house/venv` — activate with `source venv/bin/activate`

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `agents/token_ledger.py` | `UsageRecord`, `TokenLedger` class, pricing, SQLite flush, GitHub comment formatter |
| Modify | `agents/backends/base.py` | Emit usage after `call()`, `_stream_call()`, `call_with_tools()` |
| Modify | `agents/backends/ollama.py` | Emit usage after overridden `_stream_call()` |
| Modify | `orchestrator.py` | Load pricing config, set stage context var, call `start_run`/`finish_run`, add `total_cost_usd` to summary table |
| Modify | `config.yaml` | Add `cost_tracking:` section with defaults |
| Modify | `requirements.txt` | Add `tiktoken>=0.7.0` |
| Create | `tests/test_token_ledger.py` | Unit tests for `TokenLedger` |
| Create | `tests/test_token_backend_emission.py` | Tests for usage emission from backends |

---

## Task 1: Create `agents/token_ledger.py`

**Files:**
- Create: `agents/token_ledger.py`
- Test: `tests/test_token_ledger.py`

- [ ] **Step 1: Write failing tests first**

Create `tests/test_token_ledger.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/wanleung/Projects/ai-software-house && source venv/bin/activate
python -m pytest tests/test_token_ledger.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError: No module named 'agents.token_ledger'`

- [ ] **Step 3: Create `agents/token_ledger.py`**

```python
"""Token usage tracking and cost accounting for pipeline runs."""
from __future__ import annotations

import sqlite3
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

# ContextVar that backends read to tag records with the current stage name.
# Set by Orchestrator._run_stage() before calling each stage fn.
current_stage: ContextVar[str] = ContextVar("current_stage", default="unknown")


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

    def __init__(self, pricing: dict[str, list[float]] | None = None) -> None:
        # pricing: model_name -> [input_price_per_1M, output_price_per_1M]
        self._pricing: dict[str, list[float]] = pricing or {}
        self._runs: dict[str, dict] = {}          # run_id -> metadata
        self._events: dict[str, list[UsageRecord]] = {}  # run_id -> events

    # ── Public API ─────────────────────────────────────────────────────────

    def start_run(self, run_id: str, project_name: str, repo: str) -> None:
        self._runs[run_id] = {
            "run_id": run_id,
            "project_name": project_name,
            "repo": repo,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
        }
        self._events[run_id] = []

    def record(
        self,
        run_id: str,
        stage: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
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

    def finish_run(self, run_id: str) -> None:
        if run_id in self._runs:
            self._runs[run_id]["finished_at"] = datetime.now(timezone.utc).isoformat()

    def summary(self, run_id: str) -> dict:
        events = self._events.get(run_id, [])
        total_prompt = sum(e.prompt_tokens for e in events)
        total_completion = sum(e.completion_tokens for e in events)
        total_cost = sum(e.cost_usd for e in events)

        # Aggregate by stage
        by_stage: dict[str, dict] = {}
        for e in events:
            s = by_stage.setdefault(e.stage, {"stage": e.stage, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0, "models": set()})
            s["prompt_tokens"] += e.prompt_tokens
            s["completion_tokens"] += e.completion_tokens
            s["cost_usd"] += e.cost_usd
            s["models"].add(e.model)
        for s in by_stage.values():
            s["models"] = sorted(s["models"])

        # Aggregate by model
        by_model: dict[str, dict] = {}
        for e in events:
            m = by_model.setdefault(e.model, {"model": e.model, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0})
            m["prompt_tokens"] += e.prompt_tokens
            m["completion_tokens"] += e.completion_tokens
            m["cost_usd"] += e.cost_usd

        return {
            "run_id": run_id,
            "project_name": self._runs.get(run_id, {}).get("project_name", ""),
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
            "total_cost_usd": total_cost,
            "by_stage": list(by_stage.values()),
            "by_model": list(by_model.values()),
        }

    def format_github_comment(self, run_id: str) -> str:
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
        conn = sqlite3.connect(db_path)
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
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT REFERENCES runs(run_id),
                stage TEXT,
                model TEXT,
                prompt_tokens INTEGER,
                completion_tokens INTEGER,
                cost_usd REAL,
                ts TEXT
            );
        """)
        for run_id, meta in self._runs.items():
            s = self.summary(run_id)
            conn.execute(
                """INSERT OR REPLACE INTO runs
                   (run_id, project_name, github_repo, started_at, finished_at,
                    total_prompt_tokens, total_completion_tokens, total_cost_usd)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (run_id, meta["project_name"], meta["repo"],
                 meta["started_at"], meta["finished_at"],
                 s["total_prompt_tokens"], s["total_completion_tokens"], s["total_cost_usd"]),
            )
            for e in self._events.get(run_id, []):
                conn.execute(
                    """INSERT INTO usage_events
                       (run_id, stage, model, prompt_tokens, completion_tokens, cost_usd, ts)
                       VALUES (?,?,?,?,?,?,?)""",
                    (e.run_id, e.stage, e.model, e.prompt_tokens,
                     e.completion_tokens, e.cost_usd, e.timestamp.isoformat()),
                )
        conn.commit()
        conn.close()

    # ── Internal ────────────────────────────────────────────────────────────

    def _calculate_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        # Try exact match, then prefix match (e.g. "ollama/*"), then default
        prices = (
            self._pricing.get(model)
            or next((v for k, v in self._pricing.items() if model.startswith(k.rstrip("*").rstrip("/"))), None)
            or self._pricing.get("default")
        )
        if not prices:
            return 0.0
        input_price, output_price = prices[0], prices[1]
        return (prompt_tokens * input_price + completion_tokens * output_price) / 1_000_000


# Global ledger instance — replaced by Orchestrator with a configured instance.
_ledger: TokenLedger = TokenLedger()


def get_ledger() -> TokenLedger:
    return _ledger


def set_ledger(ledger: TokenLedger) -> None:
    global _ledger
    _ledger = ledger
```

- [ ] **Step 4: Run tests and verify they pass**

```bash
cd /home/wanleung/Projects/ai-software-house && source venv/bin/activate
python -m pytest tests/test_token_ledger.py -v
```
Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add agents/token_ledger.py tests/test_token_ledger.py
git commit -m "feat(tokens): add TokenLedger with pricing, SQLite flush, GitHub comment"
```

---

## Task 2: Install `tiktoken` and add to requirements

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add tiktoken to requirements.txt**

Open `requirements.txt` and add after the `openai` line:
```
tiktoken>=0.7.0
```

- [ ] **Step 2: Install it**

```bash
cd /home/wanleung/Projects/ai-software-house && source venv/bin/activate
pip install tiktoken>=0.7.0
```
Expected: `Successfully installed tiktoken-...`

- [ ] **Step 3: Verify import works**

```bash
python -c "import tiktoken; enc = tiktoken.get_encoding('cl100k_base'); print('ok', enc.encode('hello'))"
```
Expected: `ok [15339]` (or similar token ids)

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "chore: add tiktoken for streaming token estimation"
```

---

## Task 3: Add a shared token-estimation utility

**Files:**
- Modify: `agents/token_ledger.py` (add `estimate_tokens()` helper)
- Test: `tests/test_token_ledger.py` (add estimation test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_token_ledger.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_token_ledger.py::test_estimate_tokens_returns_int -v
```
Expected: `ImportError: cannot import name 'estimate_tokens'`

- [ ] **Step 3: Add `estimate_tokens` to `agents/token_ledger.py`**

Add this function at module level (before the `_ledger` global):

```python
def estimate_tokens(messages: list[dict], reply: str) -> tuple[int, int]:
    """Estimate prompt + completion token counts using tiktoken (cl100k_base).

    Used as a fallback when response.usage is not available (streaming calls).
    Returns (prompt_tokens, completion_tokens).
    """
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        prompt_text = " ".join(
            m.get("content", "") or "" for m in messages if isinstance(m.get("content"), str)
        )
        return len(enc.encode(prompt_text)), len(enc.encode(reply))
    except Exception:
        # Rough fallback if tiktoken is unavailable: ~4 chars per token
        prompt_text = " ".join(m.get("content", "") or "" for m in messages)
        return max(1, len(prompt_text) // 4), max(1, len(reply) // 4)
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_token_ledger.py -v
```
Expected: 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add agents/token_ledger.py tests/test_token_ledger.py
git commit -m "feat(tokens): add estimate_tokens() tiktoken helper for streaming fallback"
```

---

## Task 4: Emit usage from backends

**Files:**
- Modify: `agents/backends/base.py`
- Modify: `agents/backends/ollama.py`
- Create: `tests/test_token_backend_emission.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_token_backend_emission.py`:

```python
"""Tests that LLM backends emit token usage to the global TokenLedger."""
from __future__ import annotations
from unittest.mock import MagicMock, patch
import pytest
from agents.token_ledger import TokenLedger, set_ledger, get_ledger, current_stage


def _make_response(prompt_tokens: int, completion_tokens: int, content: str) -> MagicMock:
    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=content), finish_reason="stop")]
    resp.usage = usage
    return resp


def test_non_stream_call_emits_usage():
    from agents.backends.base import OpenAICompatibleBackend
    pricing = {"gpt-4.1": [2.00, 8.00], "default": [2.00, 8.00]}
    ledger = TokenLedger(pricing=pricing)
    ledger.start_run("r1", "P", "repo")
    set_ledger(ledger)

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _make_response(100, 50, "hello")
    backend = OpenAICompatibleBackend(model="gpt-4.1", client=mock_client, stream=False)

    token = current_stage.set("pm")
    try:
        result = backend.call([{"role": "user", "content": "hi"}], run_id="r1")
    finally:
        current_stage.reset(token)

    summary = ledger.summary("r1")
    assert summary["total_prompt_tokens"] == 100
    assert summary["total_completion_tokens"] == 50
    assert summary["total_cost_usd"] > 0


def test_stream_call_emits_estimated_usage():
    from agents.backends.base import OpenAICompatibleBackend
    pricing = {"gpt-4.1": [2.00, 8.00], "default": [2.00, 8.00]}
    ledger = TokenLedger(pricing=pricing)
    ledger.start_run("r2", "P", "repo")
    set_ledger(ledger)

    chunk = MagicMock(choices=[MagicMock(delta=MagicMock(content="hello world"))])
    empty_chunk = MagicMock(choices=[])
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = iter([chunk, empty_chunk])
    backend = OpenAICompatibleBackend(model="gpt-4.1", client=mock_client, stream=True)

    token = current_stage.set("architect")
    try:
        backend.call([{"role": "user", "content": "what is 2+2?"}], run_id="r2")
    finally:
        current_stage.reset(token)

    summary = ledger.summary("r2")
    assert summary["total_prompt_tokens"] > 0
    assert summary["total_completion_tokens"] > 0


def test_no_emission_without_run_id():
    """call() without run_id should not crash and should not add records."""
    from agents.backends.base import OpenAICompatibleBackend
    pricing = {"default": [2.00, 8.00]}
    ledger = TokenLedger(pricing=pricing)
    set_ledger(ledger)

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _make_response(10, 5, "hi")
    backend = OpenAICompatibleBackend(model="gpt-4.1", client=mock_client, stream=False)
    # no run_id passed — should not raise
    backend.call([{"role": "user", "content": "hi"}])
    # ledger has no runs registered, so no events
    assert ledger._events == {}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_token_backend_emission.py -v 2>&1 | head -20
```
Expected: `TypeError: call() got an unexpected keyword argument 'run_id'`

- [ ] **Step 3: Modify `agents/backends/base.py` to emit usage**

**3a.** Add import at the top of the file, after existing imports:

```python
from agents.token_ledger import current_stage, estimate_tokens, get_ledger
```

**3b.** Update `call()` to accept `run_id` and emit usage. Find the `call()` method and replace:

```python
def call(self, messages: list[dict]) -> str:
    self._pre_call()
    if self._stream:
        return self._stream_call(messages)
    if self._inter_call_delay > 0:
        time.sleep(self._inter_call_delay)
    response = _retry_with_backoff(
        lambda: self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.3,
            **self._extra_body(),
        ),
        max_retries=self._max_retries,
        base_delay=self._retry_delay,
    )
    return self._post_process(response.choices[0].message.content or "")
```

with:

```python
def call(self, messages: list[dict], run_id: str | None = None) -> str:
    self._pre_call()
    if self._stream:
        return self._stream_call(messages, run_id=run_id)
    if self._inter_call_delay > 0:
        time.sleep(self._inter_call_delay)
    response = _retry_with_backoff(
        lambda: self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.3,
            **self._extra_body(),
        ),
        max_retries=self._max_retries,
        base_delay=self._retry_delay,
    )
    content = response.choices[0].message.content or ""
    if run_id is not None:
        usage = getattr(response, "usage", None)
        if usage:
            get_ledger().record(run_id, current_stage.get(), self.model,
                                usage.prompt_tokens, usage.completion_tokens)
        else:
            pt, ct = estimate_tokens(messages, content)
            get_ledger().record(run_id, current_stage.get(), self.model, pt, ct)
    return self._post_process(content)
```

**3c.** Update `_stream_call()` to accept `run_id` and emit estimated usage. Replace the existing `_stream_call` signature and return statement:

```python
def _stream_call(self, messages: list[dict], run_id: str | None = None) -> str:
    """Collect a streaming response into a single string."""
    if self._inter_call_delay > 0:
        time.sleep(self._inter_call_delay)

    def _collect(stream) -> str:
        collected = ""
        for chunk in stream:
            if not chunk.choices:
                continue  # final usage/stop chunks have empty choices
            delta = chunk.choices[0].delta.content
            if delta:
                collected += delta
        return collected

    reply = _retry_with_backoff(
        lambda: _collect(
            self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.3,
                stream=True,
                **self._extra_body(),
            )
        ),
        max_retries=self._max_retries,
        base_delay=self._retry_delay,
    )
    if run_id is not None:
        pt, ct = estimate_tokens(messages, reply)
        get_ledger().record(run_id, current_stage.get(), self.model, pt, ct)
    return self._post_process(reply)
```

**3d.** Update `call_with_tools()` — find `return self._post_process(response.choices[0].message.content or "")` inside `call_with_tools` and add token recording. The `call_with_tools` signature should become:

```python
def call_with_tools(
    self,
    messages: list[dict],
    tools: "ToolRegistry",
    max_turns: int = 8,
    run_id: str | None = None,
) -> str:
```

And inside the loop, after each `response = _retry_with_backoff(...)` call in `call_with_tools`, add:

```python
if run_id is not None:
    usage = getattr(response, "usage", None)
    if usage:
        get_ledger().record(run_id, current_stage.get(), self.model,
                            usage.prompt_tokens, usage.completion_tokens)
```

- [ ] **Step 4: Modify `agents/backends/ollama.py` to pass `run_id` through**

In `OllamaBackend._stream_call`, update the signature to accept `run_id` and emit at the end. Find the existing overridden `_stream_call` in `ollama.py` and add `run_id: str | None = None` param, then at the end after `return self._post_process(...)`:

```python
def _stream_call(self, messages: list[dict], run_id: str | None = None) -> str:
    # ... existing implementation ...
    result = self._post_process(full_content)
    if run_id is not None:
        from agents.token_ledger import current_stage, estimate_tokens, get_ledger
        pt, ct = estimate_tokens(messages, full_content)
        get_ledger().record(run_id, current_stage.get(), self.model, pt, ct)
    return result
```

- [ ] **Step 5: Run backend emission tests**

```bash
python -m pytest tests/test_token_backend_emission.py tests/test_token_ledger.py tests/test_backends_base.py tests/test_backend_ollama.py -v
```
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add agents/backends/base.py agents/backends/ollama.py tests/test_token_backend_emission.py
git commit -m "feat(tokens): emit usage records from backend call() and _stream_call()"
```

---

## Task 5: Wire into Orchestrator

**Files:**
- Modify: `orchestrator.py`

- [ ] **Step 1: Add imports at the top of `orchestrator.py`**

Find the existing imports block and add:

```python
import uuid
from agents.token_ledger import TokenLedger, current_stage, get_ledger, set_ledger
```

- [ ] **Step 2: Add `cost_tracking` config loading in `Orchestrator.__init__`**

Add a new parameter after `progress_tracker_mode`:

```python
cost_tracking: dict | None = None,
```

And in `__init__` body after `self.tdd_commit_tests`:

```python
self._cost_tracking: dict = cost_tracking or {}
ct = self._cost_tracking
if ct.get("enabled", False):
    ledger = TokenLedger(pricing=ct.get("pricing", {}))
    set_ledger(ledger)
```

- [ ] **Step 3: Load `cost_tracking` config in `from_config()`**

Add to `from_config()` return statement (after `tdd_commit_tests`):

```python
cost_tracking=cfg.get("cost_tracking", {}),
```

- [ ] **Step 4: Set `run_id` and start run at top of `Orchestrator.run()`**

At the start of `run()`, after `start_time = time.time()`, add:

```python
run_id = str(uuid.uuid4())
result.run_id = run_id
ct = self._cost_tracking
if ct.get("enabled", False):
    active_repo = str(self.target_github.repo if self.target_github else
                      (self.github.repo if self.github else "local"))
    get_ledger().start_run(run_id, "", active_repo)  # project_name updated after PM stage
```

- [ ] **Step 5: Update project_name in ledger after PM stage sets it**

In `_finish()`, just before the summary table, add:

```python
ct = self._cost_tracking
if ct.get("enabled", False) and result.run_id:
    ledger = get_ledger()
    # Update project name now that it's known
    if result.run_id in ledger._runs:
        ledger._runs[result.run_id]["project_name"] = result.project_name or ""
    ledger.finish_run(result.run_id)
    # Flush to SQLite
    db_path = ct.get("db_path", "./token_usage.db")
    try:
        ledger.flush_to_db(db_path)
    except Exception as exc:
        console.print(f"  [yellow]⚠️  Token DB flush failed: {exc}[/yellow]")
    # Add cost to summary table and result
    s = ledger.summary(result.run_id)
    result.total_cost_usd = s["total_cost_usd"]
    result.token_usage = s
    # Post to GitHub issue if configured
    if ct.get("post_to_github", False) and self.github and result.issue_number:
        try:
            comment = ledger.format_github_comment(result.run_id)
            self.github.add_issue_comment(result.issue_number, comment)
        except Exception as exc:
            console.print(f"  [yellow]⚠️  Token comment failed: {exc}[/yellow]")
```

- [ ] **Step 6: Add total_cost_usd to the summary table in `_finish()`**

After `table.add_row("Duration", ...)`, add:

```python
if result.total_cost_usd > 0:
    table.add_row("Est. cost", f"${result.total_cost_usd:.4f} USD")
```

- [ ] **Step 7: Pass `run_id` into backend calls via stage context var**

In `_run_stage()` (or wherever each stage fn is called), set `current_stage` before the fn runs. Find the loop that calls `stage.fn(result)` and wrap it:

```python
token = current_stage.set(stage.name)
try:
    stage.fn(result)
finally:
    current_stage.reset(token)
```

Then in each agent that calls `backend.call()`, pass `run_id=result.run_id` — but since agents don't have direct access to `result`, the simpler approach is: in `backend.call()`, always use `get_ledger()` with the currently-active `run_id` from the ledger's active runs. Add a method to `TokenLedger`:

```python
def active_run_id(self) -> str | None:
    """Return the most recently started unfinished run_id, or None."""
    for run_id, meta in reversed(list(self._runs.items())):
        if meta.get("finished_at") is None:
            return run_id
    return None
```

And in `base.py` `call()` and `_stream_call()`, change the `run_id` parameter default to auto-detect:

```python
def call(self, messages: list[dict], run_id: str | None = None) -> str:
    ...
    effective_run_id = run_id if run_id is not None else get_ledger().active_run_id()
    # use effective_run_id instead of run_id for ledger.record()
```

This way agents don't need to be changed at all — usage is captured automatically.

- [ ] **Step 8: Add `run_id` and `total_cost_usd` fields to `PipelineResult`**

Find the `PipelineResult` dataclass and add after `progress_comment_id`:

```python
run_id: str = ""
total_cost_usd: float = 0.0
token_usage: dict = field(default_factory=dict)
```

- [ ] **Step 9: Run full backend + orchestrator tests**

```bash
cd /home/wanleung/Projects/ai-software-house && source venv/bin/activate
python -m pytest tests/test_token_ledger.py tests/test_token_backend_emission.py tests/test_backends_base.py tests/test_backend_ollama.py tests/test_backend_fallback.py tests/test_orchestrator*.py -v
```
Expected: all pass.

- [ ] **Step 10: Commit**

```bash
git add orchestrator.py
git commit -m "feat(tokens): wire TokenLedger into orchestrator run lifecycle"
```

---

## Task 6: Update `config.yaml` with `cost_tracking` section

**Files:**
- Modify: `config.yaml`

- [ ] **Step 1: Add `cost_tracking` section**

Add after the `pipeline:` section in `config.yaml`:

```yaml
# ── Token usage & cost tracking ────────────────────────────────────────────
# Tracks LLM token consumption per pipeline run for client chargeback.
# Persisted to a local SQLite database; optionally posted to the GitHub issue.
cost_tracking:
  enabled: false                  # set true to enable tracking
  db_path: "./token_usage.db"     # SQLite file path (relative to project root)
  post_to_github: false           # post usage summary comment to the GitHub issue

  # Pricing per 1M tokens: [input_price_usd, output_price_usd]
  # Set to [0.00, 0.00] for local/free models (Ollama, etc.)
  # Unlisted models fall back to "default".
  pricing:
    gpt-4.1:           [2.00, 8.00]
    gpt-4.1-mini:      [0.40, 1.60]
    gpt-4o:            [2.50, 10.00]
    qwen3.6-plus:      [0.50, 1.50]
    qwen3.5-plus:      [0.30, 1.20]
    thinker:           [0.00, 0.00]
    thinker-best:      [0.00, 0.00]
    coder:             [0.00, 0.00]
    fast:              [0.00, 0.00]
    chat:              [0.00, 0.00]
    default:           [2.00, 8.00]   # fallback for any unlisted model
```

- [ ] **Step 2: Commit**

```bash
git add config.yaml
git commit -m "docs(config): add cost_tracking section with pricing table"
```

---

## Task 7: Open Pull Request

- [ ] **Step 1: Push branch and open PR**

```bash
git push origin feature/token-counter
gh pr create \
  --title "feat: token counter & cost tracking for client chargeback" \
  --body "## Summary

Adds per-run LLM token usage tracking and USD cost calculation.

### What's new
- \`agents/token_ledger.py\` — \`TokenLedger\` singleton that accumulates usage events
- Backends (\`base.py\`, \`ollama.py\`) auto-emit usage after every call via context-var stage tagging
- \`tiktoken\` used as fallback estimator for streaming calls where response.usage is unavailable
- SQLite persistence to \`token_usage.db\` (path configurable)
- GitHub issue comment with per-stage breakdown posted at pipeline end
- Pipeline summary table shows estimated cost

### Configuration
\`\`\`yaml
cost_tracking:
  enabled: true
  db_path: \"./token_usage.db\"
  post_to_github: true
  pricing:
    gpt-4.1: [2.00, 8.00]
    # ...
\`\`\`

Closes #<issue-number>" \
  --base master \
  --head feature/token-counter
```

---

## Setup Before Starting

```bash
cd /home/wanleung/Projects/ai-software-house
git checkout master && git pull origin master
git checkout -b feature/token-counter
source venv/bin/activate
```
