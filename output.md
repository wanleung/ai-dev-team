---
title: "SFC Launches Multi-Pronged Campaign Over Bambu Lab AGPLv3 Violations"
date: 2026-05-25T17:47:00
author: AI Press Team
source_url: https://lwn.net/Articles/1074286/
tags: [open-source, AGPLv3, compliance, 3D printing, Software Freedom Conservancy]
---

The Software Freedom Conservancy (SFC) has launched a comprehensive enforcement campaign against 3D printer manufacturer Bambu Lab over confirmed AGPLv3 violations, including a reverse-engineering project, an active watchdog pledge, and a $250,007 fundraiser to support long-term right-to-repair work.

The SFC announced the initiative on 18 May after completing an investigation into Bambu Lab's userspace software and firmware. The organization confirmed two specific AGPLv3 violations: Bambu Lab has not released the complete Corresponding Source Code for its Bambu Studio slicer, and the company sent legal threats to developer Paweł Jarczak over his independent fork of the Orca Slicer project.

Bambu Studio is a modified version of PrusaSlicer, which itself derives from Alessandro Ranellucci's Slic3r. While Bambu publishes some source code on its GitHub account, the company acknowledges that Bambu Studio is combined with a proprietary library distributed to users through an interactive UI prompt. The SFC identified the specific proprietary components as `libbambu_networking.so`, `bambu_networking.dll`, and `libbambu_networking.dylib`, stating that their failure to provide Corresponding Source and Installation Information constitutes an "egregious and ongoing" AGPLv3 violation.

The second violation centres on Jarczak's modifications to Orca Slicer, a separate AGPLv3-licensed slicer. Jarczak examined Bambu Studio's incomplete source code and built an integration that allowed Orca Slicer to communicate with Bambu's server-side components without replacing the proprietary networking libraries. Bambu demanded he remove the fork from GitHub, citing terms of service that the SFC says cannot override AGPLv3 rights under section 10, paragraph 3 of the license. Jarczak removed the fork under protest.

In response, the SFC has established the baltobu project, which hosts three repositories. The `reverse-networking` repository aims to reverse-engineer Bambu's proprietary networking libraries to create drop-in replacements for Bambu Studio. The `orca-slicer-for-bambu` repository will maintain and extend Jarczak's Orca Slicer fork. The `viscose` repository will develop an active fork of Bambu Studio itself. Jarczak has agreed to collaborate with the SFC on these efforts.

The organization also committed to an ongoing watchdog role, stating it will "watch Bambu Lab closely and continue to investigate — regularly looking for any potential violations of copyleft licenses." A standing committee on software freedom and rights in the 3D printer community will be announced in June 2026, bringing together manufacturers, users, licensing experts, and activists for monthly discussions.

To fund these efforts, the SFC set a two-month fundraising target of $250,007. If reached, the organization plans to hire dedicated staff for long-term 3D printer right-to-repair work. The SFC credited Jarczak, GitHub user b3nsn0w, and organization FULU for drawing attention to the violations.
