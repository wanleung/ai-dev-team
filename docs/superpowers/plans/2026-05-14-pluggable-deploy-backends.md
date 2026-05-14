# Pluggable Deploy Backends Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a pluggable deploy backend system so each repo can independently choose `none`, `docker` (local), or `libvirt` (remote VM via SSH + virt-install + CoW overlay) as its deployment test strategy, configured per repo in `repos-enabled/*.yaml`.

**Architecture:** A new `agents/deploy_backends.py` module defines a `DeployBackend` ABC with `NoneBackend`, `DockerBackend` (moves existing docker logic from `DeploymentTesterAgent`), and `LibvirtBackend` (SSH → virt-install CoW overlay → rsync → pytest → teardown). `DeploymentTesterAgent` accepts a backend via injection and delegates execution to it. The orchestrator reads `deploy:` config from the watcher entry and builds the correct backend at startup.

**Tech Stack:** Python stdlib only — `subprocess`, `pathlib`, `dataclasses`, `abc`, `time`, `os`, `tempfile`. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-05-14-pluggable-deploy-backends-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `agents/deploy_backends.py` | **Create** | `DeployResult`, `DeployBackend` ABC, `NoneBackend`, `DockerBackend`, `LibvirtBackend`, `build_deploy_backend()` |
| `agents/deployment_tester.py` | **Modify** | Accept `deploy_backend` injection; add `run_smoke_tests()`; keep `run_docker_smoke_tests()` as alias |
| `orchestrator.py` | **Modify** | Read `deploy_cfg` from watcher config; build backend; inject into `DeploymentTesterAgent`; update PR comment for libvirt fields |
| `tests/test_deploy_backends.py` | **Create** | Unit tests for all backends (subprocess mocked) |
| `tests/test_deployment_tester_extended.py` | **Modify** | Add `run_smoke_tests` tests; keep existing docker tests passing |
| `tests/test_orchestrator_deploy_loop.py` | **Modify** | Inject mock backend; test none/docker/libvirt dispatch paths |

---

## Task 1: Worktree Setup

**Files:** none — git only

- [ ] **Step 1: Create worktree from master**

```bash
cd /home/wanleung/Projects/ai-software-house
git worktree add .worktrees/t16-deploy-backends -b t16-deploy-backends master
cd .worktrees/t16-deploy-backends
```

- [ ] **Step 2: Verify baseline tests pass**

```bash
cd /home/wanleung/Projects/ai-software-house/.worktrees/t16-deploy-backends
python -m pytest tests/ -q --tb=no 2>&1 | tail -5
```

Expected: all existing tests pass (≥2029 passed, 0 failed).

- [ ] **Step 3: Commit**

```bash
git commit --allow-empty -m "chore: start t16-deploy-backends worktree"
```

---

## Task 2: `DeployResult` + `DeployBackend` ABC + `NoneBackend`

**Files:**
- Create: `agents/deploy_backends.py`
- Create: `tests/test_deploy_backends.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_deploy_backends.py`:

```python
"""Tests for deploy backend abstraction — NoneBackend, DockerBackend, LibvirtBackend."""
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import pytest
from agents.deploy_backends import (
    DeployResult,
    NoneBackend,
    DockerBackend,
    LibvirtBackend,
    build_deploy_backend,
)


# ── DeployResult ──────────────────────────────────────────────────────────────

class TestDeployResult:
    def test_defaults(self):
        r = DeployResult(passed=True, output="ok", skipped=False)
        assert r.vm_name is None
        assert r.vm_ip is None
        assert r.duration_s == 0.0

    def test_all_fields(self):
        r = DeployResult(passed=False, output="err", skipped=False,
                         vm_name="aisw-test-42", vm_ip="192.168.1.5", duration_s=42.3)
        assert r.vm_name == "aisw-test-42"
        assert r.vm_ip == "192.168.1.5"
        assert r.duration_s == 42.3


# ── NoneBackend ───────────────────────────────────────────────────────────────

class TestNoneBackend:
    def test_returns_skipped(self, tmp_path):
        result = NoneBackend().run(tmp_path, {})
        assert result.skipped is True
        assert result.passed is None
        assert result.output == ""
        assert result.vm_name is None
        assert result.vm_ip is None
        assert result.duration_s == 0.0

    def test_makes_no_subprocess_calls(self, tmp_path):
        with patch("subprocess.run") as mock_run:
            NoneBackend().run(tmp_path, {})
        mock_run.assert_not_called()
```

- [ ] **Step 2: Run to verify FAIL**

```bash
cd /home/wanleung/Projects/ai-software-house/.worktrees/t16-deploy-backends
python -m pytest tests/test_deploy_backends.py -q 2>&1 | tail -10
```

Expected: `ImportError: cannot import name 'DeployResult'`

- [ ] **Step 3: Implement `DeployResult` + `DeployBackend` + `NoneBackend`**

Create `agents/deploy_backends.py`:

```python
"""Pluggable deploy backends for DeploymentTesterAgent.

Backends:
  NoneBackend    — skip deployment testing entirely
  DockerBackend  — local docker-compose smoke tests
  LibvirtBackend — remote VM via SSH + virt-install + CoW overlay + rsync
"""
from __future__ import annotations

import abc
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_log = logging.getLogger(__name__)


@dataclass
class DeployResult:
    """Result from any deploy backend run."""
    passed: Optional[bool]        # True=pass, False=fail, None=skipped
    output: str
    skipped: bool
    vm_name: Optional[str] = None   # libvirt only
    vm_ip: Optional[str] = None     # libvirt only
    duration_s: float = 0.0


class DeployBackend(abc.ABC):
    """Abstract base for deployment test backends."""

    @abc.abstractmethod
    def run(self, project_dir: Path, config: dict) -> DeployResult:
        """Execute deployment tests and return result."""


class NoneBackend(DeployBackend):
    """Skip deployment testing entirely."""

    def run(self, project_dir: Path, config: dict) -> DeployResult:
        return DeployResult(passed=None, output="", skipped=True)
```

- [ ] **Step 4: Run NoneBackend tests — expect PASS**

```bash
python -m pytest tests/test_deploy_backends.py::TestDeployResult tests/test_deploy_backends.py::TestNoneBackend -v 2>&1 | tail -15
```

Expected: 4 passed.

- [ ] **Step 5: Add `build_deploy_backend` stub tests**

Append to `tests/test_deploy_backends.py`:

