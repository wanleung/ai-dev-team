# Active Context

## Current Focus
Linux 7.1 PM Dynamic EPP Feature (ai-it-press) — pipeline run completed but produced empty PRD, Architecture Design, and Code Review Notes. Source: Phoronix article on Linux 7.1 power management merges covering AMD Dynamic EPP fixes and Intel Bartlett Lake P-state scaling. Feature scope unclear; no implementation details available.

## Recent Changes
- Netherlands Server Seizure News Feature (ai-it-press) — pipeline run completed but produced empty PRD, Architecture Design, and Code Review Notes. Source: BleepingComputer article about Netherlands seizing 800 servers of hosting firm enabling cyberattacks. Feature scope unclear; no implementation details available.
- Packagist Supply Chain Attack Feature (ai-it-press) — pipeline run completed but produced empty PRD, Architecture Design, and Code Review Notes. Source: The Hacker News article on Packagist supply chain attack (8 packages infected with GitHub-hosted Linux malware). Target: Article summarization feature for security news ingestion. Feature scope unclear; article summary truncated mid-sentence; no implementation details available.
- npm 2FA-Gated Publishing Feature (ai-it-press) — pipeline run processed feature requirement only, no implementation. Source: Hacker News article on npm's 2FA-gated publishing and package install controls for supply chain attack prevention. Feature concept: Staged publishing allowing maintainers to explicitly approve releases before public availability. PRD, Architecture Design, and Code Review Notes all empty.
- CVE-2026-48172 LiteSpeed cPanel Plugin vulnerability news feature (ai-it-press) — pipeline run completed but produced empty PRD, Architecture Design, and Code Review Notes. Source: The Hacker News article on LiteSpeed cPanel Plugin vulnerability (CVE-2026-48172, CVSS 10.0). Vulnerability: incorrect privilege assignment allowing arbitrary script execution as root. Feature scope unclear; no implementation details available.
- CVE-2026-9082 Drupal SQL Injection (ai-it-press) — content sourced from Security Affairs article about highly critical SQL injection vulnerability in Drupal under active exploitation. No implementation produced; pipeline stalled at requirements gathering stage. Time-sensitive: active exploitation confirmed within 48 hours of patch release (May 20, 2026).
- **RSS topic deduplication merged (PR #86):** `topic_dedup.py` + `rss_watcher.py` integration; supports fuzzy/keyword/LLM/all similarity methods; ADD_SOURCE, CREATE_FOLLOWUP, CREATE_NEW routing; per-target config; LLM token separated from GitHub token; configurable base URL via `LLM_BASE_URL` env var
- Pipeline run processed Linux 7.1-rc4 news summarizer feature from Phoronix (no implementation artifacts produced)
- Pipeline run processed Google Chromium vulnerability exposure article from BleepingComputer (no implementation artifacts produced)
- Pipeline run processed Microsoft Defender zero-day vulnerabilities news feature (no implementation artifacts produced)
- Pipeline run captured requirement specification for CVE-2026-46333 (The Hacker News source); no code implementation produced
- Cloud storage security feature for document handling — Implementation focused on preventing misconfigured S3 bucket exposures for sensitive documents (passports, IDs, selfies). Security-first architecture based on Tabiq breach case study (1M+ record exposure from Reqrea's hotel check-in system).
- 7-Eleven/ShinyHunters data breach article processed through news-article pipeline; article output to `articles/` with YAML frontmatter; dual translation outputs (zh-hk, zh-tw); GitHub PR automation triggered
- Infrastructure modules: `shipping_config`, `email_service`, `image_pipeline`, `observability`
- Backend stack: FastAPI + SQLAlchemy + PostgreSQL 15 with Alembic migrations
- Models: Product, Category, Cart, CartItem, Order, OrderItem, Review, User (with improved relationship definitions and database constraints)
- Routers: products, cart, checkout, orders, reviews, auth, admin, admin_reviews, admin_returns, returns, webhooks
- Services: product_service, cart_service, checkout_service, order_service, review_service, auth_service, return_service, email_service, image_pipeline
- Frontend scaffolding: React 18 + Vite + Tailwind for storefront and admin panels
- UK VAT compliance (20% default), GBP pricing with `price_excl_vat` + `vat_rate` fields
- Guest checkout support via `session_id` on cart, `guest_email` on orders
- Review moderation workflow with status (pending/approved/rejected)
- Stripe PaymentIntents integration configured
- CORS middleware and async lifespan configured
- Pillow integrated for image processing
- PR/Marketing Campaign Pipeline agents: PRAnalystAgent, PRCreativeAgent, PRProposalAgent
- PR/Marketing Campaign Pipeline config: `pipelines/pr-campaign.yaml`
- PR/Marketing Campaign Watcher config: `repos.yaml`
- PR/Marketing Campaign issue template: `.github/ISSUE_TEMPLATE/campaign-brief.md`
- PR/Marketing Campaign role prompts: `roles/pr_analyst.md`, `roles/pr_creative.md`, `roles/pr_proposal.md`

## Immediate Next Steps
1. Clarify deliverable type for Linux 7.1 PM Dynamic EPP Feature — documentation vs. code implementation (kernel module, monitoring tool, or other)
2. Extract technical specifics from Phoronix source article (AMD EPP fixes, Intel Bartlett Lake P-state scaling)
3. Create proper PRD with acceptance criteria for Linux 7.1 PM feature
4. Investigate root cause of repeated pipeline stalls producing empty deliverables across multiple features (now 20+ consecutive failures)
5. Verify upstream pipeline configuration to ensure PRD, Architecture, and Review sections are properly populated
6. Establish minimum documentation requirements for feature-mode runs

## Reference
- Source: Phoronix — Linux 7.1 PM merges (AMD Dynamic EPP, Intel Bartlett Lake P-state scaling)
- Source: BleepingComputer — Netherlands seizes 800 servers of hosting firm enabling cyberattacks
- Article URL: https://www.bleepingcomputer.com/news/security/netherlands-seizes-800-servers-of-hosting-firm-enabling-cyberattacks/
- Source: Security Affairs — CVE-2026-9082 Drupal SQL Injection (actively exploited within 48 hours of patch release May 20, 2026)
- Source: Phoronix — Linux 7.1-rc4 kernel release news summarizer
- Article URL: https://www.phoronix.com/news/Linux-7.1-rc4-Released
- Source: BleepingComputer — Google accidentally exposed details of unfixed Chromium flaw
- Article URL: https://www.bleepingcomputer.com/news/security/google-accidentally-exposed-details-of-unfixed-chromium-flaw/
- Source: BleepingComputer — Microsoft warns of new Defender zero-days exploited in attacks
- Article URL: https://www.bleepingcomputer.com/news/security/microsoft-warns-of-new-defender-zero-days-exploited-in-attacks/
- Source: The Hacker News — CVE-2026-46333 9-year-old Linux kernel privilege escalation vulnerability (CVSS 5.5)
- Article URL: https://thehackernews.com/2026/05/9-year-old-linux-kernel-flaw-enables.html
- Source case: Public Amazon S3 bucket exposed over 1 million passports, IDs, and selfies (Reqrea's Tabiq hotel check-in system)
- Root cause: Storage misconfiguration in hotel check-in system
- Security-first architecture chosen in response to Tabiq breach case study
- Bucket access controls and authentication mechanisms prioritised
- Source: Security Affairs — 7-Eleven/ShinyHunters data breach (Salesforce/CRM breach)
- Pipeline: `pipelines/news-article.yaml` (news_triage → discuss_news_analysis → news_writer → discuss_news_draft → news_editor → translate_cantonese → translate_zh_traditional → news_reviewer → news_article_pr)
- Output: `articles/` directory with YAML frontmatter (title, date, author, source_url, tags)
- Translations: Written Cantonese (zh-hk), Formal Traditional Chinese (zh-tw)
