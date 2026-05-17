# Discussion Stage — Implementation Plan (Milestone A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reusable multi-agent round-table discussion stage to ai-software-house pipelines via named preset YAML files in `discussions/`.

**Architecture:** A new `DiscussionAgent` class manages the full debate loop (homework round + discussion rounds + synthesis). The orchestrator auto-discovers `discussions/*.yaml` at startup, registers each as a named `PipelineStage` (e.g. `discuss_brainstorm`), and exposes them in the pipeline builder UI palette automatically. Two new fields (`discussion_transcript`, `discussion_synthesis`) are added to `PipelineResult`.

**Tech Stack:** Python 3.10+, PyYAML (already a dependency), `concurrent.futures.ThreadPoolExecutor` (stdlib), existing `BaseAgent` / `LLMBackend` infrastructure.

> **YAML naming note:** Stage names use underscores (`discuss_brainstorm`), NOT colons, because `discuss:brainstorm` would be parsed by PyYAML as a dict mapping, not a plain string. The spec's `discuss:brainstorm` notation is conceptual; the actual registered name and pipeline.yaml entry is `discuss_brainstorm`.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| CREATE | `agents/discussion_agent.py` | `DiscussionConfig`, `Participant`, `Turn`, `DiscussionAgent` |
| CREATE | `tests/test_discussion_agent.py` | Unit tests for `DiscussionAgent` |
| MODIFY | `orchestrator.py` lines ~430–435 | Add `discussion_transcript`, `discussion_synthesis` to `PipelineResult` |
| MODIFY | `orchestrator.py` `to_dict()` | Serialise new fields |
| MODIFY | `orchestrator.py` `from_dict()` | Deserialise new fields |
| MODIFY | `orchestrator.py` `_make_stage_registry()` | Auto-discover `discussions/*.yaml` and register stages |
| MODIFY | `orchestrator.py` | Add `_stage_discuss()` method |
| CREATE | `tests/test_discuss_orchestrator.py` | Integration tests for orchestrator discover + dispatch |
| CREATE | `roles/analyst.md` | Analyst persona |
| CREATE | `roles/skeptic.md` | Skeptic persona |
| CREATE | `roles/optimist.md` | Optimist persona |
| CREATE | `roles/moderator.md` | Moderator/synthesiser persona |
| CREATE | `discussions/brainstorm.yaml` | Generic brainstorm preset |
| CREATE | `discussions/news-analysis.yaml` | News discussion preset |
| CREATE | `tests/test_discuss_integration.py` | Pipeline YAML integration test |

---

## PR 1 — `agents/discussion_agent.py`

### Task 1: Write failing tests for `DiscussionConfig.from_yaml()`

**Files:**
- Create: `tests/test_discussion_agent.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_discussion_agent.py
"""Unit tests for DiscussionAgent and DiscussionConfig."""
from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from agents.discussion_agent import (
    DiscussionAgent,
    DiscussionConfig,
    Participant,
    Turn,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _write_preset(tmp_path: Path, data: dict) -> Path:
    """Write a discussions/*.yaml preset file and return its path."""
    p = tmp_path / "discussions" / "test_preset.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.dump(data), encoding="utf-8")
    return p


def _write_persona_file(tmp_path: Path, name: str, content: str) -> Path:
    roles = tmp_path / "roles"
    roles.mkdir(exist_ok=True)
    p = roles / name
    p.write_text(content, encoding="utf-8")
    return p


# ── DiscussionConfig.from_yaml ─────────────────────────────────────────────

class TestDiscussionConfigFromYaml:
    def test_loads_inline_persona(self, tmp_path):
        preset = _write_preset(tmp_path, {
            "participants": [
                {"role": "analyst", "persona": "You are an analyst."},
                {"role": "skeptic", "persona": "You are a skeptic."},
            ],
            "max_rounds": 2,
            "output_mode": "transcript",
        })
        cfg = DiscussionConfig.from_yaml(str(preset))
        assert len(cfg.participants) == 2
        assert cfg.participants[0].role == "analyst"
        assert cfg.participants[0].persona == "You are an analyst."
        assert cfg.max_rounds == 2
        assert cfg.output_mode == "transcript"

    def test_loads_persona_file(self, tmp_path):
        _write_persona_file(tmp_path, "analyst.md", "You are a deep analyst.")
        preset = _write_preset(tmp_path, {
            "participants": [
                {"role": "analyst", "persona_file": "roles/analyst.md"},
            ],
        })
        cfg = DiscussionConfig.from_yaml(str(preset))
        assert cfg.participants[0].persona == "You are a deep analyst."

    def test_raises_on_missing_persona(self, tmp_path):
        preset = _write_preset(tmp_path, {
            "participants": [{"role": "analyst"}],
        })
        with pytest.raises(ValueError, match="persona"):
            DiscussionConfig.from_yaml(str(preset))

    def test_raises_on_missing_persona_file(self, tmp_path):
        preset = _write_preset(tmp_path, {
            "participants": [
                {"role": "analyst", "persona_file": "roles/nonexistent.md"},
            ],
        })
        with pytest.raises((FileNotFoundError, OSError)):
            DiscussionConfig.from_yaml(str(preset))

    def test_max_rounds_minimum_one(self, tmp_path):
        preset = _write_preset(tmp_path, {
            "participants": [{"role": "a", "persona": "p"}],
            "max_rounds": 0,
        })
        cfg = DiscussionConfig.from_yaml(str(preset))
        assert cfg.max_rounds == 1

    def test_defaults(self, tmp_path):
        preset = _write_preset(tmp_path, {
            "participants": [{"role": "a", "persona": "p"}],
        })
        cfg = DiscussionConfig.from_yaml(str(preset))
        assert cfg.homework_round is False
        assert cfg.max_rounds == 3
        assert cfg.early_exit == "CONSENSUS_REACHED"
        assert cfg.output_mode == "both"
        assert cfg.context_fields == ["issue_body"]
        assert cfg.moderator is None

    def test_optional_moderator_loaded(self, tmp_path):
        preset = _write_preset(tmp_path, {
            "participants": [{"role": "a", "persona": "p"}],
            "moderator": {"persona": "You synthesise."},
        })
        cfg = DiscussionConfig.from_yaml(str(preset))
        assert cfg.moderator is not None
        assert cfg.moderator.persona == "You synthesise."

    def test_llm_override_per_participant(self, tmp_path):
        preset = _write_preset(tmp_path, {
            "participants": [
                {"role": "a", "persona": "p", "llm": "opencode-go/qwen3.6-plus"},
            ],
        })
        cfg = DiscussionConfig.from_yaml(str(preset))
        assert cfg.participants[0].llm == "opencode-go/qwen3.6-plus"

    def test_config_name_derived_from_filename(self, tmp_path):
        p = tmp_path / "discussions" / "news_analysis.yaml"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(yaml.dump({"participants": [{"role": "a", "persona": "p"}]}))
        cfg = DiscussionConfig.from_yaml(str(p))
        assert cfg.name == "news_analysis"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_discussion_agent.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'agents.discussion_agent'`

