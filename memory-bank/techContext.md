# Tech Context

## Tech Stack
- **Backend**: FastAPI (async), Python 3.11+
- **Database**: PostgreSQL 15 (JSONB for product specs)
- **Cache/Session**: Redis 7 (guest cart 7-day TTL, JWT refresh, rate limiting)
- **Frontend**: React 18, Vite, Tailwind CSS (separate Storefront/Admin builds)
- **Payments**: Stripe PaymentIntents API
- **ORM**: SQLAlchemy
- **Validation**: Pydantic v2
- **Migrations**: Alembic
- **Image Processing**: Pillow

## Infrastructure
- UK data residency (eu-west-2)
- PostgreSQL JSONB for flexible product specifications and shipping addresses
- Redis for:
  - Guest cart persistence (7-day TTL) — *implementation unverified, cart model/service files omitted from code review*
  - Rate limiting
  - JWT refresh tokens
- Alembic for database migrations
- CORS middleware for frontend-backend separation
- FastAPI async lifespan for startup/shutdown logging
- Local filesystem image storage (MVP only)

## Implemented Services
- `shipping_config`
- `email_service`
- `image_pipeline`
- `observability`
- `product_service`
- `cart_service`
- `checkout_service`
- `order_service`
- `review_service`
- `auth_service`
- `return_service`

## Environment Constraints
- GBP pricing with VAT (20% default)
- WCAG 2.1 AA compliance required
- PCI DSS SAQ-A compliance via Stripe (PaymentIntents, not handling raw card data)

## Known Configuration Gaps
- Guest cart Redis implementation unverified — critical path for checkout
- Product→Review relationship asymmetry blocks review system completion
- No CDN for image storage (local filesystem only for MVP)