```python
# ── build_deploy_backend ──────────────────────────────────────────────────────

class TestBuildDeployBackend:
    def test_none_mode(self):
        backend = build_deploy_backend({"mode": "none"})
        assert isinstance(backend, NoneBackend)

    def test_docker_mode(self):
        backend = build_deploy_backend({"mode": "docker"})
        assert isinstance(backend, DockerBackend)

    def test_libvirt_mode(self):
        cfg = {"mode": "libvirt", "virt_host": "user@host", "base_image": "/img.qcow2"}
        backend = build_deploy_backend(cfg)
        assert isinstance(backend, LibvirtBackend)

    def test_default_mode_is_docker(self):
        backend = build_deploy_backend({})
        assert isinstance(backend, DockerBackend)

    def test_unknown_mode_raises(self):
        with pytest.raises(ValueError, match="Unknown deploy mode"):
            build_deploy_backend({"mode": "kubernetes"})
```

- [ ] **Step 6: Implement `build_deploy_backend` (stub classes for now)**

Add to `agents/deploy_backends.py`:

```python
class DockerBackend(DeployBackend):
    """Local docker-compose smoke tests — implemented in Task 3."""

    def run(self, project_dir: Path, config: dict) -> DeployResult:
        raise NotImplementedError("DockerBackend.run — implemented in Task 3")


class LibvirtBackend(DeployBackend):
    """Remote VM via SSH + virt-install — implemented in Task 4."""

    def __init__(self, config: dict) -> None:
        self._cfg = config

    def run(self, project_dir: Path, config: dict) -> DeployResult:
        raise NotImplementedError("LibvirtBackend.run — implemented in Task 4")


def build_deploy_backend(deploy_cfg: dict) -> DeployBackend:
    """Factory: build the correct backend from a deploy config dict."""
    mode = deploy_cfg.get("mode", "docker")
    if mode == "none":
        return NoneBackend()
    if mode == "docker":
        return DockerBackend()
    if mode == "libvirt":
        return LibvirtBackend(deploy_cfg)
    raise ValueError(f"Unknown deploy mode: {mode!r}. Valid: none, docker, libvirt")
```

- [ ] **Step 7: Run all current deploy backend tests — expect PASS**

```bash
python -m pytest tests/test_deploy_backends.py -v 2>&1 | tail -15
```

Expected: 9 passed.

- [ ] **Step 8: Commit**

```bash
git add agents/deploy_backends.py tests/test_deploy_backends.py
git commit -m "feat: add DeployResult, DeployBackend ABC, NoneBackend, build_deploy_backend"
```

---

## Task 3: `DockerBackend`

Move existing docker logic from `DeploymentTesterAgent` into `DockerBackend`. The agent keeps `run_docker_smoke_tests()` as an alias for backward compat (Task 6).

**Files:**
- Modify: `agents/deploy_backends.py`
- Modify: `tests/test_deploy_backends.py`

- [ ] **Step 1: Write failing DockerBackend tests**

Append to `tests/test_deploy_backends.py`:

```python
# ── DockerBackend ─────────────────────────────────────────────────────────────

class TestDockerBackend:
    def test_skipped_when_no_compose_or_script(self, tmp_path):
        """Returns skipped when neither compose file nor deploy script exists."""
        result = DockerBackend().run(tmp_path, {})
        assert result.skipped is True
        assert result.passed is None
        assert result.output == ""

    def test_uses_script_when_deploy_sh_exists(self, tmp_path):
        """Routes to _run_via_script when scripts/deploy_test.sh exists."""
        scripts = tmp_path / "scripts"
        scripts.mkdir()
        (scripts / "deploy_test.sh").write_text("#!/bin/bash\necho ok")

        backend = DockerBackend()
        with patch.object(backend, "_run_via_script",
                          return_value=DeployResult(passed=True, output="ok", skipped=False)) as mock_s:
            result = backend.run(tmp_path, {})

        mock_s.assert_called_once()
        assert result.passed is True

    def test_uses_compose_when_both_files_exist(self, tmp_path):
        """Routes to _run_via_compose when docker-compose.test.yml and test_deployment.py exist."""
        (tmp_path / "docker-compose.test.yml").write_text("version: '3'")
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_deployment.py").write_text("def test_health(): pass")

        backend = DockerBackend()
        with patch.object(backend, "_run_via_compose",
                          return_value=DeployResult(passed=True, output="ok", skipped=False)) as mock_c:
            result = backend.run(tmp_path, {})

        mock_c.assert_called_once()
        assert result.passed is True

    def test_prefers_script_over_compose(self, tmp_path):
        """Script takes priority over compose when both exist."""
        scripts = tmp_path / "scripts"
        scripts.mkdir()
        (scripts / "deploy_test.sh").write_text("#!/bin/bash\necho ok")
        (tmp_path / "docker-compose.test.yml").write_text("version: '3'")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_deployment.py").write_text("pass")

        backend = DockerBackend()
        with patch.object(backend, "_run_via_script",
                          return_value=DeployResult(passed=True, output="ok", skipped=False)) as mock_s, \
             patch.object(backend, "_run_via_compose") as mock_c:
            backend.run(tmp_path, {})

        mock_s.assert_called_once()
        mock_c.assert_not_called()

    def test_run_via_script_passes_on_zero_returncode(self, tmp_path):
        script = tmp_path / "deploy_test.sh"
        script.write_text("#!/bin/bash\necho deployed")
        backend = DockerBackend()
        with patch("agents.deploy_backends.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="deployed\n", stderr="")
            result = backend._run_via_script(script, tmp_path)
        assert result.passed is True
        assert result.skipped is False
        assert "deployed" in result.output

    def test_run_via_script_fails_on_nonzero_returncode(self, tmp_path):
        script = tmp_path / "deploy_test.sh"
        script.write_text("#!/bin/bash\nexit 1")
        backend = DockerBackend()
        with patch("agents.deploy_backends.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
            result = backend._run_via_script(script, tmp_path)
        assert result.passed is False

    def test_run_via_script_combines_stdout_stderr(self, tmp_path):
        script = tmp_path / "deploy_test.sh"
        script.write_text("#!/bin/bash\necho ok")
        backend = DockerBackend()
        with patch("agents.deploy_backends.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="stdout text", stderr="stderr text")
            result = backend._run_via_script(script, tmp_path)
        assert "stdout text" in result.output
        assert "stderr text" in result.output
```

- [ ] **Step 2: Run to verify FAIL**

```bash
python -m pytest tests/test_deploy_backends.py::TestDockerBackend -q 2>&1 | tail -5
```

Expected: `NotImplementedError` or similar failures.

- [ ] **Step 3: Implement `DockerBackend` (move from `DeploymentTesterAgent`)**

Replace the `DockerBackend` stub in `agents/deploy_backends.py` with:

