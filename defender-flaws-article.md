---
title: "Attackers Exploit Active Defender Flaws to Gain SYSTEM Access and Disable Endpoint Protection"
date: 2026-05-22T00:41:00
author: AI Press Team
source_url: https://thehackernews.com/2026/05/microsoft-warns-of-two-actively.html
tags: [microsoft, defender, vulnerability, privilege-escalation, denial-of-service, CVE-2026-41091]
---

Microsoft issued an urgent advisory this week confirming that two vulnerabilities in its Defender endpoint protection platform are under active exploitation by threat actors. The flaws — one enabling privilege escalation to SYSTEM-level access and another capable of crashing the Defender service entirely — represent a tactical shift: attackers are no longer trying to bypass endpoint protection, they are targeting it directly.

The privilege escalation vulnerability, tracked as CVE-2026-41091, carries a CVSS severity rating of 7.8. Successful exploitation grants an attacker full SYSTEM privileges on the compromised machine. Microsoft attributes the root cause to improper link resolution before file access — a mechanism commonly referred to as link following — within Defender's file scanning routines.

The vulnerability exploits a timing gap in Defender's link-resolution logic. When Defender scans a file, it resolves symbolic links or junction points after performing its initial security checks rather than before. An attacker can exploit this race condition by placing a malicious symbolic link in a scanned location, then swapping the link target to a protected system file between the validation and actual access. Defender inadvertently operates on a file it should have restricted, allowing the attacker to escalate to SYSTEM privileges.

The second vulnerability, a denial-of-service flaw, remains less detailed in Microsoft's public advisories. No CVSS score has been assigned and technical specifics have not been disclosed. Its practical impact is clear: attackers can trigger a crash in the Defender service, effectively blinding endpoint protection at a moment of their choosing.

Security operations teams should prioritize an immediate patching workflow. Windows administrators are advised to deploy the latest cumulative security updates through WSUS or Microsoft Endpoint Configuration Manager, testing in an isolated environment before broad deployment. For organizations unable to patch immediately, compensating controls include disabling legacy file access protocols, enforcing strict discretionary access controls on sensitive directories, and blocking execution of untrusted files from network shares and removable media.

The broader pattern warrants attention. When a single security layer can be both exploited for escalation and crashed for evasion, defense-in-depth architecture ceases to be optional. Organizations should implement layered monitoring that detects anomalous SYSTEM-level privilege escalations and unexpected Defender service terminations, ensuring visibility persists even when endpoint agents are compromised. Deeply integrated security tools require independent telemetry layers, rigorous path-resolution auditing, and modular or sandboxed designs to maintain resilience when primary agents are targeted.

Microsoft has not publicly attributed these exploits to any specific threat actor or campaign. The undisclosed CVSS score for the denial-of-service flaw leaves enterprises without a standardized metric to prioritize remediation. For IT teams managing complex production environments, the tension between emergency patch deployment and stability testing remains unresolved — underscoring the need for automated patch management pipelines capable of rapid, validated rollouts.
