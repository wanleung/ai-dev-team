---
title: "思科修補 Secure Workload 最高嚴重程度認證繞過漏洞"
date: 2026-05-21T23:19:00
author: Sergiu Gatlan
source_url: https://www.bleepingcomputer.com/news/security/cisco-max-severity-secure-workload-flaw-gives-hackers-site-admin-privileges/
tags: [思科, Secure Workload, 漏洞, 認證繞過, Zero Trust, 雲端安全]
---

思科已釋出安全更新，修補其 Secure Workload 平台一個最高嚴重程度的漏洞，該漏洞可讓攻擊者取得 Site Admin 權限。

Cisco Secure Workload（前稱 Cisco Tetration）協助管理人員透過零信任微分段來減少網絡攻擊面，並阻止橫向移動以保護商業應用程式安全。

該安全漏洞追蹤編號為 CVE-2026-20223，發現於 Secure Workload 的內部 REST API 中，可讓未經認證的攻擊者以 Site Admin 角色的權限存取資源。

思科在周三的公告中解釋：「此漏洞源於存取 REST API 端點時的驗證與認證不足。攻擊者若能向受影響的端點發送經精心構造的 API 請求，即可利用此漏洞。」

「成功利用後，攻擊者可讀取敏感資訊，並以 Site Admin 用戶的權限跨租戶邊界進行配置變更。」

思科表示此安全漏洞沒有可用的臨時緩解措施，已為本地部署客戶釋出軟件更新修補程式，並已在基於雲端的 Cisco Secure Workload SaaS 部署中解決此問題。

| Secure Workload 版本 | 首個修復版本 |
|---|---|
| 3.9 及更早版本 | 遷移至已修復版本 |
| 3.10 | 3.10.8.3 |
| 4.0 | 4.0.3.17 |

思科補充，其產品安全事件回應團隊（PSIRT）在發布本周公告前，未發現該漏洞在實際環境中遭利用的證據。

本月早些時候，思科[警告](https://www.bleepingcomputer.com/news/security/cisco-warns-of-new-critical-sd-wan-flaw-exploited-in-zero-day-attacks/)其 Catalyst SD-WAN 軟件網絡平台存在另一個最高嚴重程度的認證繞過漏洞（CVE-2026-20182），該漏洞正被作為零日漏洞積極利用，攻擊者可藉此取得管理員權限。

美國網絡安全及基礎設施安全局（CISA）已於 5 月 14 日將 CVE-2026-20182 漏洞加入[已知被利用漏洞目錄](http://www.cisa.gov/news-events/alerts/2026/05/14/cisa-adds-one-known-exploited-vulnerability-catalog)，並命令聯邦機構在三天內（5 月 17 日前）保護受影響設備。

5 月初，思科亦[釋出安全更新](https://www.bleepingcomputer.com/news/security/new-cisco-dos-flaw-requires-manual-reboot-to-revive-devices/)，修補 Crosswork Network Controller（CNC）及 Network Services Orchestrator（NSO）中的拒絕服務（DoS）漏洞，受影響系統需要手動重新啟動才能恢復。

過去五年間，CISA 已[標記 91 個遭積極利用的思科漏洞](https://www.cisa.gov/known-exploited-vulnerabilities-catalog?f%5B0%5D=vendor_project%3A801)，其中六個被多個勒索軟件組織使用。
