# Agent Pipeline Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent field/enum naming divergences, test infrastructure failures, and commit SHA conflicts in the ai-software-house pipeline by adding a naming contract artifact, a contract validator stage, hardened role prompts, SHA retry logic, and RAG test indexing.

**Architecture:** The Architect generates a machine-readable `naming_contract.yaml` alongside the design doc; a new `contract_validate` stage after `qa_write` checks test files against this contract and blocks on divergence; `commit_file()` auto-retries on 409 with a fresh SHA; and QA/Engineer role prompts embed FastAPI DI rules and naming contract references.

**Tech Stack:** Python 3.13, pytest, PyYAML, GitHub REST API, existing orchestrator stage pattern

**Spec:** `docs/superpowers/specs/2026-05-28-agent-pipeline-improvements-design.md`

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `github_client.py` | Modify | Add `_get_contents_sha()` + SHA-retry in `commit_file()` |
| `tests/test_github_client.py` | Modify | Tests for SHA retry logic |
| `roles/qa_engineer.md` | Modify | Add FastAPI DI rules + naming contract reference |
| `roles/engineer.md` | Modify | Add naming contract reference rule |
| `roles/architect.md` | Modify | Add naming contract generation requirement |
| `roles/contract_validator.md` | Create | New agent role for contract validation |
| `agents/contract_validator.py` | Create | ContractValidatorAgent class |
| `orchestrator.py` | Modify | Add `naming_contract` field to PipelineResult, extract from architect output, new `_stage_contract_validate()`, register stage, add to TDD workflow |
| `tests/test_contract_validator.py` | Create | Unit tests for ContractValidatorAgent |
| `tests/test_orchestrator_contract.py` | Create | Integration tests for contract_validate stage |

---

## Task 1: Commit SHA Retry in `github_client.py`

**Files:**
- Modify: `github_client.py` (lines 231–263, `commit_file` method)
- Modify: `tests/test_github_client.py` (append new test class)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_github_client.py`:

```python
class TestCommitFileShaRetry:
    """commit_file retries once with a fresh SHA on 409 conflict."""

    def test_commit_file_success_no_retry(self, gc):
        """Happy path: first PUT succeeds."""
        get_resp = MagicMock()
        get_resp.ok = True
        get_resp.status_code = 200
        get_resp.text = '{"sha": "abc123"}'
        get_resp.json.return_value = {"sha": "abc123"}

        put_resp = MagicMock()
        put_resp.ok = True
        put_resp.status_code = 200
        put_resp.text = '{"commit": {}}'
        put_resp.json.return_value = {"commit": {}}

        with patch.object(gc._session, "request", side_effect=[get_resp, put_resp]) as mock_req:
            result = gc.commit_file("src/foo.py", "content", "feat: add foo", "main")

        assert result == {"commit": {}}
        assert mock_req.call_count == 2  # GET (check existing) + PUT

    def test_commit_file_409_retries_with_fresh_sha(self, gc):
        """On 409, fetches fresh SHA and retries the PUT once."""
        # GET for existing file on first commit attempt
        get_existing = MagicMock()
        get_existing.ok = True
        get_existing.status_code = 200
        get_existing.text = '{"sha": "stale-sha"}'
        get_existing.json.return_value = {"sha": "stale-sha"}

        # PUT fails with 409
        put_fail = MagicMock()
        put_fail.ok = False
        put_fail.status_code = 409
        put_fail.text = '{"message":"is at fresh-sha but expected stale-sha"}'

        # GET for fresh SHA (retry step)
        get_fresh = MagicMock()
        get_fresh.ok = True
        get_fresh.status_code = 200
        get_fresh.text = '{"sha": "fresh-sha"}'
        get_fresh.json.return_value = {"sha": "fresh-sha"}

        # Second PUT succeeds
        put_ok = MagicMock()
        put_ok.ok = True
        put_ok.status_code = 200
        put_ok.text = '{"commit": {"sha": "new-commit"}}'
        put_ok.json.return_value = {"commit": {"sha": "new-commit"}}

        with patch.object(gc._session, "request",
                          side_effect=[get_existing, put_fail, get_fresh, put_ok]) as mock_req:
            result = gc.commit_file("src/foo.py", "content", "feat: add foo", "main")

        assert result == {"commit": {"sha": "new-commit"}}
        assert mock_req.call_count == 4  # GET existing, PUT fail, GET fresh, PUT success
        # Verify the retry PUT used the fresh SHA
        retry_put_call = mock_req.call_args_list[3]
        assert retry_put_call[1]["json"]["sha"] == "fresh-sha"

    def test_commit_file_409_no_second_retry(self, gc):
        """Does NOT retry a second time if the retry also returns 409."""
        get_existing = MagicMock()
        get_existing.ok = True
        get_existing.status_code = 200
        get_existing.text = '{"sha": "sha1"}'
        get_existing.json.return_value = {"sha": "sha1"}

        put_fail = MagicMock()
        put_fail.ok = False
        put_fail.status_code = 409
        put_fail.text = '{"message":"is at sha2 but expected sha1"}'

        get_fresh = MagicMock()
        get_fresh.ok = True
        get_fresh.status_code = 200
        get_fresh.text = '{"sha": "sha2"}'
        get_fresh.json.return_value = {"sha": "sha2"}

        put_fail2 = MagicMock()
        put_fail2.ok = False
        put_fail2.status_code = 409
        put_fail2.text = '{"message":"is at sha3 but expected sha2"}'

        with patch.object(gc._session, "request",
                          side_effect=[get_existing, put_fail, get_fresh,
                                       put_fail2, put_fail2, put_fail2]):
            with pytest.raises(RuntimeError, match="409"):
                gc.commit_file("src/foo.py", "content", "feat: add foo", "main")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/wanleung/Projects/ai-software-house && source venv/bin/activate
