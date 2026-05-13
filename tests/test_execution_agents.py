"""Tests for DeploymentTesterAgent, QAPlannerAgent, MemoryBankUpdaterAgent, SeniorEngineerAgent."""
from unittest.mock import MagicMock


class TestDeploymentTesterAgent:
    """Tests for DeploymentTesterAgent."""

    def _make_agent(self):
        from agents.deployment_tester import DeploymentTesterAgent
        agent = DeploymentTesterAgent.__new__(DeploymentTesterAgent)
        agent._backend = MagicMock()
        agent.model = "gpt-4"
        agent.config = {}
        return agent

    def test_run_returns_dict_with_deploy_files(self, monkeypatch):
        """Test that run() returns a dict with deploy_files, deploy_plan, and raw_response."""
        from agents.deployment_tester import DeploymentTesterAgent
        agent = self._make_agent()
        
        mock_response = """
### FILE: docker-compose.test.yml
```yaml
version: '3.8'
services:
  app:
    build: .
```

### FILE: tests/test_deployment.py
```python
def test_health():
    assert True
```

# Deployment Test Plan

This is the deployment test plan.
"""
        monkeypatch.setattr(DeploymentTesterAgent, "call", lambda self, prompt: mock_response)
        
        files = {"app.py": "print('hello')"}
        result = agent.run(files=files, prd="# PRD", project_name="TestProject")
        
        assert "deploy_files" in result
        assert "deploy_plan" in result
        assert "raw_response" in result
        assert isinstance(result["deploy_files"], dict)
        assert "docker-compose.test.yml" in result["deploy_files"]
        assert "tests/test_deployment.py" in result["deploy_files"]
        assert "version: '3.8'" in result["deploy_files"]["docker-compose.test.yml"]
        assert "This is the deployment test plan" in result["deploy_plan"]

    def test_run_includes_prd_in_prompt(self, monkeypatch):
        """Test that run() includes PRD content in the prompt."""
        from agents.deployment_tester import DeploymentTesterAgent
        agent = self._make_agent()
        
        captured_prompts = []
        
        def mock_call(self, prompt):
            captured_prompts.append(prompt)
            return "### FILE: test.yml\n```\ntest\n```\n# Deployment Test Plan\nplan"
        
        monkeypatch.setattr(DeploymentTesterAgent, "call", mock_call)
        
        agent.run(files={"main.py": "code"}, prd="# My PRD Content", project_name="MyProject")
        
        assert len(captured_prompts) == 1
        prompt = captured_prompts[0]
        assert "MyProject" in prompt
        assert "# My PRD Content" in prompt
        assert "main.py" in prompt

    def test_run_docker_smoke_tests_returns_skipped_when_no_files(self, tmp_path):
        """Test that run_docker_smoke_tests returns skipped when no compose file exists."""
        from agents.deployment_tester import DeploymentTesterAgent
        agent = self._make_agent()
        
        result = agent.run_docker_smoke_tests(tmp_path)
        
        assert result["passed"] is None
        assert result["skipped"] is True
        assert "No docker-compose.test.yml" in result["output"]

    def test_run_via_script_success(self, tmp_path, monkeypatch):
        """Test _run_via_script returns passed=True on successful script execution."""
        from agents.deployment_tester import DeploymentTesterAgent
        import subprocess
        agent = self._make_agent()
        
        script_path = tmp_path / "scripts" / "deploy_test.sh"
        script_path.parent.mkdir(parents=True)
        script_path.write_text("#!/bin/bash\necho 'test passed'\nexit 0")
        
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "test passed\n"
        mock_proc.stderr = ""
        
        def mock_run(cmd, **kwargs):
            return mock_proc
        
        monkeypatch.setattr(subprocess, "run", mock_run)
        
        result = agent._run_via_script(script_path, tmp_path)
        
        assert result["passed"] is True
        assert result["skipped"] is False
        assert "test passed" in result["output"]

    def test_run_via_script_failure(self, tmp_path, monkeypatch):
        """Test _run_via_script returns passed=False on script failure."""
        from agents.deployment_tester import DeploymentTesterAgent
        import subprocess
        agent = self._make_agent()
        
        script_path = tmp_path / "scripts" / "deploy_test.sh"
        script_path.parent.mkdir(parents=True)
        script_path.write_text("#!/bin/bash\nexit 1")
        
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = ""
        mock_proc.stderr = "Error: test failed"
        
        monkeypatch.setattr(subprocess, "run", lambda cmd, **kwargs: mock_proc)
        
        result = agent._run_via_script(script_path, tmp_path)
        
        assert result["passed"] is False
        assert result["skipped"] is False
        assert "Error: test failed" in result["output"]

    def test_parse_files_extracts_multiple_files(self):
        """Test _parse_files extracts multiple file blocks correctly."""
        from agents.deployment_tester import DeploymentTesterAgent
        
        response = """
Some preamble text.

### FILE: docker-compose.test.yml
```yaml
version: '3.8'
services:
  app:
    build: .
```

### FILE: tests/test_deployment.py
```python
def test_health():
    assert True
```

Some trailing text.
"""
        files = DeploymentTesterAgent._parse_files(response)
        
        assert len(files) == 2
        assert "docker-compose.test.yml" in files
        assert "tests/test_deployment.py" in files
        assert "version: '3.8'" in files["docker-compose.test.yml"]
        assert "def test_health" in files["tests/test_deployment.py"]

    def test_extract_deploy_plan(self):
        """Test _extract_deploy_plan extracts the deployment test plan section."""
        from agents.deployment_tester import DeploymentTesterAgent
        
        response = """
Some initial content.

# Deployment Test Plan

This is the plan content.
It spans multiple lines.

## Another section
This should be included too.
"""
        plan = DeploymentTesterAgent._extract_deploy_plan(response)
        
        assert "Deployment Test Plan" in plan
        assert "This is the plan content" in plan
        assert "It spans multiple lines" in plan


