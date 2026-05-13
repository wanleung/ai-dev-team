"""Extended tests for DeploymentTesterAgent — run_with_github, docker smoke tests."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agents.deployment_tester import DeploymentTesterAgent


def _make_agent() -> DeploymentTesterAgent:
    agent = DeploymentTesterAgent.__new__(DeploymentTesterAgent)
    agent._llm = MagicMock()
    agent.system_prompt = ""
    agent._history = []
    agent.model = "gpt-4"
    return agent


# ── run() — deploy_snippets fallback ─────────────────────────────────────────

class TestDeploymentTesterRun:
    def test_run_uses_first_six_files_when_no_deploy_keys(self, monkeypatch):
        """run() falls back to first 6 files when no dockerfile/compose keys present."""
        agent = _make_agent()
        mock_call = MagicMock(return_value="### FILE: tests/test_deployment.py\n```\ndef test_health(): pass\n```")
        monkeypatch.setattr(agent, "call", mock_call)

        files = {f"src/module_{i}.py": f"code {i}" for i in range(8)}
        agent.run(files=files, prd="PRD text", project_name="MyApp")

        prompt = mock_call.call_args[0][0]
        # Only first 6 files should appear in the prompt code section
        assert "module_0.py" in prompt
        assert "module_5.py" in prompt
        # module_6 and module_7 should NOT appear (beyond first 6)
        assert "module_6.py" not in prompt
        assert "module_7.py" not in prompt

    def test_run_prefers_deploy_files_when_present(self, monkeypatch):
        """run() uses dockerfile/compose files when present instead of fallback."""
        agent = _make_agent()
        mock_call = MagicMock(return_value="### FILE: docker-compose.test.yml\n```\nversion: '3'\n```")
        monkeypatch.setattr(agent, "call", mock_call)

        files = {
            "Dockerfile": "FROM python:3.13",
            "docker-compose.yml": "version: '3'",
            "src/unrelated.py": "x = 1",
        }
        agent.run(files=files, prd="PRD", project_name="App")

        prompt = mock_call.call_args[0][0]
        assert "Dockerfile" in prompt
        assert "docker-compose" in prompt

    def test_run_includes_main_and_requirements(self, monkeypatch):
        """run() prioritizes main.py, app.py, requirements.txt, config files."""
        agent = _make_agent()
        mock_call = MagicMock(return_value="### FILE: tests/test_deployment.py\n```\ndef test(): pass\n```")
        monkeypatch.setattr(agent, "call", mock_call)

        files = {
            "main.py": "entry point",
            "requirements.txt": "flask==2.0",
            "config.py": "settings",
            "other.py": "not shown",
        }
        agent.run(files=files, prd="PRD", project_name="App")

        prompt = mock_call.call_args[0][0]
        assert "main.py" in prompt
        assert "requirements.txt" in prompt
        assert "config.py" in prompt
        assert "other.py" not in prompt


# ── run_with_github ───────────────────────────────────────────────────────────

class TestDeploymentTesterRunWithGithub:
    def test_commits_deploy_files_to_github(self, monkeypatch):
        """run_with_github() commits all generated deploy files to the branch."""
        agent = _make_agent()
        monkeypatch.setattr(agent, "run", MagicMock(return_value={
            "deploy_files": {
                "docker-compose.test.yml": "compose content",
                "tests/test_deployment.py": "test content",
            },
            "deploy_plan": "## Deployment Plan\n\nRun docker-compose up.",
            "raw_response": "",
        }))

        github_client = MagicMock()

        agent.run_with_github(
            files={"src/main.py": "app"},
            prd="PRD",
            project_name="MyApp",
            github_client=github_client,
            branch="feature/my-app",
            pr_number=7,
        )

        assert github_client.commit_file.call_count == 2
        committed_paths = {c[1]["path"] for c in github_client.commit_file.call_args_list}
        assert len(committed_paths) == 2
        github_client.add_pr_comment.assert_called_once()
        comment = github_client.add_pr_comment.call_args[0][1]
        assert "Deployment" in comment
        assert "🚀" in comment

    def test_posts_plan_to_correct_pr(self, monkeypatch):
        """run_with_github() posts the deployment plan to the given PR number."""
        agent = _make_agent()
        monkeypatch.setattr(agent, "run", MagicMock(return_value={
            "deploy_files": {},
            "deploy_plan": "plan text",
            "raw_response": "",
        }))

        github_client = MagicMock()
        agent.run_with_github(
            files={}, prd="P", project_name="X",
            github_client=github_client, branch="feat/x", pr_number=42,
        )

        actual_pr_number = github_client.add_pr_comment.call_args[0][0]
        assert actual_pr_number == 42

    def test_commit_message_includes_project_name(self, monkeypatch):
        """run_with_github() uses project name in commit messages."""
        agent = _make_agent()
        monkeypatch.setattr(agent, "run", MagicMock(return_value={
            "deploy_files": {"docker-compose.test.yml": "content"},
            "deploy_plan": "plan",
            "raw_response": "",
        }))

        github_client = MagicMock()
        agent.run_with_github(
            files={}, prd="P", project_name="CoolApp",
            github_client=github_client, branch="main", pr_number=1,
        )

        commit_msg = github_client.commit_file.call_args[1]["message"]
        assert "CoolApp" in commit_msg


# ── run_docker_smoke_tests ────────────────────────────────────────────────────

class TestRunDockerSmokeTests:
    def test_returns_skipped_when_no_compose_or_script(self, tmp_path):
        """run_docker_smoke_tests returns skipped=True when no files exist."""
        agent = _make_agent()
        result = agent.run_docker_smoke_tests(tmp_path)
        assert result["skipped"] is True
        assert result["passed"] is False
        assert result["output"] == ""

    def test_uses_script_when_deploy_sh_exists(self, tmp_path, monkeypatch):
        """run_docker_smoke_tests routes to _run_via_script when deploy_test.sh exists."""
        agent = _make_agent()
        script_dir = tmp_path / "scripts"
        script_dir.mkdir()
        deploy_script = script_dir / "deploy_test.sh"
        deploy_script.write_text("#!/bin/bash\necho ok")

        mock_script = MagicMock(return_value={"passed": True, "output": "ok", "skipped": False})
        monkeypatch.setattr(agent, "_run_via_script", mock_script)

        result = agent.run_docker_smoke_tests(tmp_path)

        mock_script.assert_called_once()
        assert result["passed"] is True

    def test_uses_compose_when_both_files_exist(self, tmp_path, monkeypatch):
        """run_docker_smoke_tests routes to _run_via_compose when compose+test exist."""
        agent = _make_agent()
        (tmp_path / "docker-compose.test.yml").write_text("version: '3'")
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_deployment.py").write_text("def test_health(): pass")

        mock_compose = MagicMock(return_value={"passed": True, "output": "ok", "skipped": False})
        monkeypatch.setattr(agent, "_run_via_compose", mock_compose)

        result = agent.run_docker_smoke_tests(tmp_path)

        mock_compose.assert_called_once()
        assert result["passed"] is True

    def test_prefers_script_over_compose(self, tmp_path, monkeypatch):
        """run_docker_smoke_tests uses script even when compose files also exist."""
        agent = _make_agent()

        # Create both script and compose files
        script_dir = tmp_path / "scripts"
        script_dir.mkdir()
        deploy_script = script_dir / "deploy_test.sh"
        deploy_script.write_text("#!/bin/bash\necho ok")

        (tmp_path / "docker-compose.test.yml").write_text("version: '3'")
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_deployment.py").write_text("def test_health(): pass")

        mock_script = MagicMock(return_value={"passed": True, "output": "ok", "skipped": False})
        mock_compose = MagicMock(return_value={"passed": True, "output": "ok", "skipped": False})
        monkeypatch.setattr(agent, "_run_via_script", mock_script)
        monkeypatch.setattr(agent, "_run_via_compose", mock_compose)

        result = agent.run_docker_smoke_tests(tmp_path)

        # Should use script, not compose
        mock_script.assert_called_once()
        mock_compose.assert_not_called()


# ── _run_via_script ───────────────────────────────────────────────────────────

class TestRunViaScript:
    def test_returns_passed_true_on_zero_returncode(self, tmp_path):
        """_run_via_script returns passed=True when script exits 0."""
        agent = _make_agent()
        script = tmp_path / "deploy_test.sh"
        script.write_text("#!/bin/bash\necho deployed")

        with patch("agents.deployment_tester.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="deployed\n", stderr="")
            result = agent._run_via_script(script, tmp_path)

        assert result["passed"] is True
        assert result["skipped"] is False
        assert "deployed" in result["output"]

    def test_returns_passed_false_on_nonzero_returncode(self, tmp_path):
        """_run_via_script returns passed=False when script exits non-zero."""
        agent = _make_agent()
        script = tmp_path / "deploy_test.sh"
        script.write_text("#!/bin/bash\nexit 1")

        with patch("agents.deployment_tester.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
            result = agent._run_via_script(script, tmp_path)

        assert result["passed"] is False
        assert result["skipped"] is False

    def test_captures_stdout_and_stderr(self, tmp_path):
        """_run_via_script combines stdout and stderr in output."""
        agent = _make_agent()
        script = tmp_path / "deploy_test.sh"
        script.write_text("#!/bin/bash\necho ok")

        with patch("agents.deployment_tester.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="stdout text", stderr="stderr text")
            result = agent._run_via_script(script, tmp_path)

        assert "stdout text" in result["output"]
        assert "stderr text" in result["output"]


# ── _run_via_compose ──────────────────────────────────────────────────────────

class TestRunViaCompose:
    def test_runs_full_compose_lifecycle(self, tmp_path):
        """_run_via_compose: up → health check → pytest → down."""
        agent = _make_agent()
        compose_file = tmp_path / "docker-compose.test.yml"
        test_file = tmp_path / "tests" / "test_deployment.py"

        call_results = [
            MagicMock(returncode=0, stdout="", stderr=""),   # up
            MagicMock(returncode=0, stdout="healthy", stderr=""),  # ps (healthy)
            MagicMock(returncode=0, stdout="1 passed", stderr=""),  # pytest
            MagicMock(returncode=0, stdout="", stderr=""),   # down
        ]

        with patch("agents.deployment_tester.subprocess.run", side_effect=call_results):
            with patch("agents.deployment_tester.time.sleep"):
                result = agent._run_via_compose(compose_file, test_file, tmp_path)

        assert result["passed"] is True
        assert result["skipped"] is False

    def test_returns_passed_false_when_tests_fail(self, tmp_path):
        """_run_via_compose returns passed=False when pytest exits non-zero."""
        agent = _make_agent()
        compose_file = tmp_path / "docker-compose.test.yml"
        test_file = tmp_path / "tests" / "test_deployment.py"

        call_results = [
            MagicMock(returncode=0, stdout="", stderr=""),          # up
            MagicMock(returncode=0, stdout="healthy", stderr=""),   # ps
            MagicMock(returncode=1, stdout="FAILED", stderr=""),    # pytest
            MagicMock(returncode=0, stdout="", stderr=""),          # down
        ]

        with patch("agents.deployment_tester.subprocess.run", side_effect=call_results):
            with patch("agents.deployment_tester.time.sleep"):
                result = agent._run_via_compose(compose_file, test_file, tmp_path)

        assert result["passed"] is False

    def test_teardown_runs_even_on_unhealthy(self, tmp_path):
        """_run_via_compose always calls docker-compose down (finally block)."""
        agent = _make_agent()
        compose_file = tmp_path / "docker-compose.test.yml"
        test_file = tmp_path / "tests" / "test_deployment.py"

        # 12 health-check polls all return not-healthy, then pytest, then down
        ps_unhealthy = MagicMock(returncode=0, stdout="starting", stderr="")
        call_results = (
            [MagicMock(returncode=0, stdout="", stderr="")] +  # up
            [ps_unhealthy] * 12 +  # all health checks fail
            [MagicMock(returncode=1, stdout="FAILED", stderr="")] +  # pytest
            [MagicMock(returncode=0, stdout="", stderr="")]   # down
        )

        with patch("agents.deployment_tester.subprocess.run", side_effect=call_results) as mock_run:
            with patch("agents.deployment_tester.time.sleep"):  # no real sleeps
                result = agent._run_via_compose(compose_file, test_file, tmp_path)

        # Verify 'down' was called (last subprocess.run call contains 'down')
        last_cmd = mock_run.call_args_list[-1][0][0]
        assert "down" in last_cmd
        assert result["passed"] is False

    def test_health_check_waits_for_healthy_status(self, tmp_path):
        """_run_via_compose waits up to 12 polls (60s) for healthy status."""
        agent = _make_agent()
        compose_file = tmp_path / "docker-compose.test.yml"
        test_file = tmp_path / "tests" / "test_deployment.py"

        # Becomes healthy on 3rd poll
        call_results = [
            MagicMock(returncode=0, stdout="", stderr=""),           # up
            MagicMock(returncode=0, stdout="starting", stderr=""),   # ps 1
            MagicMock(returncode=0, stdout="starting", stderr=""),   # ps 2
            MagicMock(returncode=0, stdout="healthy", stderr=""),    # ps 3 - healthy!
            MagicMock(returncode=0, stdout="1 passed", stderr=""),   # pytest
            MagicMock(returncode=0, stdout="", stderr=""),           # down
        ]

        with patch("agents.deployment_tester.subprocess.run", side_effect=call_results) as mock_run:
            with patch("agents.deployment_tester.time.sleep") as mock_sleep:
                result = agent._run_via_compose(compose_file, test_file, tmp_path)

        # Should sleep 3 times (before poll 1, 2, and 3) since sleep happens before each check
        assert mock_sleep.call_count == 3
        assert result["passed"] is True

    def test_accepts_running_status_as_healthy(self, tmp_path):
        """_run_via_compose treats 'running' status as healthy."""
        agent = _make_agent()
        compose_file = tmp_path / "docker-compose.test.yml"
        test_file = tmp_path / "tests" / "test_deployment.py"

        call_results = [
            MagicMock(returncode=0, stdout="", stderr=""),           # up
            MagicMock(returncode=0, stdout="running", stderr=""),    # ps - running is OK
            MagicMock(returncode=0, stdout="1 passed", stderr=""),   # pytest
            MagicMock(returncode=0, stdout="", stderr=""),           # down
        ]

        with patch("agents.deployment_tester.subprocess.run", side_effect=call_results):
            with patch("agents.deployment_tester.time.sleep"):
                result = agent._run_via_compose(compose_file, test_file, tmp_path)

        assert result["passed"] is True