python -m pytest tests/test_github_client.py::TestCommitFileShaRetry -v
```

Expected: 3 failures (method doesn't exist yet)

- [ ] **Step 3: Implement `_get_contents_sha()` and SHA retry in `commit_file()`**

In `github_client.py`, add this method after `get_branch_sha` (around line 200):

```python
def _get_contents_sha(self, path: str, branch: str) -> Optional[str]:
    """Return the blob SHA for *path* on *branch*, or None if not found."""
    try:
        result = self._request(
            "GET",
            f"/repos/{self.repo}/contents/{path}",
            params={"ref": branch},
            max_retries=1,
        )
        return result.get("sha")
    except RuntimeError:
        return None
```

Then modify `commit_file()` — replace the body from `encoded = ...` to the final `return self._request(...)`:

```python
def commit_file(
    self,
    path: str,
    content: str,
    message: str,
    branch: str,
    encoding: str = "utf-8",
    max_retries: int | None = None,
    _sha_retry: bool = True,
) -> dict:
    """Create or update a file in the repo on the given branch.

    Args:
        path: File path relative to repo root (e.g., 'src/main.py').
        content: Text content of the file.
        message: Git commit message.
        branch: Branch to commit to.
        encoding: Text encoding (default 'utf-8').
        max_retries: Override the default retry count.
        _sha_retry: Internal flag — False on the recursive retry to prevent loops.

    Returns:
        GitHub API response with commit and content data.
    """
    encoded = base64.b64encode(content.encode(encoding)).decode("ascii")

    payload: dict = {"message": message, "content": encoded, "branch": branch}
    try:
        existing = self._request(
            "GET",
            f"/repos/{self.repo}/contents/{path}",
            params={"ref": branch},
            max_retries=max_retries,
        )
        payload["sha"] = existing["sha"]
    except RuntimeError:
        pass  # File doesn't exist yet — create it

    try:
        return self._request(
            "PUT",
            f"/repos/{self.repo}/contents/{path}",
            json=payload,
            max_retries=max_retries,
        )
    except RuntimeError as exc:
        if _sha_retry and "409" in str(exc):
            # SHA stale — fetch current SHA and retry once
            log.warning(
                "[github_client] 409 SHA conflict on %s — fetching fresh SHA and retrying",
                path,
            )
            fresh_sha = self._get_contents_sha(path, branch)
            return self.commit_file(
                path, content, message, branch,
                encoding=encoding,
                max_retries=max_retries,
                _sha_retry=False,
            ) if fresh_sha is None else self.commit_file(
                path, content, message, branch,
                encoding=encoding,
                max_retries=max_retries,
                _sha_retry=False,
            )
        raise
```

Wait — that retry code is duplicated. Cleaner version:

```python
    except RuntimeError as exc:
        if _sha_retry and "409" in str(exc):
            log.warning(
                "[github_client] 409 SHA conflict on %s — fetching fresh SHA and retrying once",
                path,
            )
            # Recurse with _sha_retry=False to prevent infinite loop.
            # Pass fresh SHA implicitly: the recursive call re-GETs the file.
            return self.commit_file(
                path, content, message, branch,
                encoding=encoding,
                max_retries=max_retries,
                _sha_retry=False,
            )
        raise
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_github_client.py::TestCommitFileShaRetry -v
```

Expected: 3 passed

- [ ] **Step 5: Run full github_client test suite to check no regressions**

```bash
python -m pytest tests/test_github_client.py tests/test_github_client_extended.py -v
```

Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add github_client.py tests/test_github_client.py
git commit -m "fix(github_client): retry commit_file once on 409 SHA conflict"
```