```python
class DockerBackend(DeployBackend):
    """Local docker-compose smoke tests."""

    def run(self, project_dir: Path, config: dict) -> DeployResult:
        compose_file = project_dir / config.get("compose_file", "docker-compose.test.yml")
        test_file = project_dir / "tests" / "test_deployment.py"
        deploy_script = project_dir / "scripts" / "deploy_test.sh"

        if deploy_script.exists():
            return self._run_via_script(deploy_script, project_dir)
        if compose_file.exists() and test_file.exists():
            return self._run_via_compose(compose_file, test_file, project_dir,
                                         timeout=config.get("timeout_s", 300))
        return DeployResult(passed=None, output="", skipped=True)

    def _run_via_script(self, script: Path, project_dir: Path) -> DeployResult:
        script = script.resolve()
        script.chmod(0o755)
        proc = subprocess.run(
            ["bash", str(script)],
            capture_output=True, text=True,
            cwd=str(project_dir), timeout=300,
        )
        output = proc.stdout + proc.stderr
        return DeployResult(passed=proc.returncode == 0, output=output, skipped=False)

    def _run_via_compose(self, compose_file: Path, test_file: Path,
                         project_dir: Path, timeout: int = 300) -> DeployResult:
        output_lines: list[str] = []

        def _run(cmd: list[str]) -> subprocess.CompletedProcess:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  cwd=str(project_dir))
            output_lines.append(f"$ {' '.join(cmd)}")
            output_lines.append(proc.stdout)
            if proc.stderr:
                output_lines.append(proc.stderr)
            return proc

        passed = False
        try:
            _run(["docker", "compose", "-f", str(compose_file), "up", "-d", "--build"])
            healthy = False
            for _ in range(12):
                time.sleep(5)
                ps = _run(["docker", "compose", "-f", str(compose_file), "ps"])
                if "healthy" in ps.stdout or "running" in ps.stdout:
                    healthy = True
                    break
            if not healthy:
                output_lines.append("⚠️  Container did not become healthy within 60s")
            result = _run(["python", "-m", "pytest", str(test_file), "-v", "--tb=short"])
            passed = result.returncode == 0
        finally:
            _run(["docker", "compose", "-f", str(compose_file), "down", "-v"])

        return DeployResult(passed=passed, output="\n".join(output_lines), skipped=False)
```

- [ ] **Step 4: Run DockerBackend tests — expect PASS**

```bash
python -m pytest tests/test_deploy_backends.py::TestDockerBackend -v 2>&1 | tail -15
```

Expected: 7 passed.

- [ ] **Step 5: Run full test suite — no regressions**

```bash
python -m pytest tests/ -q --tb=no 2>&1 | tail -5
```

Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add agents/deploy_backends.py tests/test_deploy_backends.py
git commit -m "feat: implement DockerBackend (moved from DeploymentTesterAgent)"
```

---

## Task 4: `LibvirtBackend`

**Files:**
- Modify: `agents/deploy_backends.py`
- Modify: `tests/test_deploy_backends.py`

All subprocess calls are mocked — no real SSH required.

- [ ] **Step 1: Write failing LibvirtBackend tests**

Append to `tests/test_deploy_backends.py`:

```python
# ── LibvirtBackend helpers ────────────────────────────────────────────────────

def _libvirt_cfg(**overrides) -> dict:
    base = {
        "mode": "libvirt",
        "virt_host": "ubuntu@192.168.1.10",
        "base_image": "/var/lib/libvirt/images/ubuntu-24.04.qcow2",
        "vm_user": "ubuntu",
        "ssh_key": "/home/user/.ssh/id_ed25519",
        "teardown": "always",
        "vcpus": 2,
        "ram_mb": 2048,
    }
    base.update(overrides)
    return base


def _make_libvirt_backend(cfg=None) -> LibvirtBackend:
    return LibvirtBackend(cfg or _libvirt_cfg())


# ── LibvirtBackend ────────────────────────────────────────────────────────────

