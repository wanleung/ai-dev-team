"""
SkillLoader: discovers, detects, and injects skill content into agent prompts.

Skills are markdown files with YAML frontmatter stored in skills/ (local)
or fetched from a remote marketplace GitHub repo.
"""
from __future__ import annotations

import re
import warnings
from heapq import heappop, heappush
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
    "junior_engineer":     "Junior Engineers",
    "senior_engineer":     "Senior Engineers",
    "tier_reviewer":       "Tier Reviewers",
    "code_reviewer":       "Code Reviewers",
    "qa_planner":          "QA Planners",
    "qa_engineer":         "QA Engineers",
    "deployment_tester":   "Deployment Testers",
}


_KNOWN_FRONTMATTER_KEYS = {
    "name", "description", "version", "roles", "tags", "source",
    "required_roles", "depends_on", "min_version",
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
    # Roles that MUST be present in the roles dict for this skill to be usable.
    required_roles: list[str] = field(default_factory=list)
    # Names of other skills that must be loaded before this one.
    depends_on: list[str] = field(default_factory=list)
    # Minimum skill version string (e.g. '1.2.0'). Empty = no constraint.
    min_version: str = ""


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
        config: Optional[dict] = None,
        local_skills_dir: Optional[Path] = None,
    ) -> None:
        """Initialise SkillLoader from a config dict.

        Args:
            config: Full application config dict. Reads from config["skills"].
                    Defaults to an empty dict if not provided.
            local_skills_dir: Override path to local skills directory (used in tests).
        """
        if config is None:
            config = {}
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

    def init(self, update: bool = False) -> "SkillLoader":
        """Scan local skills and optionally fetch marketplace index.

        Args:
            update: When True, forces re-fetch of marketplace skills even if cached.

        Returns:
            self, to allow method chaining: ``SkillLoader(...).init()``.
        """
        self._local_skills = self._load_dir(self._local_dir)
        if self._marketplace_repo:
            self._marketplace_skills = self._load_marketplace(update=update)
        return self

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

        unknown_keys = set(meta.keys()) - _KNOWN_FRONTMATTER_KEYS
        if unknown_keys:
            warnings.warn(
                f"[skills] Unknown frontmatter key(s) in {path.name}: "
                f"{sorted(unknown_keys)}. Known keys: {sorted(_KNOWN_FRONTMATTER_KEYS)}"
            )

        required_roles_raw = meta.get("required_roles", [])
        if not isinstance(required_roles_raw, list):
            required_roles_raw = []

        depends_on_raw = meta.get("depends_on", [])
        if not isinstance(depends_on_raw, list):
            depends_on_raw = []

        return SkillEntry(
            name=name,
            description=str(meta.get("description", "")),
            version=str(meta.get("version", "1.0.0")),
            roles={k: bool(v) for k, v in roles_raw.items()},
            tags=[str(t).lower() for t in meta.get("tags", [])],
            source=str(meta.get("source", "local")),
            raw_body=match.group(2),
            required_roles=[str(r) for r in required_roles_raw],
            depends_on=[str(d) for d in depends_on_raw],
            min_version=str(meta.get("min_version", "")),
        )

    @staticmethod
    def _check_min_version(version: str, min_version: str) -> bool:
        """Return True if *version* >= *min_version* using PEP 440 semantics where possible.

        Uses ``packaging.version.Version`` for correct pre-release ordering (e.g. rc1 < stable).
        Falls back to naive tuple comparison if ``packaging`` is not installed or the version
        strings are not valid PEP 440 versions, logging a warning in that case.

        Args:
            version: The skill's declared version (e.g. ``"1.2.0"``).
            min_version: The minimum required version (e.g. ``"2.0.0"``). Empty = no constraint.

        Returns:
            True if version meets or exceeds min_version; False otherwise.
        """
        if not min_version:
            return True

        try:
            from packaging.version import Version, InvalidVersion
            try:
                return Version(version) >= Version(min_version)
            except InvalidVersion:
                import logging as _logging
                _logging.getLogger(__name__).warning(
                    "[skills] Non-PEP-440 version string %r or %r — falling back to tuple comparison",
                    version,
                    min_version,
                )
        except ImportError:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "[skills] 'packaging' not installed — pre-release version comparison may be inaccurate"
            )

        # Tuple-based fallback
        def _parse(v: str) -> tuple[int, ...]:
            parts = re.split(r"[.\-]", v.strip())
            result = []
            for p in parts[:3]:
                try:
                    result.append(int(p))
                except ValueError:
                    result.append(0)
            while len(result) < 3:
                result.append(0)
            return tuple(result)

        return _parse(version) >= _parse(min_version)

    # ── Detection ─────────────────────────────────────────────────────────────

    def _resolve_dependencies(
        self,
        matched: list[SkillEntry],
        skill_map: dict[str, SkillEntry],
    ) -> list[SkillEntry]:
        """Expand *matched* with missing dependencies and return topologically sorted list.

        Uses Kahn's algorithm. Raises ValueError on circular dependencies or missing deps.

        Args:
            matched: Skills selected by score (may be missing dependencies).
            skill_map: All available skills keyed by name.

        Returns:
            Topologically sorted list (dependencies before dependents).

        Raises:
            ValueError: If a skill listed in ``depends_on`` is not present in
                ``skill_map`` (missing or uninstalled dependency).
            ValueError: If a circular dependency is detected among the skills.
        """
        # Expand: pull in any missing dependencies transitively
        needed: dict[str, SkillEntry] = {s.name: s for s in matched}
        rank = {skill.name: index for index, skill in enumerate(matched)}
        next_rank = len(rank)
        queue = list(matched)
        while queue:
            skill = queue.pop(0)
            for dep_name in skill.depends_on:
                if dep_name not in needed:
                    if dep_name in skill_map:
                        dep = skill_map[dep_name]
                        needed[dep_name] = dep
                        rank[dep_name] = next_rank
                        next_rank += 1
                        queue.append(dep)
                    else:
                        raise ValueError(
                            f"[skills] Skill '{skill.name}' depends_on '{dep_name}' "
                            f"which is not loaded. Ensure all required skills are installed."
                        )

        # Kahn's algorithm for topological sort
        # Build in-degree count and adjacency list within the needed set
        in_degree: dict[str, int] = {name: 0 for name in needed}
        dependents: dict[str, list[str]] = {name: [] for name in needed}

        for name, skill in needed.items():
            for dep_name in skill.depends_on:
                if dep_name in needed:
                    in_degree[name] += 1
                    dependents[dep_name].append(name)

        # Start with skills that have no dependencies
        ready = [(rank[name], name) for name, deg in in_degree.items() if deg == 0]
        ready.sort()
        sorted_names: list[str] = []

        while ready:
            _, name = heappop(ready)
            sorted_names.append(name)
            for dependent in dependents[name]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    heappush(ready, (rank[dependent], dependent))

        if len(sorted_names) != len(needed):
            cycle_nodes = [n for n in needed if n not in sorted_names]
            raise ValueError(
                f"[skills] Circular dependency detected among: {sorted(cycle_nodes)}"
            )

        return [needed[name] for name in sorted_names]

    def detect(self, context: SkillContext) -> list[SkillEntry]:
        """Return skills relevant to the given context with dependency-aware ordering.

        Always includes ``always_load`` skills and explicitly requested skills.
        Auto-detection searches ``issue_body`` and ``repo_languages`` for tag matches.

        Args:
            context: A SkillContext describing the current task.

        Returns:
            Ordered list of matched SkillEntry objects where dependencies always
            appear before dependents, while otherwise preserving the original
            score-based order (highest score first, then name).
        """
        all_skills = self._local_skills + self._marketplace_skills
        # Filter out skills that don't meet their own min_version constraint
        filtered_skills: list[SkillEntry] = []
        for skill in all_skills:
            if not self._check_min_version(skill.version, skill.min_version):
                warnings.warn(
                    f"[skills] Skill '{skill.name}' version '{skill.version}' "
                    f"does not meet min_version '{skill.min_version}' — excluding."
                )
            else:
                filtered_skills.append(skill)
        all_skills = filtered_skills
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
        matched_skills = [skill_map[n] for n in matched_names]
        return self._resolve_dependencies(matched_skills, skill_map)

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

            # Check required_roles: if the skill declares required roles and this
            # role is not among them, skip for this role invocation.
            if skill.required_roles and role not in skill.required_roles:
                warnings.warn(
                    f"[skills] Skill '{skill.name}' has required_roles {skill.required_roles} "
                    f"but is being injected for role '{role}' — skipping."
                )
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
            if not safe_name or safe_name in (".", ".."):
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

    # ── Structured prompt extraction ──────────────────────────────────────────

    def build_structured_prompt(self, skill: SkillEntry, role: str) -> str:
        """Extract the role-scoped content block from a skill's raw_body.

        Looks for a markdown section headed ``## <role>`` (case-insensitive) and
        returns everything up to the next ``##`` heading. Falls back to the full
        ``raw_body`` if no matching section is found.

        Args:
            skill: The parsed SkillEntry.
            role: The agent role to extract content for (e.g. "engineer").

        Returns:
            The role-scoped content string, stripped of leading/trailing whitespace.
        """
        lines = skill.raw_body.splitlines(keepends=True)
        in_section = False
        section_lines: list[str] = []

        for line in lines:
            if re.match(rf"^##\s+{re.escape(role)}\s*$", line, re.IGNORECASE):
                in_section = True
                continue
            if in_section:
                if re.match(r"^##\s+", line):
                    break
                section_lines.append(line)

        if in_section:
            # Section was found (even if empty) — return its content, not the fallback.
            return "".join(section_lines).strip()
        return skill.raw_body.strip()