---

## Task 2: QA Engineer Prompt Hardening

**Files:**
- Modify: `roles/qa_engineer.md`

- [ ] **Step 1: Add FastAPI DI rules and naming contract section to `roles/qa_engineer.md`**

Open `roles/qa_engineer.md` and insert after the `## Critical Rules — Tests Must Be Runnable` section (before `## Output Format`):

```markdown
## FastAPI Test Infrastructure (Critical Rules)

### 1. Use `dependency_overrides` — NEVER `patch()` for `Depends()`

Using `unittest.mock.patch()` on a FastAPI dependency causes every test to return 422 because
FastAPI inspects `MagicMock(*args, **kwargs)` as required query parameters. The ONLY correct
pattern:

```python
from app.main import app              # import app BEFORE any patching
from app.dependencies import get_db, get_current_user

async def override_get_db():
    yield mock_db                     # YIELD not return — get_db is async generator

async def override_get_current_user():
    return mock_user                  # return is fine here

app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)
yield client
app.dependency_overrides.pop(get_db, None)
```

The `authed_client` fixture must override BOTH `get_db` AND `get_current_user`:

```python
@pytest.fixture
def authed_client(mock_db, sample_user_obj):
    mock_user = MockModel(**sample_user_obj)

    async def override_get_db():
        yield mock_db

    async def override_get_current_user():
        return mock_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
```

### 2. Mock user required fields

`sample_user_obj` MUST include at minimum:

```python
sample_user_obj = {
    "id": uuid4(),
    "email": "test@example.com",
    "display_name": "Test User",
    "status": "active",         # valid UserStatusEnum: active | suspended | deleted
    "role": "player",           # valid UserRoleEnum: player | venue_owner | admin
    "firebase_uid": "google-123456",
}
```

Never use `"user"` as a status or role — these are not valid enum values.

### 3. Field names MUST match `naming_contract.yaml`

If `naming_contract.yaml` is present in the workspace, read it before writing tests.
- Every `json={...}` payload field must appear in the contract's `request_fields`
- Every `response.json()` key assertion must appear in `response_fields`
- Every enum string literal must appear in the contract's enum lists

### 4. Python 3.13 AsyncMock fix

In Python 3.13, `AsyncMock().return_value` is an `AsyncMock`, not a `MagicMock`. Always set
`return_value` explicitly:

```python
mock_result = MagicMock()
mock_db.execute = AsyncMock(return_value=mock_result)
```
```

- [ ] **Step 2: Verify the file looks correct**

```bash
grep -c "dependency_overrides\|naming_contract\|UserStatusEnum" roles/qa_engineer.md
```

Expected: at least 3 matches (one per new rule)

- [ ] **Step 3: Commit**

```bash
git add roles/qa_engineer.md
git commit -m "docs(roles): add FastAPI DI rules and naming contract reference to qa_engineer"
```

---

## Task 3: Engineer Prompt Hardening

**Files:**
- Modify: `roles/engineer.md`

- [ ] **Step 1: Add naming contract rule to `roles/engineer.md`**

Open `roles/engineer.md` and append after the `## What to Avoid` section:

```markdown
## Naming Contract Rule (Mandatory)

Before implementing ANY endpoint or defining any field/enum, read `naming_contract.yaml`
from the workspace root.

- Request body field names MUST exactly match `request_fields` listed in the contract
- Response dict/schema field names MUST exactly match `response_fields`
- Enum values MUST exactly match the contract's enum lists (do not invent values)
- Service call argument order MUST match `service_signatures` in the contract

If `naming_contract.yaml` is not present, list all field names and enum values you are
about to use in a comment at the top of the file, so the Contract Validator can catch mismatches.
```

- [ ] **Step 2: Commit**

```bash
git add roles/engineer.md
git commit -m "docs(roles): add naming contract reference rule to engineer"
```

---

## Task 4: Architect Prompt — Naming Contract Requirement

**Files:**
- Modify: `roles/architect.md`

- [ ] **Step 1: Add naming contract output section to `roles/architect.md`**

Open `roles/architect.md` and add a new section after the architecture output section. Find the `## Output Format` section and append:

