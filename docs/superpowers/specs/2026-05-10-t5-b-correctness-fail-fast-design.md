# T5-B: Correctness & Fail-Fast — Design Spec

**Date:** 2026-05-10
**Status:** Approved

## Problem

Four medium-priority correctness gaps after T4:

1. `FileDeadLetterQueue` and `RedisDLQ` retry immediately on `nack()` — no backoff — causing tight failure loops.
2. `SkillLoader._check_min_version()` uses naive string split; `"1.2.0-rc1"` silently becomes `"1.2.0"`, pre-release ordering is wrong.
3. `OutputVerifier.verify()` calls `warnings.warn()` when a required field is missing from `PipelineResult` — should raise `OutputVerificationError` (missing field = verification failure, not a warning).
4. `SkillLoader._resolve_dependencies()` calls `warnings.warn()` when a `depends_on` dep isn't loaded — should raise `ValueError` (load-time misconfiguration).

---

## Design

### 1. DLQ Exponential Backoff

**Problem:** After `nack()`, the entry is immediately available on the next `drain()` call. A failed stage can be re-attempted thousands of times per minute.

**Fix:**
- Add `retry_after: float = 0.0` field to `DLQEntry` (Unix timestamp; 0.0 = available immediately).
- `FileDeadLetterQueue.nack()` and `RedisDLQ.nack()` both compute:
  ```
  base_delay = 30  # seconds
  max_delay  = 3600  # 1 hour cap
  backoff = min(base_delay * 2 ** (attempt_count - 1), max_delay)
  retry_after = time.time() + backoff
  ```
  Write `retry_after` into the persisted JSON.
- `FileDeadLetterQueue.drain()` skips entries where `data.get("retry_after", 0.0) > time.time()`.
- `RedisDLQ.drain()` does the same check after deserialising each hash field.
- `InMemoryDeadLetterQueue` (used in tests) also honours `retry_after` in `drain()`.
- **Backoff schedule:** attempt 1 → 30s, attempt 2 → 60s, attempt 3 → 120s, ... capped at 1h.
- The `DLQEntry.retry_after` field defaults to `0.0` so existing serialised entries (without the field) are treated as immediately available — backward compatible.

**Scope:** `core/dead_letter.py` only.

### 2. Semver-Aware min_version

**Problem:** `_check_min_version("1.2.0-rc1", "1.2.0")` returns `True` (treats rc1 as 0) — incorrect; a release candidate is not ≥ a stable release. Pre-release strings are silently dropped.

**Fix:**
- Attempt `from packaging.version import Version` at module level with a try/except.
- If `packaging` is available: use `Version(version) >= Version(min_version)`. This handles PEP 440 pre-releases, post-releases, epochs, and dev versions correctly.
- If `packaging` is not available: fall back to the existing tuple-based `_parse()` (log a `WARNING` once that precise pre-release comparison is unavailable).
- Add `packaging` to `requirements.txt` (it is almost always already installed as a transitive dep of pip/setuptools).
- If `Version()` raises `InvalidVersion` (e.g. non-PEP-440 string), fall back to tuple comparison and log a warning.

**Scope:** `skills_loader.py`, `requirements.txt`.

### 3. OutputVerifier Raises on Missing Attribute

**Problem:** When `PipelineResult` lacks a required attribute entirely (e.g. a typo in the YAML field name), `verify()` calls `warnings.warn()` and continues — the stage is marked successful despite the contract being violated.

**Fix:**
- In `OutputVerifier.verify()`, when `not hasattr(result, field)`: raise `OutputVerificationError(stage_name, field)` with a message that distinguishes "field missing from PipelineResult" from "field present but empty".
- Remove the `warnings.warn()` call entirely.
- Update the docstring to reflect that missing attributes are a hard failure.

**Scope:** `core/output_verifier.py` only.

### 4. SkillLoader Raises on Missing Dependency

**Problem:** When `skill.depends_on` lists a skill name that isn't in the loaded registry, `_resolve_dependencies()` calls `warnings.warn()` and skips the dep — the skill then runs without its dependency, silently violating topological ordering.

**Fix:**
- In `_resolve_dependencies()`, when `dep_name not in skill_map`: raise `ValueError(f"[skills] Skill '{skill.name}' depends_on '{dep_name}' which is not loaded.")`.
- This turns a silent runtime misbehaviour into a load-time configuration error.
- If a dependency is optional (future feature), it can declare `optional_depends_on` instead; for now all `depends_on` entries are required.

**Scope:** `skills_loader.py` only.

---

## Files Modified

| File | Change |
|------|--------|
| `core/dead_letter.py` | Add `retry_after` to `DLQEntry`; backoff in `nack()`; skip in `drain()` |
| `skills_loader.py` | Use `packaging.version`; raise on missing dep |
| `requirements.txt` | Add `packaging` |
| `core/output_verifier.py` | Raise instead of warn on missing attribute |

---

## Tests

- `tests/test_dlq_backoff.py` — assert `retry_after` set on nack; assert drain skips not-yet-due entries; assert immediate availability after `retry_after` passes; test all three backends (InMemory, File, Redis mock)
- `tests/test_skills_loader_version.py` — assert `packaging.Version` used when available; rc1 < stable; invalid version falls back gracefully
- `tests/test_skills_loader_missing_dep.py` — assert `ValueError` raised when depends_on skill not loaded
- `tests/test_output_verifier_missing_attr.py` — assert `OutputVerificationError` raised on missing attribute (not just empty)

---

## Non-Goals

- Changing DLQ max_attempts (existing config, not changed)
- Adding `optional_depends_on` to skill schema (future work)
- Changing `OutputVerifier` empty-field behaviour (already raises correctly)