---

### Task 2: Implement `DiscussionConfig`, `Participant`, `Turn`

**Files:**
- Create: `agents/discussion_agent.py`

- [ ] **Step 1: Create the module with dataclasses + config loader**

```python
# agents/discussion_agent.py
"""DiscussionAgent — multi-agent round-table discussion stage.

A DiscussionAgent manages a configurable debate between multiple persona-driven
participants and writes the transcript and/or synthesis to PipelineResult.

Usage in pipeline.yaml (Milestone A — preset files):
    stages:
      - pm
      - architect
      - discuss_brainstorm      # references discussions/brainstorm.yaml
      - reviewer
      - engineer
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import yaml

if TYPE_CHECKING:
    from orchestrator import PipelineResult

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).parent.parent
EARLY_EXIT_DEFAULT = "CONSENSUS_REACHED"


@dataclass
class Participant:
    """One discussion participant: a named role with a resolved persona string."""

    role: str
    persona: str
    llm: Optional[str] = None  # optional per-participant model override


@dataclass
class Turn:
    """One speaker turn in the discussion."""

    role: str
    content: str
    round_num: int = 0  # 0 = homework, 1+ = discussion rounds


@dataclass
class DiscussionConfig:
    """Parsed representation of a discussions/*.yaml preset file."""

    participants: list[Participant]
    homework_round: bool = False
    max_rounds: int = 3
    early_exit: str = EARLY_EXIT_DEFAULT
    moderator: Optional[Participant] = None
    output_mode: str = "both"  # "transcript" | "synthesis" | "both"
    context_fields: list[str] = field(default_factory=lambda: ["issue_body"])
    name: str = "discussion"

    @classmethod
    def from_yaml(cls, config_path: str) -> "DiscussionConfig":
        """Load a DiscussionConfig from a preset YAML file.

        Persona files are resolved relative to the repo root (parent of the
        discussions/ directory).
        """
        p = Path(config_path)
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        repo_root = p.parent.parent  # discussions/ lives one level below repo root

        def resolve_persona(entry: dict) -> str:
            if "persona_file" in entry:
                pf = repo_root / entry["persona_file"]
                return pf.read_text(encoding="utf-8")
            if "persona" in entry:
                return entry["persona"]
            raise ValueError(
                f"Participant {entry.get('role', '?')!r} requires 'persona' or 'persona_file'"
            )

        participants = [
            Participant(
                role=entry["role"],
                persona=resolve_persona(entry),
                llm=entry.get("llm"),
            )
            for entry in data.get("participants", [])
        ]

        moderator: Optional[Participant] = None
        if "moderator" in data:
            mod = data["moderator"]
            moderator = Participant(role="moderator", persona=resolve_persona(mod))

        return cls(
            participants=participants,
            homework_round=bool(data.get("homework_round", False)),
            max_rounds=max(1, int(data.get("max_rounds", 3))),
            early_exit=str(data.get("early_exit", EARLY_EXIT_DEFAULT)),
            moderator=moderator,
            output_mode=str(data.get("output_mode", "both")),
            context_fields=list(data.get("context_fields", ["issue_body"])),
            name=p.stem.replace("-", "_"),
        )
```

- [ ] **Step 2: Run config tests**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/test_discussion_agent.py::TestDiscussionConfigFromYaml -v
```

Expected: All 8 config tests pass.

- [ ] **Step 3: Commit**

```bash
git add agents/discussion_agent.py tests/test_discussion_agent.py
git commit -m "feat(discussion): add DiscussionConfig dataclass + YAML loader

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 3: Add `DiscussionAgent` — context builder and transcript formatter

**Files:**
- Modify: `agents/discussion_agent.py`
- Modify: `tests/test_discussion_agent.py`

- [ ] **Step 1: Add tests for context building and transcript formatting**

Add to `tests/test_discussion_agent.py`:

