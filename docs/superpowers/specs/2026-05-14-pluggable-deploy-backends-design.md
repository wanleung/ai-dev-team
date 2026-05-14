# Pluggable Deploy Backends Design

**Date:** 2026-05-14
**Feature:** Per-repo deploy mode — None / Docker / Libvirt (remote)

---

## Problem

The existing `deploy_tester` + `deploy_fix` pipeline stages are hardwired to local Docker.
There is no way for a repo to opt out of deployment testing, use a remote VM, or choose a
different execution environment. As the system manages more varied projects, this is a blocker:

- Firmware / embedded repos need a real VM (libvirt), not Docker
- Script/utility repos need no deployment test at all
- Web apps are happy with local Docker

The deploy backend needs to be selectable per repo, configured in the same place as the rest
of the repo's watcher config (`repos-enabled/<name>.yaml` or `repos.yaml`).

---

## Goals

1. Each watcher entry independently specifies its deploy mode: `none`, `docker`, or `libvirt`
2. `libvirt` provisions a VM on a **remote host** via SSH, rsyncs code in, runs tests, then tears down
3. SSH key handling is unified (one key, two hops via ProxyJump) — no second key required
4. PR comments report results (pass/fail, VM identity, teardown status) for all modes except `none`
5. Existing Docker behaviour is preserved unchanged for repos that don't set a `deploy` block
6. The `deploy_fix` retry loop works identically across all backends

---

## Non-Goals

- Kubernetes / Helm deploy backend (future)
- Windows VM support
- Multi-VM test topologies
- Building the base image — operator provides a pre-existing qcow2

---

## Config Schema

The `deploy` block is optional in any watcher entry. Default is `mode: docker`.

```yaml
# repos-enabled/firmware.yaml
tracker_repo: owner/firmware
labels:
  ai-feature: ai-feature
deploy:
  mode: libvirt
  virt_host: ubuntu@192.168.1.10       # SSH target (user@host)
  base_image: /var/lib/libvirt/images/ubuntu-24.04.qcow2
  vm_name: aisw-{repo}-{issue}         # optional template; auto-generated if omitted
  vcpus: 2                              # default: 2
  ram_mb: 2048                          # default: 2048
  vm_user: ubuntu                       # default: ubuntu (varies by cloud image)
  ssh_key: ~/.ssh/id_ed25519            # default: SSH agent
  teardown: on_pass                     # always | on_pass | keep — default: always

# repos-enabled/webapp.yaml
tracker_repo: owner/webapp
labels:
  ai-feature: ai-feature
deploy:
  mode: docker                          # local docker (default if block omitted)
  compose_file: docker-compose.test.yml # default
  timeout_s: 300                        # default

# repos-enabled/scripts.yaml
tracker_repo: owner/scripts
labels:
  ai-feature: ai-feature
deploy:
  mode: none                            # skip deploy stage entirely; no PR comment
```

`vm_name` template substitutions: `{repo}` → sanitised tracker_repo name, `{issue}` → issue number.
`ssh_key` path is expanded with `os.path.expanduser` at load time.

---

## Architecture

### New file: `agents/deploy_backends.py`

Contains the backend abstraction and all three implementations.

```
DeployBackend (ABC)
  run(project_dir: Path, config: dict) -> DeployResult

DeployResult (dataclass)
  passed: bool | None   # None = skipped/not applicable
  output: str
  skipped: bool
  vm_name: str | None   # libvirt only
  vm_ip: str | None     # libvirt only, kept for PR comment on failure
  duration_s: float

NoneBackend(DeployBackend)
  run() → DeployResult(passed=None, output="", skipped=True, vm_name=None, vm_ip=None, duration_s=0.0)

DockerBackend(DeployBackend)
  run() → wraps existing _run_via_compose / _run_via_script logic
  (moved from DeploymentTesterAgent; agent delegates to this class)

LibvirtBackend(DeployBackend)
  run() → full libvirt flow (see below)
```

Factory function used by the orchestrator:

```python
def build_deploy_backend(deploy_cfg: dict) -> DeployBackend:
    mode = deploy_cfg.get("mode", "docker")
    if mode == "none":     return NoneBackend()
    if mode == "docker":   return DockerBackend()
    if mode == "libvirt":  return LibvirtBackend(deploy_cfg)
    raise ValueError(f"Unknown deploy mode: {mode!r}")
```

