# System Patterns

## Architecture
- Async-first FastAPI for high concurrency
- Pydantic v2 for request/response validation
- PostgreSQL 15 as primary datastore (JSONB for product specs)
- Redis 7 for sub-millisecond guest cart persistence (7-day TTL), rate limiting, JWT refresh tokens
- React 18 + Vite + Tailwind with isolated builds for storefront vs admin, shared component library
- FastAPI async lifespan for startup/shutdown logging
- CORS middleware configured for frontend-backend separation
- Local filesystem image storage (MVP only, not CDN)

## PR/Marketing Campaign Pipeline
- Three-agent sequential pipeline: PRAnalystAgent → PRCreativeAgent → PRProposalAgent
- All agents extend `BaseAgent` with synchronous GitHub-driven flow
- Human posts issue → watcher dispatches pipeline → PR opened for approval
- JSON-strict output contracts with validation and fallback retry prompts
- Exponential backoff on LLM timeouts (2^attempt seconds, max 3 retries)
- Branch naming convention: `campaign/{issue_number}-{slugified_big_idea}`
- Watcher monitors `wanleung/pr-campaigns` repo, triggers on `pr-campaign` label

## Data Model
- Core entities: Product, Category, Cart, CartItem, Order, OrderItem, Review, User
- PostgreSQL JSONB for flexible product specifications and shipping addresses
- SQLAlchemy ORM with improved relationship definitions and database constraints
- UK VAT compliance: `price_excl_vat` + `vat_rate` fields on products
- Guest checkout: `session_id` on cart, `guest_email` on orders
- Review moderation: `status` (pending/approved/rejected) and `rejection_reason`
- **Known issue**: Product→Review relationship uses filtered `primaryjoin` with `back_populates`, creating asymmetric bidirectional relationship

## Service Layer
- `product_service`: Product catalog operations
- `cart_service`: Cart management
- `checkout_service`: Checkout flow
- `order_service`: Order management
- `review_service`: Review handling
- `auth_service`: Authentication
- `return_service`: Return processing
- `email_service`: Email notifications
- `image_pipeline`: Image processing (Pillow)

## API Routes
- `products`: Product catalog CRUD
- `cart`: Cart operations
- `checkout`: Checkout flow
- `orders`: Order management
- `reviews`: Customer reviews
- `auth`: Authentication
- `admin`: Admin panel operations
- `admin_reviews`: Review moderation
- `admin_returns`: Return management
- `returns`: Customer returns
- `webhooks`: External webhook handlers

## Infrastructure Modules
- `shipping_config`: Shipping rules and configuration
- `email_service`: Email notification service
- `image_pipeline`: Image processing and media management
- `observability`: Monitoring and logging integration

## Security & Compliance
- Stripe PaymentIntents API for PCI DSS SAQ-A compliance (not handling raw card data)
- UK data residency (eu-west-2)
- WCAG 2.1 AA compliance for frontend
- GBP pricing with VAT

## Patterns to Implement
- Multi-layer enforcement for UK VAT calculations and shipping rules
- CDN integration for image storage (post-MVP)
- Complete Product→Review relationship fix for admin moderation