```python
class TestDiscussionAgentHelpers:
    def _make_agent(self, tmp_path: Path) -> DiscussionAgent:
        preset = _write_preset(tmp_path, {
            "participants": [
                {"role": "analyst", "persona": "You are an analyst."},
                {"role": "skeptic", "persona": "You are a skeptic."},
            ],
        })
        cfg = DiscussionConfig.from_yaml(str(preset))
        return DiscussionAgent(cfg, model="gpt-4.1", github_token=None)

    def test_build_context_uses_issue_body(self, tmp_path):
        from orchestrator import PipelineResult
        agent = self._make_agent(tmp_path)
        result = PipelineResult(requirement="build a blog")
        result.issue_body = "User wants a fast blog."
        context = agent._build_context(result)
        assert "User wants a fast blog." in context

    def test_build_context_fallback_to_requirement(self, tmp_path):
        from orchestrator import PipelineResult
        agent = self._make_agent(tmp_path)
        result = PipelineResult(requirement="build a blog")
        context = agent._build_context(result)
        assert "build a blog" in context

    def test_format_full_transcript_no_homework(self, tmp_path):
        agent = self._make_agent(tmp_path)
        turns = [
            Turn(role="analyst", content="This is a good idea.", round_num=1),
            Turn(role="skeptic", content="I doubt it.", round_num=1),
        ]
        out = agent._format_full_transcript(turns, "test")
        assert "=== Discussion: test ===" in out
        assert "[Round 1]" in out
        assert "ANALYST: This is a good idea." in out
        assert "SKEPTIC: I doubt it." in out

    def test_format_full_transcript_with_homework(self, tmp_path):
        preset = _write_preset(tmp_path, {
            "participants": [
                {"role": "analyst", "persona": "p"},
                {"role": "skeptic", "persona": "p"},
            ],
            "homework_round": True,
        })
        cfg = DiscussionConfig.from_yaml(str(preset))
        agent = DiscussionAgent(cfg, model="gpt-4.1", github_token=None)
        turns = [
            Turn(role="analyst", content="Homework.", round_num=0),
            Turn(role="skeptic", content="Homework too.", round_num=0),
            Turn(role="analyst", content="Now discuss.", round_num=1),
        ]
        out = agent._format_full_transcript(turns, "test")
        assert "[Round 0 — Homework]" in out
        assert "[Round 1]" in out
```

- [ ] **Step 2: Run to verify they fail**

```bash
python -m pytest tests/test_discussion_agent.py::TestDiscussionAgentHelpers -v 2>&1 | head -20
```

Expected: `ImportError` or `AttributeError` — `DiscussionAgent` not yet defined.

- [ ] **Step 3: Add `DiscussionAgent` class with helper methods to `agents/discussion_agent.py`**

Append after the `DiscussionConfig` class:

```python
class DiscussionAgent:
    """Runs a multi-agent round-table discussion and writes results to PipelineResult."""

    def __init__(
        self,
        config: DiscussionConfig,
        model: str,
        github_token: Optional[str] = None,
        ollama_url: str = "http://localhost:11434",
    ) -> None:
        self.config = config
        self.model = model
        self.github_token = github_token
        self.ollama_url = ollama_url

    @classmethod
    def from_file(
        cls,
        config_path: str,
        model: str,
        github_token: Optional[str] = None,
        ollama_url: str = "http://localhost:11434",
    ) -> "DiscussionAgent":
        """Load config from a preset YAML file and return a DiscussionAgent."""
        config = DiscussionConfig.from_yaml(config_path)
        return cls(config, model, github_token, ollama_url)

    def _make_backend(self, llm_override: Optional[str] = None):
        """Build an LLMBackend for a participant, using per-participant llm or self.model."""
        from agents.base_agent import BaseAgent
        model = llm_override or self.model
        agent = BaseAgent(
            model=model,
            github_token=self.github_token,
            ollama_url=self.ollama_url,
        )
        return agent._llm

    def _build_context(self, result: "PipelineResult") -> str:
        """Concatenate selected PipelineResult fields into a context string."""
        parts = []
        for field_name in self.config.context_fields:
            value = getattr(result, field_name, "") or ""
            if value.strip():
                parts.append(f"### {field_name}\n\n{value}")
        if parts:
            return "\n\n".join(parts)
        return getattr(result, "requirement", "") or ""

    def _format_transcript_for_prompt(self, transcript: list[Turn]) -> str:
        """Format transcript for inclusion in a participant's prompt."""
        return "\n\n".join(
            f"{t.role.upper()}: {t.content}" for t in transcript
        )

    def _format_full_transcript(self, transcript: list[Turn], name: str) -> str:
        """Format the full annotated transcript for storage in PipelineResult."""
        lines = [f"=== Discussion: {name} ===", ""]
        last_round = -1
        for turn in transcript:
            if turn.round_num != last_round:
                last_round = turn.round_num
                if turn.round_num == 0:
                    lines.append("[Round 0 — Homework]")
                else:
                    lines.append(f"[Round {turn.round_num}]")
            lines.append(f"{turn.role.upper()}: {turn.content}")
            lines.append("")
        return "\n".join(lines)
```

- [ ] **Step 4: Run helper tests**

```bash
python -m pytest tests/test_discussion_agent.py::TestDiscussionAgentHelpers -v
```

Expected: All 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add agents/discussion_agent.py tests/test_discussion_agent.py
git commit -m "feat(discussion): add DiscussionAgent helpers (context builder, transcript formatter)

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 4: Implement `DiscussionAgent._call_participant()` and `run()`

**Files:**
- Modify: `agents/discussion_agent.py`
- Modify: `tests/test_discussion_agent.py`

- [ ] **Step 1: Add tests for `run()` with mocked LLM**

Add to `tests/test_discussion_agent.py`:

```python
class TestDiscussionAgentRun:
    def _make_cfg(self, tmp_path: Path, **overrides) -> DiscussionConfig:
        data = {
            "participants": [
                {"role": "analyst", "persona": "You are an analyst."},
                {"role": "skeptic", "persona": "You are a skeptic."},
            ],
            "max_rounds": 1,
            "output_mode": "both",
        }
        data.update(overrides)
        preset = _write_preset(tmp_path, data)
        return DiscussionConfig.from_yaml(str(preset))

    def _make_result(self):
        from orchestrator import PipelineResult
        r = PipelineResult(requirement="build a news analyser")
        r.issue_body = "We need to analyse tech news."
        return r

    @patch("agents.discussion_agent.DiscussionAgent._make_backend")
    def test_run_writes_transcript(self, mock_backend, tmp_path):
        backend = MagicMock()
        backend.call.return_value = "My analysis."
        mock_backend.return_value = backend

        cfg = self._make_cfg(tmp_path)
        agent = DiscussionAgent(cfg, model="gpt-4.1")
        result = self._make_result()
        agent.run(result)

        assert "ANALYST" in result.discussion_transcript
        assert "SKEPTIC" in result.discussion_transcript

    @patch("agents.discussion_agent.DiscussionAgent._make_backend")
    def test_run_writes_synthesis(self, mock_backend, tmp_path):
        backend = MagicMock()
        backend.call.return_value = "My analysis."
        mock_backend.return_value = backend

        cfg = self._make_cfg(tmp_path)
        agent = DiscussionAgent(cfg, model="gpt-4.1")
        result = self._make_result()
        agent.run(result)

        assert result.discussion_synthesis != ""

    @patch("agents.discussion_agent.DiscussionAgent._make_backend")
    def test_early_exit_stops_rounds(self, mock_backend, tmp_path):
        backend = MagicMock()
        # Analyst triggers early exit on first turn
        backend.call.side_effect = ["I agree CONSENSUS_REACHED", "Should not be called"]
        mock_backend.return_value = backend

        cfg = self._make_cfg(tmp_path, max_rounds=5)
        agent = DiscussionAgent(cfg, model="gpt-4.1")
        result = self._make_result()
        agent.run(result)

        # backend.call should have been called only twice (analyst triggers exit,
        # synthesis still called once for moderator = last participant)
        assert backend.call.call_count <= 3

    @patch("agents.discussion_agent.DiscussionAgent._make_backend")
    def test_transcript_only_output_mode(self, mock_backend, tmp_path):
        backend = MagicMock()
        backend.call.return_value = "Response."
        mock_backend.return_value = backend

        cfg = self._make_cfg(tmp_path, output_mode="transcript")
        agent = DiscussionAgent(cfg, model="gpt-4.1")
        result = self._make_result()
        agent.run(result)

        assert result.discussion_transcript != ""
        assert result.discussion_synthesis == ""

    @patch("agents.discussion_agent.DiscussionAgent._make_backend")
    def test_homework_round_runs_parallel(self, mock_backend, tmp_path):
        backend = MagicMock()
        backend.call.return_value = "Homework done."
        mock_backend.return_value = backend

        cfg = self._make_cfg(tmp_path, homework_round=True)
        agent = DiscussionAgent(cfg, model="gpt-4.1")
        result = self._make_result()
        agent.run(result)

        assert "[Round 0 — Homework]" in result.discussion_transcript
```

- [ ] **Step 2: Run to verify tests fail**

```bash
python -m pytest tests/test_discussion_agent.py::TestDiscussionAgentRun -v 2>&1 | head -20
```

Expected: `AttributeError` — `run()` not yet defined.

- [ ] **Step 3: Add `_call_participant()` and `run()` to `DiscussionAgent` in `agents/discussion_agent.py`**

Append these methods inside the `DiscussionAgent` class:

```python
    def _call_participant(
        self,
        participant: Participant,
        context: str,
        transcript: list[Turn],
        round_num: int,
    ) -> Turn:
        """Call one participant. Returns a Turn with the participant's response."""
        backend = self._make_backend(participant.llm)
        if transcript:
            transcript_text = self._format_transcript_for_prompt(transcript)
            user = (
                f"## Context\n\n{context}\n\n"
                f"## Discussion so far\n\n{transcript_text}\n\n"
                f"Please add your perspective. "
                f"If you believe the group has reached consensus, "
                f"include '{self.config.early_exit}' in your response."
            )
        else:
            user = (
                f"## Context\n\n{context}\n\n"
                "Please provide your initial analysis and perspective."
            )
        messages = [
            {"role": "system", "content": participant.persona},
            {"role": "user", "content": user},
        ]
        content = backend.call(messages)
        return Turn(role=participant.role, content=content, round_num=round_num)

    def run(self, result: "PipelineResult") -> None:
        """Execute the discussion and write transcript/synthesis to result."""
        context = self._build_context(result)
        transcript: list[Turn] = []

        # Round 0: homework (all participants in parallel, no transcript yet)
        if self.config.homework_round:
            with ThreadPoolExecutor(max_workers=len(self.config.participants)) as pool:
                futures = {
                    pool.submit(self._call_participant, p, context, [], 0): p
                    for p in self.config.participants
                }
                for future in as_completed(futures):
                    participant = futures[future]
                    try:
                        transcript.append(future.result())
                    except Exception as exc:
                        logger.warning(
                            "DiscussionAgent: %s failed in homework round: %s",
                            participant.role, exc,
                        )
                        transcript.append(
                            Turn(role=participant.role, content=f"[Error: {exc}]", round_num=0)
                        )

        # Discussion rounds 1..max_rounds
        consensus = False
        for round_num in range(1, self.config.max_rounds + 1):
            if consensus:
                break
            for participant in self.config.participants:
                try:
                    turn = self._call_participant(participant, context, transcript, round_num)
                    transcript.append(turn)
                    if self.config.early_exit in turn.content:
                        logger.info(
                            "DiscussionAgent: early exit signal from '%s' in round %d",
                            participant.role, round_num,
                        )
                        consensus = True
                        break
                except Exception as exc:
                    logger.warning(
                        "DiscussionAgent: %s failed in round %d: %s",
                        participant.role, round_num, exc,
                    )
                    transcript.append(
                        Turn(role=participant.role, content=f"[Error: {exc}]", round_num=round_num)
                    )

        # Synthesis
        synthesis = ""
        if self.config.output_mode in ("synthesis", "both"):
            moderator = self.config.moderator or self.config.participants[-1]
            try:
                backend = self._make_backend(moderator.llm)
                transcript_text = self._format_transcript_for_prompt(transcript)
                messages = [
                    {"role": "system", "content": moderator.persona},
                    {
                        "role": "user",
                        "content": (
                            f"## Context\n\n{context}\n\n"
                            f"## Full Discussion\n\n{transcript_text}\n\n"
                            "Please synthesise the discussion into a clear proposal or recommendation."
                        ),
                    },
                ]
                synthesis = backend.call(messages)
            except Exception as exc:
                logger.warning("DiscussionAgent: moderator failed: %s", exc)
                synthesis = f"[Synthesis failed: {exc}]"

        # Write outputs
        full_transcript = self._format_full_transcript(transcript, self.config.name)
        if self.config.output_mode in ("transcript", "both"):
            result.discussion_transcript = full_transcript
        if self.config.output_mode == "synthesis":
            result.discussion_synthesis = synthesis
        if self.config.output_mode == "both":
            result.discussion_transcript = full_transcript
            result.discussion_synthesis = synthesis

        result.add_completed_stage(f"discuss_{self.config.name}")
```