class TestQAPlannerAgent:
    """Tests for QAPlannerAgent."""

    def _make_agent(self):
        from agents.qa_planner import QAPlannerAgent
        agent = QAPlannerAgent.__new__(QAPlannerAgent)
        agent._backend = MagicMock()
        agent.model = "gpt-4"
        agent.config = {}
        agent._tool_registry = MagicMock()
        return agent

    def test_run_returns_test_plan(self, monkeypatch):
        """Test that run() returns a dict with test_plan, acceptance_criteria, and success."""
        from agents.qa_planner import QAPlannerAgent
        agent = self._make_agent()
        
        mock_response = """
# Test Plan

## Acceptance Criteria
- AC-01: User can login
- AC-02: User can logout
- AC-03: Session expires after timeout

TEST PLAN COMPLETE
"""
        monkeypatch.setattr(QAPlannerAgent, "call_with_tools", lambda self, prompt, tools: mock_response)
        
        result = agent.run(
            prd="# PRD",
            design="# Design",
            files={"main.py": "code"},
            project_name="Test"
        )
        
        assert "test_plan" in result
        assert "acceptance_criteria" in result
        assert "success" in result
        assert result["test_plan"] == mock_response
        assert len(result["acceptance_criteria"]) == 3
        assert "AC-01" in result["acceptance_criteria"]
        assert "AC-02" in result["acceptance_criteria"]
        assert "AC-03" in result["acceptance_criteria"]
        assert result["success"] is True

    def test_run_success_false_when_not_complete(self, monkeypatch):
        """Test that run() sets success=False when plan is incomplete."""
        from agents.qa_planner import QAPlannerAgent
        agent = self._make_agent()
        
        mock_response = "# Partial Test Plan\nStill working on it..."
        monkeypatch.setattr(QAPlannerAgent, "call_with_tools", lambda self, prompt, tools: mock_response)
        
        result = agent.run(
            prd="# PRD",
            design="# Design",
            files={},
            project_name="Test"
        )
        
        assert result["success"] is False

    def test_run_includes_prd_and_design_in_prompt(self, monkeypatch):
        """Test that run() includes PRD and design in the prompt."""
        from agents.qa_planner import QAPlannerAgent
        agent = self._make_agent()
        
        captured_prompts = []
        
        def mock_call_with_tools(self, prompt, tools):
            captured_prompts.append(prompt)
            return "# Test Plan\nTEST PLAN COMPLETE"
        
        monkeypatch.setattr(QAPlannerAgent, "call_with_tools", mock_call_with_tools)
        
        agent.run(
            prd="# My PRD Content",
            design="# My Design Content",
            files={"app.py": "def main(): pass"},
            project_name="MyProject"
        )
        
        assert len(captured_prompts) == 1
        prompt = captured_prompts[0]
        assert "MyProject" in prompt
        assert "# My PRD Content" in prompt
        assert "# My Design Content" in prompt
        assert "app.py" in prompt

    def test_run_with_repo_includes_tool_hint(self, monkeypatch):
        """Test that run() includes tool hint when repo is provided."""
        from agents.qa_planner import QAPlannerAgent
        agent = self._make_agent()
        
        captured_prompts = []
        
        def mock_call_with_tools(self, prompt, tools):
            captured_prompts.append(prompt)
            return "# Test Plan\nTEST PLAN COMPLETE"
        
        monkeypatch.setattr(QAPlannerAgent, "call_with_tools", mock_call_with_tools)
        
        agent.run(
            prd="# PRD",
            design="# Design",
            files={},
            project_name="Test",
            repo="owner/repo"
        )
        
        assert len(captured_prompts) == 1
        prompt = captured_prompts[0]
        assert "search_github_issues" in prompt
        assert "owner/repo" in prompt

    def test_extract_ac_ids(self):
        """Test _extract_ac_ids finds all AC identifiers."""
        from agents.qa_planner import QAPlannerAgent
        
        test_plan = """
# Test Plan

## Acceptance Criteria
- AC-01: Login functionality
- AC-02: Logout functionality
- AC-10: Session management
- AC-99: Error handling
"""
        ac_ids = QAPlannerAgent._extract_ac_ids(test_plan)
        
        assert len(ac_ids) == 4
        assert "AC-01" in ac_ids
        assert "AC-02" in ac_ids
        assert "AC-10" in ac_ids
        assert "AC-99" in ac_ids

    def test_truncate_files(self):
        """Test that run() truncates large files in the summary."""
        from agents.qa_planner import QAPlannerAgent
        agent = self._make_agent()
        
        # Create a dict with large files
        files = {
            "large.py": "x" * 10000,
            "small.py": "y" * 100
        }
        
        truncated = agent.truncate_files(files, max_chars=8000)
        
        # Verify truncation occurred
        assert len(str(truncated)) < 10000
        # Verify small file is intact
        assert "small.py" in truncated


