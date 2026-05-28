---
title: "Mini Shai-Hulud Compromises 323 npm Packages via Hacked Maintainer Account"
date: 2026-05-19T14:30:00
author: AI Press Team
source_url: https://thehackernews.com/2026/05/mini-shai-hulud-pushes-malicious-antv.html
tags: [npm, supply-chain-attack, security, malware, Mini-Shai-Hulud]
---

A sophisticated software supply chain attack has compromised 323 npm packages associated with the @antv ecosystem, releasing 639 malicious versions in just 22 minutes through a compromised maintainer account, cybersecurity researchers disclosed Tuesday.

The attack, attributed to the Mini Shai-Hulud threat campaign, targeted the npm maintainer account "atool" to inject credential-stealing malware into widely-used data visualization libraries. Among the affected packages is echarts-for-react, a popular React wrapper for Apache ECharts that sees approximately 1.1 million weekly downloads.

### Attack Mechanics and Scope

The compromised packages were published in a rapid, automated campaign that exploited the trusted status of the atool maintainer account. Rather than creating typosquatting packages or impersonating legitimate libraries, the attackers leveraged genuine access to push malicious updates to existing, trusted packages.

"This represents a significant evolution in supply chain attack methodology," said a security researcher familiar with the investigation. "By compromising a legitimate maintainer account, the attackers bypassed many of the detection mechanisms that would flag suspicious new packages."

The affected packages span the AntV data visualization ecosystem, which is commonly used in enterprise dashboards, analytics platforms, and business intelligence tools across organizations worldwide.

### Malware Capabilities

Analysis of the malicious code reveals extensive credential harvesting functionality targeting more than 20 cloud and development services. The malware attempts to steal:

- Amazon Web Services (AWS) credentials
- Google Cloud Platform (GCP) keys
- Microsoft Azure authentication tokens
- GitHub personal access tokens
- npm authentication tokens
- Kubernetes configuration files
- Stripe API keys

Beyond credential theft, the malware includes functionality to attempt Docker container escapes, potentially allowing attackers to move from compromised containers to host systems. Stolen data is exfiltrated to the domain t.m-kosche.com, with a fallback mechanism that pushes harvested credentials to GitHub repositories if the primary exfiltration channel fails.

Researchers have identified more than 2,200 GitHub repositories marked by the malware for potential follow-up attacks or data collection.

### Open-Sourced Malware Complicates Response

In a development that has alarmed security teams, the threat group TeamPCP released the source code for the Mini Shai-Hulud malware framework through BreachForums, a cybercriminal marketplace. This move effectively open-sources the attack toolkit, lowering barriers for copycat attackers and complicating attribution efforts.

Security firms warn that the released source code could enable less sophisticated threat actors to launch similar supply chain attacks against npm and potentially other package ecosystems such as PyPI, RubyGems, or Cargo.

### Immediate Actions for Development Teams

Organizations using packages from the @antv ecosystem should immediately audit their dependencies and identify any versions published during the attack window. Security teams should:

1. Pin all @antv and atool-maintained packages to known-good versions published before the attack timeframe
2. Implement integrity checks using npm's built-in package lock verification
3. Monitor CI/CD pipelines for unusual network connections to t.m-kosche.com or unexpected GitHub repository modifications
4. Rotate any credentials that may have been exposed on systems where affected packages were installed or executed

Detection signatures for Shai-Hulud-style attacks should focus on identifying unusual package installation patterns, unexpected network exfiltration attempts during build processes, and unauthorized access attempts to credential storage locations.

### Broader Implications

This attack marks the latest in a series of high-profile supply chain compromises that have targeted open source software ecosystems. The speed and scale of the campaign—639 malicious versions in 22 minutes—demonstrates the potential impact when attackers gain access to automated publishing pipelines.

The incident also highlights the critical importance of maintainer account security in open source ecosystems. Many widely-used packages rely on a small number of maintainers, creating single points of failure that attackers can exploit.

npm has not yet issued a public statement on the attack, but the company has previously implemented security measures including mandatory two-factor authentication for maintainers of popular packages and enhanced monitoring for suspicious publishing patterns.

Organizations discovering affected packages in their dependency trees should report incidents to their security teams and consider filing reports with npm's security team to aid ongoing investigation efforts.

*This is a developing story. More details will be added as information becomes available.*
