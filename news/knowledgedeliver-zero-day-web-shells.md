---
title: "KnowledgeDeliver LMS Zero-Day Under Active Attack to Deploy Memory-Resident Web Shells"
date: 2026-05-27T09:20:00
author: HKLUG Team
source_url: https://www.bleepingcomputer.com/news/security/knowledgedeliver-flaw-exploited-as-a-zero-day-to-install-web-shells/
tags: [CVE-2026-5426, KnowledgeDeliver, web shell, zero-day, ASP.NET, LMS, cybersecurity, machine key]
---

# KnowledgeDeliver LMS Zero-Day Under Active Attack to Deploy Memory-Resident Web Shells

A critical unauthenticated remote code execution vulnerability in the KnowledgeDeliver learning management system is being actively exploited to deploy sophisticated in-memory web shells, according to reporting by BleepingComputer on 27 May. The flaw, tracked as CVE-2026-5426, allows attackers to execute arbitrary code on affected servers without authentication, posing a severe risk to educational institutions and enterprises running the platform.

**Critically, applying the vendor patch alone does not remove existing compromises or neutralize the underlying risk — organizations must also manually rotate all hardcoded machine keys and deploy enhanced runtime monitoring to fully remediate.**

## Root Cause: Shared ASP.NET Machine Keys

The vulnerability stems from a systemic vendor configuration error. Identical ASP.NET machine keys were hardcoded into default `web.config` files shipped with KnowledgeDeliver installations distributed before 24 February 2026.

ASP.NET machine keys are cryptographic secrets used to sign and encrypt ViewState parameters — hidden form fields that maintain application state between client and server. Because every installation received the same key, any attacker who obtained it could forge signed ViewState payloads that the server would accept as legitimate. This bypasses authentication entirely and grants unauthenticated remote code execution through ViewState deserialization.

## Multi-Stage Attack Chain

Threat actors are executing a structured, multi-stage intrusion rather than opportunistic exploitation. The attack sequence follows three phases:

1. **Initial Access:** Exploitation of the ViewState deserialization flaw delivers unauthenticated remote code execution.
2. **Persistent C2:** Attackers deploy victim-tailored Cobalt Strike beacons to establish persistent command-and-control communications.
3. **In-Memory Persistence:** The Godzilla web shell is injected directly into server memory. Unlike traditional web shells that write files to disk, Godzilla operates entirely in memory, deliberately evading signature-based endpoint detection and forensic analysis.

## Who Is Affected

All KnowledgeDeliver installations distributed before 24 February 2026 are vulnerable. The platform is used by educational institutions and training organizations globally. Because the machine keys were identical across all deployments, any unpatched installation is exposed to anyone who has obtained the default key.

## Remediation Checklist for IT Administrators

Organizations running KnowledgeDeliver should execute the following steps immediately:

- [ ] **Apply the vendor patch** — Update to the latest KnowledgeDeliver release issued after 24 February 2026.
- [ ] **Rotate all hardcoded machine keys** — Locate and replace any default machine keys in `web.config` files across all affected ASP.NET applications. Generate unique per-installation keys; do not reuse keys across servers.
- [ ] **Deploy WAF rules** — Configure web application firewall rules to flag anomalous ViewState parameter lengths or structures indicative of forged payloads.
- [ ] **Audit server logs** — Review logs for unauthorized modifications to JavaScript files, plugin directories, or unexpected script execution.
- [ ] **Enable runtime monitoring** — Deploy runtime application self-protection or in-memory execution detection to identify web shell injection patterns that bypass disk-based EDR.
- [ ] **Assume compromise** — For any unpatched system, treat the server as potentially compromised. The absence of visible artifacts does not indicate safety given the in-memory nature of the Godzilla payload.

## Broader Implications

This incident underscores a recurring failure in enterprise software security: shared cryptographic defaults distributed at scale create systemic risk that no single organization can defend against independently. ViewState deserialization attacks have targeted multiple specialized platforms in recent years, reinforcing the need for vendors to generate unique cryptographic material per installation and for organizations to maintain defense-in-depth controls that detect compromise even when perimeter security fails.

For Hong Kong's education and corporate training sectors, this vulnerability highlights the importance of rigorous third-party software supply chain auditing and the assumption that perimeter defenses will eventually be bypassed.