```markdown
## Naming Contract (Required Additional Output)

After your architecture document, you MUST also output `naming_contract.yaml` using this
exact format:

```
### FILE: naming_contract.yaml
```yaml
version: 1
endpoints:
  - path: /api/example/items
    method: POST
    auth: required          # required | optional | none
    request_fields: [field1, field2, field3]
    response_fields: [id, field1, created_at]

enums:
  ExampleStatus: [active, inactive, pending]
  ExampleRole: [admin, user, guest]

service_signatures:
  - fn: example_service.create_item
    args: [db, user_id_str, item_data]
```
```

Rules:
- List EVERY API endpoint's request_fields and response_fields with the EXACT names that
  tests and clients will use (no abbreviations, no aliases)
- List EVERY enum with ALL valid string values
- Use lowercase_with_underscores for all field names and enum values
- List service functions that have non-obvious signatures (e.g. uuid vs string args)
- This contract is the single source of truth; QA and Engineer agents reference it

```

- [ ] **Step 2: Commit**

```bash
git add roles/architect.md
git commit -m "docs(roles): add naming_contract.yaml generation requirement to architect"
```

---

## Task 5: ContractValidatorAgent

**Files:**
- Create: `roles/contract_validator.md`
- Create: `agents/contract_validator.py`
- Create: `tests/test_contract_validator.py`

- [ ] **Step 1: Write failing tests for ContractValidatorAgent**

Create `tests/test_contract_validator.py`:

```python
# tests/test_contract_validator.py
import pytest
from agents.contract_validator import ContractValidatorAgent


@pytest.fixture
def contract():
    return {
        "version": 1,
        "endpoints": [
            {
                "path": "/api/forum/posts",
                "method": "POST",
                "auth": "required",
                "request_fields": ["title", "content", "image_urls"],
                "response_fields": ["id", "title", "content", "author_id"],
            }
        ],
        "enums": {
            "ReportReason": ["spam", "abusive", "inappropriate"],
            "UserStatus": ["active", "suspended", "deleted"],
        },
        "service_signatures": [],
    }


@pytest.fixture
def agent():
    return ContractValidatorAgent()


class TestContractValidatorPass:
    def test_aligned_test_passes(self, agent, contract):
        """Test file using exact field names from contract passes."""
        test_files = {
            "tests/test_forum.py": (
                'def test_create_post(authed_client):\n'
                '    resp = authed_client.post("/api/forum/posts", '
                'json={"title": "T", "content": "body", "image_urls": []})\n'
                '    assert resp.status_code == 201\n'
                '    data = resp.json()\n'
                '    assert "id" in data\n'
                '    assert "content" in data\n'
            )
        }
        result = agent.validate(contract, test_files)
        assert result["passed"] is True
        assert result["divergences"] == []

    def test_empty_test_files_passes(self, agent, contract):
        """No test files → no divergences."""
        result = agent.validate(contract, {})
        assert result["passed"] is True

    def test_no_contract_skips_validation(self, agent):
        """None contract → skip (non-blocking)."""
        result = agent.validate(None, {"tests/test_x.py": "assert True"})
        assert result["passed"] is True
        assert result["skipped"] is True


class TestContractValidatorFailures:
    def test_wrong_request_field_fails(self, agent, contract):
        """Test using 'body' instead of 'content' is caught."""
        test_files = {
            "tests/test_forum.py": (
                'json={"title": "T", "body": "text"}'  # 'body' not in contract
            )
        }
        result = agent.validate(contract, test_files)
        assert result["passed"] is False
        assert any("body" in d["field"] for d in result["divergences"])

    def test_wrong_enum_value_fails(self, agent, contract):
        """Test using 'offensive' (not in contract) is caught."""
        test_files = {
            "tests/test_report.py": (
                'json={"reason": "offensive"}'  # not in ReportReason enum
            )
        }
        result = agent.validate(contract, test_files)
        assert result["passed"] is False
        assert any("offensive" in d["field"] for d in result["divergences"])

    def test_valid_enum_value_passes(self, agent, contract):
        """Test using 'abusive' (in contract) does not flag it."""
        test_files = {
            "tests/test_report.py": (
                'json={"reason": "abusive"}'
            )
        }
        result = agent.validate(contract, test_files)
        assert result["passed"] is True

    def test_report_includes_file_and_line(self, agent, contract):
        """Divergence report includes filename."""
        test_files = {
            "tests/test_forum.py": 'json={"body_text": "hello"}'
        }
        result = agent.validate(contract, test_files)
        assert result["passed"] is False
        assert any("test_forum.py" in d["file"] for d in result["divergences"])
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/wanleung/Projects/ai-software-house && source venv/bin/activate
python -m pytest tests/test_contract_validator.py -v
```