### Modified: `agents/deployment_tester.py`

- Accepts `deploy_backend: DeployBackend` in `__init__`
- `run_docker_smoke_tests()` is replaced by `run_smoke_tests(project_dir)` which delegates to `self._backend.run(project_dir, self._deploy_config)`
- LLM prompt generation and file parsing are unchanged

### Modified: `orchestrator.py`

- Reads `deploy_cfg = watcher_config.get("deploy", {"mode": "docker"})` at startup
- Calls `build_deploy_backend(deploy_cfg)` once
- Passes backend + config into `DeploymentTesterAgent`
- `_stage_deploy_fix_loop` uses the same backend for retries
- `NoneBackend` causes the deploy fix loop to exit immediately (same as `skip_if=lambda r: not r.deploy_files`)

---

## VM Image Model

`base_image` is a **pristine, read-only template** — it is never modified.

Each pipeline run creates a **copy-on-write (CoW) overlay** backed by the base image:

```
base_image.qcow2  (shared template, untouched across all runs and repos)
       │
       ├── /tmp/aisw-overlay-firmware-42.qcow2   ← run: firmware repo, issue #42
       ├── /tmp/aisw-overlay-webapp-17.qcow2     ← concurrent run: webapp repo, issue #17
       └── /tmp/aisw-overlay-firmware-50.qcow2   ← next firmware run, fresh overlay
```

The overlay is created on virt_host before provisioning:
```bash
qemu-img create -f qcow2 \
  -b <base_image> -F qcow2 \
  /tmp/aisw-overlay-{vm_name}.qcow2
```

Overlays start at ~MB and grow only as the VM writes. On teardown the overlay is removed;
the base image is untouched. Multiple repos may share the same `base_image` safely — each run
is fully isolated via its own overlay. Concurrent pipeline runs never interfere.

---

## LibvirtBackend Execution Flow

All SSH commands are run via `subprocess` from the watcher process.

```
1. PREFLIGHT
   ssh <virt_host> "which virt-install && qemu-img --version && virsh version"
   → fail fast if libvirt/qemu not available on remote host

2. CREATE CoW OVERLAY
   ssh virt_host: qemu-img create -f qcow2 -b <base_image> -F qcow2 \
     /tmp/aisw-overlay-{vm_name}.qcow2
   → thin overlay, takes seconds, base_image untouched

3. PROVISION
   Build cloud-init NoCloud seed:
     - Derive public key: ssh-keygen -y -f <ssh_key>  (or read from agent)
     - Write user-data (cloud-config): sets vm_user, injects public key, installs python3/pip
     - Write meta-data: instance-id, local-hostname
   scp seed files to virt_host:/tmp/aisw-seed-{vm_name}/
   ssh virt_host: virt-install \
     --name <vm_name> \
     --memory <ram_mb> \
     --vcpus <vcpus> \
     --disk path=/tmp/aisw-overlay-{vm_name}.qcow2,format=qcow2 \
     --disk path=/tmp/aisw-seed-{vm_name}/seed.iso,device=cdrom \
     --import --noautoconsole --wait 0

3. WAIT FOR BOOT
   ssh virt_host: virsh domifaddr <vm_name>  (poll every 10s, max 3 min)
   Once IP appears, attempt SSH connection to VM via ProxyJump (poll every 10s, max 3 min)

4. RSYNC CODE
   rsync -az --delete \
     -e "ssh -J <virt_host> -i <ssh_key> -o StrictHostKeyChecking=no" \
     <project_dir>/ \
     <vm_user>@<vm_ip>:/opt/app/

5. RUN TESTS
   ssh -J <virt_host> -i <ssh_key> <vm_user>@<vm_ip> \
     "cd /opt/app && pip install -r requirements.txt -q && pytest tests/test_deployment.py -v"
   Capture stdout+stderr, record exit code.

7. TEARDOWN
   always:   ssh virt_host "virsh destroy <vm_name>; virsh undefine <vm_name>; \
               rm -f /tmp/aisw-overlay-{vm_name}.qcow2 /tmp/aisw-seed-{vm_name}/"
   on_pass:  above only if exit code == 0; otherwise leave running (base_image still untouched)
   keep:     leave running; log vm_name + vm_ip for operator; base_image untouched

7. RETURN DeployResult
   passed = (exit code == 0)
   output = full captured output
   vm_name, vm_ip included for PR comment
```