class TestLibvirtBackend:
    def test_preflight_failure_returns_failed_result(self, tmp_path):
        """If preflight SSH fails, return DeployResult(passed=False) immediately."""
        backend = _make_libvirt_backend()
        with patch.object(backend, "_ssh_host", side_effect=subprocess.CalledProcessError(1, "ssh")) as mock_ssh:
            result = backend.run(tmp_path, _libvirt_cfg())
        assert result.passed is False
        assert result.skipped is False
        assert "preflight" in result.output.lower() or result.output != ""

    def test_successful_run_passes_teardown_always(self, tmp_path):
        """Happy path: all steps succeed, teardown=always destroys VM."""
        backend = _make_libvirt_backend(_libvirt_cfg(teardown="always"))
        calls = []

        def mock_ssh(cmd, **kw):
            calls.append(("ssh", cmd))
            if "virsh domifaddr" in cmd:
                return "vnet0   52:54:00:xx   ipv4   192.168.122.5/24"
            return ""

        def mock_scp(src, dst, **kw):
            calls.append(("scp", src, dst))

        def mock_rsync(src, dst, **kw):
            calls.append(("rsync", src, dst))
            return ""

        def mock_ssh_vm(cmd, **kw):
            calls.append(("ssh_vm", cmd))
            return ""

        with patch.object(backend, "_ssh_host", side_effect=mock_ssh), \
             patch.object(backend, "_scp_to_host", side_effect=mock_scp), \
             patch.object(backend, "_rsync_to_vm", side_effect=mock_rsync), \
             patch.object(backend, "_ssh_vm", side_effect=mock_ssh_vm), \
             patch.object(backend, "_derive_public_key", return_value="ssh-ed25519 AAAA test"), \
             patch.object(backend, "_teardown_vm") as mock_teardown, \
             patch.object(backend, "_wait_for_ssh", return_value="192.168.122.5"):
            result = backend.run(tmp_path, _libvirt_cfg(teardown="always"))

        mock_teardown.assert_called_once()
        assert result.skipped is False

    def test_teardown_on_pass_destroys_when_passed(self, tmp_path):
        """teardown=on_pass must call teardown when tests pass."""
        backend = _make_libvirt_backend(_libvirt_cfg(teardown="on_pass"))
        with patch.object(backend, "_preflight"), \
             patch.object(backend, "_create_cow_overlay"), \
             patch.object(backend, "_provision_vm"), \
             patch.object(backend, "_wait_for_ssh", return_value="192.168.122.5"), \
             patch.object(backend, "_rsync_to_vm"), \
             patch.object(backend, "_run_tests_on_vm", return_value=(True, "1 passed")), \
             patch.object(backend, "_teardown_vm") as mock_teardown, \
             patch.object(backend, "_derive_public_key", return_value="ssh-ed25519 AAAA"):
            result = backend.run(tmp_path, _libvirt_cfg(teardown="on_pass"))

        mock_teardown.assert_called_once()
        assert result.passed is True

    def test_teardown_on_pass_keeps_vm_when_failed(self, tmp_path):
        """teardown=on_pass must NOT call teardown when tests fail."""
        backend = _make_libvirt_backend(_libvirt_cfg(teardown="on_pass"))
        with patch.object(backend, "_preflight"), \
             patch.object(backend, "_create_cow_overlay"), \
             patch.object(backend, "_provision_vm"), \
             patch.object(backend, "_wait_for_ssh", return_value="192.168.122.5"), \
             patch.object(backend, "_rsync_to_vm"), \
             patch.object(backend, "_run_tests_on_vm", return_value=(False, "1 failed")), \
             patch.object(backend, "_teardown_vm") as mock_teardown, \
             patch.object(backend, "_derive_public_key", return_value="ssh-ed25519 AAAA"):
            result = backend.run(tmp_path, _libvirt_cfg(teardown="on_pass"))

        mock_teardown.assert_not_called()
        assert result.passed is False
        assert result.vm_ip == "192.168.122.5"

    def test_teardown_keep_never_destroys(self, tmp_path):
        """teardown=keep must never call teardown."""
        backend = _make_libvirt_backend(_libvirt_cfg(teardown="keep"))
        with patch.object(backend, "_preflight"), \
             patch.object(backend, "_create_cow_overlay"), \
             patch.object(backend, "_provision_vm"), \
             patch.object(backend, "_wait_for_ssh", return_value="192.168.122.5"), \
             patch.object(backend, "_rsync_to_vm"), \
             patch.object(backend, "_run_tests_on_vm", return_value=(True, "ok")), \
             patch.object(backend, "_teardown_vm") as mock_teardown, \
             patch.object(backend, "_derive_public_key", return_value="ssh-ed25519 AAAA"):
            backend.run(tmp_path, _libvirt_cfg(teardown="keep"))

        mock_teardown.assert_not_called()

    def test_vm_name_template_substitution(self, tmp_path):
        """vm_name template {repo} and {issue} are substituted correctly."""
        cfg = _libvirt_cfg(vm_name="aisw-{repo}-{issue}")
        backend = LibvirtBackend(cfg)
        name = backend._resolve_vm_name("owner/my-repo", "42")
        assert name == "aisw-my-repo-42"

    def test_vm_name_auto_generated_when_not_set(self, tmp_path):
        """Auto-generated vm_name includes repo and issue."""
        cfg = _libvirt_cfg()
        cfg.pop("vm_name", None)
        backend = LibvirtBackend(cfg)
        name = backend._resolve_vm_name("owner/firmware", "99")
        assert "firmware" in name
        assert "99" in name

    def test_derive_public_key_calls_ssh_keygen(self, tmp_path):
        backend = _make_libvirt_backend()
        with patch("agents.deploy_backends.subprocess.check_output",
                   return_value=b"ssh-ed25519 AAAA testkey\n") as mock_co:
            key = backend._derive_public_key("/home/user/.ssh/id_ed25519")
        mock_co.assert_called_once_with(
            ["ssh-keygen", "-y", "-f", "/home/user/.ssh/id_ed25519"]
        )
        assert key == "ssh-ed25519 AAAA testkey"

    def test_derive_public_key_falls_back_to_agent_when_no_key(self, tmp_path):
        cfg = _libvirt_cfg()
        cfg.pop("ssh_key", None)
        backend = LibvirtBackend(cfg)
        with patch("agents.deploy_backends.subprocess.check_output",
                   return_value=b"ssh-ed25519 AAAA agentkey\n"):
            key = backend._derive_public_key(None)
        assert "agentkey" in key
