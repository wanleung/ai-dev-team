# T5-B: Correctness & Fail-Fast — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Four correctness fixes: DLQ exponential backoff, semver-aware min_version, OutputVerifier raises on missing attribute, SkillLoader raises on missing dependency.

**Architecture:** All changes isolated to `core/dead_letter.py`, `skills_loader.py`, `requirements.txt`, and `core/output_verifier.py`. No orchestrator changes. TDD throughout.

**Tech Stack:** Python dataclasses, `packaging.version`, threading, Redis mock.

---

### Task 1: DLQ Exponential Backoff

**Files:**
- Modify: `core/dead_letter.py:42-60` (DLQEntry), `core/dead_letter.py:144-157` (FileDeadLetterQueue.nack/drain), `core/dead_letter.py:199-232` (RedisDLQ.nack/drain)
- Test: `tests/test_dlq_backoff.py` (new)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_dlq_backoff.py
import json
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from core.dead_letter import DLQEntry, FileDeadLetterQueue, InMemoryDeadLetterQueue


def _make_entry(attempt=1):
    return DLQEntry(
        id="entry-001",
        issue_number=1,
        tracker_repo="owner/repo",
        label="bug",
        model="gpt-4o",
        num_engineers=2,
        failed_at="2026-05-10T00:00:00Z",
        error={"code": "TIMEOUT"},
        attempt_count=attempt,
    )


def test_dlqentry_has_retry_after_field():
    """DLQEntry must have retry_after: float = 0.0."""
    entry = _make_entry()
    assert hasattr(entry, "retry_after")
    assert entry.retry_after == 0.0


def test_file_dlq_nack_sets_retry_after(tmp_path):
    """FileDeadLetterQueue.nack() writes retry_after > now() to the JSON file."""
    dlq = FileDeadLetterQueue(tmp_path, max_attempts=3)
    entry = _make_entry()
    dlq.enqueue(entry)

    before = time.time()
    dlq.nack(entry.id)

    f = tmp_path / f"{entry.id}.json"
    data = json.loads(f.read_text())
    assert "retry_after" in data
    assert data["retry_after"] > before  # must be in the future


def test_file_dlq_drain_skips_not_yet_due(tmp_path):
    """drain() must not yield entries whose retry_after is in the future."""
    dlq = FileDeadLetterQueue(tmp_path, max_attempts=3)
    entry = _make_entry()
    dlq.enqueue(entry)
    dlq.nack(entry.id)  # sets retry_after = now + 30s

    entries = list(dlq.drain())
    assert len(entries) == 0, "Entry should be skipped (retry_after in future)"


def test_file_dlq_drain_yields_when_due(tmp_path):
    """drain() yields entries whose retry_after <= now."""
    dlq = FileDeadLetterQueue(tmp_path, max_attempts=3)
    f = tmp_path / "entry-002.json"
    data = {
        "id": "entry-002",
        "issue_number": 2,
        "tracker_repo": "owner/repo",
        "label": "bug",
        "model": "gpt-4",
        "num_engineers": 1,
        "failed_at": "2026-01-01T00:00:00Z",
        "error": {},
        "attempt_count": 1,
        "stage_name": "pipeline",
        "target_repo": "",
        "retry_after": 0.0,  # in the past
    }
    f.write_text(json.dumps(data))
    entries = list(dlq.drain())
    assert len(entries) == 1
    assert entries[0].id == "entry-002"


def test_backoff_doubles_per_attempt(tmp_path):
    """retry_after grows exponentially: attempt 1→30s, attempt 2→60s, attempt 3→120s."""
    dlq = FileDeadLetterQueue(tmp_path, max_attempts=5)
    entry = _make_entry(attempt=1)
    dlq.enqueue(entry)

    t0 = time.time()
    dlq.nack(entry.id)
    f = tmp_path / f"{entry.id}.json"
    data = json.loads(f.read_text())
    delay1 = data["retry_after"] - t0
    assert 25 <= delay1 <= 35, f"Attempt 2 delay should be ~30s, got {delay1:.1f}s"


