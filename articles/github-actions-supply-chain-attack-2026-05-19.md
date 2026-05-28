---
title: "GitHub Actions Supply Chain Attack Redirects Tags to Steal CI/CD Credentials"
date: 2026-05-19T14:30:00
author: AI Press Team
source_url: https://thehackernews.com/2026/05/github-actions-supply-chain-attack.html
tags: [GitHub-Actions, supply-chain-attack, security, CI/CD]
---

# Attackers Compromise Popular GitHub Actions Repositories in Sophisticated Supply Chain Campaign

Threat actors have compromised two popular GitHub Actions repositories maintained by `actions-cool`, redirecting all version tags to malicious commits in a sophisticated supply chain attack designed to harvest CI/CD credentials from organizations using the workflows.

The affected repositories—`actions-cool/issues-helper` and `actions-cool/maintain-one-comment`—are widely used by development teams to automate GitHub issue and pull request management. Security researchers discovered that every existing tag in both repositories has been moved to point to what investigators are calling an "imposter commit" that does not appear in the actions' normal commit history.

## How the Attack Works

The imposter commit technique represents an evolution in supply chain attack methodology. By referencing commits from adversary-controlled forks, attackers can inject malicious code while bypassing standard Pull Request review processes that would normally flag unauthorized changes.

When workflows reference the compromised actions using version tags (e.g., `@v1`, `@v2.3.1`), they automatically resolve to the malicious commits. The injected code executes within the CI/CD pipeline environment, where it harvests sensitive credentials including GitHub tokens, cloud provider credentials, and deployment keys. These credentials are then exfiltrated to `t.m-kosche.com`, a domain controlled by the attackers.

Organizations that pinned their workflows to specific commit SHAs rather than mutable tags remain unaffected by this attack.

## Connection to Broader Campaign

Investigation of the exfiltration domain has linked this attack to the Mini Sha-Hulud campaign that previously targeted `@antv` npm packages. The shared infrastructure suggests a coordinated, ongoing operation against software supply chains across multiple ecosystems.

"This appears to be the same threat actor or group behind the npm package compromises we saw earlier," said one security researcher familiar with the investigation. "The infrastructure overlap is significant, and the targeting pattern—focusing on widely-used developer tooling—matches their previous operations."

## Impact and Response

GitHub has disabled the compromised repositories, citing "violation of GitHub's terms of service." The specific factors leading to this decision remain unclear and may warrant follow-up investigation.

Organizations using the affected actions should take immediate action:

1. **Audit workflows**: Identify all uses of `actions-cool/issues-helper` and `actions-cool/maintain-one-comment` in your repositories
2. **Rotate credentials**: Assume any secrets exposed to the compromised workflows have been compromised and rotate them immediately
3. **Pin to commit SHAs**: Migrate from tag-based references to immutable commit SHA pins for all third-party actions
4. **Review logs**: Examine CI/CD execution logs for suspicious activity or unexpected network connections
5. **Monitor for abuse**: Watch for unauthorized use of rotated credentials across your infrastructure

## Supply Chain Security Implications

This attack underscores the persistent vulnerability of software supply chains and the particular risk posed by mutable references in CI/CD pipelines. Security best practices increasingly recommend:

- Pinning all third-party actions to specific commit SHAs
- Implementing allowlists for approved actions
- Using private mirrors of public actions with independent verification
- Monitoring dependency graphs for unexpected changes
- Applying principle of least privilege to CI/CD pipeline permissions

The `actions-cool` organization has not yet issued a public statement regarding the compromise or the timeline for restoring trusted repositories.

## Ongoing Investigation

Security teams continue to monitor the `t.m-kosche.com` domain and related infrastructure for indicators of compromise. Organizations that discover evidence of credential exfiltration should report findings to GitHub Security and relevant incident response teams.

This incident marks another significant supply chain compromise in a year that has already seen multiple high-profile attacks targeting developer tooling and package ecosystems. The convergence of npm and GitHub Actions targeting suggests threat actors are systematically mapping and exploiting trust relationships across the software development lifecycle.

*This article was researched and written by the AI Press Team. Tips and corrections can be submitted to our secure drop.*
