"""
DeploymentTesterAgent: generates deployment smoke tests and runs them via docker-compose.
"""
from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path
from typing import Optional

from .base_agent import BaseAgent


class DeploymentTesterAgent(BaseAgent):
    """Deployment Tester — generates docker-compose test config and HTTP smoke tests.

    Input:  generated code files + PRD
    Output: docker-compose.test.yml, tests/test_deployment.py, scripts/deploy_test.sh
    """

    role_name = "deployment_tester"

    def run(self, files: dict[str, str], prd: str, project_name: str = "Project") -> dict:
        """Generate deployment test artefacts.

        Returns:
            dict with keys:
                - deploy_files (dict): {filepath: content} — compose, smoke tests, scripts
                - deploy_plan (str): deployment test plan markdown
                - raw_response (str): full LLM response
        """
        # Show the LLM the Dockerfile / compose files if present, plus key source files
        deploy_snippets = {
            k: v for k, v in files.items()
            if any(keyword in k.lower() for keyword in
                   ("dockerfile", "docker-compose", "main.py", "app.py", "requirements", "config"))
        }
        if not deploy_snippets:
            deploy_snippets = dict(list(files.items())[:6])

        code_section = "\n\n".join(
            f"### FILE: {path}\n```\n{content}\n```" for path, content in deploy_snippets.items()
        )

        prompt = (
            f"You are writing deployment smoke tests for the project '{project_name}'.\n\n"
            f"**PRD:**\n---\n{prd}\n---\n\n"
            f"**Key project files:**\n\n{code_section}\n\n"
            f"Generate the deployment test artefacts following your role instructions:\n"
            f"1. docker-compose.test.yml\n"
            f"2. tests/test_deployment.py\n"
            f"3. scripts/deploy_test.sh\n"
            f"4. Deployment Test Plan"
        )

        response = self.call(prompt)
        deploy_files = self._parse_files(response)
        deploy_plan = self._extract_deploy_plan(response)

        return {
            "deploy_files": deploy_files,
            "deploy_plan": deploy_plan,
            "raw_response": response,
        }

    def run_with_github(
        self,
        files: dict[str, str],
        prd: str,
        project_name: str,
        github_client,
        branch: str,
        pr_number: int,
    ) -> dict:
        """Generate deployment tests, commit them, and post the plan to the PR."""
        result = self.run(files, prd, project_name)

        for filepath, content in result["deploy_files"].items():
            github_client.commit_file(
                path=filepath,
                content=content,
                message=f"test: add deployment smoke tests for {project_name}",
                branch=branch,
            )

        github_client.add_pr_comment(
            pr_number,
            f"## 🚀 Deployment Test Plan (DeploymentTesterAgent)\n\n{result['deploy_plan']}",
        )
        return result

    def run_docker_smoke_tests(self, project_dir: Path) -> dict:
        """Run docker-compose deployment tests locally.

        Starts docker-compose.test.yml, waits for health, runs pytest tests/test_deployment.py,
        then tears down. Returns results dict.
        """
        compose_file = project_dir / "docker-compose.test.yml"
        test_file = project_dir / "tests" / "test_deployment.py"
        deploy_script = project_dir / "scripts" / "deploy_test.sh"

        if deploy_script.exists():
            return self._run_via_script(deploy_script, project_dir)
        elif compose_file.exists() and test_file.exists():
            return self._run_via_compose(compose_file, test_file, project_dir)
        else:
            return {
                "passed": False,
                "output": "",
                "skipped": True,
            }

    def _run_via_script(self, script: Path, project_dir: Path) -> dict:
        script = script.resolve()
        script.chmod(0o755)
        proc = subprocess.run(
            ["bash", str(script)],
            capture_output=True,
            text=True,
            cwd=str(project_dir),
            timeout=300,
        )
        output = proc.stdout + proc.stderr
        return {"passed": proc.returncode == 0, "output": output, "skipped": False}

    def _run_via_compose(self, compose_file: Path, test_file: Path, project_dir: Path) -> dict:
        output_lines = []

        def run(cmd, **kwargs):
            proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(project_dir), **kwargs)
            output_lines.append(f"$ {' '.join(cmd)}")
            output_lines.append(proc.stdout)
            if proc.stderr:
                output_lines.append(proc.stderr)
            return proc

        try:
            run(["docker", "compose", "-f", str(compose_file), "up", "-d", "--build"])

            # Wait up to 60s for healthy
            healthy = False
            for _ in range(12):
                time.sleep(5)
                ps = run(["docker", "compose", "-f", str(compose_file), "ps"])
                if "healthy" in ps.stdout or "running" in ps.stdout:
                    healthy = True
                    break

            if not healthy:
                output_lines.append("⚠️  Container did not become healthy within 60s")

            # Run smoke tests
            result = run(["python", "-m", "pytest", str(test_file), "-v", "--tb=short"])
            passed = result.returncode == 0
        finally:
            run(["docker", "compose", "-f", str(compose_file), "down", "-v"])

        return {"passed": passed, "output": "\n".join(output_lines), "skipped": False}

    @staticmethod
    def _parse_files(response: str) -> dict[str, str]:
        files: dict[str, str] = {}
        current_path: Optional[str] = None
        current_lines: list[str] = []
        in_code_block = False

        for line in response.splitlines():
            if line.strip().startswith("### FILE:"):
                if current_path and current_lines:
                    files[current_path] = "\n".join(current_lines).strip()
                current_path = line.strip().removeprefix("### FILE:").strip()
                current_lines = []
                in_code_block = False
                continue
            if current_path is not None:
                if line.strip().startswith("```"):
                    in_code_block = not in_code_block
                    continue
                current_lines.append(line)

        if current_path and current_lines:
            files[current_path] = "\n".join(current_lines).strip()
        return files

    @staticmethod
    def _extract_deploy_plan(response: str) -> str:
        lines = response.splitlines()
        plan_lines: list[str] = []
        in_plan = False
        for line in lines:
            if re.search(r"#\s*Deployment Test Plan", line, re.IGNORECASE):
                in_plan = True
            if in_plan:
                plan_lines.append(line)
        return "\n".join(plan_lines).strip() if plan_lines else "Deployment test plan not generated."
