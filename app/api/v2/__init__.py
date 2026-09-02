"""Veyra v2 API routers package (Phase 6 & 7)."""

from fastapi import APIRouter

from app.api.v2.baselines import router as baselines_router
from app.api.v2.demo import router as demo_router
from app.api.v2.incidents import router as incidents_router
from app.api.v2.scoring import router as scoring_router

v2_router = APIRouter(prefix="/v2")
v2_router.include_router(scoring_router)
v2_router.include_router(incidents_router)
v2_router.include_router(baselines_router)
v2_router.include_router(demo_router)

__all__ = ["v2_router"]