```

- [ ] **Step 2: Run to verify FAIL**

```bash
python -m pytest tests/test_deploy_backends.py::TestLibvirtBackend -q 2>&1 | tail -5
```

Expected: failures (LibvirtBackend not yet implemented).

- [ ] **Step 3: Implement `LibvirtBackend`**

Replace the `LibvirtBackend` stub in `agents/deploy_backends.py` with the full implementation:

```python
class LibvirtBackend(DeployBackend):
    """Remote VM via SSH + virt-install CoW overlay + rsync + pytest + teardown."""

    def __init__(self, config: dict) -> None:
        self._cfg = config

    # ── Public entry point ────────────────────────────────────────────────────

    def run(self, project_dir: Path, config: dict) -> DeployResult:
        import tempfile
        start = time.time()
        cfg = {**self._cfg, **config}  # allow per-call overrides

        repo_name = project_dir.name
        issue = cfg.get("_issue", "0")
        vm_name = self._resolve_vm_name(repo_name, str(issue))
        virt_host = cfg["virt_host"]
        base_image = cfg["base_image"]
        vm_user = cfg.get("vm_user", "ubuntu")
        ssh_key = os.path.expanduser(cfg["ssh_key"]) if cfg.get("ssh_key") else None
        teardown_mode = cfg.get("teardown", "always")
        vcpus = cfg.get("vcpus", 2)
        ram_mb = cfg.get("ram_mb", 2048)

        output_lines: list[str] = []
        vm_ip: Optional[str] = None
        passed = False

        try:
            # 1. Preflight
            self._preflight(virt_host, ssh_key, output_lines)

            # 2. Derive public key for cloud-init
            pub_key = self._derive_public_key(ssh_key)

            # 3. CoW overlay
            overlay_path = f"/tmp/aisw-overlay-{vm_name}.qcow2"
            self._create_cow_overlay(virt_host, ssh_key, base_image, overlay_path, output_lines)

            # 4. Cloud-init seed + virt-install
            with tempfile.TemporaryDirectory() as seed_dir:
                self._provision_vm(virt_host, ssh_key, vm_name, overlay_path,
                                   seed_dir, pub_key, vm_user, vcpus, ram_mb, output_lines)

            # 5. Wait for SSH
            vm_ip = self._wait_for_ssh(virt_host, ssh_key, vm_name, vm_user, output_lines)

            # 6. Rsync code
            self._rsync_to_vm(project_dir, virt_host, vm_ip, ssh_key, vm_user, output_lines)

            # 7. Run tests
            passed, test_output = self._run_tests_on_vm(virt_host, vm_ip, ssh_key, vm_user, output_lines)
            output_lines.append(test_output)

        except Exception as exc:
            output_lines.append(f"❌ Deploy backend error: {exc}")
            passed = False

        finally:
            should_teardown = (
                teardown_mode == "always" or
                (teardown_mode == "on_pass" and passed)
            )
            if should_teardown:
                try:
                    self._teardown_vm(virt_host, ssh_key, vm_name, output_lines)
                    vm_name_final = f"{vm_name} (destroyed)"
                    vm_ip_final = None
                except Exception as exc:
                    output_lines.append(f"⚠️  Teardown failed: {exc} — VM {vm_name} may need manual cleanup")
                    vm_name_final = vm_name
                    vm_ip_final = vm_ip
            else:
                vm_name_final = vm_name
                vm_ip_final = vm_ip

        duration = time.time() - start
        return DeployResult(
            passed=passed,
            output="\n".join(output_lines),
            skipped=False,
            vm_name=vm_name_final,
            vm_ip=vm_ip_final,
            duration_s=duration,
        )

    # ── Step helpers ──────────────────────────────────────────────────────────

    def _resolve_vm_name(self, repo: str, issue: str) -> str:
        template = self._cfg.get("vm_name", "aisw-{repo}-{issue}")
        safe_repo = repo.split("/")[-1].replace("_", "-")
        return template.format(repo=safe_repo, issue=issue)

    def _derive_public_key(self, ssh_key: Optional[str]) -> str:
        if ssh_key:
            raw = subprocess.check_output(["ssh-keygen", "-y", "-f", ssh_key])
        else:
            raw = subprocess.check_output(["ssh-add", "-L"])
        return raw.decode().splitlines()[0].strip()

    def _ssh_host(self, virt_host: str, cmd: str,
                  ssh_key: Optional[str] = None, **kw) -> str:
        key_args = ["-i", ssh_key] if ssh_key else []
        proc = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=accept-new", *key_args, virt_host, cmd],
            capture_output=True, text=True, check=True, **kw
        )
        return proc.stdout.strip()

    def _scp_to_host(self, src: str, dst: str, ssh_key: Optional[str] = None) -> None:
        key_args = ["-i", ssh_key] if ssh_key else []
        subprocess.run(
            ["scp", "-r", "-o", "StrictHostKeyChecking=accept-new", *key_args, src, dst],
            check=True, capture_output=True,
        )

    def _rsync_to_vm(self, project_dir: Path, virt_host: str, vm_ip: str,
                     ssh_key: Optional[str], vm_user: str,
                     output_lines: list[str]) -> None:
        key_args = f" -i {ssh_key}" if ssh_key else ""
        ssh_proxy = f"ssh -J {virt_host}{key_args} -o StrictHostKeyChecking=no"
        cmd = [
            "rsync", "-az", "--delete",
            "-e", ssh_proxy,
            f"{project_dir}/",
            f"{vm_user}@{vm_ip}:/opt/app/",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
        output_lines.append(f"$ rsync → {vm_user}@{vm_ip}:/opt/app/")
        if proc.stderr:
            output_lines.append(proc.stderr)

    def _ssh_vm(self, virt_host: str, vm_ip: str, ssh_key: Optional[str],
                vm_user: str, cmd: str, output_lines: list[str]) -> str:
        key_args = ["-i", ssh_key] if ssh_key else []
        proc = subprocess.run(
            ["ssh",
             "-J", virt_host,
             *key_args,
             "-o", "StrictHostKeyChecking=no",
             f"{vm_user}@{vm_ip}", cmd],
            capture_output=True, text=True,
        )
        output_lines.append(f"$ ssh -J {virt_host} {vm_user}@{vm_ip} {cmd[:60]}")
        output_lines.append(proc.stdout)
        if proc.stderr:
            output_lines.append(proc.stderr)
        return proc.stdout + proc.stderr

    def _preflight(self, virt_host: str, ssh_key: Optional[str],
                   output_lines: list[str]) -> None:
        output_lines.append(f"[preflight] checking {virt_host}…")
        self._ssh_host(virt_host,
                       "which virt-install && qemu-img --version && virsh version",
                       ssh_key=ssh_key)
        output_lines.append("[preflight] ✅ virt-install + qemu-img available")

    def _create_cow_overlay(self, virt_host: str, ssh_key: Optional[str],
                            base_image: str, overlay_path: str,
                            output_lines: list[str]) -> None:
        output_lines.append(f"[overlay] creating CoW overlay from {base_image}…")
        self._ssh_host(
            virt_host,
            f"qemu-img create -f qcow2 -b {base_image} -F qcow2 {overlay_path}",
            ssh_key=ssh_key,
        )
        output_lines.append(f"[overlay] ✅ {overlay_path}")

    def _provision_vm(self, virt_host: str, ssh_key: Optional[str],
                      vm_name: str, overlay_path: str, seed_dir: str,
                      pub_key: str, vm_user: str, vcpus: int, ram_mb: int,
                      output_lines: list[str]) -> None:
        import textwrap
        seed_local = Path(seed_dir)

        user_data = textwrap.dedent(f"""\
            #cloud-config
            users:
              - name: {vm_user}
                sudo: ALL=(ALL) NOPASSWD:ALL
                ssh_authorized_keys:
                  - {pub_key}
            packages: [python3, python3-pip, git]
            package_update: true
        """)
        meta_data = f"instance-id: {vm_name}\nlocal-hostname: {vm_name}\n"

        (seed_local / "user-data").write_text(user_data)
        (seed_local / "meta-data").write_text(meta_data)

        # Build iso on host
        seed_remote = f"/tmp/aisw-seed-{vm_name}"
        self._ssh_host(virt_host, f"mkdir -p {seed_remote}", ssh_key=ssh_key)
        self._scp_to_host(str(seed_local / "user-data"),
                          f"{virt_host}:{seed_remote}/user-data", ssh_key=ssh_key)
        self._scp_to_host(str(seed_local / "meta-data"),
                          f"{virt_host}:{seed_remote}/meta-data", ssh_key=ssh_key)
        self._ssh_host(
            virt_host,
            f"cloud-localds {seed_remote}/seed.iso {seed_remote}/user-data {seed_remote}/meta-data",
            ssh_key=ssh_key,
        )

        virt_cmd = (
            f"virt-install --name {vm_name} --memory {ram_mb} --vcpus {vcpus} "
            f"--disk path={overlay_path},format=qcow2 "
            f"--disk path={seed_remote}/seed.iso,device=cdrom "
            f"--import --noautoconsole --wait 0"
        )
        output_lines.append(f"[provision] starting VM {vm_name}…")
        self._ssh_host(virt_host, virt_cmd, ssh_key=ssh_key)
        output_lines.append(f"[provision] ✅ VM {vm_name} started")

    def _wait_for_ssh(self, virt_host: str, ssh_key: Optional[str],
                      vm_name: str, vm_user: str,
                      output_lines: list[str], max_wait: int = 180) -> str:
        output_lines.append(f"[wait] waiting for {vm_name} IP (max {max_wait}s)…")
        ip: Optional[str] = None
        deadline = time.time() + max_wait

        while time.time() < deadline:
            try:
                out = self._ssh_host(virt_host, f"virsh domifaddr {vm_name}", ssh_key=ssh_key)
                for line in out.splitlines():
                    parts = line.split()
                    for p in parts:
                        if "/" in p and not p.startswith("--"):
                            ip = p.split("/")[0]
                            break
                if ip:
                    break
            except subprocess.CalledProcessError:
                pass
            time.sleep(10)

        if not ip:
            raise RuntimeError(f"VM {vm_name} did not get an IP within {max_wait}s")

        output_lines.append(f"[wait] ✅ {vm_name} IP: {ip}")

        # Wait for SSH
        output_lines.append(f"[wait] waiting for SSH on {ip}…")
        ssh_ready = False
        while time.time() < deadline:
            try:
                key_args = ["-i", ssh_key] if ssh_key else []
                subprocess.run(
                    ["ssh", "-J", virt_host, *key_args,
                     "-o", "StrictHostKeyChecking=no",
                     "-o", "ConnectTimeout=5",
                     f"{vm_user}@{ip}", "true"],
                    check=True, capture_output=True, timeout=10,
                )
                ssh_ready = True
                break
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                time.sleep(10)

        if not ssh_ready:
            raise RuntimeError(f"SSH on {vm_name} ({ip}) not reachable within {max_wait}s")

        output_lines.append(f"[wait] ✅ SSH ready on {ip}")
        return ip

    def _run_tests_on_vm(self, virt_host: str, vm_ip: str,
                         ssh_key: Optional[str], vm_user: str,
                         output_lines: list[str]) -> tuple[bool, str]:
        output_lines.append("[test] installing dependencies and running pytest…")
        key_args = ["-i", ssh_key] if ssh_key else []
        proc = subprocess.run(
            ["ssh",
             "-J", virt_host,
             *key_args,
             "-o", "StrictHostKeyChecking=no",
             f"{vm_user}@{vm_ip}",
             "cd /opt/app && pip install -r requirements.txt -q && "
             "pytest tests/test_deployment.py -v --tb=short"],
            capture_output=True, text=True, timeout=300,
        )
        output = proc.stdout + proc.stderr
        passed = proc.returncode == 0
        status = "✅ passed" if passed else "❌ failed"
        output_lines.append(f"[test] {status}")
        return passed, output

    def _teardown_vm(self, virt_host: str, ssh_key: Optional[str],
                     vm_name: str, output_lines: list[str]) -> None:
        output_lines.append(f"[teardown] destroying {vm_name}…")
        teardown_cmd = (
            f"virsh destroy {vm_name} 2>/dev/null || true; "
            f"virsh undefine {vm_name} 2>/dev/null || true; "
            f"rm -f /tmp/aisw-overlay-{vm_name}.qcow2 "
            f"/tmp/aisw-seed-{vm_name}/seed.iso "
            f"/tmp/aisw-seed-{vm_name}/user-data "
            f"/tmp/aisw-seed-{vm_name}/meta-data"
        )
        self._ssh_host(virt_host, teardown_cmd, ssh_key=ssh_key)
        output_lines.append(f"[teardown] ✅ {vm_name} destroyed")
```

- [ ] **Step 4: Run LibvirtBackend tests — expect PASS**

```bash
python -m pytest tests/test_deploy_backends.py::TestLibvirtBackend -v 2>&1 | tail -20
```

Expected: 9 passed.

- [ ] **Step 5: Run full test suite — no regressions**

```bash
python -m pytest tests/ -q --tb=no 2>&1 | tail -5
```

- [ ] **Step 6: Commit**

```bash
git add agents/deploy_backends.py tests/test_deploy_backends.py
git commit -m "feat: implement LibvirtBackend (SSH + virt-install CoW + rsync + teardown)"
```

---

## Task 5: Update `DeploymentTesterAgent`

Inject backend; add `run_smoke_tests()`; keep `run_docker_smoke_tests()` as a backward-compat alias.

**Files:**
- Modify: `agents/deployment_tester.py`
- Modify: `tests/test_deployment_tester_extended.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_deployment_tester_extended.py`:

```python
# ── run_smoke_tests (new unified method) ──────────────────────────────────────

class TestRunSmokeTests:
    def test_delegates_to_injected_backend(self, tmp_path):
        """run_smoke_tests() calls backend.run() with project_dir and deploy_config."""
        from agents.deploy_backends import DeployResult, NoneBackend
        agent = _make_agent()
        mock_backend = MagicMock()
        mock_backend.run.return_value = DeployResult(passed=True, output="ok", skipped=False)
        agent._deploy_backend = mock_backend
        agent._deploy_config = {"mode": "docker"}

        result = agent.run_smoke_tests(tmp_path)

        mock_backend.run.assert_called_once_with(tmp_path, {"mode": "docker"})
        assert result.passed is True

    def test_uses_docker_backend_by_default_when_no_backend_set(self, tmp_path):
        """run_smoke_tests() with no injected backend uses DockerBackend (returns skipped for empty dir)."""
        from agents.deploy_backends import DeployResult
        agent = _make_agent()
        # no _deploy_backend set

        result = agent.run_smoke_tests(tmp_path)

        assert isinstance(result, DeployResult)
        assert result.skipped is True   # empty dir → DockerBackend returns skipped

    def test_run_docker_smoke_tests_alias_still_works(self, tmp_path):
        """Backward-compat: run_docker_smoke_tests() returns dict with passed/skipped/output."""
        agent = _make_agent()
        result = agent.run_docker_smoke_tests(tmp_path)
        assert "passed" in result
        assert "skipped" in result
        assert "output" in result
```

- [ ] **Step 2: Run to verify FAIL**

```bash
python -m pytest tests/test_deployment_tester_extended.py::TestRunSmokeTests -q 2>&1 | tail -5
```

Expected: `AttributeError: 'DeploymentTesterAgent' object has no attribute '_deploy_backend'`

- [ ] **Step 3: Update `agents/deployment_tester.py`**

Add import at top of file:
```python
from .deploy_backends import DeployBackend, DeployResult, DockerBackend, build_deploy_backend
```

In `DeploymentTesterAgent.__init__` signature, add:
```python
def __init__(self, *args, deploy_backend: "DeployBackend | None" = None,
             deploy_config: dict | None = None, **kwargs) -> None:
```

At the end of `__init__` body:
```python
    self._deploy_backend: DeployBackend = deploy_backend or DockerBackend()
    self._deploy_config: dict = deploy_config or {}
```

Add new method after `run_with_github`:
```python
def run_smoke_tests(self, project_dir: Path) -> DeployResult:
    """Run deployment smoke tests via the configured backend."""
    return self._deploy_backend.run(project_dir, self._deploy_config)
```

Update `run_docker_smoke_tests` to be an alias:
```python
def run_docker_smoke_tests(self, project_dir: Path) -> dict:
    """Backward-compat alias for run_smoke_tests(). Returns dict for legacy callers."""
    result = self.run_smoke_tests(project_dir)
    return {"passed": result.passed, "output": result.output, "skipped": result.skipped}
```

Remove (or keep internal) `_run_via_script` and `_run_via_compose` from the agent — they now live in `DockerBackend`. The orchestrator calls `run_smoke_tests()` from now on; legacy dict callers go through the alias.

- [ ] **Step 4: Run updated tests — expect PASS**

```bash
python -m pytest tests/test_deployment_tester_extended.py -v --tb=short 2>&1 | tail -20
```

Expected: all passing (including old TestRunDockerSmokeTests which now go through alias).

- [ ] **Step 5: Run full suite**

```bash
python -m pytest tests/ -q --tb=no 2>&1 | tail -5
```

- [ ] **Step 6: Commit**

```bash
git add agents/deployment_tester.py tests/test_deployment_tester_extended.py
git commit -m "feat: DeploymentTesterAgent accepts deploy_backend injection, adds run_smoke_tests()"
```

---

## Task 6: Update `orchestrator.py`

Wire deploy config → backend → agent; update `_stage_deploy_test_runner` to use `run_smoke_tests()`; format libvirt PR comment fields.

**Files:**
- Modify: `orchestrator.py`
- Modify: `tests/test_orchestrator_deploy_loop.py`

- [ ] **Step 1: Write failing orchestrator tests**

Append to `tests/test_orchestrator_deploy_loop.py`:

```python
# ── deploy backend injection ──────────────────────────────────────────────────

from agents.deploy_backends import DeployResult, NoneBackend, DockerBackend, LibvirtBackend


def _make_orch_with_backend(tmp_path, backend):
    orch = Orchestrator.__new__(Orchestrator)
    orch.workspace_dir = tmp_path
    orch.target_github = None
    orch.engineer = MagicMock()
    orch.max_deploy_retries = 3
    orch.deployment_tester = MagicMock()
    orch.deployment_tester.run_smoke_tests.return_value = DeployResult(
        passed=True, output="ok", skipped=False
    )
    return orch


def test_none_backend_skips_deploy_test_runner(tmp_path):
    """NoneBackend: _stage_deploy_test_runner must return immediately without posting PR comment."""
    orch = _make_orch_with_backend(tmp_path, NoneBackend())
    orch.deployment_tester.run_smoke_tests.return_value = DeployResult(
        passed=None, output="", skipped=True
    )
    result = _make_result()

    orch._stage_deploy_test_runner(result)

    assert result.deploy_tests_passed is None
    assert result.deploy_test_results == ""


def test_docker_backend_posts_pr_comment_on_pass(tmp_path):
    """DockerBackend pass: PR comment posted with 🐳 prefix."""
    orch = _make_orch_with_backend(tmp_path, DockerBackend())
    orch.target_github = MagicMock()
    result = _make_result()
    result.pr_number = 7
    orch.deployment_tester.run_smoke_tests.return_value = DeployResult(
        passed=True, output="1 passed", skipped=False
    )

    orch._stage_deploy_test_runner(result)

    comment = orch.target_github.add_pr_comment.call_args[0][1]
    assert "🐳" in comment or "docker" in comment.lower()
    assert "✅" in comment


def test_libvirt_backend_posts_vm_info_on_failure(tmp_path):
    """LibvirtBackend fail with on_pass teardown: PR comment includes VM access instructions."""
    orch = _make_orch_with_backend(tmp_path, None)
    orch.target_github = MagicMock()
    result = _make_result()
    result.pr_number = 8
    orch.deployment_tester.run_smoke_tests.return_value = DeployResult(
        passed=False, output="1 failed", skipped=False,
        vm_name="aisw-firmware-8", vm_ip="192.168.122.5"
    )

    orch._stage_deploy_test_runner(result)

    comment = orch.target_github.add_pr_comment.call_args[0][1]
    assert "192.168.122.5" in comment
    assert "aisw-firmware-8" in comment
```

- [ ] **Step 2: Run to verify FAIL**

```bash
python -m pytest tests/test_orchestrator_deploy_loop.py::test_none_backend_skips_deploy_test_runner tests/test_orchestrator_deploy_loop.py::test_docker_backend_posts_pr_comment_on_pass tests/test_orchestrator_deploy_loop.py::test_libvirt_backend_posts_vm_info_on_failure -q 2>&1 | tail -10
```

- [ ] **Step 3: Update `orchestrator.py` — `__init__` and `from_config`**

In `Orchestrator.__init__`, add parameter:
```python
deploy_cfg: dict | None = None,
```

Add to `__init__` body (after `self.max_deploy_retries = max_deploy_retries`):
```python
from agents.deploy_backends import build_deploy_backend
_deploy_cfg = deploy_cfg or {"mode": "docker"}
self._deploy_cfg = _deploy_cfg
_deploy_backend = build_deploy_backend(_deploy_cfg)
self.deployment_tester = DeploymentTesterAgent(
    **{**agent_kwargs, **_mk("deployment_tester")},
    deploy_backend=_deploy_backend,
    deploy_config=_deploy_cfg,
)
```

(Remove the existing `self.deployment_tester = DeploymentTesterAgent(...)` line that doesn't pass backend.)

In `Orchestrator.from_config`, pass deploy config:
```python
deploy_cfg=watcher_config.get("deploy", {"mode": "docker"}),
```
(Add to the `Orchestrator(...)` call inside `from_config`.)

- [ ] **Step 4: Update `_stage_deploy_test_runner` in `orchestrator.py`**

Replace the method body with:

```python
def _stage_deploy_test_runner(self, result: PipelineResult) -> None:
    """Run deployment smoke tests via the configured backend."""
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in result.project_name.lower())
    project_dir = self.workspace_dir / safe

    deploy_result = self.deployment_tester.run_smoke_tests(project_dir)

    if deploy_result.skipped:
        result.deploy_tests_passed = None
        result.deploy_test_results = ""
        return

    passed = deploy_result.passed
    output = deploy_result.output
    vm_name = deploy_result.vm_name
    vm_ip = deploy_result.vm_ip
    duration = deploy_result.duration_s

    status_emoji = "✅" if passed else "❌"
    status_text = "Passed" if passed else "Failed"

    # Choose icon based on backend type
    if vm_name is not None:
        icon = "🚀"
        backend_label = "libvirt"
    else:
        icon = "🐳"
        backend_label = "docker"

    console.print(f"    {icon} Deployment tests [{backend_label}]: {status_emoji} {status_text}")

    lines = output.strip().splitlines()
    for line in lines[-20:]:
        console.print(f"    [dim]{line}[/dim]")

    result.deploy_test_results = output
    result.deploy_tests_passed = passed

    if self.target_github and result.pr_number:
        truncated = "\n".join(lines[-60:]) if len(lines) > 60 else output
        duration_str = f"{int(duration // 60)}m {int(duration % 60)}s" if duration >= 60 else f"{int(duration)}s"

        if vm_name and vm_ip:
            # Libvirt failure — VM kept alive
            virt_host = self._deploy_cfg.get("virt_host", "virt_host")
            vm_user = self._deploy_cfg.get("vm_user", "ubuntu")
            extra = (
                f"\n**VM:** `{vm_name}` @ `{vm_ip}`\n"
                f"**Access:** `ssh {virt_host}` then `ssh {vm_user}@{vm_ip}`\n"
            )
        elif vm_name:
            # Libvirt pass — destroyed
            extra = f"\n**VM:** `{vm_name}`  |  **Duration:** {duration_str}\n"
        else:
            # Docker
            extra = f"\n**Duration:** {duration_str}\n"

        comment = (
            f"## {icon} Deployment Test Results [{backend_label}]\n\n"
            f"**Status:** {status_emoji} {status_text}{extra}\n"
            f"```\n{truncated}\n```"
        )
        self.target_github.add_pr_comment(result.pr_number, comment)
