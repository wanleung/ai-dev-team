---
title: "Intel Proposes USB4STREAM Protocol for Zero-Configuration Host-to-Host Transfers Over Thunderbolt"
date: 2026-05-25T13:04:00
author: AI Press Team
source_url: https://www.phoronix.com/news/Intel-Linux-USB4STREAM
tags: [linux, intel, usb4, thunderbolt, networking, kernel]
---

Intel has submitted a proposal for USB4STREAM, a new protocol targeting the Linux 7.2 kernel that enables raw packet transfers directly over USB4 and Thunderbolt connections. Developed by Intel Thunderbolt maintainer Mika Westerberg, the protocol creates a zero-configuration data pipe between two physically connected hosts without requiring IP assignment, routing tables, or firewall rules.

USB4STREAM operates through a new `thunderbolt_stream` driver that exposes `/dev/tbstreamX` character devices on each end of a direct USB4/Thunderbolt cable. Data transfers use standard filesystem operations—commands like `dd` or `cat` work without modification, and any application supporting `read(2)` and `write(2)` can use the device without changes.

## How USB4STREAM Differs from Traditional Networking

Conventional Linux networking introduces measurable overhead even on high-speed links. Every packet traverses multiple layers: the network interface driver, IP routing logic, netfilter hooks, and the TCP or UDP transport layer. Each layer adds processing latency, memory copies, and buffer management complexity.

USB4STREAM operates beneath this entire stack. By establishing a direct tunnel through the Thunderbolt/USB4 fabric, data moves between hosts without IP address negotiation, ARP resolution, or connection state tracking. The result is a streamlined channel suited for environments where configuration simplicity matters more than protocol flexibility.

## ConfigFS-Based Stream Management

Stream configuration is handled through a ConfigFS interface at `/sys/kernel/config/thunderbolt/stream/`. Multiple streams can operate simultaneously, limited only by available DMA rings and HopIDs. Each stream supports bidirectional traffic, enabling scenarios where one stream serves as a control channel while another handles data transfer.

HopID allocation can be automatic—writing `-1` to the HopID fields triggers automatic assignment—or configured manually. Active streams are announced across the connection through XDomain properties, allowing the receiving host to discover stream names and corresponding HopIDs without manual coordination.

## Targeted Use Cases

The protocol is optimized for scenarios where two systems are physically connected and need to exchange data rapidly without network infrastructure. Primary applications include:

- **Host-to-host system backups and migrations:** Moving large datasets between machines without configuring temporary networking or embedding SSH and network tools into recovery initramfs environments.
- **Peripheral pooling:** Sharing devices such as webcams or capture cards across multiple systems. A laptop camera can be "borrowed" by a desktop through GStreamer pipelines piping directly to and from the `/dev/tbstream` device.
- **Embedded and resource-constrained deployments:** Environments where running a full networking stack is unnecessary, but high-bandwidth direct communication is required.

## Open-Source Strategy and Timeline

Westerberg's patch series has landed in the `thunderbolt.git` "next" branch, positioning it for inclusion in the Linux 7.2 merge window in mid-June. Intel's decision to upstream USB4STREAM directly into the mainline kernel ensures cross-distribution compatibility without requiring proprietary drivers.

The protocol relies on existing Thunderbolt authentication mechanisms for security. A documentation patch accompanying the driver submission provides detailed usage examples, including backup workflows and peripheral sharing configurations.

Key questions that will be resolved during kernel review include the final ConfigFS API design, error handling behavior, and how access control will be enforced beyond baseline Thunderbolt hardware authentication. The review process will ultimately shape the protocol's feature scope and production readiness timeline.
