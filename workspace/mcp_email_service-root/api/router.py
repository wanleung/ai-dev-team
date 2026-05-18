"""FastAPI router aggregation for the REST API Gateway.

Combines all endpoint routers under the configured API prefix.
"""

from fastapi import APIRouter

from api.accounts import router as accounts_router
from api.attachments import router as attachments_router
from api.emails import router as emails_router

api_router = APIRouter()
api_router.include_router(accounts_router)
api_router.include_router(emails_router)
api_router.include_router(attachments_router)
