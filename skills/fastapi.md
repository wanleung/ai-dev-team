---
name: fastapi
description: FastAPI Python REST API development guidance
version: 1.0.0
roles:
  architect: true
  engineer: true
  code_reviewer: true
  qa_engineer: true
  product_manager: false
  architect_reviewer: false
  pm_reviewer: false
tags: [fastapi, python, api, rest, pydantic, uvicorn, sqlalchemy, alembic]
source: local
---

# FastAPI Skill

## For Architects
- Organise by domain, not by layer: `app/features/users/`, `app/features/orders/`, etc.
- Use `APIRouter` per feature; mount all routers in `app/main.py`
- Pydantic v2 for all request/response schemas; keep ORM models separate from schemas
- Prefer SQLAlchemy 2.x async. Use PostgreSQL/`asyncpg` for production services; SQLite is acceptable for tests, smoke deployments, and deliberate MVP/local-only apps
- Use Alembic for production schema migrations; table auto-create is acceptable only for tests/prototypes
- Use dependency injection (`Depends`) for DB sessions, auth, and settings

## For Engineers
- All endpoints must have response models (`response_model=`) — never return raw dicts
- Use `lifespan` context manager (not deprecated `on_startup`/`on_shutdown`)
- Settings via `pydantic-settings` `BaseSettings` with `.env` support; never `os.getenv` inline
- Background tasks: use `BackgroundTasks` for fire-and-forget; Celery for reliable queuing
- Version public business APIs, e.g. `/api/v1/...`; health checks and internal operational routes may stay unversioned when that matches project convention
- SQLAlchemy 2.x `DeclarativeBase` must be **subclassed**, never instantiated:
  ```python
  # ✅ correct
  class Base(DeclarativeBase):
      pass

  # ❌ wrong — Base.metadata raises AttributeError
  Base = DeclarativeBase()
  ```

## For Code Reviewers
- Reject endpoints without `response_model` — breaks OpenAPI schema
- Flag `os.getenv` / hardcoded config values — must use `settings` object
- Verify all DB operations use async (`await session.execute(...)`)
- Check that migration files are committed for production schema changes; tests/prototypes using table auto-create must be clearly scoped
- Flag missing `status_code` on create endpoints (should be `201`)
- Flag `Base = DeclarativeBase()` — must be `class Base(DeclarativeBase): pass` (instantiation breaks `.metadata`)

## For QA Engineers
- Use `httpx.AsyncClient` with `app` transport for integration tests (not `TestClient` for async)
- Test both success and error paths for every endpoint
- Include database migration test: apply migrations to empty DB and verify schema
- Test rate limiting and auth token expiry if implemented
- Verify OpenAPI docs render at `/docs` without errors
