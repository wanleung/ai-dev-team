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
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import yaml

if TYPE_CHECKING:
    from orchestrator import PipelineResult

logger = logging.getLogger(__name__)

EARLY_EXIT_DEFAULT = "CONSENSUS_REACHED"
_VALID_OUTPUT_MODES = frozenset({"transcript", "synthesis", "both"})
_MENTION_RE = re.compile(r'@([A-Za-z_][A-Za-z0-9_]*)\b')


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

    def __post_init__(self) -> None:
        if self.output_mode not in _VALID_OUTPUT_MODES:
            raise ValueError(
                f"output_mode must be one of {sorted(_VALID_OUTPUT_MODES)!r}, got {self.output_mode!r}"
            )

    @classmethod
    def from_yaml(cls, config_path: str, base_dir: Path | None = None) -> "DiscussionConfig":
        """Load a DiscussionConfig from a preset YAML file.

        Persona files are resolved relative to ``base_dir`` when provided,
        otherwise falls back to ``p.parent.parent`` (i.e. the repo root when
        the YAML lives at ``<repo>/discussions/<name>.yaml``).

        Args:
            config_path: Path to the YAML preset file.
            base_dir: Optional root directory for resolving persona_file paths.
                      Useful when the YAML is not at the standard depth.
        """
        p = Path(config_path)
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        repo_root = base_dir if base_dir is not None else p.parent.parent

        if not isinstance(data, dict):
            raise ValueError(
                f"{config_path!r}: expected a YAML mapping at top level, got {type(data).__name__}"
            )
        raw_participants = data.get("participants", [])
        if not isinstance(raw_participants, list):
            raise ValueError(f"{config_path!r}: 'participants' must be a list")

        def resolve_persona(entry: dict) -> str:
            if "persona_file" in entry:
                pf = repo_root / entry["persona_file"]
                return pf.read_text(encoding="utf-8")
            if "persona" in entry:
                return entry["persona"]
            raise ValueError(
                f"Participant {entry.get('role', '?')!r} requires 'persona' or 'persona_file'"
            )

        participants = []
        for entry in raw_participants:
            role = entry.get("role") if isinstance(entry, dict) else None
            if not role:
                raise ValueError(f"Participant entry missing required 'role' key: {entry!r}")
            participants.append(
                Participant(
                    role=role,
                    persona=resolve_persona(entry),
                    llm=entry.get("llm"),
                )
            )

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


class DiscussionAgent:
    """Runs a multi-agent round-table discussion and writes results to PipelineResult."""

    def __init__(
        self,
        config: DiscussionConfig,
        model: str = "gpt-4.1",
        github_token: Optional[str] = None,
        ollama_url: str = "http://localhost:11434",
    ) -> None:
        """Initialise with a resolved DiscussionConfig."""
        self.config = config
        self.model = model
        self.github_token = github_token
        self.ollama_url = ollama_url
        self._backend_cache: dict = {}

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
        """Build an LLMBackend for a participant, cached per model string."""
        from agents.base_agent import BaseAgent
        model = llm_override or self.model
        if model not in self._backend_cache:
            agent = BaseAgent(
                model=model,
                github_token=self.github_token,
                ollama_url=self.ollama_url,
            )
            self._backend_cache[model] = agent._llm
        return self._backend_cache[model]

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

    def _run_homework_round(self, context: str) -> list[Turn]:
        """Run homework round: all participants think independently in parallel."""
        transcript: list[Turn] = []
        with ThreadPoolExecutor(max_workers=len(self.config.participants)) as pool:
            futures = {
                pool.submit(self._call_participant, p, context, [], 0): p
                for p in self.config.participants
            }
            # as_completed() yields in completion order, not submission order.
            # Homework transcript ordering is therefore non-deterministic across runs.
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
        return transcript

    def _extract_mentions(self, text: str) -> list:
        """Return Participant objects for valid @role mentions in text."""
        role_map = {p.role: p for p in self.config.participants}
        return [role_map[m] for m in _MENTION_RE.findall(text) if m in role_map]

    def _run_discussion_rounds(self, context: str, transcript: list[Turn]) -> list[Turn]:
        """Run N discussion rounds with @mention-based turn order routing."""
        turn_order = list(self.config.participants)
        for round_num in range(1, self.config.max_rounds + 1):
            next_priority: list[Participant] = []
            consensus = False
            for participant in turn_order:
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
                    # Collect @mentions to reprioritise next round
                    for p in self._extract_mentions(turn.content):
                        if p is not participant and p not in next_priority:
                            next_priority.append(p)
                except Exception as exc:
                    logger.warning(
                        "DiscussionAgent: %s failed in round %d: %s",
                        participant.role, round_num, exc,
                    )
                    transcript.append(
                        Turn(role=participant.role, content=f"[Error: {exc}]", round_num=round_num)
                    )
            # Rebuild turn order: mentioned roles first, rest in original order
            remaining = [p for p in self.config.participants if p not in next_priority]
            turn_order = next_priority + remaining
            if consensus:
                break
        return transcript

    def _run_synthesis(self, context: str, transcript: list[Turn]) -> str:
        """Generate synthesis from the moderator (or last participant as fallback)."""
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
            return backend.call(messages)
        except Exception as exc:
            logger.warning("DiscussionAgent: moderator failed: %s", exc)
            return f"[Synthesis failed: {exc}]"

    def _write_outputs(
        self, result: "PipelineResult", transcript: list[Turn], synthesis: str
    ) -> None:
        """Write transcript and/or synthesis to PipelineResult based on output_mode."""
        full_transcript = self._format_full_transcript(transcript, self.config.name)
        if self.config.output_mode in ("transcript", "both"):
            result.discussion_transcript = full_transcript
        if self.config.output_mode in ("synthesis", "both"):
            result.discussion_synthesis = synthesis

    def run(self, result: "PipelineResult") -> None:
        """Execute the full discussion and write results to result."""
        context = self._build_context(result)
        transcript = self._run_homework_round(context) if self.config.homework_round else []
        transcript = self._run_discussion_rounds(context, transcript)
        synthesis = ""
        if self.config.output_mode in ("synthesis", "both"):
            synthesis = self._run_synthesis(context, transcript)
        self._write_outputs(result, transcript, synthesis)
        result.add_completed_stage(f"discuss_{self.config.name}")
