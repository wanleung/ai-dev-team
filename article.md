---
title: "Dillo Maintainer Proposes Terminal Recordings to Verify Human Authorship in Open-Source Projects"
date: 2026-05-26T19:26:00
author: AI Press Team
source_url: https://lwn.net/Articles/1074534/
tags: [open-source, AI, code-review, FOSS, asciinema]
---

A maintainer of the Dillo web browser has proposed a novel approach to verifying human authorship in free and open-source software contributions: requiring new contributors to submit terminal session recordings alongside their patches. The proposal, published by Rodrigo Arias Mallo on the Dillo project website and reported by LWN.net on 26 May, suggests using `asciinema` — an existing open-source terminal recording tool — to create an auditable record of the development process rather than relying solely on static code analysis.

The proposal emerges from a growing concern across the FOSS community about the proliferation of AI-generated code submissions. As large language models become increasingly capable of producing functional patches, maintainers face mounting difficulty distinguishing between contributions authored by developers with genuine understanding of a codebase and those generated automatically with minimal human oversight. Mallo's approach shifts the verification paradigm from examining output to examining process.

## How the Framework Works

Under the proposed system, new contributors would record their terminal sessions while developing a patch. The recording would capture the full workflow — including debugging attempts, iterative changes, and decision-making moments — providing maintainers with context that a final diff alone cannot convey. The framework is designed to remain voluntary rather than mandatory, reflecting a deliberate choice to preserve the low barrier to entry that has historically defined open-source participation.

The technical rationale is straightforward: while AI systems can generate code patches with ease, producing a convincing terminal recording that demonstrates authentic problem-solving requires substantially more computational effort and contextual awareness. The friction involved in fabricating such recordings acts as a practical deterrent against low-effort automated submissions, even if it does not constitute an absolute guarantee of human authorship.

## Technical Critique and Limitations

The proposal raises several questions that warrant careful consideration before adoption. Terminal recordings, while informative, introduce significant review overhead. Maintainers would need to watch session recordings in addition to reading diffs — a time investment that may prove unsustainable for high-traffic projects or small teams with limited review capacity. The scalability of this approach remains an open concern.

Privacy considerations also merit attention. Terminal sessions may inadvertently expose sensitive information such as environment variables, file paths, or credentials. Projects adopting this framework would need to establish clear guidelines on what content is acceptable to record and how contributors should redact sensitive data before submission.

Furthermore, the proposal does not fully address the trajectory of AI capability. As AI agents advance toward more realistic, context-aware terminal interaction, the gap between genuine and fabricated recordings may narrow. The framework may serve as a near-term mitigation rather than a long-term solution.

## Implications for Enterprise Teams

For Hong Kong-based developers and enterprise teams managing open-source dependencies, the proposal offers a concrete signal of how verification practices may evolve. Organizations that rely heavily on third-party FOSS components should monitor whether major projects adopt similar frameworks, as compliance with contributor verification requirements could become a factor in upstream engagement strategy.

Enterprise teams contributing to open-source projects should consider establishing internal guidelines for terminal recording practices — including standardised redaction procedures and acceptable session length — before such requirements become widespread. Early preparation can reduce onboarding friction when projects begin requesting workflow documentation.

The broader lesson for IT strategy is that trust in open-source supply chains is shifting from code-centric verification to process-centric verification. Teams that understand and adapt to this shift will be better positioned to maintain productive relationships with upstream maintainers while ensuring the integrity of their own contributions.

## Open Questions Remain

The Dillo proposal is a starting point, not a finished standard. Key questions persist: How should projects formally accommodate legitimate AI-assisted workflows while still verifying meaningful human oversight? What constitutes an acceptable recording length? How can review workloads be distributed or automated without undermining the transparency the framework aims to provide?

Mallo's proposal has sparked discussion precisely because it acknowledges these uncertainties while offering a practical, open-source-compatible mechanism to begin addressing them. Whether the approach gains traction beyond the Dillo project will depend on how the community answers these questions in the months ahead.
