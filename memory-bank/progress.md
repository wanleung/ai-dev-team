# Progress

## Done
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
- Linux 7.1-rc4 News Summarizer pipeline run produced no implementation artifacts — only requirement specification captured; full PRD, architecture, and code pending
- Google Chromium vulnerability pipeline run produced no implementation artifacts — only requirement specification captured; full PRD, architecture, and code pending
- Microsoft Defender zero-day pipeline run produced no implementation artifacts — only requirement specification captured; full PRD, architecture, and code pending
- CVE-2026-46333 pipeline run produced no implementation artifacts — only requirement specification captured; full PRD, architecture, and code pending
- Pattern observed: Multiple consecutive pipeline runs completing without populating PRD, Architecture, or Code Review sections
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
