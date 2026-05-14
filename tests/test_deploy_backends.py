"""Tests for deploy backend abstraction — NoneBackend, DockerBackend, LibvirtBackend."""
import subprocess
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

        def mock_ssh(virt_host, cmd, **kw):
            calls.append(("ssh", cmd))
            if "virsh domifaddr" in cmd:
                return "vnet0   52:54:00:xx   ipv4   192.168.122.5/24"
            return ""

        def mock_scp(src, dst, **kw):
            calls.append(("scp", src, dst))

        def mock_rsync(*args, **kw):
            calls.append(("rsync",))
            return ""

        with patch.object(backend, "_ssh_host", side_effect=mock_ssh), \
             patch.object(backend, "_scp_to_host", side_effect=mock_scp), \
             patch.object(backend, "_rsync_to_vm", side_effect=mock_rsync), \
             patch.object(backend, "_run_tests_on_vm", return_value=(True, "1 passed")), \
             patch.object(backend, "_derive_public_key", return_value="ssh-ed25519 AAAA test"), \
             patch.object(backend, "_teardown_vm") as mock_teardown, \
             patch.object(backend, "_wait_for_ssh", return_value="192.168.122.5"):
            result = backend.run(tmp_path, _libvirt_cfg(teardown="always"))

        mock_teardown.assert_called_once()
        assert result.skipped is False
        assert result.passed is True

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
