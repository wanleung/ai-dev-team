---
title: "CISA Lists Actively Exploited Drupal Core Flaw in KEV Catalog, Mandates Rapid Patching"
date: 2026-05-24T21:32:00
author: AI Press Team
source_url: https://securityaffairs.com/192566/uncategorized/u-s-cisa-adds-a-flaw-in-drupal-core-to-its-known-exploited-vulnerabilities-catalog.html
tags: [drupal, cisa, kev, vulnerability, patching]
---

The U.S. Cybersecurity and Infrastructure Security Agency (CISA) has added a critical Drupal Core vulnerability to its Known Exploited Vulnerabilities (KEV) catalog, confirming active exploitation in the wild. The listing compels federal civilian agencies to patch within 14 days and serves as an urgent directive for all organisations running the open-source content management system.

The vulnerability carries a CVSS severity score of 9.8, enabling remote code execution without authentication. Drupal's security team released emergency patches in May, directing administrators to upgrade to version 10.2.5 or 9.5.15 and above. Administrators must cross-reference Drupal's official security advisory to confirm the correct CVE identifier — early coverage incorrectly conflated this flaw with CVE-2026-9082, a separate Microsoft Exchange Server vulnerability also tracked by CISA. Misattributed CVEs risk misdirecting remediation efforts and leaving Drupal instances exposed.

CISA's KEV catalog functions as a binding mandate for federal agencies, which must apply patches or deploy compensating controls within two weeks of listing. For private sector operators, the catalog operates as a de facto urgency benchmark. The agency's decision to include this Drupal vulnerability signals confirmed weaponisation, elevating the risk from theoretical to an immediate operational threat.

The gap between patch publication and enterprise deployment remains the primary attack surface. Threat actors routinely monitor open-source security advisories, reverse-engineer published fixes, and build working exploits before organisations complete internal testing. This reality exposes the structural inadequacy of calendar-based patch management workflows. Security teams must prioritise internet-facing Drupal instances for immediate updates. Legacy or heavily customised systems that cannot meet the two-week baseline should be temporarily withdrawn from public networks until a validated remediation path is established.

For Hong Kong IT administrators managing Drupal deployments across government, financial services, and education sectors, the KEV listing reinforces the need to align internal patching SLAs with international threat intelligence. HKCERT routinely mirrors CISA advisories and issues local guidance for critical vulnerabilities; organisations subscribed to HKCERT alerts should treat this listing as a trigger for accelerated patch cycles. Enterprises running public-facing Drupal infrastructure should verify asset inventory completeness and prioritise external-facing systems for immediate updates.

This incident highlights a broader governance challenge for organisations dependent on community-maintained open-source platforms. Unlike commercial software backed by dedicated vendor support teams, CMS platforms like Drupal require proactive oversight: continuous security feed monitoring, automated vulnerability scanning, and streamlined deployment pipelines that compress the window between patch availability and production rollout. Teams relying on manual, reactive patching processes should treat this listing as a catalyst for investing in automated vulnerability management tooling.

Drupal administrators who have not yet applied the May security updates should do so immediately. Any instance that cannot be patched due to customisation constraints or dependency conflicts must be removed from public network access until a secure remediation path is validated.
