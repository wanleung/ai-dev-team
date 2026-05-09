# T3-B: Skill Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire up three `SkillEntry` fields that were added in T2-E but never enforced: `depends_on` (topological ordering of skills), `required_roles` (validate roles before injection), and `min_version` (semver constraint on skill version). These were directly inspired by the superpowers marketplace skill system, which itself uses `depends_on` for skill ordering.

**Architecture:**
- `depends_on` → `detect()` appends dependency skills automatically and raises on cycles. Uses Kahn's algorithm (iterative topological sort, no external deps).
- `required_roles` → `for_role()` skips a skill and emits `UserWarning` if the requested role is not in `required_roles` AND `required_roles` is non-empty.
- `min_version` → `detect()` compares `version` against `min_version` using tuple comparison on `(major, minor, patch)` integers; warns and excludes skills that don't meet the constraint.

**Tech Stack:** Python 3.11+, pytest. No new dependencies — semver parsing is done inline with `re` (already imported).

**Branch:** `t3-b-skill-wiring` (from master)

---

### Task 1: `depends_on` topological sort in `detect()`

**Files:**
- Modify: `skills_loader.py` (`detect()` method ~line 198; add `_resolve_dependencies()` helper)
- Test: `tests/test_skills_loader_structured.py` (add 3 tests)

**Context:** `SkillEntry.depends_on` is a list of skill names that must be included before this skill. Currently `detect()` ranks skills by tag score but ignores dependencies — if skill B depends_on skill A, and A scores higher than B, the order is correct by coincidence only. If A doesn't match the context at all, it's silently missing. Fix: after scoring, call `_resolve_dependencies()` which uses Kahn's algorithm to expand the matched set (pulling in dependencies that weren't matched directly) and reorder by dependency graph, raising `ValueError` on cycles.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_skills_loader_structured.py`:

```python
def _make_skill(tmp_path, name, depends_on=None, tags=None, version="1.0.0"):
    """Helper: write a minimal skill file and return its path."""
    deps_str = ""
    if depends_on:
        deps_str = f"depends_on: [{', '.join(depends_on)}]\n"
    tags_str = f"tags: [{', '.join(tags or [])}]\n"
    content = (
        f"---\nname: {name}\ndescription: {name} skill\nversion: {version}\n"
        f"roles: {{engineer: true}}\n{deps_str}{tags_str}---\n\n# {name}\nContent of {name}.\n"
    )
    skill_file = tmp_path / f"{name}.md"
    skill_file.write_text(content)
    return skill_file


def test_detect_pulls_in_dependency_not_directly_matched(tmp_path):
    """detect() includes skill B when skill A depends_on B, even if B has no tag match."""
    _make_skill(tmp_path, "base-skill", tags=["base"])
    _make_skill(tmp_path, "advanced-skill", depends_on=["base-skill"], tags=["advanced"])

    loader = SkillLoader(local_skills_dir=tmp_path).init()
    ctx = SkillContext(issue_body="advanced", explicit_skills=[], repo_languages=[])
    result = loader.detect(ctx)

    names = [s.name for s in result]
    assert "base-skill" in names, "Dependency should be pulled in automatically"
    assert "advanced-skill" in names


def test_detect_dependency_ordered_before_dependent(tmp_path):
    """detect() places base-skill before advanced-skill when advanced depends_on base."""
    _make_skill(tmp_path, "base-skill", tags=["base"])
    _make_skill(tmp_path, "advanced-skill", depends_on=["base-skill"], tags=["advanced"])

    loader = SkillLoader(local_skills_dir=tmp_path).init()
    ctx = SkillContext(issue_body="base advanced", explicit_skills=[], repo_languages=[])
    result = loader.detect(ctx)

    names = [s.name for s in result]
    assert names.index("base-skill") < names.index("advanced-skill"), (
        f"base-skill must come before advanced-skill, got: {names}"
    )


def test_detect_raises_on_circular_dependency(tmp_path):
    """detect() raises ValueError when skills have a circular dependency."""
    import warnings
    _make_skill(tmp_path, "skill-x", depends_on=["skill-y"], tags=["x"])
    _make_skill(tmp_path, "skill-y", depends_on=["skill-x"], tags=["y"])

    loader = SkillLoader(local_skills_dir=tmp_path).init()
    ctx = SkillContext(issue_body="x y", explicit_skills=[], repo_languages=[])
    with pytest.raises(ValueError, match="[Cc]ircular"):
        loader.detect(ctx)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/wanleung/Projects/ai-software-house
