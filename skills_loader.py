"""
SkillLoader: discovers, detects, and injects skill content into agent prompts.

Skills are markdown files with YAML frontmatter stored in skills/ (local)
or fetched from a remote marketplace GitHub repo.
"""
from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


# ── Security: allowed URL prefixes for marketplace fetches ────────────────────
ALLOWED_URL_PREFIXES = ("https://raw.githubusercontent.com/",)

# ── Role name mapping ─────────────────────────────────────────────────────────
# Maps internal role key → markdown section header suffix
_ROLE_SECTION_MAP: dict[str, str] = {
    "product_manager":     "Product Managers",
    "pm_reviewer":         "PM Reviewers",
    "architect":           "Architects",
    "architect_reviewer":  "Architect Reviewers",
    "engineer":            "Engineers",
    "code_reviewer":       "Code Reviewers",
    "qa_planner":          "QA Planners",
    "qa_engineer":         "QA Engineers",
    "deployment_tester":   "Deployment Testers",
}


@dataclass
class SkillEntry:
    """Parsed skill from a markdown file."""

    name: str
    description: str
    version: str
    roles: dict[str, bool]   # role_key → enabled
    tags: list[str]
    source: str              # "local" or "marketplace"
    raw_body: str            # full markdown body (below frontmatter)


@dataclass
class SkillBlock:
    """A role-scoped content block ready for prompt injection."""

    name: str
    source: str
    content: str             # extracted section text for the specific role


@dataclass
class SkillContext:
    """Context used for skill detection."""

    issue_body: str
    explicit_skills: list[str]           # parsed from "skills: name1, name2" in issue
    repo_languages: list[str]            # language names from GitHub Linguist (lowercase)