Expected: ImportError (module not created yet)

- [ ] **Step 3: Create `roles/contract_validator.md`**

```markdown
# Contract Validator Agent

You validate that generated test files are aligned with the project's `naming_contract.yaml`.

## Input

You receive:
1. The contents of `naming_contract.yaml` (parsed as a dict)
2. All test files (dict mapping filename → source code)

## Your Job

Scan every test file for:

1. **Request field mismatches** — find `json={...}` dict literals. Each key must appear in
   the `request_fields` of the relevant endpoint in the contract.

2. **Response field mismatches** — find `response.json()` key lookups (e.g. `data["key"]`,
   `assert "key" in data`). Each key must appear in the `response_fields` of the relevant
   endpoint.

3. **Enum value mismatches** — find string literals that look like enum values (appear in
   json payloads as values). Cross-reference all `enums` in the contract. Flag any string
   not found in any enum list — unless it's clearly not an enum value (e.g. a URL, email,
   UUID placeholder).

## Output Format

If no divergences found:

```
PASS
```

If divergences found, output a list:

```
FAIL
- file: tests/test_forum.py
  field: body_text
  issue: field 'body_text' not found in any endpoint's request_fields (contract has: content, title, image_urls)
  suggestion: rename to 'content'

- file: tests/test_report.py
  field: offensive
  issue: enum value 'offensive' not found in any enum list
  suggestion: use one of: spam, abusive, inappropriate, harassment, other
```
```

- [ ] **Step 4: Create `agents/contract_validator.py`**

```python
# agents/contract_validator.py
"""ContractValidatorAgent — validates test files against naming_contract.yaml."""
from __future__ import annotations

import ast
import re
from typing import Optional


class ContractValidatorAgent:
    """Validates that test files use field names and enum values from naming_contract.yaml."""

    def validate(
        self,
        contract: Optional[dict],
        test_files: dict[str, str],
    ) -> dict:
        """Check test files against the naming contract.

        Args:
            contract: Parsed naming_contract.yaml dict, or None if not available.
            test_files: Mapping of filename to source code.

        Returns:
            dict with keys:
              - passed: bool
              - skipped: bool (True if contract is None)
              - divergences: list of {file, field, issue, suggestion}
        """
        if contract is None:
            return {"passed": True, "skipped": True, "divergences": []}

        if not test_files:
            return {"passed": True, "skipped": False, "divergences": []}

        all_request_fields: set[str] = set()
        all_response_fields: set[str] = set()
        for ep in contract.get("endpoints", []):
            all_request_fields.update(ep.get("request_fields", []))
            all_response_fields.update(ep.get("response_fields", []))

        all_enum_values: set[str] = set()
        for values in contract.get("enums", {}).values():
            all_enum_values.update(values)

        all_known_fields = all_request_fields | all_response_fields | all_enum_values

        divergences: list[dict] = []

        for filename, source in test_files.items():
            divergences.extend(
                self._check_json_payload_fields(filename, source, all_request_fields, all_enum_values, all_known_fields, contract)
            )

        return {
            "passed": len(divergences) == 0,
            "skipped": False,
            "divergences": divergences,
        }

    def _check_json_payload_fields(
        self,
        filename: str,
        source: str,
        all_request_fields: set[str],
        all_enum_values: set[str],
        all_known_fields: set[str],
        contract: dict,
    ) -> list[dict]:
        """Find json={...} dict literals and check their keys and string values."""
        divergences: list[dict] = []

        # Extract json={...} payload keys using regex (handles multi-line and nested)
        # Pattern: json={"key": value, ...}
        json_pattern = re.compile(r'json\s*=\s*\{([^}]*)\}', re.DOTALL)
        for match in json_pattern.finditer(source):
            payload_src = match.group(1)
            # Extract string keys from the payload
            key_pattern = re.compile(r'["\']([a-zA-Z_][a-zA-Z0-9_]*)["\'][\s]*:')
            for key_match in key_pattern.finditer(payload_src):
                key = key_match.group(1)
                if key not in all_request_fields and key not in _COMMON_NON_CONTRACT_KEYS:
                    all_field_names = sorted(all_request_fields)
                    divergences.append({
                        "file": filename,
                        "field": key,
                        "issue": (
                            f"field '{key}' not found in any endpoint's request_fields "
                            f"(contract has: {', '.join(all_field_names[:5])}{'...' if len(all_field_names) > 5 else ''})"
                        ),
                        "suggestion": self._suggest_similar(key, all_request_fields),
                    })

            # Check string values in json payloads that look like enum values
            val_pattern = re.compile(r':\s*["\']([a-zA-Z_][a-zA-Z0-9_]*)["\']')
            for val_match in val_pattern.finditer(payload_src):
                val = val_match.group(1)
                # Only flag if it looks like an enum (lowercase, short, in a values position)
                # and if there ARE enums defined in the contract
                if contract.get("enums") and len(val) <= 30 and "_" in val or val.islower():
                    # Check if this value could be an enum value
                    if not self._is_enum_value_valid(val, all_enum_values, all_known_fields):
                        all_enum_vals = sorted(all_enum_values)
                        divergences.append({
                            "file": filename,
                            "field": val,
                            "issue": (
                                f"enum value '{val}' not found in any enum list "
                                f"(contract has: {', '.join(all_enum_vals[:5])}{'...' if len(all_enum_vals) > 5 else ''})"
                            ),
                            "suggestion": self._suggest_similar(val, all_enum_values),
                        })

        return divergences

    def _is_enum_value_valid(self, val: str, all_enum_values: set[str], all_known_fields: set[str]) -> bool:
        """Return True if val is a known enum value or a safe non-enum string."""
        if val in all_enum_values:
            return True
        # Safe: common fixture values that are not enum values
        if val in _SAFE_NON_ENUM_VALUES:
            return True
        # Safe: looks like a test placeholder, not an enum
        if len(val) > 30 or val.startswith("test") or val.startswith("mock"):
            return True
        return False

    def _suggest_similar(self, field: str, candidates: set[str]) -> str:
        """Return the most similar candidate, or empty string."""
        if not candidates:
            return ""
        # Simple: find candidates that share a prefix or suffix
        for c in sorted(candidates):
            if field in c or c in field:
                return f"did you mean '{c}'?"
        return f"use one of: {', '.join(sorted(candidates)[:3])}"


# Keys that are legitimately not in the naming contract
_COMMON_NON_CONTRACT_KEYS = frozenset({
    "page", "per_page", "limit", "offset", "sort", "order",
    "filter", "search", "q", "cursor", "token",
})

# String values that are safe and not enum values
_SAFE_NON_ENUM_VALUES = frozenset({
    "true", "false", "null", "none",
    "asc", "desc",
    "get", "post", "put", "patch", "delete",
})
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
python -m pytest tests/test_contract_validator.py -v
```

