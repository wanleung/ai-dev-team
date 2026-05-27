"""intake_scoring.py — Scoring pipeline for intake_triage.

Provides: ScoreParser, ScoringEngine, VerdictRouter, ScoredVerdict.
"""
from __future__ import annotations

import ast
import logging
import re
import sys
from typing import NamedTuple

log = logging.getLogger("intake_scoring")

# ---------------------------------------------------------------------------
# Synthesis normalisation
# ---------------------------------------------------------------------------

_MD_BOLD_RE = re.compile(r"\*\*([^*\n]+?)\*\*:?")
_MD_HEADER_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_MD_BULLET_ITEM_RE = re.compile(r"^[-*]\s+(?=ITEM\s+\d)", re.MULTILINE | re.IGNORECASE)


def _normalize_synthesis(text: str) -> str:
    """Strip common markdown formatting that breaks verdict-block parsing.

    Thinking models (e.g. MiMo) sometimes wrap structured output in markdown
    bold (``**ITEM 1:**``) or heading markers (``### ITEM 1``).  This function
    removes those decorations so the plain-text regexes match reliably.

    Transformations applied (in order):
    - ``**text**`` or ``**text:**`` → ``text`` or ``text:``
    - ``## text`` → ``text`` (markdown headings stripped)
    - ``- ITEM N`` → ``ITEM N`` (bullet prefixes before ITEM lines)
    """
    text = _MD_BOLD_RE.sub(lambda m: m.group(1), text)
    text = _MD_HEADER_RE.sub("", text)
    text = _MD_BULLET_ITEM_RE.sub("", text)
    return text


# ---------------------------------------------------------------------------
# ScoreParser
# ---------------------------------------------------------------------------

# Matches:  SCORES: relevance=8 news_value=9 ...
# The negative lookahead (?!ITEM\s+\d) prevents the lazy wildcard from
# crossing into the next item's block, so a missing SCORES line in ITEM N
# cannot steal ITEM N+1's scores.
_SCORES_LINE_RE = re.compile(
    r"^ITEM\s+(\d+)(?:(?!^ITEM\s+\d)[\s\S])*?^SCORES:\s*((?:\w+=\d+\s*)+)",
    re.IGNORECASE | re.MULTILINE,
)
_KV_RE = re.compile(r"(\w+)=(\d+)")


class ScoreParser:
    """Extract per-item dimension scores from moderator synthesis text."""

    def __init__(self, dimensions: list[str], score_scale: int = 10) -> None:
        """Initialise the parser.

        Args:
            dimensions: Ordered list of score dimension names to extract.
            score_scale: Maximum value of the scale; neutral defaults to
                ``score_scale // 2``.
        """
        self.dimensions = dimensions
        self.score_scale = score_scale
        self._neutral = score_scale // 2

    def _neutral_scores(self) -> dict[str, int]:
        """Return a dict with every dimension set to the neutral score."""
        return {dim: self._neutral for dim in self.dimensions}

    def parse_batch(self, synthesis: str, item_count: int) -> list[dict[str, int]]:
        """Return list of {dimension: score} dicts, one per item (1-indexed → 0-indexed).

        Missing dimensions are filled with neutral (``score_scale // 2``).
        If synthesis has fewer SCORES blocks than *item_count*, the extra
        positions are padded with neutral dicts.

        Args:
            synthesis: Full synthesis string produced by the moderator LLM.
            item_count: Expected number of items; result list length equals this.

        Returns:
            A list of length *item_count* where each element maps dimension
            names to integer scores.
        """
        if item_count < 1:
            raise ValueError(f"item_count must be >= 1, got {item_count!r}")

        synthesis = _normalize_synthesis(synthesis)
        raw: dict[int, dict[str, int]] = {}
        for m in _SCORES_LINE_RE.finditer(synthesis):
            idx = int(m.group(1))
            kv = {k: int(v) for k, v in _KV_RE.findall(m.group(2))}
            scores = self._neutral_scores()
            for dim in self.dimensions:
                if dim in kv:
                    val = kv[dim]
                    if not (0 <= val <= self.score_scale):
                        log.warning(
                            "Score out of range for dimension %r: %d (scale 0–%d); clamping.",
                            dim, val, self.score_scale,
                        )
                    scores[dim] = max(0, min(val, self.score_scale))
            if idx in raw:
                log.debug("ScoreParser: ITEM %d seen twice in synthesis; using later scores.", idx)
            raw[idx] = scores

        results = []
        for i in range(1, item_count + 1):
            results.append(raw.get(i, self._neutral_scores()))

        if not raw:
            log.warning(
                "ScoreParser: no SCORES blocks found in synthesis "
                "(all %d items will get neutral score). "
                "First 500 chars of synthesis: %.500s",
                item_count, synthesis,
            )

        return results


# ---------------------------------------------------------------------------
# ScoringEngine
# ---------------------------------------------------------------------------

_ALLOWED_AST_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.FloorDiv,
    ast.UAdd, ast.USub,
    ast.Constant,   # Python 3.8+ replaces ast.Num
    ast.Name,       # variable references only
    ast.Load,       # Name context — reading a variable is always safe
)

# ast.Num was replaced by ast.Constant in Python 3.8.
# Only include it for pre-3.8 interpreters where the parser genuinely emits Num nodes.
# On 3.8+, ast.Constant already covers all numerics; ast.Num is a deprecated alias
# whose __instancecheck__ fires a DeprecationWarning on every isinstance() miss.
if sys.version_info < (3, 8):
    try:
        _ALLOWED_AST_NODES = _ALLOWED_AST_NODES + (ast.Num,)  # type: ignore[attr-defined]
    except AttributeError:
        pass


