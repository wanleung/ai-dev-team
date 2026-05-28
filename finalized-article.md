---
title: "Attackers Weaponize Critical Drupal PostgreSQL Flaw Within Days of Patch"
date: 2026-05-23T19:53:00
author: AI Press Team
source_url: https://securityaffairs.com/192557/security/cve-2026-9082-drupals-highly-critical-sql-injection-flaw-is-already-under-active-attack.html
tags: [drupal, sql-injection, postgresql, cve-2026-9082, web-security]
---

Threat actors began exploiting a critical SQL injection vulnerability in Drupal within 48 hours of the patch release, with security firms tracking thousands of attacks targeting sites running PostgreSQL databases.

Drupal issued the emergency security update on May 20 for CVE-2026-9082, a flaw in an API designed to sanitize database queries. The vulnerability allows unauthenticated attackers to send specially crafted requests and inject arbitrary SQL commands on PostgreSQL-backed installations. Drupal updated the advisory on May 22 to confirm exploit attempts were being detected in the wild.

The vulnerability carries a risk score of 23 out of 25 on Drupal's NIST-based CVSS scale. Successful exploitation can result in information disclosure, privilege escalation, and in some configurations, remote code execution. The flaw only affects sites using PostgreSQL as their database backend, which Drupal estimates at under 5 percent of all installations — still representing thousands of potentially vulnerable sites across government, education, media, and enterprise sectors.

Imperva reported observing over 15,000 exploitation attempts targeting nearly 6,000 individual sites across 65 countries in the first two days after disclosure. Nearly half of those attacks focused on gaming and financial services websites. The United States accounted for 61.8 percent of targeted sites, followed by Singapore at 6.6 percent and Australia at 6.3 percent.

Researchers noted that current activity is dominated by reconnaissance and validation, with attackers mapping vulnerable sites and confirming exploit functionality. The pattern suggests campaigns are still in the identification phase rather than widespread data extraction.

Drupal maintainers had warned ahead of the patch release that exploits could surface within hours or days. The last time Drupal saw active exploitation of a highly critical flaw was in 2019, when a remote code execution vulnerability was weaponized within days of patching.

Administrators running Drupal on PostgreSQL should apply the patch immediately. Those on MySQL or MariaDB are not affected by this vulnerability but should verify their database backend configuration. Organizations seeing unusual database query patterns or failed authentication attempts should treat those as potentially hostile and investigate promptly.
