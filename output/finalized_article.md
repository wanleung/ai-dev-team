---
title: "Google's ANGLE Graphics Layer Gains Native Wayland Support, Easing Linux Desktop Migration"
date: 2026-05-26T22:27:00
author: AI Press Team
source_url: https://www.phoronix.com/news/ANGLE-Merges-Wayland
tags: [Linux, Wayland, Chromium, ANGLE, CEF, Open Source]
---

Google 的 ANGLE（Almost Native Graphics Layer Engine）已合併原生 Wayland 後端支援，移除了一項多年來迫使 Chromium Embedded Framework（CEF）應用程式依賴 Xwayland 的重要阻礙。是次上游程式碼整合為 CEF 及 Electron 架構應用程式開闢了直接途徑，使其無需 X11 轉換層即可與 Wayland 合成器通訊。

ANGLE 負責將 OpenGL API 呼叫轉換為 Vulkan、Direct3D 或其他原生圖形 API，多年來一直嵌入於 Chromium 的渲染堆疊中。由於缺乏原生 Wayland 支援，大量基於 CEF 和 Electron 框架的桌面應用程式在 Wayland 工作階段中別無選擇，只能透過 Xwayland 相容層運行。新合併的後端正正填补了這一缺口。

對終端用戶而言，實際好處包括正確的分數縮放、安全的螢幕分享協定，以及原生輸入法整合。對於企業 Linux 部署，消除 X11 依賴可減少攻擊面，並移除一直影響現代 Wayland 發行版桌面體驗的轉換開銷。

用戶不會立即看到變化。合併後的 ANGLE 程式碼必須先通過 Chromium 的發佈流程，然後整合到 CEF 中，最後由各個應用程式維護者重新編譯並重新分發其軟件。每個下游項目都遵循自己的時間表，使得廣泛採用成為一個分階段的過程，而非單一事件。

是次合併反映了 Wayland 在 Linux 桌面生態系統中更廣泛的成熟發展。主要發行版現在預設採用 Wayland 工作階段，合成器開發者亦已系統性地解決了早期的相容性缺口。ANGLE 曾是阻止依賴嵌入式 Chromium 渲染的應用程式實現完整原生 Wayland 運作的少數顯著障礙之一。

對於管理 Linux 工作站的 IT 團隊而言，這項發展提供了一條技術途徑，可加速因 CEF 相容性問題而延遲的 Wayland 遷移。組織現在可以有信心地規劃分階段推出，確信底層渲染堆疊將支援原生 Wayland 運作。部分應用程式維護者可能會將此更新列為較低優先級，而特定合成器的邊緣情況可能需要額外測試，但上游基礎現已就位。

是次合併填补了一個貫穿多代 Linux 桌面演變的相容性缺口，為生態系統提供了一條清晰路線，使最廣泛的桌面應用程式能夠實現完全原生的 Wayland 運作。