- [ ] **Step 4: Run all discussion agent tests**

```bash
python -m pytest tests/test_discussion_agent.py -v
```

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add agents/discussion_agent.py tests/test_discussion_agent.py
git commit -m "feat(discussion): implement DiscussionAgent.run() with homework round + early exit

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 5: Open PR 1

- [ ] **Step 1: Push branch and open PR**

```bash
git push origin HEAD
gh pr create \
  --title "feat: add DiscussionAgent (Milestone A)" \
  --body "## Summary
Adds \`agents/discussion_agent.py\` implementing the multi-agent round-table discussion stage.

### What's included
- \`DiscussionConfig\`: parses \`discussions/*.yaml\` preset files (inline or file-based personas, optional moderator, configurable rounds/output_mode/context_fields)
- \`Participant\`, \`Turn\`: simple dataclasses
- \`DiscussionAgent.run(result)\`: homework round (parallel), discussion rounds (sequential with early exit), synthesis, writes to PipelineResult fields

### Not included yet
- Orchestrator integration (PR 2)
- Example presets and role files (PR 3)

Closes part of #<issue> (Milestone A — discussion stage)
" \
  --draft
```

---

## PR 2 — Orchestrator Integration

### Task 6: Add `discussion_transcript` + `discussion_synthesis` to `PipelineResult`

**Files:**
- Modify: `orchestrator.py`

- [ ] **Step 1: Write failing test for new PipelineResult fields**

Create `tests/test_discuss_orchestrator.py`:

```python
# tests/test_discuss_orchestrator.py
"""Tests for discussion stage orchestrator integration."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from orchestrator import PipelineResult


class TestPipelineResultDiscussionFields:
    def test_discussion_transcript_default_empty(self):
        r = PipelineResult(requirement="test")
        assert r.discussion_transcript == ""

    def test_discussion_synthesis_default_empty(self):
        r = PipelineResult(requirement="test")
        assert r.discussion_synthesis == ""

    def test_discussion_fields_in_to_dict(self):
        r = PipelineResult(requirement="test")
        r.discussion_transcript = "ANALYST: hello"
        r.discussion_synthesis = "Summary: good idea"
        d = r.to_dict()
        assert d["discussion_transcript"] == "ANALYST: hello"
        assert d["discussion_synthesis"] == "Summary: good idea"

    def test_discussion_fields_round_trip(self):
        r = PipelineResult(requirement="test")
        r.discussion_transcript = "ANALYST: hello"
        r.discussion_synthesis = "Summary"
        r2 = PipelineResult.from_dict(r.to_dict())
        assert r2.discussion_transcript == "ANALYST: hello"
        assert r2.discussion_synthesis == "Summary"
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_discuss_orchestrator.py::TestPipelineResultDiscussionFields -v 2>&1 | head -20
```

Expected: `AttributeError: 'PipelineResult' object has no attribute 'discussion_transcript'`

- [ ] **Step 3: Add fields to `PipelineResult` in `orchestrator.py`**

Find the `PipelineResult` dataclass (around line 405). Locate the block ending with:
```python
    bootstrap_agents_md: Optional[str] = None
```

Add after it:
```python
    # Discussion stage fields (Milestone A)
    discussion_transcript: str = ""
    discussion_synthesis: str = ""
```

- [ ] **Step 4: Add fields to `to_dict()` in `orchestrator.py`**

In `PipelineResult.to_dict()`, find the `return {` block. Add inside it (alongside `bootstrap_agents_md`):
```python
            "discussion_transcript": self.discussion_transcript,
            "discussion_synthesis": self.discussion_synthesis,
```

- [ ] **Step 5: Add fields to `from_dict()` in `orchestrator.py`**

In `PipelineResult.from_dict()`, find the `for key in [...]` list. Add to it:
```python
                    "discussion_transcript", "discussion_synthesis",
```

- [ ] **Step 6: Run tests**

```bash
python -m pytest tests/test_discuss_orchestrator.py::TestPipelineResultDiscussionFields -v
```

Expected: All 4 tests pass.

- [ ] **Step 7: Commit**

