---
title: "Intel Archives Another Wave of Open-Source Tools, Including CVE Scanner and OBS Plugin"
date: 2026-05-23T20:09:00
author: AI Press Team
source_url: https://www.phoronix.com/news/Intel-EOL-OBS-Plugin-And-More
tags: [Intel, Open Source, DevOps, Security, CVE Binary Tool, OBS Studio]
---

Intel has formally archived another batch of open-source projects this week, continuing a months-long retreat from maintaining developer utilities that no longer align with the company's strategic priorities. The latest round includes the Thunderbolt Share plugin for OBS Studio, the CVE Binary Tool Action for vulnerability scanning, the Streaming Media Transcoding Application (SMTA), the Intel Trusted Ledger Config Store for SGX enclaves, and the SCAP research project from Intel Labs. An additional project, Self-Governed Remote Attestation, was briefly archived before being reinstated the same day following what appears to have been an internal miscommunication.

The archival notices come days after Intel sunset another group of repositories, including the BigDL Time Series Toolkit and others. Over the past year, Intel has wound down numerous efforts — most notably Clear Linux, its Software Defined Silicon projects, and open-ecosystem evangelism programmes — as the company concentrates its open-source contributions on areas directly tied to its current business, such as compilers and the Linux kernel.

Archived repositories remain publicly accessible, but active maintenance has ceased. For engineering teams that integrated these tools into production workflows, the shift places the burden of upkeep on the community or forces migration to alternatives.

The retirement of the CVE Binary Tool Action carries the most immediate operational risk. The utility had been used to scan GitHub repositories, binaries, component lists, and software bills of materials for known vulnerabilities. Teams relying on it for automated CI/CD security checks should now evaluate replacement options. As editorial guidance, tools like Aqua Security's Trivy offer broad language and container scanning support, while OWASP Dependency-Check remains a mature choice for Java and .NET ecosystems. Organisations should audit their pipelines promptly to ensure vulnerability detection does not lapse during the transition.

The Thunderbolt Share OBS plugin's archival affects content creators and streaming teams who used it to capture and transmit display and audio between computers over Thunderbolt connections. Affected users should investigate OBS's native hardware acceleration features or third-party plugins that support Intel Quick Sync Video without depending on Intel-maintained tooling.

Intel's consolidation reflects a broader shift in how large technology companies approach open-source engagement. Corporate contributions are increasingly tied to direct business needs rather than broad community support. Vendor-backed tools introduce operational risk when strategic roadmaps change, and end-of-life announcements can disrupt established workflows without warning. Teams that treat third-party dependencies as permanent infrastructure are the most exposed.

Practical steps for affected organisations include auditing all repositories and pipelines that depend on Intel's archived utilities, documenting which functionalities lack direct replacements, and establishing contingency protocols for future vendor-lifecycle events. Where no suitable alternative exists, community-led forks are an option — but independent stewardship demands dedicated engineering capacity and ongoing security review.

The lesson for IT teams is clear: corporate open-source projects should be evaluated not only for their immediate usefulness but for their long-term viability. Diversifying toolchains, retaining internal expertise around critical dependencies, and planning for vendor exit scenarios are now essential practices for resilient software operations.
