---
title: "Linux 7.1 Merges Power Management Fixes for AMD EPP and Intel Bartlett Lake"
date: 2026-05-22T19:47:00
author: AI Press Team
source_url: https://www.phoronix.com/news/Linux-7.1-PM-Dynamic-EPP-Bart
tags: [Linux, Kernel, AMD, Intel, Power Management]
---

The Linux 7.1 merge window has integrated a batch of power management patches addressing bugs in both AMD and Intel CPU drivers. The updates resolve translation errors in AMD's Dynamic Enhanced Performance Preference implementation and correct a frequency scaling bug that caused Intel Bartlett Lake processors to report an incorrect 7GHz maximum frequency.

AMD's Dynamic EPP feature, introduced earlier in the 7.1 cycle, allows the kernel to automatically adjust performance profiles based on whether a Ryzen system is running on AC or battery power. Early versions of the code contained bugs that led to imprecise power state transitions. As part of this week's merge, the feature has been moved from a Kconfig build-time option to a runtime module parameter (`amd_pstate=dynamic_epp=1`), meaning users must now explicitly enable it at boot. The accompanying bug fixes aim to bring the functionality closer to a state where it can be enabled by default in a future release.

Intel's P-State driver received a scaling correction for Bartlett Lake P-core-only processors after the driver was erroneously calculating a 7GHz top frequency. The fix was originally queued for Linux 7.2 but was pulled forward into the 7.1 cycle. A separate correction also addresses incorrect scaling factor reporting on Raptor Lake E CPUs.

For system administrators managing affected hardware, the patches are now available in the mainline tree. Teams preparing for the 7.1 release should test pre-release kernels in staging environments, particularly on systems that have shown thermal throttling or performance instability. The `cpupower` and `turbostat` utilities can help verify that EPP settings and frequency transitions are behaving as expected. Those using custom power profiles or scheduler tunings should review their configurations, as the corrected driver behaviour may interact differently with existing policies.

Linux 7.1 remains in development, with a stable release expected later this year.