def _safe_eval(expr_str: str, variables: dict[str, float]) -> float:
    """Evaluate a numeric expression with only the given variables in scope.

    Parses *expr_str* into an AST and walks every node to ensure only
    whitelisted arithmetic nodes are present.  The compiled expression is then
    evaluated with ``__builtins__`` removed so no built-in functions are
    accessible.

    Args:
        expr_str: A string containing an arithmetic expression that may
            reference keys from *variables*.
        variables: Mapping of allowed variable names to their float values.

    Returns:
        The float result of the evaluated expression.

    Raises:
        ValueError: If any disallowed AST node is encountered or if the
            expression references an unknown variable name.
    """
    try:
        tree = ast.parse(expr_str, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"invalid formula syntax: {exc}") from exc
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_AST_NODES):
            raise ValueError(
                f"disallowed AST node {type(node).__name__!r} in formula"
            )
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float)):
            raise ValueError(
                f"disallowed constant type {type(node.value).__name__!r} in formula"
            )
        if isinstance(node, ast.Name) and node.id not in variables:
            raise ValueError(f"unknown variable {node.id!r} in formula")
    code = compile(tree, "<formula>", "eval")
    try:
        return float(eval(code, {"__builtins__": {}}, variables))  # noqa: S307
    except ZeroDivisionError as exc:
        raise ValueError("formula produced division by zero") from exc


class ScoringEngine:
    """Apply a safe formula to a dimension-score dict and return a clamped float.

    The formula is evaluated using a restricted AST evaluator that permits only
    arithmetic operations and named variables.  The result is clamped to the
    range ``[0, score_scale]``.

    Example::

        engine = ScoringEngine(
            formula="(relevance * 1.5 + news_value * 2.0) / 3.5 * 10",
            score_scale=10,
        )
        engine.score({"relevance": 8, "news_value": 9})  # → 9.286...
    """

    def __init__(self, formula: str, score_scale: int = 10) -> None:
        """Initialise the engine.

        Args:
            formula: Arithmetic expression string referencing dimension names
                as variables (e.g. ``"relevance * 1.5 + news_value * 2.0"``).
            score_scale: Upper bound for clamping; lower bound is always 0.
        """
        self.formula = formula
        self.score_scale = score_scale

    def score(self, dimension_scores: dict[str, int]) -> float:
        """Evaluate *formula* with the given dimension scores.

        Args:
            dimension_scores: Mapping of dimension name to integer score.

        Returns:
            A float in ``[0, score_scale]``.

        Raises:
            ValueError: If the formula contains disallowed AST nodes or
                references an unknown variable.
        """
        variables = {k: float(v) for k, v in dimension_scores.items()}
        result = _safe_eval(self.formula, variables)
        clamped = float(max(0.0, min(float(self.score_scale), result)))
        if clamped != result:
            log.warning(
                "ScoringEngine formula result %.4f clamped to %.4f (scale 0–%s).",
                result, clamped, self.score_scale,
            )
        return clamped


# ---------------------------------------------------------------------------
# VerdictRouter
# ---------------------------------------------------------------------------


class ScoredVerdict(NamedTuple):
    verdict: str                       # "PUBLISH" or "SKIP"
    score: float                       # final computed score
    notes: str                         # editorial notes from moderator
    dimension_scores: dict[str, int]   # raw per-dimension values


# Extracts NOTES line per item.
# Same tempered-greedy-token strategy as _SCORES_LINE_RE:
# (?:(?!^ITEM\s+\d)[\s\S])*? prevents the match from crossing an ITEM boundary.
# ^NOTES: with MULTILINE captures exactly one line per item.
_ITEM_NOTES_RE = re.compile(
    r"^ITEM\s+(\d+)(?:(?!^ITEM\s+\d)[\s\S])*?^NOTES:\s*(.+?)$",
    re.IGNORECASE | re.MULTILINE,
)


class VerdictRouter:
    """Route items to PUBLISH/SKIP based on computed score vs threshold."""

    def __init__(
        self,
        dimensions: list[str],
        score_scale: int,
        formula: str,
        threshold: float,
    ) -> None:
        """Initialise the router.

        Args:
            dimensions: Ordered list of score dimension names.
            score_scale: Maximum value of the dimension scale (e.g. 10).
            formula: Arithmetic expression referencing dimension names as variables.
            threshold: Minimum score required for a PUBLISH verdict.
        """
        self._parser = ScoreParser(dimensions=dimensions, score_scale=score_scale)
        self._engine = ScoringEngine(formula=formula, score_scale=score_scale)
        self.threshold = threshold

    def route(self, synthesis: str, item_count: int) -> list[ScoredVerdict]:
        """Return one ScoredVerdict per item.

        Score is computed from dimension values regardless of the AI-written verdict;
        threshold comparison is the authoritative PUBLISH/SKIP decision.

        Args:
            synthesis: Full synthesis string produced by the moderator LLM.
            item_count: Expected number of items; result list length equals this.

        Returns:
            A list of length *item_count* of :class:`ScoredVerdict` instances.
        """
        all_scores = self._parser.parse_batch(synthesis, item_count)

        # Normalise once for NOTES extraction (parse_batch normalises its own copy)
        normalised = _normalize_synthesis(synthesis)

        # Extract notes per item
        notes_map: dict[int, str] = {}
        for m in _ITEM_NOTES_RE.finditer(normalised):
            idx = int(m.group(1))
            notes_map[idx] = m.group(2).strip()

        results = []
        for i, dim_scores in enumerate(all_scores, 1):
            score = self._engine.score(dim_scores)
            verdict = "PUBLISH" if score >= self.threshold else "SKIP"
            notes = notes_map.get(i, "")
            results.append(ScoredVerdict(
                verdict=verdict,
                score=score,
                notes=notes,
                dimension_scores=dim_scores,
            ))
        return results
