# Tech Context

## Backend Stack
- Python 3.12
- FastAPI (async framework)
- SQLAlchemy (ORM)
- Pydantic (data validation)
- Alembic (migrations)

## Database & Infrastructure
- PostgreSQL 16 (primary database)
  - PostGIS extension for geospatial queries
  - JSON field support
- Redis 7 (caching/queuing)
- S3 (file storage)

## Mobile Stack
- Flutter 3.x
- Target platforms: iOS and Android
- State management framework (foundation implemented)
- Routing foundation implemented

## Admin Web Stack
- React 19
- TypeScript

## Pipeline Infrastructure
- Orchestrator-based pipeline execution
- TDD pipeline with TDDReviewerAgent
- Agent system prompts in `roles/*.md`
- Design documentation in `docs/superpowers/`
- Content generation pipeline (ai-it-press):
  - `openai` library for LLM interaction
  - File-based I/O for persistence
  - JSON queue file (`queue.json`) for state management
  - Single-run execution (not long-running service)

## Localization
- Traditional Chinese (Hong Kong)
- Font stack configured for full TCH character support

## Development Tools
- Auto-generated API docs (FastAPI/Swagger)

## Constraints
- All UI strings must use Traditional Chinese with Hong Kong terminology
- Database enums must be validated at schema level
- Foreign key constraints enforced at database level
