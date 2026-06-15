"""API-Version v1: buendelt alle v1-Router."""

from fastapi import APIRouter

from app.api.v1.endpoint_claims import router as claims_router

api_router_v1 = APIRouter()
api_router_v1.include_router(claims_router)

__all__ = ["api_router_v1"]