Expected: all 8 tests pass

- [ ] **Step 6: Commit**

```bash
git add agents/contract_validator.py roles/contract_validator.md tests/test_contract_validator.py
git commit -m "feat(agents): add ContractValidatorAgent to catch field/enum naming mismatches"
```

---

## Task 6: Wire Contract Validator into Pipeline

**Files:**
- Modify: `orchestrator.py`
- Create: `tests/test_orchestrator_contract.py`

- [ ] **Step 1: Write failing tests for the new pipeline stage**

Create `tests/test_orchestrator_contract.py`:

```python
# tests/test_orchestrator_contract.py
"""Tests for the contract_validate pipeline stage."""
import pytest
from unittest.mock import MagicMock, patch
from orchestrator import Orchestrator, PipelineResult


@pytest.fixture
def orch():
    o = Orchestrator.__new__(Orchestrator)
    o.contract_validator = MagicMock()
    o._stage_skips = {}
    return o


class TestStageContractValidate:
    def test_skips_when_no_naming_contract(self, orch):
        """Stage is a no-op when result.naming_contract is None."""
        result = PipelineResult(project_name="test")
        result.naming_contract = None
        result.test_files = {"tests/test_x.py": "assert True"}

        orch._stage_contract_validate(result)

        orch.contract_validator.validate.assert_not_called()

    def test_skips_when_no_test_files(self, orch):
        """Stage is a no-op when result.test_files is empty."""
        result = PipelineResult(project_name="test")
        result.naming_contract = {"version": 1, "endpoints": [], "enums": {}}
        result.test_files = {}

        orch._stage_contract_validate(result)

        orch.contract_validator.validate.assert_not_called()

    def test_passes_when_validation_passes(self, orch):
        """Stage completes normally when validator returns passed=True."""
        result = PipelineResult(project_name="test")
        result.naming_contract = {"version": 1, "endpoints": [], "enums": {}}
        result.test_files = {"tests/test_x.py": "assert True"}

        orch.contract_validator.validate.return_value = {
            "passed": True, "skipped": False, "divergences": []
        }

        orch._stage_contract_validate(result)  # should not raise

        assert result.contract_validation_passed is True

    def test_stores_divergences_on_failure(self, orch):
        """Stage stores divergences when validator returns passed=False."""
        result = PipelineResult(project_name="test")
        result.naming_contract = {"version": 1, "endpoints": [], "enums": {}}
        result.test_files = {"tests/test_x.py": 'json={"body_text": "x"}'}

        orch.contract_validator.validate.return_value = {
            "passed": False,
            "skipped": False,
            "divergences": [{"file": "tests/test_x.py", "field": "body_text",
                             "issue": "not in contract", "suggestion": "use content"}],
        }

        orch._stage_contract_validate(result)

        assert result.contract_validation_passed is False
        assert len(result.contract_divergences) == 1
        assert result.contract_divergences[0]["field"] == "body_text"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_orchestrator_contract.py -v
```

