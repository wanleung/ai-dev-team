---
title: "KnowledgeDeliver LMS Zero-Day Under Active Attack to Deploy Memory-Resident Web Shells"
date: 2026-05-27T09:20:00
author: HKLUG Team
source_url: https://www.bleepingcomputer.com/news/security/knowledgedeliver-flaw-exploited-as-a-zero-day-to-install-web-shells/
tags: [CVE-2026-5426, KnowledgeDeliver, web shell, zero-day, ASP.NET, LMS, cybersecurity]
---

# KnowledgeDeliver LMS Zero-Day Under Active Attack to Deploy Memory-Resident Web Shells

A critical unauthenticated remote code execution vulnerability in the KnowledgeDeliver learning management system is being actively exploited to deploy sophisticated in-memory web shells, according to reporting by BleepingComputer on 27 May. The flaw, tracked as CVE-2026-5426, allows attackers to execute arbitrary code on affected servers without authentication, posing a severe risk to educational institutions and enterprises running the platform.

## Root Cause: Hardcoded Machine Keys

The vulnerability stems from a fundamental vendor misconfiguration. Identical ASP.NET machine keys were hardcoded into default `web.config` files shipped with KnowledgeDeliver installations prior to 24 February 2026. ASP.NET machine keys are cryptographic secrets used to sign and encrypt ViewState parameters — hidden form fields that maintain state between client and server in ASP.NET applications.

Because the same key was distributed across all installations, any attacker in possession of the key can forge signed ViewState payloads that the server trusts as legitimate. This effectively bypasses authentication mechanisms and grants unauthenticated remote code execution.

## Multi-Stage Attack Chain

Threat actors are executing a methodical, multi-stage compromise operation. Initial exploitation of the ViewState deserialization flaw delivers remote code execution, which attackers then use to deploy victim-tailored Cobalt Strike beacons for persistent command-and-control communications.

The final stage involves installing the Godzilla web shell — an in-memory payload designed specifically to evade signature-based detection tools. Unlike traditional web shells that write files to disk, Godzilla operates entirely in memory, making it significantly harder for conventional endpoint detection and response solutions to identify and compounding forensic investigation efforts.

## Who Is Affected

All KnowledgeDeliver installations distributed before 24 February 2026 are vulnerable and require immediate action. The learning management system is used by educational institutions and training organizations globally. Given the hardcoded nature of the machine keys, any unpatched deployment is effectively open to exploitation by anyone who has obtained the default key.

## Remediation: Patching Alone Is Not Enough

Organizations operating KnowledgeDeliver must take immediate steps to assess their exposure. Applying the vendor patch is necessary but insufficient — organizations must also manually rotate all hardcoded machine keys found in `web.config` files across affected installations. Without key rotation, patched systems remain vulnerable to attacks leveraging the previously distributed default keys.

Security teams should additionally deploy web application firewall rules to flag anomalous ViewState parameter lengths or structures, audit server logs for unauthorized modifications to JavaScript files or plugin directories, and enable runtime monitoring to detect in-memory web shell execution patterns.

## Broader Implications

This incident reflects a recurring pattern in enterprise software security: shared cryptographic defaults distributed at scale create systemic risk that no single organization can defend against independently. ViewState deserialization attacks have targeted multiple specialized software platforms in recent years, underscoring the need for vendors to generate unique cryptographic material per installation and for organizations to maintain defense-in-depth controls that can detect compromise even when perimeter security fails.

For education and corporate training sectors running the platform, this vulnerability reinforces the importance of auditing third-party software supply chains rigorously and assuming that perimeter defenses alone are insufficient.