class TestMemoryBankUpdaterAgent:
    """Tests for MemoryBankUpdaterAgent."""

    def _make_agent(self):
        from agents.memory_bank_updater import MemoryBankUpdaterAgent
        agent = MemoryBankUpdaterAgent.__new__(MemoryBankUpdaterAgent)
        agent._backend = MagicMock()
        agent.model = "gpt-4"
        agent.config = {}
        return agent

    def test_update_returns_updated_files(self, monkeypatch):
        """Test that update() returns a dict of updated memory bank files."""
        from agents.memory_bank_updater import MemoryBankUpdaterAgent
        agent = self._make_agent()
        
        mock_response = """
### FILE: memory-bank/activeContext.md
# Active Context

Updated content for active context.

### FILE: memory-bank/progress.md
# Progress

New progress entry: implemented authentication module.
"""
        monkeypatch.setattr(MemoryBankUpdaterAgent, "call", lambda self, prompt: mock_response)
        
        current_bank = {
            "activeContext.md": "# Active Context\nOld content",
            "progress.md": "# Progress\nOld progress"
        }
        run_summary = "Implemented authentication module with JWT tokens."
        
        result = agent.update(current_bank, run_summary)
        
        assert "activeContext.md" in result
        assert "progress.md" in result
        assert "Updated content for active context" in result["activeContext.md"]
        assert "implemented authentication module" in result["progress.md"]

    def test_update_includes_run_summary_in_prompt(self, monkeypatch):
        """Test that update() includes the run summary in the prompt."""
        from agents.memory_bank_updater import MemoryBankUpdaterAgent
        agent = self._make_agent()
        
        captured_prompts = []
        
        def mock_call(self, prompt):
            captured_prompts.append(prompt)
            return "### FILE: memory-bank/progress.md\nUpdated"
        
        monkeypatch.setattr(MemoryBankUpdaterAgent, "call", mock_call)
        
        current_bank = {"progress.md": "Old content"}
        run_summary = "This is the pipeline run summary with specific details."
        
        agent.update(current_bank, run_summary)
        
        assert len(captured_prompts) == 1
        prompt = captured_prompts[0]
        assert "This is the pipeline run summary with specific details" in prompt
        assert "Old content" in prompt

    def test_update_includes_current_bank_in_prompt(self, monkeypatch):
        """Test that update() includes current bank contents in the prompt."""
        from agents.memory_bank_updater import MemoryBankUpdaterAgent
        agent = self._make_agent()
        
        captured_prompts = []
        
        def mock_call(self, prompt):
            captured_prompts.append(prompt)
            return "### FILE: memory-bank/activeContext.md\nUpdated"
        
        monkeypatch.setattr(MemoryBankUpdaterAgent, "call", mock_call)
        
        current_bank = {
            "activeContext.md": "# Current Active Context",
            "progress.md": "# Current Progress"
        }
        
        agent.update(current_bank, "Run summary")
        
        assert len(captured_prompts) == 1
        prompt = captured_prompts[0]
        assert "# Current Active Context" in prompt
        assert "# Current Progress" in prompt
        assert "memory-bank/activeContext.md" in prompt
        assert "memory-bank/progress.md" in prompt

    def test_parse_output_extracts_only_valid_bank_files(self):
        """Test _parse_output only returns files in BANK_FILES."""
        from agents.memory_bank_updater import MemoryBankUpdaterAgent
        
        raw = """
### FILE: memory-bank/activeContext.md
Valid file content

### FILE: memory-bank/invalid.md
This should be ignored

### FILE: memory-bank/progress.md
Another valid file
"""
        agent = self._make_agent()
        result = agent._parse_output(raw)
        
        assert "activeContext.md" in result
        assert "progress.md" in result
        assert "invalid.md" not in result
        assert len(result) == 2

    def test_parse_output_handles_empty_response(self):
        """Test _parse_output returns empty dict for response with no files."""
        from agents.memory_bank_updater import MemoryBankUpdaterAgent
        
        raw = "No file headers in this response."
        agent = self._make_agent()
        result = agent._parse_output(raw)
        
        assert result == {}

    def test_update_returns_only_changed_files(self, monkeypatch):
        """Test that update() only returns files that actually changed."""
        from agents.memory_bank_updater import MemoryBankUpdaterAgent
        agent = self._make_agent()
        
        # Mock response only updates one file
        mock_response = "### FILE: memory-bank/progress.md\nNew progress content"
        monkeypatch.setattr(MemoryBankUpdaterAgent, "call", lambda self, prompt: mock_response)
        
        current_bank = {
            "activeContext.md": "Unchanged",
            "progress.md": "Old progress",
            "techContext.md": "Also unchanged"
        }
        
        result = agent.update(current_bank, "Summary")
        
        # Only progress.md should be returned
        assert len(result) == 1
        assert "progress.md" in result
        assert "activeContext.md" not in result
        assert "techContext.md" not in result