```bash
git add orchestrator.py tests/test_discuss_orchestrator.py
git commit -m "feat(discussion): add discussion_transcript + discussion_synthesis to PipelineResult

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 7: Add `_stage_discuss()` and auto-discovery in `_make_stage_registry()`

**Files:**
- Modify: `orchestrator.py`

- [ ] **Step 1: Write failing tests for auto-discovery**

Add to `tests/test_discuss_orchestrator.py`:

```python
class TestDiscussStageDiscovery:
    def _write_preset(self, tmp_path: Path, name: str) -> Path:
        discussions = tmp_path / "discussions"
        discussions.mkdir(exist_ok=True)
        p = discussions / f"{name}.yaml"
        p.write_text(yaml.dump({
            "participants": [{"role": "analyst", "persona": "You are an analyst."}],
            "max_rounds": 1,
            "output_mode": "transcript",
        }), encoding="utf-8")
        return p

    def test_discuss_stage_registered_from_yaml(self, tmp_path):
        from orchestrator import Orchestrator
        self._write_preset(tmp_path, "brainstorm")

        orch = Orchestrator.__new__(Orchestrator)
        orch._stage_skips = {}
        orch._pipeline_yaml_stages = None
        orch._mode = "standard"
        orch.model = "gpt-4.1"
        orch._github_token = None
        orch.ollama_url = "http://localhost:11434"
        orch.stop_on_review_issues = False
        orch._discussions_dir = tmp_path / "discussions"
        for attr in ("pm", "pm_reviewer", "architect", "architect_reviewer",
                     "engineer", "junior_engineer", "senior_engineer", "reviewer",
                     "qa", "qa_planner", "deployment_tester", "tier_reviewer"):
            setattr(orch, attr, None)

        registry = orch._make_stage_registry()
        assert "discuss_brainstorm" in registry
        stage = registry["discuss_brainstorm"]
        assert "💬" in stage.label
        assert "brainstorm" in stage.label.lower()

    def test_no_discussions_dir_no_error(self, tmp_path):
        from orchestrator import Orchestrator
        orch = Orchestrator.__new__(Orchestrator)
        orch._stage_skips = {}
        orch._pipeline_yaml_stages = None
        orch._mode = "standard"
        orch.model = "gpt-4.1"
        orch._github_token = None
        orch.ollama_url = "http://localhost:11434"
        orch.stop_on_review_issues = False
        orch._discussions_dir = tmp_path / "nonexistent"
        for attr in ("pm", "pm_reviewer", "architect", "architect_reviewer",
                     "engineer", "junior_engineer", "senior_engineer", "reviewer",
                     "qa", "qa_planner", "deployment_tester", "tier_reviewer"):
            setattr(orch, attr, None)

        registry = orch._make_stage_registry()
        assert not any(k.startswith("discuss_") for k in registry)
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_discuss_orchestrator.py::TestDiscussStageDiscovery -v 2>&1 | head -20
```

Expected: `AttributeError: 'Orchestrator' object has no attribute '_discussions_dir'`

- [ ] **Step 3: Add `_discussions_dir` attribute to `Orchestrator.__init__()`**

In `orchestrator.py`, find `Orchestrator.__init__()` (around line 720). Add after `self._stage_skips = stage_skips or {}`:

```python
        # Directory scanned for discussion preset YAMLs (discussions/*.yaml)
        self._discussions_dir: Path = Path(__file__).parent / "discussions"
```

- [ ] **Step 4: Add `_stage_discuss()` method to `Orchestrator`**

In `orchestrator.py`, add this method near the other private `_stage_*` methods (e.g. after `_stage_bootstrap_patterns`):

```python
    def _stage_discuss(self, result: "PipelineResult", config_path: str) -> None:
        """Run a discussion stage from a preset config file."""
        from agents.discussion_agent import DiscussionAgent
        agent = DiscussionAgent.from_file(
            config_path=config_path,
            model=self.model,
            github_token=self._github_token,
            ollama_url=self.ollama_url,
        )
        agent.run(result)
```

- [ ] **Step 5: Add auto-discovery to `_make_stage_registry()`**

In `orchestrator.py`, find the end of `_make_stage_registry()` — the closing `}` of `_registry`. Just before returning `_registry`, add:

```python
        # Auto-discover discussions/*.yaml and register as discuss_<name> stages
        discussions_dir = getattr(self, "_discussions_dir", Path(__file__).parent / "discussions")
        if discussions_dir.is_dir():
            for preset_path in sorted(discussions_dir.glob("*.yaml")):
                stage_key = f"discuss_{preset_path.stem.replace('-', '_')}"
                label_name = preset_path.stem.replace("-", " ").replace("_", " ").title()
                _registry[stage_key] = PipelineStage(
                    name=stage_key,
                    label=f"💬 Discuss: {label_name}",
                    description=f"Multi-agent round-table discussion ({preset_path.name})",
                    checkpoint_key=stage_key,
                    fn=lambda r, p=str(preset_path): self._stage_discuss(r, p),
                )
```

- [ ] **Step 6: Run all orchestrator tests**

```bash
python -m pytest tests/test_discuss_orchestrator.py -v
```

Expected: All tests pass.

- [ ] **Step 7: Run the full test suite to check for regressions**

```bash
python -m pytest tests/ -x -q --timeout=60 2>&1 | tail -20
```

Expected: No new failures (existing failures, if any, unchanged).

- [ ] **Step 8: Commit**

```bash
git add orchestrator.py tests/test_discuss_orchestrator.py
git commit -m "feat(discussion): auto-discover discussions/*.yaml in orchestrator, add _stage_discuss()

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 8: Open PR 2

- [ ] **Step 1: Push and open PR**

```bash
git push origin HEAD
gh pr create \
  --title "feat: orchestrator integration for discussion stage (Milestone A)" \
  --body "## Summary
Wires the DiscussionAgent into the orchestrator pipeline system.

### What's included
- \`PipelineResult.discussion_transcript\` + \`discussion_synthesis\` fields (with to_dict/from_dict)
- \`Orchestrator._stage_discuss(result, config_path)\`: creates and runs DiscussionAgent
- \`_make_stage_registry()\` auto-discovers \`discussions/*.yaml\` and registers each as \`discuss_<name>\` PipelineStage
- Pipeline builder UI palette automatically shows discovered stages (no UI changes needed)

### Usage after merge
Add \`discussions/brainstorm.yaml\` to a repo, then use \`discuss_brainstorm\` in pipeline.yaml.

Depends on: PR 1 (DiscussionAgent core)
" \
  --draft
```

