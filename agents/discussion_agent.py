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
    def _load_yaml_config(cls, config_path: str, base_dir: Path | None = None) -> tuple[dict, Path, Path]:
        """Load and validate YAML configuration file.
        
        Returns:
            Tuple of (data, path, repo_root)
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
        return data, p, repo_root

    @staticmethod
    def _resolve_persona(entry: dict, repo_root: Path) -> str:
        """Resolve persona string from entry (persona_file or inline persona)."""
        if "persona_file" in entry:
            pf = repo_root / entry["persona_file"]
            return pf.read_text(encoding="utf-8")
        if "persona" in entry:
            return entry["persona"]
        raise ValueError(
            f"Participant {entry.get('role', '?')!r} requires 'persona' or 'persona_file'"
        )

    @classmethod
    def _build_participants(cls, raw_participants: list, repo_root: Path) -> list[Participant]:
        """Build list of Participant objects from raw YAML entries."""
        participants = []
        for entry in raw_participants:
            role = entry.get("role") if isinstance(entry, dict) else None
            if not role:
                raise ValueError(f"Participant entry missing required 'role' key: {entry!r}")
            participants.append(
                Participant(
                    role=role,
                    persona=cls._resolve_persona(entry, repo_root),
                    llm=entry.get("llm"),
                    homework_llm=entry.get("homework_llm"),
                )
            )
        return participants

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
        data, p, repo_root = cls._load_yaml_config(config_path, base_dir)
        raw_participants = data.get("participants", [])
        participants = cls._build_participants(raw_participants, repo_root)
        moderator: Optional[Participant] = None
        if "moderator" in data:
            mod = data["moderator"]
            moderator = Participant(role="moderator", persona=cls._resolve_persona(mod, repo_root))
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
        dashscope_api_key: Optional[str] = None,
        dashscope_url: Optional[str] = None,
        dashscope_think: bool = False,
        dashscope_preserve_thinking: bool = False,
        dashscope_stream: bool = True,
        fallbacks: Optional[list] = None,
    ) -> None:
        """Initialise with a resolved DiscussionConfig.

        Args:
            config: Resolved DiscussionConfig instance.
            model: Default LLM model for all participants.
            console: Optional Console for streaming output (discussion rounds only).
            roles_dir: Path to roles/ directory for auto_participants (defaults to repo root).
            tool_registry: Optional tools for homework round when participant uses homework_llm.
        """
        self.config = config
        self.model = model
        self.github_token = github_token
        self.ollama_url = ollama_url
        self.console = console
        self.roles_dir: Path = roles_dir if roles_dir is not None else Path(__file__).parent.parent / "roles"
        self.tool_registry = tool_registry
        self.dashscope_api_key = dashscope_api_key
        self.dashscope_url = dashscope_url
        self.dashscope_think = dashscope_think
        self.dashscope_preserve_thinking = dashscope_preserve_thinking
        self.dashscope_stream = dashscope_stream
        self.fallbacks: list = fallbacks or []
        self._backend_cache: dict = {}

    @classmethod
    def from_file(
        cls,
        config_path: str,
        model: str,
        github_token: Optional[str] = None,
        ollama_url: str = "http://localhost:11434",
        tool_registry=None,
        dashscope_api_key: Optional[str] = None,
        dashscope_url: Optional[str] = None,
        dashscope_think: bool = False,
        dashscope_preserve_thinking: bool = False,
        dashscope_stream: bool = True,
        fallbacks: Optional[list] = None,
    ) -> "DiscussionAgent":
        """Load config from a preset YAML file and return a DiscussionAgent."""
        config = DiscussionConfig.from_yaml(config_path)
        return cls(
            config, model, github_token, ollama_url,
            tool_registry=tool_registry,
            dashscope_api_key=dashscope_api_key,
            dashscope_url=dashscope_url,
            dashscope_think=dashscope_think,
            dashscope_preserve_thinking=dashscope_preserve_thinking,
            dashscope_stream=dashscope_stream,
            fallbacks=fallbacks,
        )

    def _make_backend(self, llm_override: Optional[str] = None):
        """Build an LLMBackend (or FallbackLLMBackend) for a participant, cached per model string."""
        from agents.backends.factory import create_backend
        model = llm_override or self.model
        if model not in self._backend_cache:
            cfg: dict = {
                "model": model,
                "ollama_url": self.ollama_url,
                "dashscope_api_key": self.dashscope_api_key,
                "dashscope_url": self.dashscope_url,
                "think": self.dashscope_think,
                "preserve_thinking": self.dashscope_preserve_thinking,
                "stream": self.dashscope_stream,
            }
            if self.fallbacks:
                cfg["fallbacks"] = self.fallbacks
            self._backend_cache[model] = create_backend(cfg, github_token=self.github_token)
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

    def _build_participant_messages(
        self, context: str, transcript: list[Turn], participant: Participant
    ) -> list[dict]:
        """Build messages for participant prompt."""
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
        return [
            {"role": "system", "content": participant.persona},
            {"role": "user", "content": user},
        ]

    def _build_homework_config(self, model: str) -> dict:
        """Build backend config dict for homework round."""
        hw_cfg: dict = {
            "model": model,
            "ollama_url": self.ollama_url,
            "dashscope_api_key": self.dashscope_api_key,
            "dashscope_url": self.dashscope_url,
            "think": self.dashscope_think,
            "preserve_thinking": self.dashscope_preserve_thinking,
            "stream": self.dashscope_stream,
        }
        if self.fallbacks:
            hw_cfg["fallbacks"] = self.fallbacks
        return hw_cfg

    def _call_homework_with_tools(
        self, participant: Participant, user_content: str, backend
    ) -> str:
        """Call participant's homework round with tool support."""
        from agents.base_agent import BaseAgent
        from agents.backends.factory import create_backend
        hw_cfg = self._build_homework_config(participant.homework_llm)
        hw_llm = create_backend(hw_cfg, github_token=self.github_token)
        hw_agent = BaseAgent(
            model=participant.homework_llm,
            llm=hw_llm,
            github_token=self.github_token,
            system_prompt=participant.persona,
        )
        try:
            return hw_agent.call_with_tools(user_content, tools=self.tool_registry)
        except NotImplementedError:
            logger.warning(
                "DiscussionAgent: %s homework_llm '%s' doesn't support tools, falling back",
                participant.role, participant.homework_llm,
            )
            return backend.call([
                {"role": "system", "content": participant.persona},
                {"role": "user", "content": user_content},
            ])

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
        effective_llm = participant.homework_llm if (is_homework and participant.homework_llm) else participant.llm
        backend = self._make_backend(effective_llm)
        streaming = self.console is not None and round_num > 0
        if streaming:
            self.console.print(
                f"\n[bold cyan]{participant.role}[/bold cyan] (round {round_num})"
            )
        messages = self._build_participant_messages(context, transcript, participant)
        on_token = (lambda tok: self.console.print(tok, end="", highlight=False)) if streaming else None
        if is_homework and participant.homework_llm and self.tool_registry is not None:
            content = self._call_homework_with_tools(participant, messages[1]["content"], backend)
        else:
            content = backend.call(messages, on_token=on_token)
        return Turn(role=participant.role, content=content, round_num=round_num)

    def _run_homework_sequential(self, context: str) -> list[Turn]:
        """Run homework sequentially as fallback when thread pool unavailable."""
        # ThreadPoolExecutor cannot be created (interpreter shutdown in a leaked
        # background thread). Run participants sequentially as fallback.
        transcript = []
        for p in self.config.participants:
            try:
                transcript.append(self._call_participant(p, context, [], 0))
            except Exception as e:
                logger.warning("DiscussionAgent: %s failed in homework: %s", p.role, e)
                transcript.append(Turn(role=p.role, content=f"[Error: {e}]", round_num=0))
        return transcript

    def _run_homework_round(self, context: str) -> list[Turn]:
        """Run homework round: all participants think independently in parallel."""
        transcript: list[Turn] = []
        try:
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
        except RuntimeError as exc:
            logger.warning(
                "DiscussionAgent: parallel homework unavailable (%s) — running sequentially", exc
            )
            transcript = self._run_homework_sequential(context)
        return transcript

    def _parse_llm_selection_response(self, response: str, pool: list[str], n: int) -> list[str]:
        """Parse LLM response and extract valid role names."""
        selected = [
            line.strip().lstrip("- ").lower()
            for line in response.splitlines()
            if line.strip()
        ]
        pool_lower = {r.lower() for r in pool}
        return [r for r in selected if r in pool_lower][:n]

    def _load_selected_participants(self, valid_roles: list[str]) -> list[Participant]:
        """Load persona files for selected roles and build Participant list."""
        participants: list[Participant] = []
        for role in valid_roles:
            persona_file = self.roles_dir / f"{role}.md"
            if not persona_file.exists():
                logger.warning(
                    "auto_participants: persona file not found for role %s, skipping", role
                )
                continue
            participants.append(Participant(role=role, persona=persona_file.read_text()))
        return participants

    def _select_participants(self, context: str) -> list[Participant]:
        """Use LLM to select participants from auto_participants pool.

        Returns:
            List of Participant objects (falls back to config.participants on error).
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
            valid = self._parse_llm_selection_response(response, pool, n)
            if not valid:
                logger.warning("auto_participants: no valid roles, falling back")
                return self.config.participants
            participants = self._load_selected_participants(valid)
            return participants if participants else self.config.participants
        except Exception as exc:
            logger.warning("auto_participants: selection failed (%s), falling back", exc)
            return self.config.participants

    def _extract_mentions(self, text: str, participants: list | None = None) -> list:
        """Return Participant objects for valid @role mentions in text."""
        source = participants if participants is not None else self.config.participants
        role_map = {p.role: p for p in source}
        return [role_map[m] for m in _MENTION_RE.findall(text) if m in role_map]

    def _process_participant_turn(
        self, participant: Participant, context: str, transcript: list[Turn],
        round_num: int, effective_participants: list[Participant]
    ) -> tuple[Turn | None, list[Participant], bool]:
        """Process one participant turn. Returns (turn|None, mentioned_participants, consensus).
        
        Appends the resulting Turn to `transcript` as a side effect.
        """
        try:
            turn = self._call_participant(participant, context, transcript, round_num)
            transcript.append(turn)
            if self.config.early_exit in turn.content:
                logger.info(
                    "DiscussionAgent: early exit signal from '%s' in round %d",
                    participant.role, round_num,
                )
                return turn, [], True
            mentions = [
                p for p in self._extract_mentions(turn.content, effective_participants)
                if p is not participant
            ]
            return turn, mentions, False
        except Exception as exc:
            logger.warning(
                "DiscussionAgent: %s failed in round %d: %s",
                participant.role, round_num, exc,
            )
            transcript.append(
                Turn(role=participant.role, content=f"[Error: {exc}]", round_num=round_num)
            )
            return None, [], False

    def _run_discussion_rounds(self, context: str, transcript: list[Turn]) -> list[Turn]:
        """Run N discussion rounds with @mention-based turn order routing."""
        effective_participants = (
            self._select_participants(context)
            if self.config.auto_participants
            else self.config.participants
        )
        turn_order = list(effective_participants)
        for round_num in range(1, self.config.max_rounds + 1):
            next_priority: list[Participant] = []
            consensus = False
            for participant in turn_order:
                _, mentions, consensus = self._process_participant_turn(
                    participant, context, transcript, round_num, effective_participants
                )
                for p in mentions:
                    if p not in next_priority:
                        next_priority.append(p)
                if consensus:
                    break
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

    def _persist_to_memory(
        self, disc_result: DiscussionResult, memory_store, repo: str
    ) -> None:
        """Persist discussion to memory store if configured."""
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

    def run(
        self,
        result: "PipelineResult | None" = None,
        *,
        context: Optional[str] = None,
        memory_store=None,
        repo: str = "local",
    ) -> "DiscussionResult":
        """Execute the full discussion and return a DiscussionResult.

        Two call styles:
        - Pipeline: pass result (context extracted, outputs written back)
        - Standalone: pass context directly (returns DiscussionResult only)

        Args:
            result: Optional PipelineResult (context extracted, outputs written back).
            context: Optional raw context string (standalone style, takes priority if result=None).
            memory_store: Optional MemoryStore for persisting transcript when config.memory=True.

        Returns:
            DiscussionResult with transcript and synthesis.
        """
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
        if result is not None:
            self._write_outputs(result, transcript, synthesis)
            result.add_completed_stage(f"discuss_{self.config.name}")
        self._persist_to_memory(disc_result, memory_store, repo)
        return disc_result
