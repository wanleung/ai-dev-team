# Active Context

## Current Focus
RSS topic deduplication — merged to master (PR #86). Prevents duplicate GitHub Issues when multiple RSS sources cover the same news story.

## Recent Changes
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
1. Re-run pipeline with proper PRD generation for Linux 7.1-rc4 news summarizer feature
2. Complete PRD with functional requirements, input/output specs, acceptance criteria for Linux 7.1-rc4 summarizer
3. Create architecture design with tech stack, module breakdown, API contracts for Linux 7.1-rc4 summarizer
4. Implement the summarizer (scraping, parsing, summarization logic) for Linux 7.1-rc4
5. Add tests and run code review before marking Linux 7.1-rc4 feature complete
6. Clarify feature scope: Is this a news article ingestion, vulnerability tracking entry, or security alert feature?
7. Complete PRD with specific deliverables for Google Chromium vulnerability coverage
8. Create architecture design for ai-it-press news integration
9. Implement and review code for Google Chromium vulnerability feature
10. Verify article content exists in `/content/news/` directory (expected: `google-chromium-vulnerability-exposure.md` or similar)
11. Confirm metadata extraction completed (title, summary, source, publish date) for Google Chromium vulnerability article
12. Parse BleepingComputer article for CVE identifiers, affected Defender versions, and attack vectors
13. Define PRD for Microsoft Defender zero-day vulnerability coverage with specific acceptance criteria
14. Design data model for vulnerability tracking
15. Document architecture decisions for vulnerability content handling
16. Implement scraping or ingestion pipeline for BleepingComputer security feeds
17. Create API endpoints or UI components for vulnerability alerts
18. Add notification system for zero-day exploits
19. Clarify scope: determine if this is a one-off article parser or a recurring security feed system
20. Check existing vulnerability tracking infrastructure before building new components
21. Write complete PRD for CVE-2026-46333 Linux kernel vulnerability coverage with acceptance criteria
22. Define architecture for vulnerability content processing and summarization
23. Implement feature: article fetcher, vulnerability parser, summary generator
24. Add tests and code review documentation for CVE-2026-46333 feature
25. Verify actual files/modules created during cloud storage security run (check `git diff` or recent commits)
26. Ensure bucket policies explicitly deny public access by default
27. Implement encryption-at-rest for all sensitive document storage
28. Add automated scanning for public bucket misconfigurations
29. Document specific endpoints, modules, and security controls implemented for cloud storage
30. Complete PRD for cloud storage security feature with acceptance criteria
31. Document architecture decisions for secure document storage
32. Establish template for data breach articles (Salesforce/CRM breaches)
33. Document ShinyHunters threat actor background for future references
34. Add checklist for breach article verification (confirmed vs. claimed numbers)
35. Ensure source URLs point to original reporting (Security Affairs in this case)
36. Verify Salesforce/CRM breach terminology accuracy for technical audience
37. Document pattern for handling franchisee data vs. customer data distinctions
38. Create `wanleung/pr-campaigns` companion repo with issue template (campaign-brief.md removed from this repo — belongs there)
39. Add `repos.yaml` to `repos-enabled/` and configure watcher
40. Verify `GitHubClient.create_pull_request()` signature and return value
41. Add pipeline to orchestrator's available pipelines list
42. Test with alternative LLM backends (Ollama, etc.)
43. Resume MCP Email Service architecture design document

## Reference
- Source: Phoronix — Linux 7.1-rc4 kernel release news summarizer
- Article URL: https://www.phoronix.com/news/Linux-7.1-rc4-Released
- Source: BleepingComputer — Google accidentally exposed details of unfixed Chromium flaw
- Article URL: https://www.bleepingcomputer.com/news/security/google-accidentally-exposed-details-of-unfixed-chromium-flaw/
- Issue: Google leaked details of a Chromium flaw allowing JavaScript background execution after browser close, enabling remote code execution
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
