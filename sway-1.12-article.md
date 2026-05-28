---
title: "Sway 1.12 Delivers HDR10 Rendering, Window Capture, and Expanded Wayland Protocol Support"
date: 2026-05-25T18:00:00
author: AI Press Team
source_url: https://www.phoronix.com/news/Sway-1.12-Released
tags: [sway, wayland, hdr10, vulkan, linux, wlroots, tiling-window-manager]
---

Sway, the i3-compatible Wayland compositor built on wlroots, has reached version 1.12 with HDR10 rendering support, individual window capture, and five newly adopted Wayland protocols. The release also removes the hard block on unsupported GPU drivers, introduces a default configuration with media key bindings, and formally supports display manager startup.

The headline feature is HDR10 support when using Sway's Vulkan renderer. HDR10 is the most widely adopted open HDR format, enabling wider color gamuts and extended luminance ranges on compatible displays. A new `--device-primaries` flag lets the compositor pull color primaries directly from a monitor's EDID data, improving color accuracy for users working with calibrated panels. HDR functionality requires a Vulkan-capable GPU stack and an HDR-certified display — it is not automatic on all hardware.

Sway 1.12 adopts five new Wayland protocols: `color-management-v1`, `color-representation-v1`, `xdg-toplevel-tag-v1`, `ext-workspace-v1`, and `wl_fixes`. The color management protocols pair with the HDR10 additions to give applications finer control over output color spaces. The workspace and toplevel tagging protocols improve how compositors organize and label windows across multiple outputs — a meaningful upgrade for developers running complex multi-monitor setups.

Other additions include support for capturing individual windows during screen sharing, handling for keypad slide switches, and a shipped default configuration file pre-wired with playerctl key bindings for media control. The compositor also no longer refuses to launch on systems with unsupported GPU drivers such as NVIDIA's proprietary stack, instead displaying a warning and continuing startup. Display managers are now officially recognized as a supported method for starting Sway sessions.

The wlroots foundation continues to serve Sway well, keeping the codebase lean while surfacing upstream graphics improvements across the Wayland ecosystem. By sharing display and protocol handling with other compositors, the project avoids duplicating work and can adopt new specifications as they stabilize.

Users upgrading should review the release notes for protocol identifiers and any configuration adjustments. Those enabling HDR10 will need to confirm their GPU driver exposes the required Vulkan extensions and may need to set output parameters in their Sway config. The full release is available on [GitHub](https://github.com/swaywm/sway/releases/tag/1.12).
