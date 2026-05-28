# System Patterns

## Architecture Overview
- **Backend**: FastAPI (Python 3.12) with async support
- **Mobile**: Flutter 3.x for cross-platform iOS/Android
- **Admin Web**: React 19 + TypeScript
- **Database**: PostgreSQL 16 with PostGIS for geospatial queries
- **Cache/Queue**: Redis 7
- **Storage**: S3 for file storage

## Pipeline Architecture
- Orchestrator-based pipeline execution with stage-based processing
- TDD pipeline includes TDDReviewerAgent for correctness + quality review
- Retry logic in review stages returns original files on failure
- `PipelineResult` includes `tdd_review_summary` field
- **Content Generation Pipeline (ai-it-press)** — Linear pipeline pattern (Fetch → Generate → Format → Store) for single-article generation; state managed via JSON queue file (`queue.json`); single-run execution triggered by pipeline runner; not designed as long-running service

## Backend Patterns
- Clean separation of concerns:
  - SQLAlchemy ORM models for database layer
  - Pydantic schemas for request/response validation
  - Alembic for database migrations
- Mixins used for shared model behavior
- Database-level constraints for data integrity
- Auto-generated API documentation via FastAPI

## Agent Patterns
- Agents exported from `agents/__init__.py`
- System prompts stored in `roles/` directory as markdown files
- Test coverage for retry paths and failure scenarios
- Design specs and implementation plans in `docs/superpowers/`

## Data Models
- User profiles with snooker-specific attributes
- Second-hand equipment trading marketplace with detailed attribute filtering
- Venue/location data with geospatial support

## Localization
- Traditional Chinese (Hong Kong) terminology mandated
- Font stack configured for full TCH support
- All UI strings, system prompts, and error messages use HK terminology (e.g., "登入" not "登录")

## Authentication
- Apple ID authentication
- Gmail OAuth authentication
