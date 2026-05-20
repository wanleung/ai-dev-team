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
    llm: Optional[str] = None           # model for discussion rounds
    homework_llm: Optional[str] = None  # model for homework round (supports tools); falls back to llm


@dataclass
class Turn:
    """One speaker turn in the discussion."""

    role: str
    content: str
    round_num: int = 0  # 0 = homework, 1+ = discussion rounds


@dataclass
class DiscussionResult:
    """Return value from DiscussionAgent.run() when called with a context string."""

    transcript: list["Turn"]
    synthesis: str


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
    memory: bool = True  # persist transcript to MemoryStore after each run
    auto_participants: dict | None = None
    verdict_format: str = ""  # optional format instruction appended to synthesis prompt
    # Format: {"pool": ["role1", "role2", ...], "select": 3}
    # "pool" = available role names (must have persona files in roles/)
    # "select" = how many to pick

    def __post_init__(self) -> None:
        if self.output_mode not in _VALID_OUTPUT_MODES:
            raise ValueError(
                f"output_mode must be one of {sorted(_VALID_OUTPUT_MODES)!r}, got {self.output_mode!r}"
            )
        if self.auto_participants is not None:
            if not isinstance(self.auto_participants.get("pool"), list):
                raise ValueError("auto_participants['pool'] must be a list of role name strings")
            if "select" in self.auto_participants and not isinstance(self.auto_participants["select"], int):
                raise ValueError("auto_participants['select'] must be an integer")

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
                    homework_llm=entry.get("homework_llm"),
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
            verdict_format=str(data.get("verdict_format", "")),
        )