Expected: AttributeError / ImportError

- [ ] **Step 3: Add `naming_contract`, `contract_validation_passed`, `contract_divergences` fields to `PipelineResult`**

In `orchestrator.py`, find the `PipelineResult` dataclass (around line 360). Add after `tdd_review_summary`:

```python
    # Contract validation fields
    naming_contract: Optional[dict] = None              # parsed naming_contract.yaml from architect
    contract_validation_passed: Optional[bool] = None  # None = not run
    contract_divergences: list[dict] = field(default_factory=list)
```

Also add the import at the top of the class imports section if not already present:
```python
from agents.contract_validator import ContractValidatorAgent
```

- [ ] **Step 4: Instantiate ContractValidatorAgent in `Orchestrator.__init__`**

Find where other agents are instantiated (around line 995, near `self.architect = ...`). Add:

```python
self.contract_validator = ContractValidatorAgent()
```

- [ ] **Step 5: Add `_stage_contract_validate()` method**

After the `_stage_qa_write()` method (~line 4490), add:

```python
def _stage_contract_validate(self, result: PipelineResult) -> None:
    """Validate test files against naming_contract.yaml."""
    if not result.naming_contract:
        _log.info("contract_validate: no naming_contract present — skipping")
        return
    if not result.test_files:
        _log.info("contract_validate: no test files — skipping")
        return

    console.print("\n[bold cyan]📋 Contract Validator[/bold cyan]")
    validation = self.contract_validator.validate(
        result.naming_contract, result.test_files
    )
    result.contract_validation_passed = validation["passed"]
    result.contract_divergences = validation.get("divergences", [])

    if validation.get("skipped"):
        console.print("[dim]⏭ Contract validation skipped (no contract)[/dim]")
        return

    if validation["passed"]:
        console.print("[green]✅ Contract validation passed — all field names aligned[/green]")
    else:
        count = len(result.contract_divergences)
        console.print(f"[yellow]⚠️  Contract validation: {count} divergence(s) found[/yellow]")
        for d in result.contract_divergences[:5]:
            console.print(f"  [red]✗[/red] {d['file']}: '{d['field']}' — {d['issue']}")
            if d.get("suggestion"):
                console.print(f"    [dim]→ {d['suggestion']}[/dim]")
        if count > 5:
            console.print(f"  [dim]... and {count - 5} more[/dim]")
```

- [ ] **Step 6: Register the stage in `_make_stage_registry()`**

Find `stages["tdd_review"]` (around line 2109). Add after it:

```python
stages["contract_validate"] = PipelineStage(
    name="contract_validate",
    label="Contract Validation",
    checkpoint_key="contract_validate",
    fn=lambda r: self._stage_contract_validate(r),
    skip_if=lambda r: bool(self._stage_skips.get("contract_validate")),
)
```

- [ ] **Step 7: Add `contract_validate` to the `tdd` workflow**

Find the `"tdd"` workflow list (around line 643):

```python
"tdd": [
    "qa_planner",
    "qa_write",
    "tier_review",
    "junior_engineer",
    ...
]
```

Change to:

```python
"tdd": [
    "qa_planner",
    "qa_write",
    "contract_validate",      # ← add here, after qa_write before engineer
    "tier_review",
    "junior_engineer",
    "senior_engineer",
    "test_fix",
    "reviewer",
    "deploy_tester",
    "deploy_fix",
],
```

- [ ] **Step 8: Extract `naming_contract.yaml` from architect output**

