# Progress

## Done
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

## In Progress
- None

## Not Started
- Frontend component implementation (storefront and admin UI)
- Product catalog CRUD APIs
- Authentication layer (customers + admin roles)
- Admin order management UI
- Product pages, categories, and media upload endpoints
- UK VAT/GBP handling for cart & checkout

## Known Issues / Tech Debt
- **Product→Review relationship asymmetry** (`backend/app/models/product.py:38-43`): filtered `primaryjoin` with `back_populates` creates asymmetric bidirectional relationship that will break admin moderation workflow — blocks merge
- **Guest cart Redis implementation unverified**: cart model and service files omitted from code review — critical path for checkout, still unresolved from previous runs
- Product catalog & CMS: no product pages, categories, or media upload endpoints
- Review system: incomplete (blocked by model relationship issue)
- Cart & checkout: not implemented (UK VAT/GBP handling pending)
- Order management: no admin order processing UI or APIs
- Authentication: no customer/admin auth system
- Local filesystem image storage (MVP only, not CDN)