```

- [ ] **Step 5: Run updated orchestrator tests — expect PASS**

```bash
python -m pytest tests/test_orchestrator_deploy_loop.py -v --tb=short 2>&1 | tail -20
```

Expected: all passing.

- [ ] **Step 6: Run full suite — no regressions**

```bash
python -m pytest tests/ -q --tb=no 2>&1 | tail -5
```

- [ ] **Step 7: Commit**

```bash
git add orchestrator.py tests/test_orchestrator_deploy_loop.py
git commit -m "feat: wire deploy backends into orchestrator; libvirt-aware PR comments"
```

---

## Task 7: Update Config Examples and README

**Files:**
- Modify: `repos-enabled/custom-blog.yaml` (add deploy block as example)
- Modify: `README.md` (document deploy config)

- [ ] **Step 1: Add `deploy` block to an existing repos-enabled file**

Edit `repos-enabled/custom-blog.yaml` — add at end:

```yaml
deploy:
  mode: docker
```

- [ ] **Step 2: Add deploy documentation to README**

Find the section about `repos.yaml` / `repos-enabled` configuration in `README.md`. After the existing watcher config fields, add:

```markdown
### Per-repo deploy mode

Each repo can independently choose how deployment smoke tests run:

```yaml
# repos-enabled/my-repo.yaml
tracker_repo: owner/my-repo
labels:
  ai-feature: ai-feature

deploy:
  mode: docker            # local docker-compose (default if omitted)

# --- or ---

deploy:
  mode: libvirt           # remote VM on a libvirt host
  virt_host: ubuntu@192.168.1.10
  base_image: /var/lib/libvirt/images/ubuntu-24.04.qcow2
  vm_user: ubuntu         # default: ubuntu
  ssh_key: ~/.ssh/id_ed25519  # default: SSH agent
  vcpus: 2                # default: 2
  ram_mb: 2048            # default: 2048
  teardown: on_pass       # always | on_pass | keep  (default: always)

# --- or ---

deploy:
  mode: none              # skip deployment testing entirely
```

