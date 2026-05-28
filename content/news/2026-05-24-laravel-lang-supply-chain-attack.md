---
title: "Laravel Lang 供應鏈攻擊遭篡改 Git 標籤 大量竊取開發者憑證"
date: 2026-05-24T03:46:00
author: AI Press Team
source_url: https://www.bleepingcomputer.com/news/security/laravel-lang-packages-hijacked-to-deploy-credential-stealing-malware/
tags: [supply-chain-attack, laravel, composer, open-source-security, credential-theft]
---

安全公司 StepSecurity、Aikido Security 及 Socket 週五通報，Laravel Lang 本地化套件遭受供應鏈攻擊，入侵者篡改數百個 GitHub 版本標籤，將其指向惡意提交，導致開發者面臨大規模憑證竊取威脅。

受影響的儲存庫位於 Laravel Lang 組織下，包括 `laravel-lang/lang`、`laravel-lang/http-statuses`、`laravel-lang/attributes`，以及可能的 `laravel-lang/actions`。這些第三方翻譯套件不屬於官方 Laravel 專案。Aikido 統計三個儲存庫共有 233 個遭篡改的版本，Socket 則估計約有 700 個歷史版本可能受到波及。

入侵者並未直接在專案原始碼中植入惡意程式碼，而是利用 GitHub 的一項功能，使標籤能夠指向同一儲存庫分支中的提交。所有既有 Git 標籤均被重新指向新的惡意提交，攻擊於協調世界時 22:32 從 `laravel-lang/lang`（含 502 個標籤）開始，至 00:00 完成對 `laravel-lang/actions` 的篡改。四個儲存庫使用了相同的偽造作者身分、修改檔案及載荷行為，顯示單一行為人取得組織層級的推送權限後執行了整起操作。

開發者透過 Composer 安裝或更新這些套件時，套件管理器會解析被篡改的標籤，從入侵者控制的分支下載程式碼，並將惡意版本視為合法發行版。

## 惡意程式碼與憑證收集

遭篡改的發行版引入了一個名為 `src/helpers.php` 的檔案，該檔案會由 Composer 自動載入。此檔案作為下載器，從指揮控制伺服器 `flipboxstudio[.]info` 下載第二階段 PHP 載荷。

下載的載荷為跨平台憑證竊取程式，針對 Linux、macOS 及 Windows 系統。它會收集雲端憑證、Kubernetes 機密、Vault 令牌、Git 憑證、CI/CD 機密、SSH 金鑰、瀏覽器資料、加密貨幣錢包、密碼管理器儲存內容、VPN 設定檔，以及本地 `.env` 檔案。該惡意程式內建正規表達式模式，用於從檔案與環境變數中提取 AWS 金鑰、GitHub 令牌、Slack 令牌、Stripe 機密、資料庫憑證、JWT、SSH 私鑰，以及加密貨幣恢復助記詞。

在 Windows 系統上，PHP 載荷會解碼一個 base64 編碼的可執行檔，並將其寫入 `%TEMP%` 資料夾，使用隨機 `.exe` 檔名。BleepingComputer 的分析確認該二進位檔為 `DebugElevator`，這是一款資訊竊取程式，專門針對 Chrome、Brave 及 Edge 瀏覽器，提取解密已儲存憑證所需的 App-Bound Encryption 金鑰。內嵌的 PDB 路徑引用了 Windows 帳戶名稱 `Mero`，並包含字串 `claude`，顯示該惡意軟體的開發可能曾借助 AI 輔助。

資料收集完畢後，遭竊資訊會被加密並傳回入侵者的 C2 伺服器。

## 應對與修復措施

Packagist 已移除恶意版本，並暫時將受影響的套件下架，以防止進一步安裝。

使用 Laravel Lang 套件的開發團隊應立即採取以下行動：

1. **檢查 `composer.lock`**，確認攻擊期間是否安裝了任何 `laravel-lang` 套件，並將已安裝版本與官方套件註冊表比對，找出已被撤銷或標記的發行版。

2. **在專案目錄執行 `composer audit`**，檢查已安裝套件是否出现在 Packagist 安全公告資料庫中，該資料庫會標記已知遭篡改的版本。

3. **移除受污染的套件**，從 `composer.lock` 刪除受影響的條目，清除 `vendor/laravel-lang` 目錄，然後執行 `composer install` 以從已驗證的標籤取得乾淨版本。

4. **輪換所有憑證**，在任何曾安裝遭篡改套件的系統上，儲存在 `.env` 檔案中的所有憑證均應視為已外洩，包括資料庫密碼、API 令牌及服務金鑰，必須立即重新產生。

5. **審查基礎設施存取記錄**，檢查雲端服務、資料庫及第三方整合在暴露期間是否有未經授權的存取行為，並排查是否有歷史連線指向 `flipboxstudio[.]info`。

## 對開源安全的深遠影響

此次事件暴露了套件管理器在版本解析機制上的結構性盲點。自動化依賴套件掃描工具通常只會分析儲存庫的預設分支或已發佈的壓縮檔，尋找已知漏洞特徵。入侵者透過篡改版本標籤而非直接修改原始碼，創造出從元資料角度看似合法、卻在安裝時傳遞惡意載荷的發行版。

語意版本控制慣例假定已標籤的發行版代表經過驗證的程式碼快照。當此假定被破壞時，依賴標籤完整性作為真實性訊號的自動化工具便缺乏內建機制來偵測此類入侵。

安全研究人員建議將所有第三方依賴套件固定於已驗證的明確版本，避免自動進行次要或修補程式更新；在支援的情況下實施加密套件簽章驗證；將軟體組成分析工具整合至 CI/CD 流程，以監控異常發行版；並對所有套件維護者執行嚴格的儲存庫存取控制，包括多重要素驗證，以及受保護的分支與標籤政策。

開源社群仍在努力於分散式儲存庫之間標準化加密簽章與標籤保護機制，同時避免引入阻礙社群貢獻的摩擦。在此類機制普及之前，開發團隊必須將自動化依賴套件解析視為不可信任的攻擊面，並自行部署額外的驗證層。
