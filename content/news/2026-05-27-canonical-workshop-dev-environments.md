---
title: "Canonical Launches Workshop for One-Command Sandboxed Dev Environments on Ubuntu"
date: 2026-05-27T06:00:00
author: AI Press Team
source_url: "https://www.phoronix.com/news/Canonical-Ubuntu-Workshop"
tags: [canonical, ubuntu, workshop, lxd, development-tools, snap, containers, ai-agents]
---

Canonical has released Workshop, a new Snap-packaged application that provisions sandboxed development environments on Ubuntu with a single command. The tool targets developers who need reproducible, shareable workspaces — particularly teams building with AI agents that require strict confinement.

Workshop environments are defined in YAML configuration files that specify the SDKs, dependencies, and host resource access each project needs. Those files can be version-controlled and distributed across a team, ensuring every developer gets an identical setup regardless of their underlying hardware.

## Built on LXD, Designed for Composability

Workshop runs on top of LXD system containers and requires version 6.8 or newer. Once installed, developers can pull pre-built SDK images — including NVIDIA CUDA, AMD ROCm, Ollama, and OpenCode — by declaring them in their Workshop YAML. Environments can be created, upgraded, or torn down on demand.

Host resource access is handled through an interface system modelled after snapd. Rather than writing custom mount scripts or mapping filesystem paths manually, developers declare which resources their environment needs — desktop display access, SSH agent forwarding, specific devices — and Workshop enforces those boundaries uniformly.

## Agent-Ready Sandboxing

A distinguishing feature of Workshop is its explicit support for agentic AI workflows. The development environments run as unprivileged containers, limiting the attack surface available to workloads executing inside them. SDKs inside a Workshop are restricted to a standardised set of resource requests, meaning AI agents operating within an environment cannot escalate beyond the permissions defined in the YAML configuration.

"Ease of use for developers shouldn't mean ease of access for AI agents," said Dmitry Lyfar, Engineering Manager at Canonical. "Resource allocation remains simple and consistent across all environments to minimize human error, while non-privileged defaults effectively constrain workload capabilities."

Jon Seager, Canonical's VP of Engineering, framed the release as a response to the shrinking gap between cutting-edge tooling and mainstream adoption. "Developers operating at the cutting edge want to focus on what they're building, not on dependencies or workstation configuration," Seager said. "Workshop enables developers to achieve that elegantly with a single YAML file that defines their environment, and pulls the exact dependencies and components they need."

## Getting Started

Workshop is available now via the Snap store. Installation requires LXD 6.8 or newer:

```
sudo snap install --channel=6/stable lxd
sudo snap install --classic workshop
```

Full documentation, including guides on managing modular workspaces and building custom SDKs, is hosted at [documentation.ubuntu.com/canonical-workshop](https://documentation.ubuntu.com/canonical-workshop/latest/). Initial details and community discussion are ongoing on the [Ubuntu Discourse](https://discourse.ubuntu.com/t/introducing-workshop-launch-sandboxed-development-environments-on-ubuntu-with-a-single-command/83322).