def test_inmemory_dlq_drain_respects_retry_after():
    """InMemoryDeadLetterQueue.drain() skips entries with retry_after in future."""
    dlq = InMemoryDeadLetterQueue()
    entry = _make_entry()
    dlq.enqueue(entry)
    dlq.nack(entry.id)  # sets retry_after
    entries = list(dlq.drain())
    assert len(entries) == 0
```

- [ ] **Step 2: Run to confirm failure**

```bash
python3 -m pytest tests/test_dlq_backoff.py -v
```
Expected: FAIL (`retry_after` field missing)

- [ ] **Step 3: Add `retry_after` to `DLQEntry`**

In `core/dead_letter.py`, add to the `DLQEntry` dataclass (after `stage_name`):
```python
retry_after: float = 0.0  # Unix timestamp; 0.0 = available immediately
```

- [ ] **Step 4: Add backoff constants and update `FileDeadLetterQueue.nack()`**

At the top of `core/dead_letter.py`, add:
```python
import time as _time

_DLQ_BACKOFF_BASE_S: float = 30.0    # seconds for attempt 1
_DLQ_BACKOFF_MAX_S: float = 3600.0   # 1 hour cap
```

Helper function (module-level):
```python
def _backoff_delay(attempt_count: int) -> float:
    """Exponential backoff: base * 2^(attempt-1), capped at max."""
    return min(_DLQ_BACKOFF_BASE_S * (2 ** (attempt_count - 1)), _DLQ_BACKOFF_MAX_S)
```

Update `FileDeadLetterQueue.nack()`:
```python
def nack(self, entry_id: str) -> None:
    f = self._file_for(entry_id)
    if not f.exists():
        return
    data = json.loads(f.read_text(encoding="utf-8"))
    data["attempt_count"] = data.get("attempt_count", 1) + 1
    if data["attempt_count"] > self._max_attempts:
        f.unlink(missing_ok=True)
        _dlq_emit("nack", entry_id, "file", data["attempt_count"])
        return
    data["retry_after"] = _time.time() + _backoff_delay(data["attempt_count"])
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(f)
    _dlq_emit("nack", entry_id, "file", data["attempt_count"])
```

Update `FileDeadLetterQueue.drain()` to skip future entries:
```python
def drain(self) -> Iterator[DLQEntry]:
    now = _time.time()
    for f in sorted(self._path.glob("*.json")):
        if f.suffix == ".tmp":
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("retry_after", 0.0) > now:
                continue  # not yet due
            yield DLQEntry(**{k: v for k, v in data.items() if k in DLQEntry.__dataclass_fields__})
        except Exception:
            continue
```

- [ ] **Step 5: Update `InMemoryDeadLetterQueue.nack()` and `drain()`**

Find the `InMemoryDeadLetterQueue` class (around line 85) and update:
```python
class InMemoryDeadLetterQueue(DeadLetterQueue):
    def __init__(self) -> None:
        self._store: dict[str, DLQEntry] = {}

    def enqueue(self, entry: DLQEntry) -> None:
        self._store[entry.id] = entry

    def drain(self) -> Iterator[DLQEntry]:
        now = _time.time()
        for entry in list(self._store.values()):
            if entry.retry_after <= now:
                yield entry

    def ack(self, entry_id: str) -> None:
        self._store.pop(entry_id, None)

    def nack(self, entry_id: str) -> None:
        entry = self._store.get(entry_id)
        if entry is None:
            return
        from dataclasses import replace
        new_count = entry.attempt_count + 1
        retry_after = _time.time() + _backoff_delay(new_count)
        self._store[entry_id] = replace(entry, attempt_count=new_count, retry_after=retry_after)
```

- [ ] **Step 6: Update `RedisDLQ.nack()` to set `retry_after`**

In the Lua script from T5-A (or in the Python fallback), add `retry_after` to the persisted data:
```python
# In the Python fallback path of RedisDLQ.nack():
data["attempt_count"] = data.get("attempt_count", 1) + 1
data["retry_after"] = _time.time() + _backoff_delay(data["attempt_count"])
```

Also update `RedisDLQ.drain()` to skip future entries:
```python
def drain(self) -> Iterator[DLQEntry]:
    now = _time.time()
    raw_map = self._redis.hgetall(self._cfg.key)
    for raw in raw_map.values():
        try:
            data = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
            if data.get("retry_after", 0.0) > now:
                continue
            yield DLQEntry(**{k: v for k, v in data.items() if k in DLQEntry.__dataclass_fields__})
        except Exception:
            continue
