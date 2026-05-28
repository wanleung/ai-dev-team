---
title: "Intel Submits pmtctl to Linux Kernel for Unified Platform Telemetry Access"
date: 2026-05-26T11:11:00
author: AI Press Team
source_url: "https://www.phoronix.com/news/Intel-pmtctl-Tool"
tags: [linux, intel, hardware-monitoring, open-source, kernel]
---

Intel has posted a 17-patch series to the Linux kernel mailing list introducing `pmtctl`, a userspace utility designed to provide standardized access to Intel Platform Monitoring Technology (PMT) data from within the mainline kernel. The submission represents a strategic pivot toward kernel-native hardware telemetry, aiming to replace years of fragmented, out-of-tree monitoring solutions with a single upstream-maintained interface.

The tool, proposed for inclusion in the kernel's `tools/perf` directory, would serve as a bridge between Linux systems and Intel's PMT infrastructure, which exposes real-time power consumption, thermal readings, and performance telemetry from modern Intel processors and chipsets. For system administrators, this would eliminate the need to juggle vendor-specific daemons, custom scripts, and third-party drivers that have historically complicated hardware monitoring workflows.

The move aligns with a broader industry shift toward embedding telemetry directly in the kernel, driven by tightening data center energy mandates and sustainability compliance requirements. By moving PMT access upstream, Intel is shifting hardware monitoring away from proprietary agents toward a model where metric collection is auditable, reproducible, and maintained alongside the kernel itself. For data center operators managing large-scale deployments, unified access to power and thermal metrics enables dynamic power management strategies that can reduce operational costs while meeting increasingly granular reporting obligations.

Mainline acceptance, however, remains contingent on rigorous upstream review. Kernel maintainers will need to evaluate several open questions before the patch series can be merged. Chief among them are access control and data sanitization — specifically, what mechanisms will prevent unprivileged processes from reading telemetry that could reveal sensitive operational patterns. The review cycle will also need to establish which Intel microarchitectures receive initial support, how backward compatibility will be maintained across processor generations, and how `pmtctl` will differentiate from or integrate with established telemetry interfaces like Running Average Power Limit (RAPL) and the `libpfm` performance counter library.

Downstream observability projects will need to adapt once `pmtctl` stabilizes. Monitoring frameworks including Prometheus exporters and Grafana integrations will likely require updated collectors to consume the tool's output, making early coordination on metric schema standardization critical for cloud-native and high-performance computing environments. Tracking these downstream adaptation efforts will be essential for understanding the tool's real-world impact.

The 17-patch series is now open for discussion on the Linux kernel mailing list. Its acceptance will depend on the outcome of the standard upstream review process, during which maintainers will assess code quality, architectural soundness, and alignment with existing kernel subsystems.
