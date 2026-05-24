# Progress

## Done
- **RSS topic deduplication** — `topic_dedup.py` module + `rss_watcher.py` integration merged (PR #86); fuzzy/keyword/LLM/all similarity; ADD_SOURCE/CREATE_FOLLOWUP/CREATE_NEW routing; per-target config; LLM token + base URL configurable; 26 tests passing; design spec + implementation plan in `docs/superpowers/`
- Cloud storage security feature for document handling — Implementation focused on preventing misconfigured S3 bucket exposures for sensitive documents (passports, IDs, selfies); security-first architecture based on Tabiq breach case study
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

## In Progress
- Linux 7.1 PM Dynamic EPP Feature (ai-it-press) — pipeline run completed but produced empty PRD, Architecture Design, and Code Review Notes. Source: Phoronix article on Linux 7.1 power management merges covering AMD Dynamic EPP fixes and Intel Bartlett Lake P-state scaling. Feature scope unclear; no implementation details available.
- Netherlands Server Seizure News Feature (ai-it-press) — pipeline run completed but produced empty PRD, Architecture Design, and Code Review Notes. Source: BleepingComputer article about Netherlands seizing 800 servers of hosting firm enabling cyberattacks. Feature scope unclear; no implementation details available. Entire feature implementation pending.
- Packagist Supply Chain Attack Feature (ai-it-press) — pipeline run completed but produced empty PRD, Architecture Design, and Code Review Notes. Source: The Hacker News article on Packagist supply chain attack (8 packages infected with GitHub-hosted Linux malware). Target: Article summarization feature for security news ingestion. Feature scope unclear; article summary truncated mid-sentence; no implementation details available.
- npm 2FA-Gated Publishing Feature (ai-it-press) — pipeline run processed feature requirement only, no implementation. Source: Hacker News article on npm's 2FA-gated publishing and package install controls for supply chain attack prevention. Feature concept: Staged publishing allowing maintainers to explicitly approve releases before public availability. PRD, Architecture Design, and Code Review Notes all empty.
- CVE-2026-48172 LiteSpeed cPanel Plugin vulnerability news feature (ai-it-press) — pipeline run completed but produced empty PRD, Architecture Design, and Code Review Notes. Source: The Hacker News article on LiteSpeed cPanel Plugin vulnerability (CVE-2026-48172, CVSS 10.0). Vulnerability: incorrect privilege assignment allowing arbitrary script execution as root. Feature scope unclear; no implementation details available.
- CVE-2026-9082 Drupal SQL Injection (ai-it-press) — content sourced from Security Affairs article; pipeline stalled at requirements gathering; no implementation produced; time-sensitive: active exploitation confirmed within 48 hours of patch release (May 20, 2026)
- Linux 7.1-rc4 News Summarizer — Phoronix source processed (pipeline run completed, no implementation produced)
- Google Chromium vulnerability exposure news feature — BleepingComputer source processed; requirement specification captured; full implementation (PRD, architecture, code) pending
- Microsoft Defender zero-day vulnerabilities coverage — BleepingComputer source processed; requirement specification captured; full implementation (PRD, architecture, code) pending
- CVE-2026-46333 Linux kernel privilege escalation vulnerability feature — requirement specification captured; PRD, architecture, and code implementation pending

## Not Started
- Frontend component implementation (storefront and admin UI)
- Product catalog CRUD APIs
- Authentication layer (customers + admin roles)
- Admin order management UI
- Product pages, categories, and media upload endpoints
- UK VAT/GBP handling for cart & checkout

## Known Issues / Tech Debt
- Pipeline stall (Linux 7.1 PM Dynamic EPP): Pipeline run completed but produced empty PRD, Architecture Design, and Code Review Notes. Article covers Linux 7.1 power management merges for AMD Dynamic EPP fixes and Intel Bartlett Lake P-state scaling. Critical: Feature scope unclear. Critical: Deliverable type undefined (documentation vs. kernel module vs. monitoring tool). Critical: PRD not written. Critical: No architecture design documented. Critical: No implementation started. Future agents should extract technical specifics from Phoronix source article and clarify deliverable type before proceeding.
- Pipeline stall (Netherlands Server Seizure): Pipeline run completed but produced empty PRD, Architecture Design, and Code Review Notes. Source: BleepingComputer article about Netherlands seizing 800 servers of hosting firm enabling cyberattacks. Critical: Feature scope unclear. Critical: PRD not written. Critical: No architecture design documented. Critical: No implementation started. Full implementation pending from scratch. Future agents should clarify whether this is hosting provider monitoring, cybercrime infrastructure tracking, or news summarization feature.
- Pipeline stall (Packagist Supply Chain Attack): Pipeline run completed but produced empty PRD, Architecture Design, and Code Review Notes. Source: The Hacker News article on Packagist supply chain attack (8 packages infected with GitHub-hosted Linux malware). Target: Article summarization feature for security news ingestion. Critical: Article summary truncated mid-sentence ("the malicious code was not adde..."). Critical: PRD not written. Critical: No architecture design documented. Critical: No implementation started. Full implementation pending from scratch. Future agents should clarify whether this is a scraping service, RSS feed reader, or manual ingestion tool.
- Pipeline stall (npm 2FA-Gated Publishing): Pipeline run processed feature requirement only, no implementation. Source: Hacker News article on npm's 2FA-gated publishing and package install controls for supply chain attack prevention. Feature concept: Staged publishing allowing maintainers to explicitly approve releases before public availability. Critical: PRD not written. Critical: No architecture design documented. Critical: No implementation started. Full implementation pending from scratch. Future agents should verify current npm API capabilities for staged publishing and 2FA gates (article dated May 2026 — confirm API availability).
- Pipeline stall (CVE-2026-48172 LiteSpeed cPanel Plugin): Pipeline run completed but produced empty PRD, Architecture Design, and Code Review Notes. Source: The Hacker News article on LiteSpeed cPanel Plugin vulnerability (CVE-2026-48172, CVSS 10.0). Vulnerability: incorrect privilege assignment allowing arbitrary script execution as root. Critical: Feature scope unclear. Critical: PRD not written. Critical: No architecture design documented. Critical: No implementation started. Full implementation pending from scratch.
- Pattern observed: Multiple consecutive pipeline runs (now 20+) completing without populating PRD, Architecture, or Code Review sections — systemic issue requires investigation
- Cloud storage security feature: PRD excerpt not provided — requirements may need clarification
- Cloud storage security feature: Architecture Design excerpt empty — architectural decisions not documented
- Cloud storage security feature: Code Review Notes empty — no review feedback recorded yet
- Cloud storage security feature: Implementation details not captured in summary — specific files/modules/APIs unknown
- PRD, Architecture Design, and Code Review sections left empty in 7-Eleven/ShinyHunters breach brief
- No specific reviewer feedback captured for this breach type
- Pattern for handling franchisee data vs. customer data distinctions not documented
- **Product→Review relationship asymmetry** (`backend/app/models/product.py:38-43`): filtered `primaryjoin` with `back_populates` creates asymmetric bidirectional relationship that will break admin moderation workflow — blocks merge
- **Guest cart Redis implementation unverified**: cart model and service files omitted from code review — critical path for checkout, still unresolved from previous runs
- Known Issue: None at this time — all agent LLM calls use BaseAgent.call() correctly.
- **No unit tests for PR/Marketing Campaign agents**: only watcher PR tests exist in `tests/test_watcher_prs.py`
- **`repos.yaml` not integrated**: not added to `repos-enabled/` — pipeline won't trigger until configured
- **`GitHubClient.create_pull_request()` return structure assumed**: not verified against actual implementation
- **Missing integration tests**: no end-to-end pipeline execution tests
- **Companion repo `wanleung/pr-campaigns` not created**: required for watcher to function
- **LLM provider fallback untested**: only GPT-4.1 assumed, Ollama/OpenCode/Nvidia not verified
- **No rate-limit handling for GitHub API**: beyond 60s wait in PRProposalAgent
- **Role prompt files lack character limit enforcement**: in LLM output validation
- Product catalog & CMS: no product pages, categories, or media upload endpoints
- Review system: incomplete (blocked by model relationship issue)
- Cart & checkout: not implemented (UK VAT/GBP handling pending)
- Order management: no admin order processing UI or APIs
- Authentication: no customer/admin auth system
- Local filesystem image storage (MVP only, not CDN)