**`mode: libvirt`** provisions a fresh VM from a CoW overlay of `base_image` (the base image is never
modified), rsyncs the project into `/opt/app/`, runs `tests/test_deployment.py` via SSH ProxyJump
through `virt_host`, then tears down based on `teardown`. Multiple repos can share the same
`base_image` safely — each run gets its own isolated overlay.
```

- [ ] **Step 3: Run tests to confirm nothing broken**

```bash
python -m pytest tests/ -q --tb=no 2>&1 | tail -5
```

- [ ] **Step 4: Commit**

```bash
git add repos-enabled/custom-blog.yaml README.md
git commit -m "docs: add per-repo deploy mode config to README and repos-enabled examples"
```

---

## Task 8: Open PR

- [ ] **Step 1: Push branch**

```bash
cd /home/wanleung/Projects/ai-software-house/.worktrees/t16-deploy-backends
git push -u origin t16-deploy-backends
```

- [ ] **Step 2: Open PR**

```bash
gh pr create \
  --title "feat: pluggable deploy backends — none/docker/libvirt per repo" \
  --body "## Summary

Adds a per-repo pluggable deploy backend system. Each repo in \`repos-enabled/\` can independently choose:

- \`mode: none\` — skip deployment testing
- \`mode: docker\` — local docker-compose smoke tests (existing behaviour, now in \`DockerBackend\`)
- \`mode: libvirt\` — remote VM via SSH + virt-install CoW overlay + rsync + pytest + teardown

### Key design
- \`agents/deploy_backends.py\`: \`DeployBackend\` ABC + three implementations + \`build_deploy_backend()\`
- \`DeploymentTesterAgent\`: accepts \`deploy_backend\` injection; new \`run_smoke_tests()\` method; \`run_docker_smoke_tests()\` kept as backward-compat alias
- Orchestrator reads \`deploy:\` block from watcher config, builds backend at startup
- PR comments include VM name/IP for libvirt failures (to aid debugging when \`teardown: on_pass\`)

### libvirt VM model
Base image is a pristine read-only template. Each run creates a CoW overlay via \`qemu-img create -f qcow2 -b <base>\`. Multiple repos share the same base image safely. Overlay is destroyed on teardown; base is never touched.

Spec: \`docs/superpowers/specs/2026-05-14-pluggable-deploy-backends-design.md\`" \
  --base master
```

- [ ] **Step 3: Confirm PR opened and note URL**

```bash
gh pr view --web
```

---

## Self-Review Notes

- All 7 steps of the LibvirtBackend flow are covered (preflight, CoW overlay, provision, wait, rsync, test, teardown)
- All three teardown modes tested (always, on_pass/pass, on_pass/fail, keep)
- `run_docker_smoke_tests()` alias preserves backward compat — existing callers still get a dict
- `_stage_deploy_test_runner` handles `skipped=True` without posting PR comment (NoneBackend)
- PR comment distinguishes docker (🐳) vs libvirt (🚀) and includes VM IP on failure
- `build_deploy_backend({})` defaults to `DockerBackend` — no config change needed for existing repos
- libvirt `_deploy_cfg` stored on orchestrator (`self._deploy_cfg`) so PR comment formatter can read `virt_host` and `vm_user`