class DiscussionAgent:
    """Runs a multi-agent round-table discussion and writes results to PipelineResult."""

    def __init__(
        self,
        config: DiscussionConfig,
        model: str = "gpt-4.1",
        github_token: Optional[str] = None,
        ollama_url: str = "http://localhost:11434",
        console=None,
        roles_dir: Optional[Path] = None,
        tool_registry=None,
    ) -> None:
        """Initialise with a resolved DiscussionConfig.

        Args:
            config:        Resolved :class:`DiscussionConfig` instance.
            model:         Default LLM model string for all participants.
            github_token:  Optional GitHub token (forwarded to BaseAgent).
            ollama_url:    Ollama base URL (forwarded to BaseAgent).
            console:       Optional ``rich.console.Console`` instance.  When
                           provided, each participant's turn header is printed
                           and response tokens are streamed live.  Streaming
                           only applies to sequential discussion rounds — the
                           homework round is always silent regardless of this
                           setting.
            roles_dir:     Optional path to the directory containing role persona
                           files (``{role}.md``).  Defaults to
                           ``Path(__file__).parent.parent / "roles"`` (the repo
                           root ``roles/`` folder).  Used by
                           :meth:`_select_participants` when ``auto_participants``
                           is configured.
            tool_registry: Optional ToolRegistry passed to participants during
                           the homework round only.  Ignored for discussion rounds.
                           Only used when a participant declares ``homework_llm``
                           and that backend supports tool calling.
        """
        self.config = config
        self.model = model
        self.github_token = github_token
        self.ollama_url = ollama_url
        self.console = console
        self.roles_dir: Path = roles_dir if roles_dir is not None else Path(__file__).parent.parent / "roles"
        self.tool_registry = tool_registry
        self._backend_cache: dict = {}

    @classmethod
    def from_file(
        cls,
        config_path: str,
        model: str,
        github_token: Optional[str] = None,
        ollama_url: str = "http://localhost:11434",
        tool_registry=None,
    ) -> "DiscussionAgent":
        """Load config from a preset YAML file and return a DiscussionAgent."""
        config = DiscussionConfig.from_yaml(config_path)
        return cls(config, model, github_token, ollama_url, tool_registry=tool_registry)

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
        """Call one participant. Returns a Turn with the participant's response.

        When ``self.console`` is set and this is a discussion round
        (``round_num > 0``), a turn header is printed and tokens are streamed
        live to the console.  Homework-round calls (``round_num == 0``) are
        always silent to avoid garbled output from concurrent threads.

        If the participant declares ``homework_llm`` and a ``tool_registry`` is
        available, the homework round uses that model with tool calling so the
        participant can search the codebase/memory before writing their analysis.
        Discussion rounds always use the fast ``llm`` model without tools.
        """
        is_homework = round_num == 0
        if is_homework and participant.homework_llm:
            effective_llm = participant.homework_llm
        else:
            effective_llm = participant.llm
        backend = self._make_backend(effective_llm)

        # Print turn header for sequential discussion rounds only.
        streaming = self.console is not None and round_num > 0
        if streaming:
            self.console.print(
                f"\n[bold cyan]{participant.role}[/bold cyan] (round {round_num})"
            )

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

        on_token = None
        if streaming:
            on_token = lambda tok: self.console.print(tok, end="", highlight=False)

        # Homework round: use tool-calling if a homework_llm and tool_registry are set
        if is_homework and participant.homework_llm and self.tool_registry is not None:
            from agents.base_agent import BaseAgent
            hw_agent = BaseAgent(
                model=participant.homework_llm,
                github_token=self.github_token,
                ollama_url=self.ollama_url,
                system_prompt=participant.persona,
            )
            try:
                content = hw_agent.call_with_tools(user, tools=self.tool_registry)
            except NotImplementedError:
                # homework_llm doesn't support tools — fall back to plain call
                logger.warning(
                    "DiscussionAgent: %s homework_llm '%s' doesn't support tools, "
                    "falling back to plain call",
                    participant.role, participant.homework_llm,
                )
                content = backend.call(messages, on_token=on_token)
        else:
            content = backend.call(messages, on_token=on_token)
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

    def _select_participants(self, context: str) -> list[Participant]:
        """Use LLM to select participants from the auto_participants pool.

        Sends a prompt to the backend asking it to choose the best subset of
        roles for the given context.  If the LLM response contains no
        recognisable role names (or the call fails), falls back to
        ``config.participants``.

        Args:
            context: The discussion context string.

        Returns:
            A list of :class:`Participant` objects to use for the discussion.
        """
        cfg = self.config.auto_participants
        pool: list[str] = cfg.get("pool", [])
        n: int = cfg.get("select", len(pool))

        prompt = (
            f"You are selecting discussion participants. Given this context:\n{context}\n\n"
            f"Choose {n} roles from this pool that would provide the most valuable perspectives:\n"
            + "\n".join(f"- {r}" for r in pool)
            + "\n\nReply with only the role names, one per line."
        )
        backend = self._make_backend(self.model)
        try:
            response = backend.call([
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt},
            ])
            selected = [
                line.strip().lstrip("- ").lower()
                for line in response.splitlines()
                if line.strip()
            ]
            pool_lower = {r.lower() for r in pool}
            valid = [r for r in selected if r in pool_lower][:n]
            if not valid:
                logger.warning(
                    "auto_participants: no valid roles in LLM response, falling back"
                )
                return self.config.participants
            participants: list[Participant] = []
            for role in valid:
                persona_file = self.roles_dir / f"{role}.md"
                if not persona_file.exists():
                    logger.warning(
                        "auto_participants: persona file not found for role %s, skipping", role
                    )
                    continue
                participants.append(Participant(role=role, persona=persona_file.read_text()))
            return participants if participants else self.config.participants
        except Exception as exc:
            logger.warning(
                "auto_participants: selection failed (%s), falling back", exc
            )
            return self.config.participants

    def _extract_mentions(self, text: str, participants: list | None = None) -> list:
        """Return Participant objects for valid @role mentions in text."""
        source = participants if participants is not None else self.config.participants
        role_map = {p.role: p for p in source}
        return [role_map[m] for m in _MENTION_RE.findall(text) if m in role_map]

    def _run_discussion_rounds(self, context: str, transcript: list[Turn]) -> list[Turn]:
        """Run N discussion rounds with @mention-based turn order routing."""
        if self.config.auto_participants:
            effective_participants = self._select_participants(context)
        else:
            effective_participants = self.config.participants
        turn_order = list(effective_participants)
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
                    for p in self._extract_mentions(turn.content, effective_participants):
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
            remaining = [p for p in effective_participants if p not in next_priority]
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
            synthesis_instruction = (
                "Please synthesise the discussion into a clear proposal or recommendation."
            )
            if self.config.verdict_format:
                synthesis_instruction = (
                    f"{synthesis_instruction}\n\n{self.config.verdict_format}"
                )
            messages = [
                {"role": "system", "content": moderator.persona},
                {
                    "role": "user",
                    "content": (
                        f"## Context\n\n{context}\n\n"
                        f"## Full Discussion\n\n{transcript_text}\n\n"
                        f"{synthesis_instruction}"
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

    def run(
        self,
        result: "PipelineResult | None" = None,
        *,
        context: Optional[str] = None,
        memory_store=None,
        repo: str = "local",
    ) -> "DiscussionResult":
        """Execute the full discussion and write results to result.

        Supports two call styles:

        1. Legacy / orchestrator style::

               agent.run(pipeline_result, memory_store=store)

           ``result`` must be a ``PipelineResult``.  Context is extracted via
           ``_build_context(result)`` and outputs are written back to ``result``.

        2. Standalone / test style::

               disc_result = agent.run(context="some text", memory_store=store)

           ``context`` is used directly.  A ``DiscussionResult`` is always
           returned by both styles.

        Args:
            result:       Optional PipelineResult (legacy style). When provided the
                          context is built from its fields and outputs are written
                          back to it.
            context:      Optional raw context string (standalone style). Takes
                          priority when ``result`` is None.
            memory_store: Optional MemoryStore.  When ``config.memory`` is True and
                          this is not None, the synthesis (or transcript) is
                          persisted after the run.

        Returns:
            A :class:`DiscussionResult` with the raw transcript and synthesis.
        """
        # Resolve context string from whichever source was provided.
        if context is None:
            if result is None:
                raise ValueError("DiscussionAgent.run() requires either 'result' or 'context'.")
            context = self._build_context(result)

        transcript = self._run_homework_round(context) if self.config.homework_round else []
        transcript = self._run_discussion_rounds(context, transcript)
        synthesis = ""
        if self.config.output_mode in ("synthesis", "both"):
            synthesis = self._run_synthesis(context, transcript)

        disc_result = DiscussionResult(transcript=transcript, synthesis=synthesis)

        # Write outputs back to PipelineResult when using the legacy call style.
        if result is not None:
            self._write_outputs(result, transcript, synthesis)
            result.add_completed_stage(f"discuss_{self.config.name}")

        # Persist to memory store if configured.
        if self.config.memory and memory_store is not None:
            summary = (
                disc_result.synthesis
                if disc_result.synthesis
                else "\n".join(t.content for t in disc_result.transcript)
            )
            memory_store.save(
                repo=repo,
                summary=summary,
                tags=["discussion", "transcript"],
                mode="discussion",
            )

        return disc_result