python3 -m pytest tests/test_skills_loader_structured.py::test_detect_pulls_in_dependency_not_directly_matched tests/test_skills_loader_structured.py::test_detect_dependency_ordered_before_dependent tests/test_skills_loader_structured.py::test_detect_raises_on_circular_dependency -v
```

Expected: All 3 FAIL (dependencies not pulled in, no order enforcement, no cycle detection).

- [ ] **Step 3: Add `_resolve_dependencies()` to `SkillLoader`**

Add this method to the `SkillLoader` class (before `detect()`):

```python
def _resolve_dependencies(
    self,
    matched: list[SkillEntry],
    skill_map: dict[str, SkillEntry],
) -> list[SkillEntry]:
    """Expand *matched* with missing dependencies and return topologically sorted list.

    Uses Kahn's algorithm. Raises ValueError on circular dependencies.

    Args:
        matched: Skills selected by score (may be missing dependencies).
        skill_map: All available skills keyed by name.

    Returns:
        Topologically sorted list (dependencies before dependents).

    Raises:
        ValueError: If a circular dependency is detected among the skills.
    """
    # Expand: pull in any missing dependencies transitively
    needed: dict[str, SkillEntry] = {s.name: s for s in matched}
    queue = list(matched)
    while queue:
        skill = queue.pop(0)
        for dep_name in skill.depends_on:
            if dep_name not in needed:
                if dep_name in skill_map:
                    dep = skill_map[dep_name]
                    needed[dep_name] = dep
                    queue.append(dep)
                else:
                    warnings.warn(
                        f"[skills] Skill '{skill.name}' depends_on '{dep_name}' "
                        f"which is not loaded — skipping dependency."
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
    ready = sorted(name for name, deg in in_degree.items() if deg == 0)
    sorted_names: list[str] = []

    while ready:
        name = ready.pop(0)
        sorted_names.append(name)
        for dependent in sorted(dependents[name]):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                ready.append(dependent)

    if len(sorted_names) != len(needed):
        cycle_nodes = [n for n in needed if n not in sorted_names]
        raise ValueError(
            f"[skills] Circular dependency detected among: {sorted(cycle_nodes)}"
        )

    return [needed[name] for name in sorted_names]
```

- [ ] **Step 4: Call `_resolve_dependencies()` at the end of `detect()`**

In `detect()`, replace the final two lines:

**Before:**
```python
    # Sort by score descending, then name for stable ordering
    matched_names = sorted(scores, key=lambda n: (-scores[n], n))
    return [skill_map[n] for n in matched_names]
```

**After:**
```python
    # Sort by score descending, then name for stable ordering
    matched_names = sorted(scores, key=lambda n: (-scores[n], n))
    matched_skills = [skill_map[n] for n in matched_names]
    return self._resolve_dependencies(matched_skills, skill_map)
```

- [ ] **Step 5: Run tests**

```bash
python3 -m pytest tests/test_skills_loader_structured.py -v
```

Expected: All pass (including existing 7 tests + 3 new ones).

- [ ] **Step 6: Commit**

```bash
git add skills_loader.py tests/test_skills_loader_structured.py
git commit -m "feat(skills): implement depends_on topological sort in SkillLoader.detect()"
```

---

### Task 2: Enforce `required_roles` in `for_role()`

**Files:**
- Modify: `skills_loader.py` (`for_role()` method ~line 249)
- Test: `tests/test_skills_loader_structured.py` (add 2 tests)

**Context:** `SkillEntry.required_roles` lists roles that MUST be present for this skill to be usable. Currently `for_role()` only checks `skill.roles.get(role, False)` (whether the role is enabled in frontmatter). It never checks `required_roles`. If a skill declares `required_roles: [architect, engineer]` but is loaded in a context with only `engineer`, it should be excluded with a warning. Fix: in `for_role()`, before the section extraction, check that `role` is in `skill.required_roles` if `required_roles` is non-empty.

Note: `required_roles` is not a role-enablement gate (that's `roles`). It's a "this skill only makes sense when ALL these roles are active in the pipeline". Since `for_role()` is called per-role, the check should be: if `required_roles` is non-empty and `role` is NOT in `required_roles`, skip this skill for this role.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_skills_loader_structured.py`:

```python
def test_for_role_excludes_skill_when_role_not_in_required_roles(tmp_path):
    """for_role() skips a skill if role is not listed in required_roles."""
    content = (
        "---\nname: arch-only\ndescription: arch only\nversion: 1.0.0\n"
        "roles: {engineer: true, architect: true}\n"
        "required_roles: [architect]\n"
        "---\n\n## For Architects\nArch content.\n\n## For Engineers\nEng content.\n"
    )
    (tmp_path / "arch-only.md").write_text(content)

    loader = SkillLoader(local_skills_dir=tmp_path).init()
    ctx = SkillContext(issue_body="", explicit_skills=["arch-only"], repo_languages=[])
    matched = loader.detect(ctx)

    # engineer role: arch-only has required_roles=[architect], engineer is NOT in it → skip
    import warnings
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        blocks = loader.for_role("engineer", matched)
    assert blocks == [], f"Expected no blocks for engineer, got: {blocks}"
    assert any("required_roles" in str(warning.message) for warning in w)


def test_for_role_includes_skill_when_role_in_required_roles(tmp_path):
    """for_role() includes the skill when role IS listed in required_roles."""
    content = (
        "---\nname: arch-only\ndescription: arch only\nversion: 1.0.0\n"
        "roles: {engineer: true, architect: true}\n"
        "required_roles: [architect]\n"
        "---\n\n## For Architect Reviewers\nArch content.\n"
    )
    (tmp_path / "arch-only.md").write_text(content)

    loader = SkillLoader(local_skills_dir=tmp_path).init()
    ctx = SkillContext(issue_body="", explicit_skills=["arch-only"], repo_languages=[])
    matched = loader.detect(ctx)

    blocks = loader.for_role("architect", matched)
    assert len(blocks) == 1
    assert "Arch content" in blocks[0].content
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python3 -m pytest tests/test_skills_loader_structured.py::test_for_role_excludes_skill_when_role_not_in_required_roles tests/test_skills_loader_structured.py::test_for_role_includes_skill_when_role_in_required_roles -v
```

Expected: First test FAILS (engineer gets the block even though required_roles=[architect]).

- [ ] **Step 3: Add `required_roles` check to `for_role()`**

In `skills_loader.py`, in the `for_role()` method, add a check immediately after the `if not skill.roles.get(role, False): continue` line:

```python
    for skill in matched_skills:
        # Check role is enabled in frontmatter
        if not skill.roles.get(role, False):
            continue

        # Check required_roles: if the skill declares required roles and this
        # role is not among them, skip for this role invocation.
        if skill.required_roles and role not in skill.required_roles:
            warnings.warn(
                f"[skills] Skill '{skill.name}' requires roles {skill.required_roles} "
                f"but is being injected for role '{role}' — skipping."
            )
            continue

        # Extract the role-specific section
        content = self._extract_section(skill.raw_body, section_header)
```

- [ ] **Step 4: Run all skill loader tests**

```bash
python3 -m pytest tests/test_skills_loader_structured.py -v
```

Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add skills_loader.py tests/test_skills_loader_structured.py
git commit -m "feat(skills): enforce required_roles constraint in for_role()"
```

---

### Task 3: Enforce `min_version` semver in `detect()`

**Files:**
- Modify: `skills_loader.py` (`detect()` method; add `_check_min_version()` helper)
- Test: `tests/test_skills_loader_structured.py` (add 2 tests)

**Context:** `SkillEntry.min_version` specifies a minimum version string (e.g. `"1.2.0"`) that the skill's own `version` must meet. Currently it's parsed and stored but never compared. Fix: add `_check_min_version(version, min_version)` that parses both as `(major, minor, patch)` tuples and compares; in `detect()`, exclude skills whose version doesn't meet the constraint.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_skills_loader_structured.py`:

```python
def test_detect_excludes_skill_below_min_version(tmp_path):
    """detect() excludes a skill whose version is below min_version."""
    content = (
        "---\nname: old-skill\ndescription: desc\nversion: 1.1.0\n"
        "min_version: 2.0.0\nroles: {engineer: true}\ntags: [python]\n"
        "---\n\nContent.\n"
    )
    (tmp_path / "old-skill.md").write_text(content)

    loader = SkillLoader(local_skills_dir=tmp_path).init()
    ctx = SkillContext(issue_body="python", explicit_skills=[], repo_languages=[])

    import warnings
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = loader.detect(ctx)

    assert all(s.name != "old-skill" for s in result), "Skill below min_version should be excluded"
    assert any("min_version" in str(warning.message) for warning in w)


def test_detect_includes_skill_meeting_min_version(tmp_path):
    """detect() includes a skill whose version meets min_version."""
    content = (
        "---\nname: new-skill\ndescription: desc\nversion: 2.1.0\n"
        "min_version: 2.0.0\nroles: {engineer: true}\ntags: [python]\n"
        "---\n\nContent.\n"
    )
    (tmp_path / "new-skill.md").write_text(content)

    loader = SkillLoader(local_skills_dir=tmp_path).init()
    ctx = SkillContext(issue_body="python", explicit_skills=[], repo_languages=[])
    result = loader.detect(ctx)

    assert any(s.name == "new-skill" for s in result), "Skill meeting min_version should be included"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python3 -m pytest tests/test_skills_loader_structured.py::test_detect_excludes_skill_below_min_version tests/test_skills_loader_structured.py::test_detect_includes_skill_meeting_min_version -v
```

Expected: First test FAILS (old-skill is included even though version 1.1.0 < min_version 2.0.0).

- [ ] **Step 3: Add `_check_min_version()` helper to `SkillLoader`**

Add before `detect()`:

```python
@staticmethod
def _check_min_version(version: str, min_version: str) -> bool:
    """Return True if *version* >= *min_version* (semver-style comparison).

    Parses both strings as ``MAJOR.MINOR.PATCH`` integers. Missing components
    default to 0. Returns True if *min_version* is empty (no constraint).

    Args:
        version: The skill's declared version (e.g. ``"1.2.0"``).
        min_version: The minimum required version (e.g. ``"2.0.0"``). Empty = no constraint.

    Returns:
        True if version meets or exceeds min_version; False otherwise.
    """
    if not min_version:
        return True

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
```

- [ ] **Step 4: Apply version check in `detect()` before scoring**

In `detect()`, after building `all_skills` and `skill_map`, add a version filter:

```python
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
```

- [ ] **Step 5: Run all skill loader tests**

```bash
python3 -m pytest tests/test_skills_loader_structured.py -v
```

Expected: All pass (existing 9 + 2 new = 11 tests).

- [ ] **Step 6: Commit**

```bash
git add skills_loader.py tests/test_skills_loader_structured.py
git commit -m "feat(skills): enforce min_version semver constraint in SkillLoader.detect()"
```

---

### Task 4: Branch, push, PR

- [ ] **Step 1: Create branch and push**

```bash
git checkout -b t3-b-skill-wiring master
# (develop all 3 tasks on this branch)
git push -u origin t3-b-skill-wiring
```

- [ ] **Step 2: Create PR**

```bash
gh pr create \
  --title "feat(skills): T3-B — wire depends_on, required_roles, min_version in SkillLoader" \
  --body "## Summary
Inspired by the superpowers marketplace skill system (which uses \`depends_on\` itself), this PR wires up three SkillEntry fields added in T2-E that were parsed but never enforced:

- **\`depends_on\`**: \`detect()\` now pulls in dependency skills transitively and returns a topologically sorted list (Kahn's algorithm). Raises \`ValueError\` on cycles.
- **\`required_roles\`**: \`for_role()\` now skips a skill with \`UserWarning\` if the requested role is not listed in \`required_roles\` (when non-empty).
- **\`min_version\`**: \`detect()\` now excludes skills whose \`version\` < \`min_version\` with \`UserWarning\`. Parsed as MAJOR.MINOR.PATCH tuples; no external deps.

## Test Plan
- [ ] 7 new tests in \`tests/test_skills_loader_structured.py\`
- [ ] All existing skill loader tests still pass" \
  --base master
```
