"""Graceful degradation policy: reduce engineers, fallback model, skip optional stages.

Usage:
    from core.degradation import DegradationPolicy, DegradationContext
    policy = DegradationPolicy(reliability_cfg.degradation, llm_cfg)

    try:
        result = cb.call(lambda: agent.run(...))
    except CircuitOpenError as exc:
        ctx = DegradationContext(reason=str(exc), ...)
        degraded = policy.apply(num_engineers, model, skippable_stages, ctx)
        # use degraded.num_engineers, degraded.model, degraded.skipped_stages
"""
from __future__ import annotations

from dataclasses import dataclass, field

from config_schema import DegradationConfig, LLMConfig
from core.events import DegradationEvent, emit_event


@dataclass
class DegradationContext:
    """Context describing why degradation was triggered.
    
    The ``original_num_engineers`` and ``original_model`` fields are intended for
    external audit logging only and are not used by DegradationPolicy internally.
    """

    reason: str
    original_num_engineers: int
    original_model: str


@dataclass
class DegradationResult:
    """The outcome of applying the degradation policy."""

    num_engineers: int
    model: str
    skipped_stages: list[str]
    actions_taken: list[str] = field(default_factory=list)


class DegradationPolicy:
    """Applies configured degradation strategies when the pipeline is under pressure.

    Three strategies are supported (each independently toggleable):
    - ``reduce_engineers``: lower the engineer count by one (minimum 1).
    - ``fallback_model``: swap the current LLM for the next model in the fallback chain.
    - ``skip_optional_stages``: omit stages that appear in both *skippable_stages* and
      the configured *optional_stages* list.
    """

    def __init__(self, cfg: DegradationConfig, llm_cfg: LLMConfig) -> None:
        self._cfg = cfg
        self._fallback_chain: list[str] = list(llm_cfg.fallback or [])

    def apply(
        self,
        num_engineers: int,
        model: str,
        skippable_stages: list[str],
        context: DegradationContext,
    ) -> DegradationResult:
        """Apply the degradation policy and return adjusted pipeline parameters.

        Args:
            num_engineers: The currently planned number of engineer agents.
            model: The LLM model identifier currently in use.
            skippable_stages: Pipeline stages the caller considers safe to skip.
            context: Metadata about why degradation is being triggered.

        Returns:
            A :class:`DegradationResult` with (potentially) reduced engineer count,
            substituted model, and a list of stages to omit.

        Raises:
            ValueError: If num_engineers < 1.
        """
        if num_engineers < 1:
            raise ValueError(f"num_engineers must be >= 1, got {num_engineers}")

        if not self._cfg.enabled:
            return DegradationResult(
                num_engineers=num_engineers,
                model=model,
                skipped_stages=[],
            )

        actions: list[str] = []
        result_engineers = num_engineers
        result_model = model
        result_skipped: list[str] = []

        # Strategy 1: reduce engineer count by one (floor at 1)
        if self._cfg.reduce_engineers and num_engineers > 1:
            result_engineers = num_engineers - 1  # guard above ensures this is >= 1
            actions.append(
                f"reduce_engineers: {num_engineers} → {result_engineers} (reason: {context.reason})"
            )

        # Strategy 2: substitute the next model in the fallback chain.
        # If the current model appears in the chain, advance to the entry after it.
        # If it is not in the chain at all, start from chain[0].
        # If already at the last entry, no cheaper option exists — leave unchanged.
        if self._cfg.fallback_model and self._fallback_chain:
            try:
                # Uses first occurrence; callers should ensure the chain has no duplicates.
                next_idx = self._fallback_chain.index(model) + 1
            except ValueError:
                next_idx = 0  # current model not listed → start from beginning

            if next_idx < len(self._fallback_chain):
                result_model = self._fallback_chain[next_idx]
                actions.append(
                    f"fallback_model: {model} → {result_model} (reason: {context.reason})"
                )

        # Strategy 3: skip stages that are both skippable and in optional_stages
        if self._cfg.skip_optional_stages:
            to_skip = [
                s for s in skippable_stages
                if s in self._cfg.optional_stages
            ]
            if to_skip:
                result_skipped = to_skip
                actions.append(
                    f"skip_optional_stages: {to_skip} (reason: {context.reason})"
                )

        result = DegradationResult(
            num_engineers=result_engineers,
            model=result_model,
            skipped_stages=result_skipped,
            actions_taken=actions,
        )
        if actions:
            emit_event(DegradationEvent(
                trigger=context.reason,
                actions_taken=actions,
            ))
        return result
