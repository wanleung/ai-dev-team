---
title: "CISA Credentials Exposed in Public GitHub Repository for Six Months"
date: 2026-05-19T14:30:00
author: AI Press Team
source_url: https://arstechnica.com/information-technology/2026/05/in-stunning-display-of-stupid-secret-cisa-credentials-found-in-public-github-repo/
tags: [CISA, GitHub, Credential Leak, Nightwing, Cybersecurity]
---

The Cybersecurity and Infrastructure Security Agency had plaintext passwords, SSH private keys, and tokens exposed in a public GitHub repository since November 2025. The breach came to light through reporting by Ars Technica and security researcher Brian Krebs.

The repository — named "Private-CISA" and managed by Virginia-based contractor Nightwing — remained publicly accessible until GitGuardian researcher Guillaume Valadon discovered it through automated scanning. After attempts to notify the repository owner went unanswered, Valadon contacted Krebs, who published the story on May 19, 2026.

## Discovery and Verification

GitGuardian's automated scanning detected the exposed credentials during routine monitoring of public code repositories. Commit logs showed that GitHub's default secret protection mechanisms had been disabled by the repository administrator, according to Valadon.

Security researcher Philippe Caturegli, founder of Seralys, tested the credentials and confirmed they provided high-privilege access to multiple AWS GovCloud accounts. The repository has since been taken offline.

Nightwing has not commented publicly and referred questions to CISA. The agency has not disclosed which specific systems were accessible through the exposed credentials or whether unauthorized access occurred during the six-month exposure window.

## Context and Precedent

This incident marks another security lapse for CISA within the same year. In January 2026, then-acting CISA Director Madhu Gottumukkala uploaded sensitive government documents to ChatGPT after receiving an exemption from the agency's own AI usage policy. Gottumukkala was removed from his role in February.

CISA operates under Binding Operational Directive 22-01, the same vulnerability remediation framework the agency promotes for federal systems. The exposure suggests a gap between policy and implementation within the agency's own development workflows.

## Implications for Security Teams

The incident underscores a challenge familiar to security professionals: the difference between knowing best practices and consistently applying them. CISA has publicly recommended credential scanning tools like GitLeaks and TruffleHog, secret management platforms including HashiCorp Vault and AWS Secrets Manager, and pre-commit hooks to prevent sensitive data from entering version control.

For IT security teams and open-source maintainers, the situation reinforces several priorities:

- Automated credential scanning must run before commits reach remote repositories
- Existing repositories need periodic auditing to catch historical exposures
- Credential rotation policies should treat any exposed secret as compromised
- Access controls should follow least-privilege principles to limit blast radius

## Looking Forward

The incident places CISA in an uncomfortable position for an agency whose credibility rests on demonstrated security competence. However, security professionals note that human error affects even expert organizations.

What distinguishes mature security programs is not perfect prevention but transparent incident response and systematic improvement. The security community will likely watch how CISA handles remediation and whether the agency updates its guidance based on this experience.
