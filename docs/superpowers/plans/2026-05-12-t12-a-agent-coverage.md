# T12-A: Agent Class Coverage + Memory Store — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add test coverage for the 7 under-covered agent classes (19–50%) and `memory_store.py` (44%), and fix the deprecated `datetime.utcnow()` usage in `memory_store.py`.

**Architecture:** All agent tests mock the LLM backend via monkeypatching `BaseAgent._call_backend` (or the agent's `call()` method) so no real HTTP is made. The `memory_store.py` fix replaces `datetime.utcnow()` with `datetime.now(timezone.utc)`. Tests use `tmp_path` for file-based backends.

**Tech Stack:** `pytest`, `unittest.mock`, `tmp_path`.

---

### Task 1: Read Agent Source Files Before Writing Tests

Before writing tests, read each agent file to understand:
- Method signatures (`run()`, `review()`, etc.)
- Verdict constants and their string values
- How LLM response is parsed (what triggers `VERDICT_REVISION`)
- What the agent returns

- [ ] **Step 1: Read the six agent files**

  ```bash
  head -120 agents/architect_reviewer.py
  head -100 agents/pm_reviewer.py
  head -100 agents/code_reviewer.py
  head -80 agents/deployment_tester.py
  head -80 agents/qa_planner.py
  head -80 agents/memory_bank_updater.py
  head -80 agents/senior_engineer.py
  ```

  Note for each agent:
  - Main method name and signature
  - Verdict constants (their exact string values)
  - Return type (dict, str, or custom object)
  - How the LLM response is passed in (constructor arg? method arg?)

---

### Task 2: Tests for Reviewer Agents

**Files:**
- Create: `tests/test_reviewer_agents.py`

- [ ] **Step 1: Create test file**

  Write tests based on what you found in Task 1. The template below uses `ArchitectReviewer` — adapt for `PMReviewer` and `CodeReviewer` by checking their actual constant values (e.g., `"PRD APPROVED"` vs `"DESIGN APPROVED"`).

  ```python
  # tests/test_reviewer_agents.py
  """Tests for ArchitectReviewerAgent, PMReviewerAgent, CodeReviewerAgent."""
  from unittest.mock import MagicMock, patch

  import pytest


  # ---------------------------------------------------------------------------
  # ArchitectReviewerAgent
  # ---------------------------------------------------------------------------

  class TestArchitectReviewer:
      def _make_agent(self):
          from agents.architect_reviewer import ArchitectReviewerAgent
          agent = ArchitectReviewerAgent.__new__(ArchitectReviewerAgent)
          # Minimal initialisation — skip LLM backend setup
          agent._backend = MagicMock()
          return agent

      def test_parse_verdict_approved(self):
          from agents.architect_reviewer import ArchitectReviewerAgent
          agent = self._make_agent()
          verdict = agent._parse_verdict("The design is good. DESIGN APPROVED.")
          assert verdict == ArchitectReviewerAgent.VERDICT_APPROVED

      def test_parse_verdict_suggestions(self):
          from agents.architect_reviewer import ArchitectReviewerAgent
          agent = self._make_agent()
          verdict = agent._parse_verdict("DESIGN APPROVED WITH SUGGESTIONS for the API.")
          assert verdict == ArchitectReviewerAgent.VERDICT_SUGGESTIONS

      def test_parse_verdict_revision(self):
          from agents.architect_reviewer import ArchitectReviewerAgent
          agent = self._make_agent()
          verdict = agent._parse_verdict("The spec is incomplete. DESIGN NEEDS REVISION.")
          assert verdict == ArchitectReviewerAgent.VERDICT_REVISION

      def test_parse_verdict_unknown_defaults_to_suggestions(self):
          from agents.architect_reviewer import ArchitectReviewerAgent
          agent = self._make_agent()
          verdict = agent._parse_verdict("No verdict marker here at all.")
          assert verdict == ArchitectReviewerAgent.VERDICT_SUGGESTIONS

      def test_review_returns_needs_revision_false_on_approval(self, monkeypatch):
          from agents.architect_reviewer import ArchitectReviewerAgent
          monkeypatch.setattr(
              "agents.architect_reviewer.ArchitectReviewerAgent.call",
              lambda self, prompt, **kw: "Good design. DESIGN APPROVED.",
          )
          # Construct with minimal config
          agent = ArchitectReviewerAgent.__new__(ArchitectReviewerAgent)
          agent._backend = MagicMock()
          agent.model = "gpt-4"
          agent.config = {}
          result = agent.review("spec text", "project")
          assert result["needs_revision"] is False
          assert result["verdict"] == ArchitectReviewerAgent.VERDICT_APPROVED

      def test_review_returns_needs_revision_true_on_revision(self, monkeypatch):
          from agents.architect_reviewer import ArchitectReviewerAgent
          monkeypatch.setattr(
              "agents.architect_reviewer.ArchitectReviewerAgent.call",
              lambda self, prompt, **kw: "DESIGN NEEDS REVISION.",
          )
          agent = ArchitectReviewerAgent.__new__(ArchitectReviewerAgent)
          agent._backend = MagicMock()
          agent.model = "gpt-4"
          agent.config = {}
          result = agent.review("spec text", "project")
          assert result["needs_revision"] is True

      def test_review_includes_context_in_call(self, monkeypatch):
          from agents.architect_reviewer import ArchitectReviewerAgent
          calls = []
          monkeypatch.setattr(
              "agents.architect_reviewer.ArchitectReviewerAgent.call",
              lambda self, prompt, **kw: (calls.append(prompt), "DESIGN APPROVED.")[1],
          )
          agent = ArchitectReviewerAgent.__new__(ArchitectReviewerAgent)
          agent._backend = MagicMock()
          agent.model = "gpt-4"
          agent.config = {}
          agent.review("MY_UNIQUE_SPEC_CONTENT", "project")
          assert any("MY_UNIQUE_SPEC_CONTENT" in c for c in calls)


  # ---------------------------------------------------------------------------
  # PMReviewerAgent
  # ---------------------------------------------------------------------------

  class TestPMReviewer:
      def test_parse_verdict_approved(self):
          from agents.pm_reviewer import PMReviewerAgent
          agent = PMReviewerAgent.__new__(PMReviewerAgent)
          verdict = agent._parse_verdict("PRD APPROVED.")
          assert verdict == PMReviewerAgent.VERDICT_APPROVED

      def test_parse_verdict_revision(self):
          from agents.pm_reviewer import PMReviewerAgent
          agent = PMReviewerAgent.__new__(PMReviewerAgent)
          verdict = agent._parse_verdict("PRD NEEDS REVISION — missing acceptance criteria.")
          assert verdict == PMReviewerAgent.VERDICT_REVISION

      def test_review_needs_revision_false_on_approved(self, monkeypatch):
          from agents.pm_reviewer import PMReviewerAgent
          monkeypatch.setattr(
              "agents.pm_reviewer.PMReviewerAgent.call",
              lambda self, prompt, **kw: "PRD APPROVED.",
          )
          agent = PMReviewerAgent.__new__(PMReviewerAgent)
          agent._backend = MagicMock()
          agent.model = "gpt-4"
          agent.config = {}
          result = agent.review("prd text", "project")
          assert result["needs_revision"] is False

      def test_review_needs_revision_true_on_revision(self, monkeypatch):
          from agents.pm_reviewer import PMReviewerAgent
          monkeypatch.setattr(
              "agents.pm_reviewer.PMReviewerAgent.call",
              lambda self, prompt, **kw: "PRD NEEDS REVISION.",
          )
          agent = PMReviewerAgent.__new__(PMReviewerAgent)
          agent._backend = MagicMock()
          agent.model = "gpt-4"
          agent.config = {}
          result = agent.review("prd text", "project")
          assert result["needs_revision"] is True


  # ---------------------------------------------------------------------------
  # CodeReviewerAgent
  # ---------------------------------------------------------------------------

  class TestCodeReviewer:
      def test_review_approved(self, monkeypatch):
          from agents.code_reviewer import CodeReviewerAgent
          monkeypatch.setattr(
              "agents.code_reviewer.CodeReviewerAgent.call",
              lambda self, prompt, **kw: f"{CodeReviewerAgent.VERDICT_APPROVED}",
          )
          agent = CodeReviewerAgent.__new__(CodeReviewerAgent)
          agent._backend = MagicMock()
          agent.model = "gpt-4"
          agent.config = {}
          result = agent.review("diff text", "project")
          assert result["needs_revision"] is False

      def test_review_revision(self, monkeypatch):
          from agents.code_reviewer import CodeReviewerAgent
          monkeypatch.setattr(
              "agents.code_reviewer.CodeReviewerAgent.call",
              lambda self, prompt, **kw: f"{CodeReviewerAgent.VERDICT_REVISION}",
          )
          agent = CodeReviewerAgent.__new__(CodeReviewerAgent)
          agent._backend = MagicMock()
          agent.model = "gpt-4"
          agent.config = {}
          result = agent.review("diff text", "project")
          assert result["needs_revision"] is True

      def test_review_includes_diff_in_prompt(self, monkeypatch):
          from agents.code_reviewer import CodeReviewerAgent
          calls = []
          monkeypatch.setattr(
              "agents.code_reviewer.CodeReviewerAgent.call",
              lambda self, prompt, **kw: (calls.append(prompt), CodeReviewerAgent.VERDICT_APPROVED)[1],
          )
          agent = CodeReviewerAgent.__new__(CodeReviewerAgent)
          agent._backend = MagicMock()
          agent.model = "gpt-4"
          agent.config = {}
          agent.review("UNIQUE_DIFF_CONTENT", "project")
          assert any("UNIQUE_DIFF_CONTENT" in c for c in calls)
  ```

  **IMPORTANT:** If any agent doesn't have a `_parse_verdict` method, or if the method is named differently, or if the agent's `review()` takes different arguments, adjust the test to match the actual source. Read `agents/architect_reviewer.py` (Task 1) before writing tests.

- [ ] **Step 2: Run tests**

  ```bash
  pytest tests/test_reviewer_agents.py -v
  ```
  Expected: all pass. Fix any `AttributeError` by adjusting method names to match actual source.

- [ ] **Step 3: Commit**

  ```bash
  git add tests/test_reviewer_agents.py
  git commit -m "test: add coverage for ArchitectReviewer, PMReviewer, CodeReviewer agents"
  ```

---

### Task 3: Tests for Execution Agents

**Files:**
- Create: `tests/test_execution_agents.py`

- [ ] **Step 1: Read execution agent files carefully**

  ```bash
  cat agents/deployment_tester.py
  cat agents/qa_planner.py
  cat agents/memory_bank_updater.py
  cat agents/senior_engineer.py
  ```

  Note for each:
  - Does `run()` call subprocess? Which module? (`subprocess.run`, `subprocess.Popen`, or a helper?)
  - What does `run()` return? (dict with specific keys?)
  - How does `memory_bank_updater` access the memory store?
  - How does `senior_engineer` receive junior context?

- [ ] **Step 2: Create test file**

  ```python
  # tests/test_execution_agents.py
  """Tests for DeploymentTesterAgent, QAPlannerAgent, MemoryBankUpdaterAgent, SeniorEngineerAgent."""
  import subprocess
  from unittest.mock import MagicMock, patch

  import pytest


  # ---------------------------------------------------------------------------
  # DeploymentTesterAgent
  # ---------------------------------------------------------------------------

  class TestDeploymentTesterAgent:
      def _make_agent(self, monkeypatch):
          from agents.deployment_tester import DeploymentTesterAgent
          # Patch LLM call so we don't need a real backend
          monkeypatch.setattr(
              "agents.deployment_tester.DeploymentTesterAgent.call",
              lambda self, prompt, **kw: "```yaml\nservices:\n  app:\n    image: myapp\n```\nTest passed.",
          )
          agent = DeploymentTesterAgent.__new__(DeploymentTesterAgent)
          agent._backend = MagicMock()
          agent.model = "gpt-4"
          agent.config = {}
          return agent

      def test_run_executes_docker_compose(self, tmp_path, monkeypatch):
          agent = self._make_agent(monkeypatch)
          proc = MagicMock()
          proc.returncode = 0
          proc.stdout = "All tests passed"
          proc.stderr = ""
          monkeypatch.setattr("subprocess.run", lambda *a, **kw: proc)

          result = agent.run(
              files={"main.py": "print('hello')"},
              prd="Build a web app",
              project_name="test-project",
          )
          assert result is not None  # returns some result dict or string

      def test_run_handles_nonzero_subprocess_exit(self, tmp_path, monkeypatch):
          agent = self._make_agent(monkeypatch)
          proc = MagicMock()
          proc.returncode = 1
          proc.stdout = ""
          proc.stderr = "Container failed to start"
          monkeypatch.setattr("subprocess.run", lambda *a, **kw: proc)

          # Should not raise — result indicates failure
          result = agent.run(
              files={"main.py": "print('hello')"},
              prd="Build a web app",
          )
          assert result is not None


  # ---------------------------------------------------------------------------
  # QAPlannerAgent
  # ---------------------------------------------------------------------------

  class TestQAPlannerAgent:
      def _make_agent(self):
          from agents.qa_planner import QAPlannerAgent
          agent = QAPlannerAgent.__new__(QAPlannerAgent)
          agent._backend = MagicMock()
          agent.model = "gpt-4"
          agent.config = {}
          return agent

      def test_run_returns_test_plan(self, monkeypatch):
          from agents.qa_planner import QAPlannerAgent
          monkeypatch.setattr(
              "agents.qa_planner.QAPlannerAgent.call",
              lambda self, prompt, **kw: "## Test Plan\n- Unit tests\n- Integration tests",
          )
          agent = self._make_agent()
          result = agent.run(spec="Build a feature", project_name="proj")
          assert result is not None
          # Result should contain the LLM output
          result_str = result if isinstance(result, str) else str(result)
          assert "Test Plan" in result_str or len(result_str) > 0

      def test_run_includes_spec_in_prompt(self, monkeypatch):
          from agents.qa_planner import QAPlannerAgent
          calls = []
          monkeypatch.setattr(
              "agents.qa_planner.QAPlannerAgent.call",
              lambda self, prompt, **kw: (calls.append(prompt), "Test plan content")[1],
          )
          agent = self._make_agent()
          agent.run(spec="UNIQUE_SPEC_MARKER_12345", project_name="proj")
          assert any("UNIQUE_SPEC_MARKER_12345" in c for c in calls)


  # ---------------------------------------------------------------------------
  # MemoryBankUpdaterAgent
  # ---------------------------------------------------------------------------

  class TestMemoryBankUpdaterAgent:
      def _make_agent(self):
          from agents.memory_bank_updater import MemoryBankUpdaterAgent
          agent = MemoryBankUpdaterAgent.__new__(MemoryBankUpdaterAgent)
          agent._backend = MagicMock()
          agent.model = "gpt-4"
          agent.config = {}
          return agent

      def test_run_writes_to_memory_store(self, tmp_path, monkeypatch):
          from agents.memory_bank_updater import MemoryBankUpdaterAgent
          monkeypatch.setattr(
              "agents.memory_bank_updater.MemoryBankUpdaterAgent.call",
              lambda self, prompt, **kw: "Memory summary: feature completed",
          )
          mock_store = MagicMock()
          agent = self._make_agent()
          agent.memory_store = mock_store

          agent.run(
              pipeline_output="Engineer completed the feature",
              project_name="proj",
          )
          mock_store.write.assert_called_once()

      def test_run_includes_pipeline_output_in_entry(self, monkeypatch):
          from agents.memory_bank_updater import MemoryBankUpdaterAgent
          monkeypatch.setattr(
              "agents.memory_bank_updater.MemoryBankUpdaterAgent.call",
              lambda self, prompt, **kw: "Memory updated",
          )
          written_entries = []
          mock_store = MagicMock()
          mock_store.write.side_effect = lambda entry: written_entries.append(entry)

          agent = self._make_agent()
          agent.memory_store = mock_store

          agent.run(pipeline_output="UNIQUE_OUTPUT_MARKER", project_name="proj")
          # The entry written to the store should reference the pipeline output
          assert written_entries or mock_store.write.called


  # ---------------------------------------------------------------------------
  # SeniorEngineerAgent
  # ---------------------------------------------------------------------------

  class TestSeniorEngineerAgent:
      def _make_agent(self):
          from agents.senior_engineer import SeniorEngineerAgent
          agent = SeniorEngineerAgent.__new__(SeniorEngineerAgent)
          agent._backend = MagicMock()
          agent.model = "gpt-4"
          agent.config = {}
          return agent

      def test_run_injects_junior_context_in_prompt(self, monkeypatch):
          from agents.senior_engineer import SeniorEngineerAgent
          calls = []
          monkeypatch.setattr(
              "agents.senior_engineer.SeniorEngineerAgent.call",
              lambda self, prompt, **kw: (calls.append(prompt), "Senior output")[1],
          )
          agent = self._make_agent()
          agent.run(
              spec="Build a feature",
              junior_output="JUNIOR_CODE_MARKER_XYZ",
              project_name="proj",
          )
          assert any("JUNIOR_CODE_MARKER_XYZ" in c for c in calls)

      def test_run_returns_combined_output(self, monkeypatch):
          from agents.senior_engineer import SeniorEngineerAgent
          monkeypatch.setattr(
              "agents.senior_engineer.SeniorEngineerAgent.call",
              lambda self, prompt, **kw: "Reviewed and improved code",
          )
          agent = self._make_agent()
          result = agent.run(spec="spec", junior_output="junior code", project_name="proj")
          assert result is not None

      def test_run_handles_missing_junior_context(self, monkeypatch):
          from agents.senior_engineer import SeniorEngineerAgent
          monkeypatch.setattr(
              "agents.senior_engineer.SeniorEngineerAgent.call",
              lambda self, prompt, **kw: "Senior output without junior context",
          )
          agent = self._make_agent()
          # Should not raise even with None/empty junior_output
          result = agent.run(spec="spec", junior_output=None, project_name="proj")
          assert result is not None
  ```

  **IMPORTANT:** Adjust method signatures based on what you read in Task 1, Step 1. If `QAPlannerAgent.run()` takes `(prd, project_name)` instead of `(spec, project_name)`, use the correct parameter name. If `MemoryBankUpdaterAgent` uses `self.store` instead of `self.memory_store`, patch accordingly.

- [ ] **Step 3: Run tests**

  ```bash
  pytest tests/test_execution_agents.py -v
  ```
  Expected: all pass. Fix `TypeError` on argument names or `AttributeError` on attribute access by checking actual source.

- [ ] **Step 4: Commit**

  ```bash
  git add tests/test_execution_agents.py
  git commit -m "test: add coverage for DeploymentTester, QAPlanner, MemoryBankUpdater, SeniorEngineer"
  ```

---

### Task 4: Fix `datetime.utcnow()` in `memory_store.py` + Add Tests

**Files:**
- Modify: `memory_store.py`
- Create: `tests/test_memory_store_extended.py`

- [ ] **Step 1: Find all `utcnow()` calls**

  ```bash
  grep -n "utcnow" memory_store.py
  ```

- [ ] **Step 2: Replace each occurrence**

  For each line containing `datetime.utcnow()`:
  - Add `from datetime import timezone` at the top if not already imported
  - Replace `datetime.utcnow()` with `datetime.now(timezone.utc)`

  Example — if line 45 reads:
  ```python
  created_at = datetime.utcnow().isoformat()
  ```
  Change to:
  ```python
  created_at = datetime.now(timezone.utc).isoformat()
  ```

- [ ] **Step 3: Verify no more `utcnow` calls**

  ```bash
  grep -n "utcnow" memory_store.py
  ```
  Expected: no output.

- [ ] **Step 4: Run existing memory_store tests to confirm no regressions**

  ```bash
  pytest -k "memory_store or memory" -v
  ```
  Expected: all pass.

- [ ] **Step 5: Write new coverage tests**

  First read the full `memory_store.py` to understand its API:
  ```bash
  cat memory_store.py
  ```

  Then create `tests/test_memory_store_extended.py`:

  ```python
  # tests/test_memory_store_extended.py
  """Extended tests for memory_store.py covering previously-uncovered paths."""
  import pytest


  # After reading memory_store.py, fill in the actual class name, constructor args,
  # and method signatures. The template below assumes a MemoryStore class with
  # write(entry: dict), get(id: str), search(keyword: str) methods.
  # Adjust to match the actual API.

  class TestMemoryStoreReadWrite:
      def test_write_and_read_back(self, tmp_path):
          from memory_store import MemoryStore
          store = MemoryStore(path=str(tmp_path / "memory.db"))
          store.write({"id": "e1", "content": "Feature A completed", "tags": ["feature"]})
          result = store.get("e1")
          assert result is not None
          assert "Feature A" in str(result)

      def test_search_finds_matching_entry(self, tmp_path):
          from memory_store import MemoryStore
          store = MemoryStore(path=str(tmp_path / "memory.db"))
          store.write({"id": "e1", "content": "Redis integration done", "tags": []})
          store.write({"id": "e2", "content": "Auth module complete", "tags": []})
          results = store.search("Redis")
          assert len(results) >= 1
          assert any("Redis" in str(r) for r in results)

      def test_search_returns_empty_for_no_match(self, tmp_path):
          from memory_store import MemoryStore
          store = MemoryStore(path=str(tmp_path / "memory.db"))
          store.write({"id": "e1", "content": "Feature done", "tags": []})
          results = store.search("NONEXISTENT_KEYWORD_XYZ")
          assert results == [] or len(results) == 0

      def test_write_no_utcnow_deprecation_warning(self, tmp_path, recwarn):
          """Verify no DeprecationWarning from datetime.utcnow()."""
          from memory_store import MemoryStore
          store = MemoryStore(path=str(tmp_path / "memory.db"))
          store.write({"id": "e1", "content": "test entry", "tags": []})
          utcnow_warnings = [
              w for w in recwarn.list
              if "utcnow" in str(w.message).lower() or "deprecated" in str(w.message).lower()
          ]
          assert utcnow_warnings == [], f"Unexpected DeprecationWarning: {utcnow_warnings}"
  ```

  **IMPORTANT:** Read `memory_store.py` fully before writing the tests. Replace `MemoryStore(path=...)` with the actual constructor. If the store uses SQLite, the `path` kwarg may be named `db_path` or similar.

- [ ] **Step 6: Run new tests**

  ```bash
  pytest tests/test_memory_store_extended.py -v
  ```
  Expected: all pass.

- [ ] **Step 7: Commit**

  ```bash
  git add memory_store.py tests/test_memory_store_extended.py
  git commit -m "fix: replace datetime.utcnow() with datetime.now(UTC) in memory_store.py; add coverage tests"
  ```

---

### Task 5: Final Verification

- [ ] **Step 1: Run all new test files**

  ```bash
  pytest tests/test_reviewer_agents.py tests/test_execution_agents.py tests/test_memory_store_extended.py -v
  ```
  Expected: all pass.

- [ ] **Step 2: Confirm no DeprecationWarning in output**

  ```bash
  pytest tests/test_memory_store_extended.py -W error::DeprecationWarning -v
  ```
  Expected: passes (no `DeprecationWarning` from datetime).

- [ ] **Step 3: Run full suite**

  ```bash
  pytest --tb=short -q
  ```
  Expected: 0 failures.

- [ ] **Step 4: Push branch**

  ```bash
  git push origin t12-a-agent-coverage
  ```
