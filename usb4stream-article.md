---
title: "Intel Proposes USB4STREAM Protocol to Bypass Linux Networking Stack for Direct Host-to-Host Transfers"
date: 2026-05-25T13:04:00
author: AI Press Team
source_url: https://www.phoronix.com/news/Intel-Linux-USB4STREAM
tags: [linux, intel, usb4, thunderbolt, networking, kernel]
---

Intel has submitted a proposal for USB4STREAM, a new protocol targeting the Linux 7.2 kernel that enables raw packet transfers directly over USB4 and Thunderbolt connections. The protocol bypasses the traditional TCP/IP stack, creating a zero-configuration data pipe between two hosts that preserves the full 40Gbps bandwidth of the underlying physical link.

Intel describes USB4STREAM as a "super simple" mechanism for moving packets between systems without requiring IP assignment, routing tables, or firewall rules. The approach positions the protocol as a specialized complement to conventional Ethernet and Wi-Fi infrastructure rather than a replacement.

## How USB4STREAM Differs from Traditional Networking

Conventional Linux networking introduces measurable overhead even on high-speed links. Every packet traverses multiple layers: the network interface driver, IP routing logic, netfilter hooks, and the TCP or UDP transport layer. Each layer adds processing latency, memory copies, and buffer management complexity.

USB4STREAM operates beneath this entire stack. By establishing a direct pipe over the USB4/Thunderbolt controller, data moves between hosts without IP address negotiation, ARP resolution, or connection state tracking. The result is a deterministic, low-latency channel suited for environments where configuration simplicity matters more than protocol flexibility.

Security relies on existing Thunderbolt authentication mechanisms, with management exposed through a new sysfs interface once the patch series lands in the mainline kernel.

## Targeted Use Cases

The protocol is optimized for scenarios where two systems are physically connected and need to exchange data rapidly without network infrastructure. Primary applications include:

- **Host-to-host system backups and migrations:** Moving large datasets between machines without configuring a temporary network or dealing with transfer bottlenecks introduced by the networking stack.
- **Peripheral pooling:** Sharing devices such as webcams or capture cards across multiple systems without virtualization overhead or network-based streaming protocols.
- **Embedded and industrial deployments:** Resource-constrained environments where running a full networking stack is unnecessary, but high-bandwidth direct communication is required.

## Relevance to Hong Kong IT Professionals

For Hong Kong enterprise IT teams and developers working in data-intensive sectors such as fintech, media production, and edge computing, USB4STREAM offers a potential tool for simplifying direct system-to-system workflows. The protocol's zero-configuration nature could reduce setup time in environments where temporary high-speed transfers are frequent but network infrastructure is either unavailable or over-provisioned for the task.

However, the protocol's reliance on physical Thunderbolt connectivity means it is not suited for distributed or remote scenarios. Hong Kong organizations evaluating this technology should consider it strictly as a point-to-point solution for co-located systems.

## Open-Source Strategy and Timeline

Intel's decision to upstream USB4STREAM directly into the Linux kernel ensures that the protocol will be available across all major distributions without requiring proprietary drivers. The patch series is expected to enter the Linux 7.2 review cycle, where kernel maintainers will evaluate the sysfs API design, error handling, and security model before final acceptance.

Key questions remain around the specific access-control mechanisms that will be finalized beyond baseline Thunderbolt authentication, as well as which developer tooling and reference implementations will emerge to support adoption. The kernel review process will ultimately shape the protocol's feature scope and production readiness.