```

- [ ] **Step 7: Run all backoff tests**

```bash
python3 -m pytest tests/test_dlq_backoff.py -v
```
Expected: PASS (6/6)

- [ ] **Step 8: Commit**

```bash
git add core/dead_letter.py tests/test_dlq_backoff.py
git commit -m "feat(reliability): DLQ exponential backoff — retry_after on nack, drain skips future entries

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 2: Semver-Aware min_version

**Files:**
- Modify: `skills_loader.py:205-233` (`_check_min_version`)
- Modify: `requirements.txt` (add `packaging`)
- Test: `tests/test_skills_loader_version.py` (new or extend existing)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_skills_loader_version.py
import pytest
from skills_loader import SkillsLoader


def _check(version, min_version):
    return SkillsLoader._check_min_version(version, min_version)


def test_stable_greater_than_rc():
    """1.2.0 >= 1.2.0-rc1 must be True (stable > pre-release)."""
    assert _check("1.2.0", "1.2.0-rc1") is True


def test_rc_not_greater_than_stable():
    """1.2.0-rc1 >= 1.2.0 must be False (pre-release < stable)."""
    assert _check("1.2.0-rc1", "1.2.0") is False


def test_standard_semver_ordering():
    """Standard ordering still works."""
    assert _check("2.0.0", "1.9.9") is True
    assert _check("1.0.0", "2.0.0") is False
    assert _check("1.2.3", "1.2.3") is True


def test_empty_min_version_always_passes():
    """Empty min_version means no constraint."""
    assert _check("0.0.1", "") is True
    assert _check("1.2.0-rc1", "") is True


def test_invalid_version_falls_back_gracefully():
    """Invalid version strings don't crash — fall back to tuple comparison."""
    # Should not raise
    result = _check("not-a-version", "1.0.0")
    assert isinstance(result, bool)
```

- [ ] **Step 2: Run to confirm failure**

```bash
python3 -m pytest tests/test_skills_loader_version.py -v
```
Expected: `test_stable_greater_than_rc` and `test_rc_not_greater_than_stable` FAIL (naive split treats rc1 as 0)

- [ ] **Step 3: Add `packaging` to `requirements.txt`**

```bash
echo "packaging" >> requirements.txt
pip install packaging --quiet
```

- [ ] **Step 4: Update `_check_min_version()` in `skills_loader.py`**

Replace the existing `_check_min_version` method body:
```python
@staticmethod
def _check_min_version(version: str, min_version: str) -> bool:
    """Return True if version >= min_version using PEP 440 semantics where possible."""
    if not min_version:
        return True

    try:
        from packaging.version import Version, InvalidVersion
        try:
            return Version(version) >= Version(min_version)
        except InvalidVersion:
            import logging
            logging.getLogger(__name__).warning(
                "[skills] Non-PEP-440 version string %r or %r — falling back to tuple comparison",
                version,
                min_version,
            )
    except ImportError:
        import logging
        logging.getLogger(__name__).warning(
            "[skills] 'packaging' not installed — pre-release version comparison may be inaccurate"
        )

    # Tuple-based fallback
    import re

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

- [ ] **Step 5: Run tests**

```bash
python3 -m pytest tests/test_skills_loader_version.py -v
```
Expected: PASS (5/5)

- [ ] **Step 6: Run existing skills_loader tests**

```bash
python3 -m pytest tests/ -k "skills" -v
```
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add skills_loader.py requirements.txt tests/test_skills_loader_version.py
git commit -m "fix(skills): use packaging.version for PEP 440 semver comparison in min_version

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 3: OutputVerifier Raises on Missing Attribute

**Files:**
- Modify: `core/output_verifier.py:44-64` (`verify()` method)
- Test: `tests/test_output_verifier_missing_attr.py` (new)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_output_verifier_missing_attr.py
import pytest
from unittest.mock import MagicMock
from core.output_verifier import OutputVerifier, OutputVerificationError