Find `_stage_architect()` (around line 3765). After `result.design = arch_result["design"]`, add:

```python
# Extract naming_contract.yaml if architect generated it
naming_contract_raw = arch_result.get("files", {}).get("naming_contract.yaml", "")
if naming_contract_raw:
    try:
        import yaml
        result.naming_contract = yaml.safe_load(naming_contract_raw)
        _log.info("architect: loaded naming_contract.yaml (%d endpoints, %d enums)",
                  len(result.naming_contract.get("endpoints", [])),
                  len(result.naming_contract.get("enums", {})))
    except Exception as exc:
        _log.warning("architect: failed to parse naming_contract.yaml: %s", exc)
```

- [ ] **Step 9: Run the new tests to verify they pass**

```bash
python -m pytest tests/test_orchestrator_contract.py -v
```

Expected: 4 passed

- [ ] **Step 10: Run the full test suite to check no regressions**

```bash
python -m pytest tests/ -q --tb=short 2>&1 | tail -15
```

Expected: all existing tests still pass (same count as before)

- [ ] **Step 11: Commit**

```bash
git add orchestrator.py tests/test_orchestrator_contract.py
git commit -m "feat(orchestrator): add contract_validate stage to TDD pipeline"
```

---

## Task 7: RAG Test Indexing After `qa_write`

**Files:**
- Modify: `orchestrator.py` (`_stage_qa_write` method, ~line 4450)

- [ ] **Step 1: Add RAG indexing call in `_stage_qa_write()`**

Find `_stage_qa_write()`. At the end of the method (after the `tdd_commit_tests` block), add:

```python
# Index test files into RAG so Engineer can search test expectations
if self.repo_auto_indexer and result.test_files:
    try:
        # Use the existing index_files API (same as regular code indexing)
        for filepath, content in result.test_files.items():
            safe_name = "".join(
                c if c.isalnum() or c in "-_./'" else "_"
                for c in (result.project_name or "project").lower()
            )
            self.repo_auto_indexer.index_text(
                text=content,
                source=filepath,
                collection="test_files",
            )
        _log.info(
            "[qa_write] indexed %d test file(s) into RAG collection 'test_files'",
            len(result.test_files),
        )
    except Exception as exc:
        _log.warning("[qa_write] RAG test indexing failed (non-fatal): %s", exc)
```

Note: This uses `index_text()` if available, with a graceful fallback. The `except` ensures this never blocks the pipeline.

- [ ] **Step 2: Verify the call site is correct by checking the indexer API**

```bash
grep -n "def index" /home/wanleung/Projects/ai-software-house/rag-mcp/indexer.py 2>/dev/null | head -10
```

If `index_text` doesn't exist, check what method does exist and adjust the call accordingly.

- [ ] **Step 3: Run the full test suite**

```bash
python -m pytest tests/ -q --tb=short 2>&1 | tail -10
```

Expected: all tests pass

- [ ] **Step 4: Commit**

```bash
git add orchestrator.py
git commit -m "feat(orchestrator): index test files into RAG after qa_write stage"
```

---

## Task 8: Final Verification

- [ ] **Step 1: Run the complete test suite**

```bash
cd /home/wanleung/Projects/ai-software-house && source venv/bin/activate
python -m pytest tests/ -q 2>&1 | tail -15
```

Expected: all existing tests pass + new tests from Tasks 1, 5, 6 pass

- [ ] **Step 2: Verify all 6 deliverables are complete**

```bash
# 1. SHA retry
grep -n "_sha_retry\|_get_contents_sha" github_client.py | head -5

# 2. QA rules
grep -n "dependency_overrides\|naming_contract" roles/qa_engineer.md | head -3

# 3. Engineer rule
grep -n "naming_contract\|Naming Contract" roles/engineer.md | head -3

# 4. Architect rule
grep -n "naming_contract.yaml\|Naming Contract" roles/architect.md | head -3

# 5. Contract validator
ls agents/contract_validator.py roles/contract_validator.md

# 6. Pipeline stage
grep -n "contract_validate" orchestrator.py | head -5
```

- [ ] **Step 3: Commit final summary**

```bash
git commit --allow-empty -m "chore: all 6 pipeline improvements delivered

- fix(github_client): SHA retry on 409 commit conflict
- docs(roles): QA/Engineer/Architect naming contract rules  
- feat(agents): ContractValidatorAgent
- feat(orchestrator): contract_validate stage in TDD pipeline
- feat(orchestrator): RAG test indexing after qa_write"
```
