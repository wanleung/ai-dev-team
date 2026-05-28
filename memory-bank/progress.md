# Progress

## Done
- **Glassworm Botnet Takedown Article (ai-it-press)** — Cybersecurity news article covering coordinated takedown of Glassworm botnet by CrowdStrike, Google, and Shadowserver on May 26, 2026; sourced from Security Affairs (securityaffairs.com); factual reporting style; supply chain poisoning narrative (malicious tools/packages targeting developers); four simultaneous C2 channel kills
- **GlassWorm Malware Article Pipeline (ai-it-press)** — Content generation pipeline for GlassWorm malware takedown article; input queue processor, LLM-based content generation module, output formatter; Python with `openai` library; file-based I/O; JSON queue (`queue.json`) state management; single-run execution
- **Agent Skills Article (ai-it-press)** — External article by Addy Osmani from O'Reilly Radar ingested, summarized, and prepared for publication; attribution preserved as repost/permission-based content; content acquisition workflow executed
- **Glassworm Botnet Article (ai-it-press)** — Technical news article generated for BleepingComputer; covers Solana blockchain and BitTorrent DHT usage by botnet; Markdown-formatted output at `articles/glassworm-botnet-disrupted.md`; automated content generation pipeline used
- **Cache Aware Scheduling Article (ai-it-press)** — Phoronix-sourced article generated on Cache Aware Scheduling benchmarks for AMD Zen 5 (Linux 7.2); covers PostgreSQL, Valkey, and network performance improvements; WordPress-compatible output; source attribution preserved
- **Content Summary Module (ai-it-press)** — Module built to fetch and summarize LWN.net articles; first article processed: "MOT: a tool to fight openwashing in AI" (LWN 1073420); output structured as concise factual summary (<400 words) covering OSI definitions, openwashing, and MOT tool
- **TDD Reviewer Agent** — `TDDReviewerAgent` implemented with correctness + quality review capabilities; `agents/tdd_reviewer.py` (235 lines); `tests/test_tdd_reviewer.py` (141 tests covering retry path); `roles/tdd_reviewer.md` system prompt (48 lines); exported from `agents/__init__.py`
- **TDD Pipeline Integration** — orchestrator wired to call TDDReviewerAgent; `tdd_review_summary` field added to `PipelineResult`; retry logic returns original files on failure
- **Intake Scoring Improvements** — `intake_scoring.py` updated; `tests/test_intake_scoring.py` added (32 lines)
- **TDD Reviewer Documentation** — implementation plan (848 lines) and design spec (195 lines) in `docs/superpowers/`
- Backend project setup (Python 3.12 / FastAPI)
- PostgreSQL 16, Redis 7, and S3 storage configuration
- User models with snooker-specific profile data
- Authentication system (Apple ID, Gmail OAuth)
- Core database schemas for MVP
- Second-hand equipment trading marketplace models with attribute filtering
- Venue/location data structures
- Flutter 3.x mobile project structure (iOS and Android)
- Mobile state management and routing foundations
- React 19 + TypeScript admin dashboard scaffold
- Traditional Chinese (Hong Kong) localization configuration
- Architecture design: SQLAlchemy ORM, Pydantic schemas, Alembic migrations separation

## In Progress
- None

## Planned
- Input validation and security sanitization for source URLs and LLM-generated output
- Unit and integration test suite for content pipeline
- PRD and architecture documentation for pipeline operational triggering and input/output formats
- Automated feed or scraping integration for article sourcing
- Validation step for generated article's factual accuracy against source URL
- Article template enhancement with automated section generation or image/media placeholders
- Content formatting validation (markdown, front matter, site metadata) in build process
- Missing database indexes for frequently queried fields
- Schema drift resolution between ORM models and Pydantic schemas
- News module implementation (currently placeholder)
- Admin dashboard expansion with analytics
- Real-time features (chat, notifications)
- User badge/achievement system
- Advanced search with geospatial filtering for venues
- N+1 query optimization in list endpoints
- Standardized error handling across API endpoints

## Known Issues / Tech Debt
- **MINOR**: PRD, Architecture Design, and Code Review Notes were empty/missing for Glassworm botnet article run — no upstream specifications or reviewer feedback captured; quality gates may not have been formally applied
- **MINOR**: Article metadata (author, date, tags, SEO) population not confirmed for Glassworm botnet article
- **MINOR**: Internal linking verification needed — new article should cross-reference related cybersecurity/botnet content if exists
- **MAJOR**: No input validation on source URL in content pipeline (security risk if extended)
- **MAJOR**: No sanitization of LLM-generated output in content pipeline (security risk if extended)
- **MAJOR**: No unit or integration tests for content pipeline (omitted due to unclear initial requirements)
- **MAJOR**: File-based queue management lacks concurrency control (needs redesign for parallel/frequent processing)
- **MINOR**: Article sourcing process remains manual; no automated feed or scraping integration exists
- **MINOR**: No validation step for generated article's factual accuracy against source URL
- **MINOR**: Article template is basic; lacks automated section generation or image/media placeholders
- **MINOR**: Content formatting validation (markdown, front matter, site metadata) not integrated into build process
- **MINOR**: PRD, Architecture Design, and Code Review sections were empty for this content-focused run — pipeline may not need these for pure content tasks, but this should be documented
- **MAJOR**: Missing database indexes for user_id in trading listings and venue locations
- **MAJOR**: Potential N+1 query issues in list endpoints
- **MAJOR**: Schema drift between ORM models and Pydantic validation schemas
- **MINOR**: Inconsistent error handling in some API endpoints
- **MINOR**: Placeholder/TODO comments left in production code
- **MINOR**: Content summary module hardcoded for single source URL; needs configuration, input validation, and error handling for scaling
- **MINOR**: No SEO metadata, image assets, or structured data generated alongside article content
