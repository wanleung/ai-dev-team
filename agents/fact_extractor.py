"""FactExtractorAgent — pulls atomic, structured facts out of a completed pipeline run.

A run summary is a paragraph, and paragraphs compress badly: a specific
detail survives the first LLM re-summarization (the monthly rollup) but is
the first thing dropped in the second (the quarterly rollup). This agent
extracts the individual facts *before* that happens, so each one is stored
as its own row (memory_store.py tier='fact') instead of a clause inside a
sentence that might not survive two compression passes.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from .base_agent import BaseAgent

ROLE_FILE = Path(__file__).parent.parent / "roles" / "fact_extractor.md"

_VALID_TYPES = {"decision", "issue", "learning", "status"}
_DEFAULT_TYPE = "status"


class FactExtractorAgent(BaseAgent):
    role_name = "fact_extractor"

    def extract(
        self,
        repo: str,
        requirement: str,
        prd: str,
        design: str,
        review: str,
        summary: str,
        existing_facts: Optional[list[dict]] = None,
    ) -> list[dict]:
        """Extract atomic facts from a completed pipeline run.

        Args:
            existing_facts: Optional current facts for this repo (the shape
                MemoryStore.list_facts() returns — needs "id", "entity",
                "type", "fact"). When given, the LLM may mark a new fact as
                updating one of these via a "supersedes" id in its output —
                supermemory calls this the "updates" relation. Facts the new
                extraction doesn't touch are left alone.

        Returns:
            List of {"type", "entity", "fact", "resolved"} dicts, one per
            atomic fact, each optionally carrying a "supersedes" int key.
            Empty list on a run with nothing fact-worthy, or on unparseable
            LLM output — this is best-effort; callers should never treat an
            empty result as an error.
        """
        prompt = self._build_prompt(repo, requirement, prd, design, review, summary, existing_facts)
        raw = self.call(prompt)
        valid_ids = {f["id"] for f in existing_facts} if existing_facts else set()
        return self._parse_facts(raw, valid_ids)

    def _build_prompt(
        self,
        repo: str,
        requirement: str,
        prd: str,
        design: str,
        review: str,
        summary: str,
        existing_facts: Optional[list[dict]],
    ) -> str:
        existing_block = ""
        if existing_facts:
            lines = "\n".join(
                f'- id={f["id"]} [{f["type"]}] {f["entity"]}: {f["fact"]}' for f in existing_facts
            )
            existing_block = f"""

## Existing facts for this repo (reference by id if this run updates one)
{lines}"""

        return f"""Extract atomic facts from this completed pipeline run.

## Repo: {repo}
## Requirement:
{requirement[:500]}

## PRD (excerpt):
{prd[:1000]}

## Architecture Design (excerpt):
{design[:1000]}

## Code Review Notes:
{review[:800]}

## Run summary (already written — do not just restate this):
{summary[:1200]}
{existing_block}

---

Follow the fact types, atomicity rule, and JSON output format from your role instructions.
If a new fact updates or replaces one of the existing facts listed above (e.g. a fixed issue,
a changed decision), include "supersedes": <that fact's id> on it."""

    def _parse_facts(self, raw: str, valid_supersede_ids: Optional[set[int]] = None) -> list[dict]:
        """Validate and normalise the LLM's parsed JSON array. Never raises.

        Args:
            valid_supersede_ids: Known existing-fact ids the LLM was shown.
                A "supersedes" value not in this set (hallucinated, or no
                existing facts were shown at all) is dropped rather than
                trusted — supersession only applies to ids we know are real.
        """
        parsed = self._parse_json_array(raw)
        if parsed is None:
            return []

        valid_ids = valid_supersede_ids or set()
        facts: list[dict] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            fact_text = str(item.get("fact", "")).strip()
            if not fact_text:
                continue
            fact_type = str(item.get("type", "")).strip().lower()
            if fact_type not in _VALID_TYPES:
                fact_type = _DEFAULT_TYPE
            entity = str(item.get("entity", "")).strip()
            resolved = bool(item.get("resolved", False))
            out = {"type": fact_type, "entity": entity, "fact": fact_text, "resolved": resolved}

            supersedes = item.get("supersedes")
            if supersedes is not None:
                try:
                    supersedes_id = int(supersedes)
                except (TypeError, ValueError):
                    supersedes_id = None
                if supersedes_id in valid_ids:
                    out["supersedes"] = supersedes_id
            facts.append(out)
        return facts

    def _parse_json_array(self, raw: str) -> list | None:
        """Parse a JSON array from LLM response text.

        Handles markdown code fences and prose wrapped around the array
        (falls back to a regex extraction of the first [...] block).
        Returns None — never raises — on anything unparseable.
        """
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            result = json.loads(cleaned)
            return result if isinstance(result, list) else None
        except json.JSONDecodeError:
            m = re.search(r"\[.*\]", cleaned, re.DOTALL)
            if not m:
                return None
            try:
                result = json.loads(m.group(0))
                return result if isinstance(result, list) else None
            except json.JSONDecodeError:
                return None
