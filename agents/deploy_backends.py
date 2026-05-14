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
import re as _re
import subprocess
import tempfile
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_SAFE_ID_RE = _re.compile(r'^[A-Za-z0-9._/-]+$')


def _safe_id(value: str, name: str = "value", extra_chars: str = "") -> str:
    """Validate that a string is safe to embed in a shell command string.

    Args:
        value:       The string to validate.
        name:        Human-readable label used in the error message.
        extra_chars: Additional characters to allow beyond the default set
                     ``[A-Za-z0-9._/-]``.  For example ``"@:"`` permits
                     SSH ``user@host:port`` style values.

    Returns:
        ``value`` unchanged if it matches the allowed character set.

    Raises:
        ValueError: If ``value`` contains characters outside the allowed set.
    """
    allowed = r'A-Za-z0-9._/-' + _re.escape(extra_chars)
    pattern = _re.compile(r'^[' + allowed + r']+$')
    if not pattern.match(value):
        raise ValueError(
            f"Unsafe characters in {name}={value!r}. "
            f"Only [A-Za-z0-9._/-{extra_chars}] allowed."
        )
    return value

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
        """Return a skipped result without running any subprocess."""
        return DeployResult(passed=None, output="", skipped=True)


class DockerBackend(DeployBackend):
    """Local docker-compose smoke tests."""

    def run(self, project_dir: Path, config: dict) -> DeployResult:
        """Run docker-based deployment tests.

        Prefers scripts/deploy_test.sh if present; falls back to
        docker-compose.test.yml + tests/test_deployment.py; skips otherwise.
        """
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
        """Execute a shell deploy script and return the result."""
        script = script.resolve()
        script.chmod(0o755)
        start = time.time()
        proc = subprocess.run(
            ["bash", str(script)],
            capture_output=True, text=True,
            cwd=str(project_dir), timeout=300,
        )
        output = proc.stdout + proc.stderr
        return DeployResult(passed=proc.returncode == 0, output=output, skipped=False,
                            duration_s=time.time() - start)

    def _run_via_compose(self, compose_file: Path, test_file: Path,
                         project_dir: Path, timeout: int = 300) -> DeployResult:
        """Bring up docker-compose services, run pytest, then tear down."""
        output_lines: list[str] = []

        def _run(cmd: list[str], timeout: int | None = None) -> subprocess.CompletedProcess:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  cwd=str(project_dir), timeout=timeout)
            output_lines.append(f"$ {' '.join(cmd)}")
            output_lines.append(proc.stdout)
            if proc.stderr:
                output_lines.append(proc.stderr)
            return proc

        passed = False
        start = time.time()
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
            result = _run(["python3", "-m", "pytest", str(test_file), "-v", "--tb=short"],
                          timeout=timeout)
            passed = result.returncode == 0
        finally:
            _run(["docker", "compose", "-f", str(compose_file), "down", "-v"])

        return DeployResult(passed=passed, output="\n".join(output_lines), skipped=False,
                            duration_s=time.time() - start)


class LibvirtBackend(DeployBackend):
    """Remote VM via SSH + virt-install CoW overlay + rsync + pytest + teardown."""

    def __init__(self, config: dict) -> None:
        self._cfg = config

    # ── Public entry point ────────────────────────────────────────────────────

    def run(self, project_dir: Path, config: dict) -> DeployResult:
        """Provision a VM, rsync code, run tests, and optionally tear down."""
        start = time.time()
        cfg = {**self._cfg, **config}  # allow per-call overrides

        repo_name = project_dir.name
        issue = cfg.get("_issue", "0")
        base_image = _safe_id(cfg["base_image"], "base_image")
        vm_user = _safe_id(cfg.get("vm_user", "ubuntu"), "vm_user")
        vm_name = _safe_id(self._resolve_vm_name(repo_name, str(issue)), "vm_name")
        virt_host = _safe_id(cfg["virt_host"], "virt_host", extra_chars="@:")
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
        """Resolve VM name from template or auto-generate from repo and issue.

        Inputs are sanitised before embedding: repo basename keeps only
        ``[A-Za-z0-9-]`` (other chars replaced with ``-``); issue keeps only
        ``[A-Za-z0-9]``.
        """
        safe_repo = _re.sub(r'[^A-Za-z0-9-]', '-', repo.split("/")[-1])
        safe_issue = _re.sub(r'[^A-Za-z0-9]', '', issue)
        template = self._cfg.get("vm_name", "aisw-{repo}-{issue}")
        return template.format(repo=safe_repo, issue=safe_issue)

    def _derive_public_key(self, ssh_key: Optional[str]) -> str:
        """Extract SSH public key from private key file or ssh-agent."""
        if ssh_key:
            raw = subprocess.check_output(["ssh-keygen", "-y", "-f", ssh_key])
        else:
            raw = subprocess.check_output(["ssh-add", "-L"])
        return raw.decode().splitlines()[0].strip()

    def _ssh_host(self, virt_host: str, cmd: str,
                  ssh_key: Optional[str] = None, **kw) -> str:
        """Run a command on the virt host over SSH and return stdout."""
        key_args = ["-i", ssh_key] if ssh_key else []
        proc = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=accept-new", *key_args, virt_host, cmd],
            capture_output=True, text=True, check=True, **kw
        )
        return proc.stdout.strip()

    def _scp_to_host(self, src: str, dst: str, ssh_key: Optional[str] = None) -> None:
        """Copy a file to the virt host via SCP."""
        key_args = ["-i", ssh_key] if ssh_key else []
        subprocess.run(
            ["scp", "-r", "-o", "StrictHostKeyChecking=accept-new", *key_args, src, dst],
            check=True, capture_output=True,
        )

    def _rsync_to_vm(self, project_dir: Path, virt_host: str, vm_ip: str,
                     ssh_key: Optional[str], vm_user: str,
                     output_lines: list[str]) -> None:
        """Rsync project directory to the VM via jump host."""
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

    def _preflight(self, virt_host: str, ssh_key: Optional[str],
                   output_lines: list[str]) -> None:
        """Verify virt-install and qemu-img are available on the virt host."""
        output_lines.append(f"[preflight] checking {virt_host}…")
        self._ssh_host(virt_host,
                       "which virt-install && qemu-img --version && virsh version",
                       ssh_key=ssh_key)
        output_lines.append("[preflight] ✅ virt-install + qemu-img available")

    def _create_cow_overlay(self, virt_host: str, ssh_key: Optional[str],
                            base_image: str, overlay_path: str,
                            output_lines: list[str]) -> None:
        """Create a Copy-on-Write QCOW2 overlay from the base image."""
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
        """Create cloud-init seed ISO and start VM via virt-install."""
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
        """Poll virsh domifaddr and wait until SSH is reachable; return VM IP."""
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
        """Install deps and run pytest on the VM; return (passed, output)."""
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
        """Destroy VM, undefine it, and remove overlay + seed files."""
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


def build_deploy_backend(deploy_cfg: dict) -> DeployBackend:
    """Factory: build the correct backend from a deploy config dict.

    Args:
        deploy_cfg: Dict with at least ``mode`` key (none/docker/libvirt).
                    Defaults to ``docker`` when key is absent.

    Returns:
        The appropriate :class:`DeployBackend` instance.

    Raises:
        ValueError: If an unknown mode is specified.
    """
    mode = deploy_cfg.get("mode", "docker")
    if mode == "none":
        return NoneBackend()
    if mode == "docker":
        return DockerBackend()
    if mode == "libvirt":
        return LibvirtBackend(deploy_cfg)
    raise ValueError(f"Unknown deploy mode: {mode!r}. Valid: none, docker, libvirt")