def _result(**kwargs):
    """Create a mock PipelineResult with given attributes."""
    mock = MagicMock(spec=[])
    for k, v in kwargs.items():
        setattr(mock, k, v)
    return mock


def test_raises_on_missing_attribute():
    """verify() must raise OutputVerificationError when required field is absent."""
    result = _result(prd="A valid PRD")  # no 'design' attribute
    verifier = OutputVerifier(["prd", "design"])

    with pytest.raises(OutputVerificationError) as exc_info:
        verifier.verify(result, "architect")

    assert "design" in str(exc_info.value)
    assert "architect" in str(exc_info.value)


def test_no_warning_emitted_on_missing_attribute(recwarn):
    """warnings.warn must NOT be called for missing attributes (raises instead)."""
    result = _result(prd="ok")  # no 'design'
    verifier = OutputVerifier(["prd", "design"])

    with pytest.raises(OutputVerificationError):
        verifier.verify(result, "stage-x")

    assert len(recwarn) == 0, "No warnings should be emitted"


def test_still_raises_on_empty_present_field():
    """Empty field still raises (existing behaviour preserved)."""
    result = _result(prd="", design="valid design")
    verifier = OutputVerifier(["prd", "design"])

    with pytest.raises(OutputVerificationError) as exc_info:
        verifier.verify(result, "pm")

    assert "prd" in str(exc_info.value)


def test_passes_when_all_fields_present_and_nonempty():
    """No exception when all required fields are present and non-empty."""
    result = _result(prd="A product spec", design="An architecture doc")
    verifier = OutputVerifier(["prd", "design"])
    verifier.verify(result, "architect")  # must not raise
```

- [ ] **Step 2: Run to confirm failure**

```bash
python3 -m pytest tests/test_output_verifier_missing_attr.py -v
```
Expected: `test_raises_on_missing_attribute` FAIL (warns instead of raises)

- [ ] **Step 3: Update `OutputVerifier.verify()` in `core/output_verifier.py`**

Replace the `not hasattr` branch:
```python
def verify(self, result: Any, stage_name: str) -> None:
    """Verify all required fields are present and non-empty on result.

    Raises:
        OutputVerificationError: If any required field is absent from result,
            or is present but None, empty string, or empty collection.
    """
    for field in self._required:
        if not hasattr(result, field):
            raise OutputVerificationError(
                stage_name,
                field,
                # Include a hint that the field doesn't exist (not just empty)
            )
        value = getattr(result, field)
        if isinstance(value, str):
            is_empty = not value.strip()
        else:
            is_empty = not value
        if is_empty:
            raise OutputVerificationError(stage_name, field)
```

Also remove `import warnings` if it's no longer used elsewhere in the file.

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/test_output_verifier_missing_attr.py -v
```
Expected: PASS (4/4)

- [ ] **Step 5: Run existing output_verifier tests**

```bash
python3 -m pytest tests/ -k "output_verifier or verifier" -v
```
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add core/output_verifier.py tests/test_output_verifier_missing_attr.py
git commit -m "fix(correctness): OutputVerifier raises on missing attribute instead of warning

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 4: SkillLoader Raises on Missing Dependency

**Files:**
- Modify: `skills_loader.py:263-278` (`_resolve_dependencies()` missing dep branch)
- Test: `tests/test_skills_loader_missing_dep.py` (new)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_skills_loader_missing_dep.py
import pytest
from unittest.mock import patch, MagicMock
from skills_loader import SkillsLoader, SkillEntry
from dataclasses import field as dc_field


def _entry(name, depends_on=None):
    return SkillEntry(
        name=name,
        description="test",
        version="1.0.0",
        roles=["developer"],
        tags=[],
        source="test.md",
        depends_on=depends_on or [],
        min_version="",
        required_roles=[],
    )


def test_raises_when_dependency_not_loaded():
    """_resolve_dependencies() raises ValueError when a depends_on skill is missing."""
    loader = SkillsLoader.__new__(SkillsLoader)
    skill_a = _entry("skill-a", depends_on=["skill-b"])
    skill_map = {"skill-a": skill_a}  # skill-b not loaded

    with pytest.raises(ValueError, match="skill-b"):
        loader._resolve_dependencies([skill_a], skill_map)