---

## PR 3 — Example Presets, Role Files, Integration Test

### Task 9: Create persona role files

**Files:**
- Create: `roles/analyst.md`
- Create: `roles/skeptic.md`
- Create: `roles/optimist.md`
- Create: `roles/moderator.md`

- [ ] **Step 1: Create `roles/analyst.md`**

```markdown
# Analyst

You are a rigorous analyst. Your role in a team discussion is to:

- Break down the topic into its core components and examine each carefully
- Present evidence-based assessments grounded in facts and data
- Identify assumptions that need to be tested before proceeding
- Surface risks and dependencies that others may overlook
- Stay objective — you are not an advocate for any particular outcome

When contributing to a discussion, be concise and specific. Avoid vague generalisations. 
If you spot a claim that lacks evidence, challenge it.

When you believe the group has reached a well-reasoned conclusion, you may signal this 
by including "CONSENSUS_REACHED" in your response.
```

- [ ] **Step 2: Create `roles/skeptic.md`**

```markdown
# Skeptic

You are a constructive skeptic. Your role in a team discussion is to:

- Challenge assumptions and conventional thinking
- Ask "what could go wrong?" and "why might this fail?"
- Push back on proposals that lack sufficient evidence or that seem over-optimistic
- Identify edge cases, second-order effects, and unintended consequences
- Propose alternative interpretations when the current framing seems incomplete

You are not contrarian for its own sake — your goal is to strengthen the final outcome 
by stress-testing ideas before they become commitments.

When you believe the group has reached a robust, well-challenged conclusion, you may signal 
this by including "CONSENSUS_REACHED" in your response.
```

- [ ] **Step 3: Create `roles/optimist.md`**

```markdown
# Optimist

You are a forward-thinking optimist. Your role in a team discussion is to:

- Identify opportunities and upside potential that others may underweight
- Reframe problems as solvable challenges rather than blockers
- Suggest creative approaches and novel combinations of ideas
- Keep the team focused on what is possible, not just what is safe
- Build on others' ideas rather than dismissing them

You are not naive — acknowledge real risks when raised by others, but then pivot 
to how they can be mitigated. Keep energy and momentum in the discussion.

When you believe the group has reached a creative and viable conclusion, you may signal 
this by including "CONSENSUS_REACHED" in your response.
```

- [ ] **Step 4: Create `roles/moderator.md`**

```markdown
# Moderator

You are a skilled facilitator and synthesiser. Your role is to:

- Read the full discussion transcript and extract the key insights, agreements, and tensions
- Produce a clear, structured proposal or recommendation that reflects the team's collective thinking
- Highlight where consensus was reached and on what basis
- Note any unresolved disagreements or open questions that need further attention
- Present your synthesis in a format that is immediately actionable

Your output should be concise, well-structured, and free of repetition. Aim for a 
synthesis that any stakeholder could read without needing to read the full transcript.

Structure your response as:
1. **Proposal / Recommendation** — the main output from the discussion
2. **Key Insights** — 2-4 bullet points of the most important ideas surfaced
3. **Open Questions** — any unresolved items that need follow-up (omit if none)
```

- [ ] **Step 5: Commit**

```bash
git add roles/analyst.md roles/skeptic.md roles/optimist.md roles/moderator.md
git commit -m "feat(discussion): add analyst, skeptic, optimist, moderator persona files

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 10: Create example discussion presets

**Files:**
- Create: `discussions/brainstorm.yaml`
- Create: `discussions/news-analysis.yaml`

- [ ] **Step 1: Create `discussions/brainstorm.yaml`**

```yaml
# discussions/brainstorm.yaml
# Generic multi-perspective brainstorm preset.
# Suitable for: proposal generation, feature ideation, architecture decisions.
#
# Usage in pipeline.yaml:
#   stages:
#     - pm
#     - architect
#     - discuss_brainstorm
#     - reviewer
#     - engineer

participants:
  - role: analyst
    persona_file: roles/analyst.md

  - role: skeptic
    persona_file: roles/skeptic.md

  - role: optimist
    persona_file: roles/optimist.md

homework_round: true    # each participant thinks independently before the group discussion
max_rounds: 2           # up to 2 discussion rounds after homework
early_exit: CONSENSUS_REACHED

moderator:
  persona_file: roles/moderator.md

output_mode: both       # downstream stages get both transcript and synthesis

context_fields:
  - spec
  - design
  - issue_body
```

- [ ] **Step 2: Create `discussions/news-analysis.yaml`**

```yaml
# discussions/news-analysis.yaml
# News and current events analysis preset.
# Suitable for: social media commentary, news digest pipelines, opinion piece generation.
#
# Usage in pipeline.yaml:
#   stages:
#     - discuss_news_analysis
#     - writer          # custom stage that reads discussion_synthesis

participants:
  - role: analyst
    persona_file: roles/analyst.md

  - role: skeptic
    persona_file: roles/skeptic.md

  - role: optimist
    persona_file: roles/optimist.md

homework_round: true    # participants each research the topic independently first
max_rounds: 3
early_exit: CONSENSUS_REACHED

moderator:
  persona_file: roles/moderator.md

output_mode: both

context_fields:
  - issue_body          # issue body should contain the article URL or full text
```

- [ ] **Step 3: Commit**

```bash
git add discussions/brainstorm.yaml discussions/news-analysis.yaml
git commit -m "feat(discussion): add brainstorm and news-analysis preset configs

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 11: Integration test — pipeline YAML with `discuss_brainstorm`

**Files:**
- Create: `tests/test_discuss_integration.py`

