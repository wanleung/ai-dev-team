---
title: "systemd 261-rc1 Introduces Native OS Installer, Cloud Metadata Service and Unified Storage Tool"
date: 2026-05-22T17:05:00
author: AI Press Team
source_url: https://www.phoronix.com/news/systemd-261-rc1
tags: [systemd, linux, cloud, infrastructure, security]
---

The systemd project has published the first release candidate of version 261, extending the init system and service manager into OS provisioning, cloud metadata handling, and storage lifecycle management. Reported by Phoronix on 22 May, the release represents one of the most expansive feature additions to systemd in recent cycles.

The centerpiece of 261-rc1 is `systemd-sysinstall`, a text-based installer that consolidates systemd's partitioning logic, credential management, and system configuration into a single deployment workflow. Operating from temporary boot media such as a USB drive, the installer copies the target operating system onto destination hardware, offering an alternative to distribution-specific installers and custom provisioning scripts.

Cloud infrastructure gains `systemd-imdsd`, a daemon that exposes Instance Metadata Service endpoints to local applications. The daemon includes a built-in hardware database that identifies major cloud platforms through SMBIOS data, covering Amazon EC2, Microsoft Azure, Google Compute Engine, Oracle Cloud, Tencent Cloud, and Hetzner. Centralizing metadata access under systemd provides a vendor-agnostic interface for cloud VMs, reducing reliance on vendor-specific agents.

Storage management arrives through `storagectl`, a command-line utility with a Varlink interface that presents storage resources in a unified format for managed user storage. How the tool will coexist with established storage managers like LVM, `cryptsetup`, and ZFS remains an open question for heterogeneous production environments.

Additional changes in 261-rc1 include:

- A `systemd-tpm2-swtpm.service` that runs the IBM Software TPM as an automatic fallback on systems without physical TPM hardware
- PID1 support for the kernel's Live Update Orchestrator and Kernel Handover capabilities
- A new `CPUSetPartition=` unit setting for configuring cgroup partition types
- A `RestrictFileSystemAccess=` directive using a BPF LSM program to restrict execution to binaries on signed DM-VERITY protected filesystems
- A `tmpfiles.d/root.conf` entry enforcing 0555 permissions on the root directory
- A `DefaultMemoryZSwapWriteback=` manager setting providing a system-wide default for Zswap writeback behaviour

Historical debates about systemd's expanding scope are likely to resurface with this release. The project's maintainers appear to view these additions as pragmatic responses to infrastructure fragmentation rather than arbitrary feature creep. Whether major distributions adopt the native installer framework broadly or confine it to specific ecosystems will become clearer as testing progresses.

Full details of the 261-rc1 changes are available on the project's GitHub release page.
