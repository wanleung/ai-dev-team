---
title: "Laravel Lang Supply Chain Attack Harvests Developer Credentials Via Rewritten Git Tags"
date: 2026-05-24T03:46:00
author: AI Press Team
source_url: https://www.bleepingcomputer.com/news/security/laravel-lang-packages-hijacked-to-deploy-credential-stealing-malware/
tags: [supply-chain-attack, laravel, composer, open-source-security, credential-theft]
---

A supply chain attack against the Laravel Lang localization packages has exposed developers to a broad credential-stealing campaign after an attacker rewrote hundreds of GitHub version tags to point to malicious commits, security firms StepSecurity, Aikido Security, and Socket reported on Friday.

The compromise affected four repositories under the Laravel Lang organization: `laravel-lang/lang`, `laravel-lang/http-statuses`, `laravel-lang/attributes`, and possibly `laravel-lang/actions`. These third-party translation packages are not part of the official Laravel project. Aikido counted 233 compromised versions across three repositories, while Socket estimated roughly 700 historical versions may have been impacted.

Rather than injecting malicious code into the project's source repository, the attacker used a GitHub feature that allows tags to reference commits in forks of the same repository. Every existing git tag was rewritten to point at a new malicious commit, starting at 22:32 UTC against `laravel-lang/lang` (which carries 502 tags) and finishing by 00:00 UTC against `laravel-lang/actions`. All four repositories shared the same fake author identity, modified files, and payload behavior, suggesting a single actor with organization-wide push access carried out the operation.

When developers installed or updated these packages through Composer, the package manager resolved the rewritten tags and downloaded code from the attacker-controlled fork, treating the malicious releases as legitimate.

## Malicious Payload and Credential Harvesting

The compromised releases introduced a file named `src/helpers.php` that was automatically loaded by Composer. This file acted as a dropper, downloading a second-stage PHP payload from a command-and-control server at `flipboxstudio[.]info`.

The downloaded payload is a cross-platform credential stealer targeting Linux, macOS, and Windows systems. It harvests cloud credentials, Kubernetes secrets, Vault tokens, Git credentials, CI/CD secrets, SSH keys, browser data, cryptocurrency wallets, password manager stores, VPN configurations, and local `.env` files. The malware includes regular expression patterns designed to extract AWS keys, GitHub tokens, Slack tokens, Stripe secrets, database credentials, JWTs, SSH private keys, and cryptocurrency recovery phrases from files and environment variables.

On Windows systems, the PHP payload extracts a base64-encoded executable written to the `%TEMP%` folder under a random `.exe` filename. BleepingComputer's analysis identified this binary as `DebugElevator`, an infostealer targeting Chrome, Brave, and Edge browsers by extracting App-Bound Encryption keys needed to decrypt stored credentials. An embedded PDB path references the Windows account name `Mero` and contains the string `claude`, suggesting AI assistance in the malware's development.

Once collected, the stolen data is encrypted and transmitted back to the attacker's C2 server.

## Response and Remediation

Packagist responded to the incident by removing the malicious versions and temporarily unlisting the affected packages to prevent further installations.

Development teams using Laravel Lang packages should take immediate action:

1. **Audit `composer.lock`** for any `laravel-lang` packages installed during the attack window and compare installed versions against the official package registry to identify revoked or flagged releases.

2. **Run `composer audit`** in your project directory to check installed packages against the Packagist security advisory database, which will flag known compromised versions.

3. **Remove tainted packages** by deleting affected entries from `composer.lock`, purging the `vendor/laravel-lang` directory, and running `composer install` to fetch clean versions from verified tags.

4. **Rotate all credentials** stored in `.env` files on any system where the compromised packages were installed. Treat database passwords, API tokens, and service keys as exposed and regenerate them immediately.

5. **Review infrastructure access logs** for cloud services, databases, and third-party integrations to identify any unauthorized access during the exposure window. Check for historical outbound connections to `flipboxstudio[.]info`.

## Broader Implications for Open Source Security

This incident highlights a structural blind spot in how package managers handle version resolution. Automated dependency scanners typically analyze repository default branches or published tarballs for known vulnerability signatures. By manipulating version tags instead of modifying source code directly, the attacker created releases that appeared legitimate from a metadata perspective while delivering malicious payloads during installation.

Semantic versioning conventions assume that a tagged release represents a verified, intentional snapshot of code. When that assumption is violated, automated tools that rely on tag integrity as a signal of authenticity have no built-in mechanism to detect the compromise.

Security researchers recommend pinning all third-party dependencies to exact, verified versions rather than allowing automatic minor or patch updates, implementing cryptographic package signature verification where supported, integrating Software Composition Analysis tools into CI/CD pipelines to monitor for anomalous releases, and enforcing strict repository access controls including multi-factor authentication and protected branch and tag policies for all package maintainers.

The open-source ecosystem continues to grapple with standardizing cryptographic signing and tag protection across decentralized repositories without introducing friction that discourages community contributions. Until such mechanisms become universal, development teams must treat automated dependency resolution as an untrusted surface and implement their own verification layers.