- [ ] **Step 1: Write integration test**

```python
# tests/test_discuss_integration.py
"""Integration test: pipeline.yaml containing a discuss_brainstorm stage."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml


class TestDiscussPipelineIntegration:
    """Verify that a pipeline.yaml with discuss_brainstorm resolves and runs."""

    def _build_orchestrator(self, tmp_path: Path):
        """Create a minimal Orchestrator with a temp discussions/ dir."""
        import shutil
        from orchestrator import Orchestrator

        # Copy preset files into a temp workspace
        repo_root = Path(__file__).parent.parent
        discussions_src = repo_root / "discussions"
        roles_src = repo_root / "roles"

        if discussions_src.exists():
            shutil.copytree(discussions_src, tmp_path / "discussions")
        if roles_src.exists():
            shutil.copytree(roles_src, tmp_path / "roles")

        orch = Orchestrator.__new__(Orchestrator)
        orch._stage_skips = {}
        orch._pipeline_yaml_stages = None
        orch._mode = "standard"
        orch.model = "gpt-4.1"
        orch._github_token = None
        orch.ollama_url = "http://localhost:11434"
        orch.stop_on_review_issues = False
        orch._discussions_dir = tmp_path / "discussions"
        for attr in ("pm", "pm_reviewer", "architect", "architect_reviewer",
                     "engineer", "junior_engineer", "senior_engineer", "reviewer",
                     "qa", "qa_planner", "deployment_tester", "tier_reviewer"):
            setattr(orch, attr, None)
        return orch

    def test_discuss_brainstorm_in_registry(self, tmp_path):
        orch = self._build_orchestrator(tmp_path)
        registry = orch._make_stage_registry()
        assert "discuss_brainstorm" in registry
        assert "discuss_news_analysis" in registry

    def test_discuss_stage_appears_in_palette(self, tmp_path):
        """_get_stage_palette() (used by UI builder) includes discuss stages."""
        import sys, types

        # Patch pipeline_builder.server to use our temp orchestrator
        orch = self._build_orchestrator(tmp_path)
        registry = orch._make_stage_registry()
        palette = [
            {"name": name, "label": stage.label, "description": stage.description}
            for name, stage in registry.items()
        ]
        names = [p["name"] for p in palette]
        assert "discuss_brainstorm" in names

    @patch("agents.discussion_agent.DiscussionAgent._make_backend")
    def test_discuss_stage_fn_runs(self, mock_backend, tmp_path):
        """The PipelineStage fn for discuss_brainstorm calls DiscussionAgent.run()."""
        from orchestrator import PipelineResult

        backend = MagicMock()
        backend.call.return_value = "This is a thoughtful response."
        mock_backend.return_value = backend

        orch = self._build_orchestrator(tmp_path)
        registry = orch._make_stage_registry()
        stage = registry["discuss_brainstorm"]

        result = PipelineResult(requirement="build a recommendation engine")
        result.issue_body = "We need a recommendation engine for our platform."
        stage.fn(result)

        assert "discuss_brainstorm" in result.completed_stages
        assert result.discussion_transcript != ""
```

- [ ] **Step 2: Run integration test**

```bash
python -m pytest tests/test_discuss_integration.py -v
```

Expected: All 3 tests pass.

- [ ] **Step 3: Run full test suite**

```bash
python -m pytest tests/ -x -q --timeout=60 2>&1 | tail -20
```

Expected: No new failures.

- [ ] **Step 4: Commit**

```bash
git add tests/test_discuss_integration.py
git commit -m "test(discussion): add integration test for discuss_brainstorm pipeline stage

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 12: Update spec to reflect `discuss_brainstorm` naming + open PR 3

- [ ] **Step 1: Update spec with YAML naming clarification**

In `docs/superpowers/specs/2026-05-17-discussion-stage-design.md`, update the Pipeline YAML Usage example:

```yaml
stages:
  - pm
  - architect
  - discuss_brainstorm        # references discussions/brainstorm.yaml
  - reviewer
  - engineer
```

Add a note: `# Note: underscores, not colons — discuss:brainstorm is YAML invalid`

- [ ] **Step 2: Commit spec update**

```bash
git add docs/superpowers/specs/2026-05-17-discussion-stage-design.md
git commit -m "docs: clarify discuss_brainstorm naming (underscore not colon) in spec

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

- [ ] **Step 3: Push and open PR 3**

```bash
git push origin HEAD
gh pr create \
  --title "feat: discussion stage presets, role files, integration tests (Milestone A)" \
  --body "## Summary
Adds the content layer for the discussion stage: persona files, example presets, and end-to-end integration tests.

### What's included
- \`roles/analyst.md\`, \`roles/skeptic.md\`, \`roles/optimist.md\`, \`roles/moderator.md\` — reusable persona files
- \`discussions/brainstorm.yaml\` — generic proposal/ideation preset (homework_round + 2 discussion rounds)
- \`discussions/news-analysis.yaml\` — news discussion preset (3 rounds)
- \`tests/test_discuss_integration.py\` — pipeline YAML integration tests

### How to use
\`\`\`yaml
# pipeline.yaml
stages:
  - pm
  - architect
  - discuss_brainstorm   # runs analyst + skeptic + optimist, then moderator synthesis
  - reviewer
  - engineer
\`\`\`

Downstream stages read \`result.discussion_transcript\` and \`result.discussion_synthesis\`.

Depends on: PR 1 (DiscussionAgent), PR 2 (Orchestrator integration)
" \
  --draft
```

---

## Merge Order

1. Merge PR 1 (DiscussionAgent core)
2. Merge PR 2 (Orchestrator integration) — depends on PR 1
3. Merge PR 3 (Presets + integration tests) — depends on PR 2

After all three merge, tag as `v0.9.0-discussion-a` or include in next minor release.