class TestSeniorEngineerAgent:
    """Tests for SeniorEngineerAgent."""

    def _make_agent(self):
        from agents.senior_engineer import SeniorEngineerAgent
        agent = SeniorEngineerAgent.__new__(SeniorEngineerAgent)
        agent._backend = MagicMock()
        agent.model = "gpt-4"
        agent.config = {}
        agent._tool_registry = None
        return agent

    def test_run_module_injects_junior_context(self, monkeypatch):
        """Test that run_module() injects junior_files into the design context."""
        from agents.senior_engineer import SeniorEngineerAgent
        agent = self._make_agent()
        
        captured_designs = []
        
        def mock_run_module(self, design, module, project_name, framework_context):
            captured_designs.append(design)
            return {
                "files": {"main.py": "code"},
                "module_name": "integration",
                "raw_response": "response"
            }
        
        # Patch the parent class method
        from agents.engineer import EngineerAgent
        monkeypatch.setattr(EngineerAgent, "run_module", mock_run_module)
        
        junior_files = {
            "models/user.py": "class User: pass",
            "utils/helpers.py": "def helper(): pass"
        }
        
        module = {"name": "api", "description": "API endpoints"}
        result = agent.run_module(
            design="# System Design",
            module=module,
            junior_files=junior_files
        )
        
        assert len(captured_designs) == 1
        design = captured_designs[0]
        assert "Junior Code Context" in design
        assert "models/user.py" in design
        assert "class User: pass" in design
        assert "utils/helpers.py" in design
        assert "def helper" in design
        assert "# System Design" in design

    def test_run_module_without_junior_context(self, monkeypatch):
        """Test that run_module() works without junior_files."""
        from agents.senior_engineer import SeniorEngineerAgent
        agent = self._make_agent()
        
        captured_designs = []
        
        def mock_run_module(self, design, module, project_name, framework_context):
            captured_designs.append(design)
            return {
                "files": {"main.py": "code"},
                "module_name": "integration",
                "raw_response": "response"
            }
        
        from agents.engineer import EngineerAgent
        monkeypatch.setattr(EngineerAgent, "run_module", mock_run_module)
        
        module = {"name": "api", "description": "API endpoints"}
        result = agent.run_module(
            design="# System Design",
            module=module,
            junior_files=None
        )
        
        assert len(captured_designs) == 1
        design = captured_designs[0]
        assert "Junior Code Context" not in design
        assert design == "# System Design"

    def test_run_module_returns_parent_result(self, monkeypatch):
        """Test that run_module() returns the result from parent's run_module."""
        from agents.senior_engineer import SeniorEngineerAgent
        agent = self._make_agent()
        
        expected_result = {
            "files": {"api.py": "def api_handler(): pass"},
            "module_name": "integration",
            "raw_response": "Full LLM response"
        }
        
        def mock_run_module(self, design, module, project_name, framework_context):
            return expected_result
        
        from agents.engineer import EngineerAgent
        monkeypatch.setattr(EngineerAgent, "run_module", mock_run_module)
        
        module = {"name": "api", "description": "API"}
        result = agent.run_module(design="# Design", module=module)
        
        assert result == expected_result

    def test_run_module_with_test_files_injects_tdd_section(self, monkeypatch):
        """Test that run_module() injects test files into the design for TDD."""
        from agents.senior_engineer import SeniorEngineerAgent
        agent = self._make_agent()
        
        captured_designs = []
        
        def mock_run_module(self, design, module, project_name, framework_context):
            captured_designs.append(design)
            return {"files": {}, "module_name": "api", "raw_response": ""}
        
        from agents.engineer import EngineerAgent
        monkeypatch.setattr(EngineerAgent, "run_module", mock_run_module)
        
        test_files = {
            "tests/test_api.py": "def test_endpoint(): assert True"
        }
        
        module = {"name": "api", "description": "API"}
        result = agent.run_module(
            design="# System Design",
            module=module,
            test_files=test_files
        )
        
        assert len(captured_designs) == 1
        design = captured_designs[0]
        assert "Pre-written tests your implementation must pass" in design
        assert "tests/test_api.py" in design
        assert "def test_endpoint" in design
        assert "Do not modify the test files" in design

    def test_run_module_with_both_junior_and_test_files(self, monkeypatch):
        """Test that run_module() handles both junior_files and test_files."""
        from agents.senior_engineer import SeniorEngineerAgent
        agent = self._make_agent()
        
        captured_designs = []
        
        def mock_run_module(self, design, module, project_name, framework_context):
            captured_designs.append(design)
            return {"files": {}, "module_name": "api", "raw_response": ""}
        
        from agents.engineer import EngineerAgent
        monkeypatch.setattr(EngineerAgent, "run_module", mock_run_module)
        
        junior_files = {"models/user.py": "class User: pass"}
        test_files = {"tests/test_api.py": "def test_api(): pass"}
        
        module = {"name": "api", "description": "API"}
        result = agent.run_module(
            design="# System Design",
            module=module,
            junior_files=junior_files,
            test_files=test_files
        )
        
        assert len(captured_designs) == 1
        design = captured_designs[0]
        assert "Junior Code Context" in design
        assert "models/user.py" in design
        assert "Pre-written tests your implementation must pass" in design
        assert "tests/test_api.py" in design
        assert "# System Design" in design

    def test_run_module_truncates_large_test_files(self, monkeypatch):
        """Test that run_module() truncates test files that are too large."""
        from agents.senior_engineer import SeniorEngineerAgent
        agent = self._make_agent()
        
        captured_designs = []
        
        def mock_run_module(self, design, module, project_name, framework_context):
            captured_designs.append(design)
            return {"files": {}, "module_name": "api", "raw_response": ""}
        
        from agents.engineer import EngineerAgent
        monkeypatch.setattr(EngineerAgent, "run_module", mock_run_module)
        
        # Create a test file larger than MAX_FILE_CHARS (3000)
        large_test = "x" * 5000
        test_files = {"tests/test_large.py": large_test}
        
        module = {"name": "api", "description": "API"}
        result = agent.run_module(
            design="# System Design",
            module=module,
            test_files=test_files
        )
        
        assert len(captured_designs) == 1
        design = captured_designs[0]
        assert "truncated" in design.lower()