class SkillLoader:
    """Loads, detects, and injects skills for ai-software-house agents."""

    def __init__(
        self,
        config: dict,
        local_skills_dir: Optional[Path] = None,
    ) -> None:
        """Initialise SkillLoader from a config dict.

        Args:
            config: Full application config dict. Reads from config["skills"].
            local_skills_dir: Override path to local skills directory (used in tests).
        """
        skills_cfg = config.get("skills", {})
        self._always_load: list[str] = skills_cfg.get("always_load", [])
        self._marketplace_repo: str = skills_cfg.get("marketplace_repo", "")
        raw_cache = skills_cfg.get("cache_dir", "") or ""
        self._cache_dir: Optional[Path] = Path(raw_cache).expanduser() if raw_cache else None
        self._fetch_timeout: int = int(skills_cfg.get("fetch_timeout", 5))
        self._local_dir: Path = local_skills_dir or Path("skills")
        self._local_skills: list[SkillEntry] = []
        self._marketplace_skills: list[SkillEntry] = []

    # ── Initialisation ────────────────────────────────────────────────────────

    def init(self, update: bool = False) -> None:
        """Scan local skills and optionally fetch marketplace index.

        Args:
            update: When True, forces re-fetch of marketplace skills even if cached.
        """
        self._local_skills = self._load_dir(self._local_dir)
        if self._marketplace_repo:
            self._marketplace_skills = self._load_marketplace(update=update)

    def _load_dir(self, directory: Path) -> list[SkillEntry]:
        """Parse all .md files in a directory into SkillEntry objects.

        Args:
            directory: Path to the directory containing skill markdown files.

        Returns:
            List of successfully parsed SkillEntry objects (malformed files are skipped).
        """
        skills: list[SkillEntry] = []
        if not directory.is_dir():
            return skills
        for md_file in sorted(directory.glob("*.md")):
            entry = self._parse_skill_file(md_file)
            if entry is not None:
                skills.append(entry)
        return skills

    def _parse_skill_file(self, path: Path) -> Optional[SkillEntry]:
        """Parse a single skill markdown file.

        Args:
            path: Path to the markdown file.

        Returns:
            A SkillEntry if parsing succeeds, None on any error (with a warning).
        """
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            warnings.warn(f"[skills] Cannot read {path}: {exc}")
            return None

        # Split YAML frontmatter (between --- delimiters)
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
        if not match:
            warnings.warn(f"[skills] No frontmatter found in {path.name}, skipping.")
            return None

        try:
            meta = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError as exc:
            warnings.warn(f"[skills] Invalid YAML frontmatter in {path.name}: {exc}, skipping.")
            return None

        name = str(meta.get("name", path.stem))
        roles_raw = meta.get("roles", {})
        if not isinstance(roles_raw, dict):
            roles_raw = {}

        return SkillEntry(
            name=name,
            description=str(meta.get("description", "")),
            version=str(meta.get("version", "1.0.0")),
            roles={k: bool(v) for k, v in roles_raw.items()},
            tags=[str(t).lower() for t in meta.get("tags", [])],
            source=str(meta.get("source", "local")),
            raw_body=match.group(2),
        )

    # ── Detection ─────────────────────────────────────────────────────────────

    def detect(self, context: SkillContext) -> list[SkillEntry]:
        """Return skills relevant to the given context, ranked by tag overlap.

        Always includes ``always_load`` skills and explicitly requested skills.
        Auto-detection searches ``issue_body`` and ``repo_languages`` for tag matches.

        Args:
            context: A SkillContext describing the current task.

        Returns:
            Ordered list of matched SkillEntry objects (highest score first).
        """
        all_skills = self._local_skills + self._marketplace_skills
        skill_map = {s.name: s for s in all_skills}

        # Combine all context text for tag scanning (lowercase)
        context_text = (context.issue_body + " " + " ".join(context.repo_languages)).lower()

        scores: dict[str, int] = {}

        # always_load: score = 999 (always included)
        for name in self._always_load:
            if name in skill_map:
                scores[name] = 999
            else:
                warnings.warn(f"[skills] always_load skill '{name}' not found, skipping.")

        # explicit skills requested in issue body
        for name in context.explicit_skills:
            if name in skill_map:
                scores[name] = max(scores.get(name, 0), 998)
            else:
                warnings.warn(f"[skills] Explicit skill '{name}' not found, skipping.")

        # auto-detect by tag matching
        for skill in all_skills:
            if skill.name in scores:
                continue  # already pinned by always_load or explicit
            hit_count = sum(
                1 for tag in skill.tags
                if re.search(r"\b" + re.escape(tag) + r"\b", context_text)
            )
            if hit_count > 0:
                scores[skill.name] = hit_count

        # Sort by score descending, then name for stable ordering
        matched_names = sorted(scores, key=lambda n: (-scores[n], n))
        return [skill_map[n] for n in matched_names]

    # ── Role-scoped injection ─────────────────────────────────────────────────

    def for_role(self, role: str, matched_skills: list[SkillEntry]) -> list[SkillBlock]:
        """Return content blocks for a specific agent role from matched skills.

        Skills with the role disabled in their frontmatter (``role: false``) are
        excluded entirely. Skills that are enabled but have no matching section in
        their body are also silently skipped.

        Args:
            role: Internal role key (e.g. ``"engineer"``, ``"qa_engineer"``).
            matched_skills: List of skills returned by :meth:`detect`.

        Returns:
            List of SkillBlock objects containing role-specific content.
        """
        section_header = _ROLE_SECTION_MAP.get(role)
        if section_header is None:
            warnings.warn(f"[skills] Unknown role '{role}', no section map entry found.")
            return []
        blocks: list[SkillBlock] = []

        for skill in matched_skills:
            # Check role is enabled in frontmatter
            if not skill.roles.get(role, False):
                continue

            # Extract the role-specific section
            content = self._extract_section(skill.raw_body, section_header)
            if content:
                blocks.append(SkillBlock(name=skill.name, source=skill.source, content=content.strip()))

        return blocks

    def _extract_section(self, body: str, section_suffix: Optional[str]) -> str:
        """Extract a ``## For <section_suffix>`` block from the markdown body.

        Args:
            body: The raw markdown body text (below the frontmatter).
            section_suffix: The suffix after ``## For `` to match (e.g. ``"Engineers"``).

        Returns:
            Stripped text content of the section, or an empty string if not found.
        """
        if not section_suffix:
            return ""

        # Match "## For <suffix>" (case-insensitive), capture until next ## or end
        pattern = (
            r"(?im)^##\s+For\s+" + re.escape(section_suffix) + r"\s*$"
            r"(.*?)"
            r"(?=^##\s|\Z)"
        )
        m = re.search(pattern, body, re.DOTALL | re.MULTILINE)
        return m.group(1).strip() if m else ""

    # ── Prompt rendering ──────────────────────────────────────────────────────

    def render_prompt_block(self, blocks: list[SkillBlock]) -> str:
        """Render skill blocks as a prompt section for injection into agent system prompts.

        Args:
            blocks: List of SkillBlock objects from :meth:`for_role`.

        Returns:
            A formatted markdown string to prepend/append to agent system prompts,
            or an empty string if no blocks are provided.
        """
        if not blocks:
            return ""
        lines = [
            "## Skills Loaded\n",
            "The following skills are active for this task. Read and follow their guidance. "
            "Note in your response which skills you applied and how.\n",
        ]
        for block in blocks:
            lines.append(f"### {block.name} ({block.source})\n")
            lines.append(block.content)
            lines.append("")
        return "\n".join(lines)

    # ── Marketplace ───────────────────────────────────────────────────────────

    def _load_marketplace(self, update: bool = False) -> list[SkillEntry]:
        """Fetch skills from the remote marketplace GitHub repo.

        Falls back to a local cache if the network request fails. If no cache
        is available, returns an empty list with a warning.

        Args:
            update: When True, always re-fetch from remote even if cached.

        Returns:
            List of SkillEntry objects sourced from the marketplace.
        """
        import json
        import urllib.request

        if not self._marketplace_repo:
            return []

        owner_repo = self._marketplace_repo
        index_url = f"https://raw.githubusercontent.com/{owner_repo}/main/skills-index.json"

        # Critical 2: validate marketplace index URL against allowlist
        if not index_url.startswith(ALLOWED_URL_PREFIXES):
            warnings.warn(
                f"[skills] Marketplace index URL '{index_url}' is not in the allowed prefixes, skipping."
            )
            return []

        # Determine cache directory
        cache_dir = self._cache_dir or Path.home() / ".ai-software-house" / "skills"
        cache_dir.mkdir(parents=True, exist_ok=True)
        index_cache = cache_dir / "skills-index.json"

        # Fetch index
        index_data: list[dict] = []
        try:
            with urllib.request.urlopen(index_url, timeout=self._fetch_timeout) as resp:
                index_data = json.loads(resp.read().decode())
            index_cache.write_text(json.dumps(index_data), encoding="utf-8")
        except Exception as exc:
            warnings.warn(f"[skills] Marketplace fetch failed ({exc}). ")
            if index_cache.exists():
                warnings.warn("[skills] Using cached marketplace index.")
                index_data = json.loads(index_cache.read_text(encoding="utf-8"))
            else:
                warnings.warn("[skills] No cache available, skipping marketplace skills.")
                return []

        # Critical 3: validate index_data is a list
        if not isinstance(index_data, list):
            warnings.warn("[skills] Marketplace index is not a JSON array, skipping marketplace skills.")
            return []

        # Fetch/cache individual skill files
        skills: list[SkillEntry] = []
        for item in index_data:
            skill_name = item.get("name", "")
            skill_url = item.get("url", "")

            # Critical 1: sanitise skill_name to prevent path traversal
            safe_name = Path(skill_name).name
            if not safe_name or safe_name == ".":
                warnings.warn(f"[skills] Invalid skill name '{skill_name}', skipping.")
                continue

            # Critical 2: validate skill URL against allowlist
            if not skill_url.startswith(ALLOWED_URL_PREFIXES):
                warnings.warn(
                    f"[skills] Marketplace skill '{safe_name}' has untrusted URL '{skill_url}', skipping."
                )
                continue

            skill_cache = cache_dir / f"{safe_name}.md"

            if skill_cache.exists() and not update:
                entry = self._parse_skill_file(skill_cache)
            else:
                try:
                    with urllib.request.urlopen(skill_url, timeout=self._fetch_timeout) as resp:
                        skill_content = resp.read().decode()
                    skill_cache.write_text(skill_content, encoding="utf-8")
                    entry = self._parse_skill_file(skill_cache)
                except Exception as exc:
                    warnings.warn(f"[skills] Failed to fetch marketplace skill '{safe_name}': {exc}")
                    entry = self._parse_skill_file(skill_cache) if skill_cache.exists() else None

            if entry is not None:
                entry.source = "marketplace"
                skills.append(entry)

        return skills

    def update_marketplace(self) -> None:
        """Re-fetch marketplace index and all cached skills."""
        self._marketplace_skills = self._load_marketplace(update=True)