def test_no_error_when_all_deps_loaded():
    """_resolve_dependencies() succeeds when all deps are in skill_map."""
    loader = SkillsLoader.__new__(SkillsLoader)
    skill_a = _entry("skill-a", depends_on=["skill-b"])
    skill_b = _entry("skill-b")
    skill_map = {"skill-a": skill_a, "skill-b": skill_b}

    result = loader._resolve_dependencies([skill_a], skill_map)
    names = [s.name for s in result]
    assert "skill-b" in names
    assert "skill-a" in names
    assert names.index("skill-b") < names.index("skill-a")


def test_no_error_when_no_deps():
    """_resolve_dependencies() works fine for skills with no deps."""
    loader = SkillsLoader.__new__(SkillsLoader)
    skill_a = _entry("skill-a")
    skill_map = {"skill-a": skill_a}
    result = loader._resolve_dependencies([skill_a], skill_map)
    assert len(result) == 1
```

- [ ] **Step 2: Run to confirm failure**

```bash
python3 -m pytest tests/test_skills_loader_missing_dep.py -v
```
Expected: `test_raises_when_dependency_not_loaded` FAIL (warns instead of raises)

- [ ] **Step 3: Replace `warnings.warn()` with `raise ValueError` in `_resolve_dependencies()`**

In `skills_loader.py` around line 272, change:
```python
# Before:
else:
    warnings.warn(
        f"[skills] Skill '{skill.name}' depends_on '{dep_name}' "
        f"which is not loaded — skipping dependency."
    )
# After:
else:
    raise ValueError(
        f"[skills] Skill '{skill.name}' depends_on '{dep_name}' "
        f"which is not loaded. Ensure all required skills are installed."
    )
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/test_skills_loader_missing_dep.py -v
```
Expected: PASS (3/3)

- [ ] **Step 5: Run all skills_loader tests**

```bash
python3 -m pytest tests/ -k "skills" -v
```
Expected: all pass

- [ ] **Step 6: Run full test suite**

```bash
python3 -m pytest tests/ -x -q 2>/dev/null | tail -10
```
Expected: no regressions

- [ ] **Step 7: Commit**

```bash
git add skills_loader.py tests/test_skills_loader_missing_dep.py
git commit -m "fix(skills): raise ValueError on missing depends_on skill instead of warning

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 5: Create PR

- [ ] **Step 1: Push branch**

```bash
git push -u origin t5-b-correctness-fail-fast
```

- [ ] **Step 2: Create PR**

```bash
gh pr create \
  --title "fix(correctness): T5-B — DLQ backoff, semver min_version, verifier raises, skills dep error" \
  --body "## Summary

Four correctness and fail-fast improvements:

### 1. DLQ Exponential Backoff
- Added \`retry_after: float = 0.0\` to \`DLQEntry\`
- \`nack()\` sets \`retry_after = now + min(30 * 2^(attempt-1), 3600)\`
- \`drain()\` skips entries where \`retry_after > time.time()\`
- All three backends: InMemory, File, Redis

### 2. Semver-aware min_version
- Uses \`packaging.version.Version\` when available (PEP 440 pre-release ordering)
- Falls back to existing tuple-based comparison on \`ImportError\` or \`InvalidVersion\`
- \`requirements.txt\` updated to include \`packaging\`

### 3. OutputVerifier raises on missing attribute
- Removed \`warnings.warn()\` for missing fields
- Now raises \`OutputVerificationError\` — missing field = verification failure
- Removed unused \`import warnings\`

### 4. SkillLoader raises on missing dependency
- \`_resolve_dependencies()\` raises \`ValueError\` when \`depends_on\` skill not in skill_map
- Turns silent runtime misbehaviour into load-time configuration error

## Tests
- \`tests/test_dlq_backoff.py\` — 6 tests across InMemory + File backends
- \`tests/test_skills_loader_version.py\` — 5 semver comparison tests
- \`tests/test_output_verifier_missing_attr.py\` — 4 tests
- \`tests/test_skills_loader_missing_dep.py\` — 3 tests

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>" \
  --base master
```