Timeout: entire flow has a configurable `timeout_s` (default 600s for libvirt, 300s for docker).
All subprocess calls raise `subprocess.TimeoutExpired` on timeout; caught and reported as failure.

---

## SSH Key Handling

```
ssh_key config present  →  use that private key for both hops
ssh_key absent          →  rely on SSH agent (no -i flag passed)
```

**Hop 1 (watcher → virt_host):** `ssh -i <ssh_key> <virt_host> <command>`

**Hop 2 (watcher → VM via ProxyJump):**
`ssh -J <virt_host> -i <ssh_key> -o StrictHostKeyChecking=no <vm_user>@<vm_ip>`

`StrictHostKeyChecking=no` is required for hop 2 because the VM is ephemeral — its host key is new each run. For hop 1 (the known hypervisor), `StrictHostKeyChecking` is left at default (checks `~/.ssh/known_hosts`).

Public key injection into cloud-init: derived once at backend init via
`subprocess.check_output(["ssh-keygen", "-y", "-f", str(ssh_key_path)])`.
If `ssh_key` is absent, the SSH agent's first identity is used
(`ssh-add -L | head -1`).

---

## PR Comments

**DockerBackend — pass:**
```
## 🐳 Deployment Test Results [docker]

**Status:** ✅ Passed  |  **Duration:** 45s

<last 60 lines of pytest output>
```

**LibvirtBackend — pass (teardown: always):**
```
## 🚀 Deployment Test Results [libvirt]

**Status:** ✅ Passed  |  **VM:** aisw-myrepo-42 (destroyed)  |  **Duration:** 4m 12s

<last 60 lines of pytest output>
```

**LibvirtBackend — fail (teardown: on_pass):**
```
## 🚀 Deployment Test Results [libvirt]

**Status:** ❌ Failed — VM kept alive for debugging
**VM:** aisw-myrepo-42 @ 192.168.1.45
**Access:** ssh ubuntu@192.168.1.10 then ssh ubuntu@192.168.1.45

<last 60 lines of output>
```

**NoneBackend:** no PR comment posted; deploy stage is silently skipped.

---

## Error Handling

| Failure point | Behaviour |
|---|---|
| virt_host unreachable | DeployResult(passed=False), PR comment with SSH error |
| virt-install not found on host | DeployResult(passed=False), preflight error in comment |
| VM never gets IP (timeout) | DeployResult(passed=False), "VM did not boot within 3 min" |
| VM SSH never responds (timeout) | DeployResult(passed=False), "VM SSH not reachable" |
| rsync fails | DeployResult(passed=False), rsync stderr in output |
| pytest not found in VM | DeployResult(passed=False), stderr captured |
| Teardown fails | Logged as warning; DeployResult.passed unchanged; VM name included in PR comment for manual cleanup |
| Docker not available (docker mode) | DeployResult(passed=None, skipped=True); existing behaviour preserved |

---

## Testing

- Unit tests mock `subprocess.run` / `subprocess.check_output` — no real SSH or Docker needed
- `NoneBackend`: assert `run()` returns `skipped=True`, no subprocess calls
- `DockerBackend`: assert existing docker test behaviour (moved from test_deployment_tester.py)
- `LibvirtBackend`: mock the 7-step flow; verify correct SSH commands, ProxyJump args, cloud-init content, teardown variants
- Integration: `test_orchestrator_deploy_loop.py` updated to inject a mock backend

---

## File Changes Summary

| File | Change |
|---|---|
| `agents/deploy_backends.py` | **New** — NoneBackend, DockerBackend, LibvirtBackend, build_deploy_backend() |
| `agents/deployment_tester.py` | Modified — accepts backend, delegates execution to it |
| `orchestrator.py` | Modified — reads deploy config, builds backend, injects into agent |
| `tests/test_deploy_backends.py` | **New** — unit tests for all three backends |
| `tests/test_deployment_tester.py` | Modified — updated for new backend injection pattern |
| `tests/test_orchestrator_deploy_loop.py` | Modified — inject mock backend |
| `docs/superpowers/specs/2026-05-14-pluggable-deploy-backends-design.md` | This file |
