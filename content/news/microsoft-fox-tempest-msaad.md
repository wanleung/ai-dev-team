---
title: "Microsoft Dismantles Fox Tempest: Malware-Signing Network Abused Trust Infrastructure"
date: 2026-05-19T10:30:00
author: AI Press Team
source_url: https://securityaffairs.com/192391/cyber-crime/microsoft-dismantled-malware-signing-network-fox-tempest.html
tags: [Microsoft, Fox Tempest, Malware, Code-Signing, Security, MSaaS]
---

# Microsoft Dismantles Fox Tempest: Malware-Signing Network Abused Trust Infrastructure

Microsoft's Digital Crimes Unit has dismantled Fox Tempest, a malware-signing-as-a-service (MSaaS) operation that issued fraudulent code-signing certificates to cybercriminals. The disruption removes a key enabler of ransomware and malware campaigns that relied on trusted digital signatures to bypass endpoint security.

According to Security Affairs, Fox Tempest created over 1,000 certificates and established hundreds of Azure tenants and subscriptions to support its operation. Microsoft revoked more than 1,000 code-signing certificates linked to the group and filed a lawsuit against Fox Tempest and Vanilla Tempest, enabling domain seizures and infrastructure takedowns.

## Trust Infrastructure as a Service

Fox Tempest operated signspace[.]cloud, a platform that allowed threat actors to obtain short-lived Microsoft-issued certificates through abused Artifact Signing processes. The certificates had 72-hour validity windows, designed to evade revocation lists and automated blacklisting before security vendors could identify and block them.

Users passed identity verification to obtain certificates, suggesting the likely use of stolen identities. The platform included admin and customer portals where malicious files were uploaded and signed, with infrastructure built on Azure and linked to a GitHub repository named code-signing-service.

In February 2026, Fox Tempest expanded by providing pre-configured virtual machines hosted on third-party infrastructure, allowing customers to submit malware for signing directly. This reduced friction and improved scalability for distributing trusted but malicious binaries.

## Pricing and Customer Base

Fox Tempest monetized its service by charging between $5,000 and $9,000 for access, with higher tiers receiving priority access and virtual machines for signing malicious code. The operation was actively managed on Telegram, where channels advertised EV certificate access and buyers coordinated payments.

Microsoft Threat Intelligence assesses that Fox Tempest is a well-resourced group handling infrastructure creation, customer relations, and financial transactions. Since September 2025, the group has been linked to operators including Vanilla Tempest, Storm-0501, Storm-2561, and Storm-0249, which used Fox Tempest-signed malware in attacks delivered through malvertising, SEO poisoning, and fake ads.

The group is also tied to ransomware affiliates behind families such as INC, Qilin, and Akira, with millions in alleged proceeds. Signed malware distributed through the service included Rhysida ransomware, Oyster, Lumma Stealer, and Vidar.

"The downstream impact of these operations has resulted in attacks against a broad range of industry sectors, including healthcare, education, government, and financial services, impacting organizations globally including, but not limited to the United States, France, India, and China," Microsoft stated.

## Security Recommendations

Microsoft recommends layered defenses against similar attacks, including cloud protection, Safe Links and Attachments, SmartScreen, and strong identity controls. Key steps include tamper protection, limiting admin rights, and enabling attack surface reduction rules.

Organizations should configure endpoint detection systems to validate certificate issuer, expiration window, and historical reputation—not merely verify signature presence. Monitoring for anomalous certificate lifecycles and short-lived certificate patterns can indicate abuse. Requiring multi-factor authentication for all code-signing operations with comprehensive audit trails adds protection against unauthorized certificate issuance.

Subscribing to certificate transparency logs enables security teams to detect unauthorized signing activities associated with their organization's identity, providing early warning of potential impersonation or compromise.

## Disruption Requires Continued Collaboration

Microsoft's action involved collaboration with cybersecurity company Resecurity, Europol's European Cybercrime Centre (EC3), and the Federal Bureau of Investigation (FBI). The company emphasized that disruption actions don't happen in isolation and require ongoing partnership across the security ecosystem.

"Collaboration is critical, as different organizations and sectors have visibility into different parts of the cybercrime ecosystem," Microsoft concluded. "In this case, we are working closely with cybersecurity company Resecurity, whose insights help us better understand how Fox Tempest operates."

## Broader Implications

The Fox Tempest takedown underscores the need for fundamental reassessment of trust-based security models. As certificate abuse becomes more prevalent, the industry must move beyond signature-only validation toward multi-factor authenticity verification that considers certificate history, issuer reputation, and behavioral patterns.

For the open-source and IT communities, the disruption serves as a reminder that trust infrastructure requires continuous vigilance. Developers should monitor certificate transparency logs for their projects, implement robust signing practices, and stay informed about emerging certificate abuse techniques.

Microsoft's action demonstrates that platform providers bear responsibility for policing their trust ecosystems. However, sustainable protection requires collaboration between vendors, security researchers, and enterprise defenders to identify and disrupt abuse before it reaches production environments.

The Fox Tempest takedown is a victory, but it is not a solution. Until systemic changes address the underlying vulnerabilities in certificate issuance and validation, trust infrastructure will remain an attractive target for cybercriminals seeking to bypass defenses by weaponizing authenticity itself.
